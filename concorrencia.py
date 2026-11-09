# concorrencia.py - Infraestrutura compartilhada entre TODAS as sessões (abas/usuários) do processo Streamlit.
#
# O Streamlit executa um script por sessão (aba do navegador) em threads diferentes, mas todas as sessões
# compartilham o mesmo processo Python. Tudo que é global (st.cache_resource, variáveis de módulo) é, portanto,
# compartilhado por todos os usuários. Este módulo concentra esse estado global em UM objeto protegido por locks:
#
#   - sessões autenticadas (token de sessão, papel do usuário) e presença ("quem está online");
#   - trava branda por norma (aviso quando duas pessoas mexem na mesma norma);
#   - seções críticas por chave (serializa "verifica e depois grava" no banco);
#   - semáforo global de chamadas de IA (evita estourar a cota quando 2+ usuários processam juntos);
#   - bloqueio temporário de login por tentativas inválidas;
#   - trilha de auditoria em memória (e, se existir a tabela "auditoria", também no banco).
import hashlib
import secrets
import threading
import time
from collections import deque
from contextlib import contextmanager

import streamlit as st

TTL_PRESENCA_S = 75            # sem batimento por este tempo => considerado offline
TTL_TRAVA_S = 900              # trava branda de norma expira em 15 min sem renovação
TTL_SESSAO_S = 8 * 3600        # duração do login persistente (cookie)
MAX_FALHAS_LOGIN = 5
JANELA_FALHAS_S = 300
BLOQUEIO_LOGIN_S = 60
IA_SIMULTANEAS_PADRAO = 3
COOKIE_SESSAO = "cn_sessao"


class Registro:
    """Estado global compartilhado. Não guarda nada sensível além do hash dos tokens."""

    def __init__(self, ia_simultaneas=IA_SIMULTANEAS_PADRAO):
        self.lock = threading.RLock()
        self.presenca = {}           # sid -> {usuario, pagina, acao, norma, desde, visto}
        self.travas = {}             # chave -> {usuario, sid, desde, visto}
        self.tokens = {}             # sha256(token) -> {usuario, papel, exp}
        self.falhas_login = {}       # usuario(lower) -> [timestamps]
        self.bloqueios = {}          # usuario(lower) -> instante liberação
        self.locks_chave = {}        # chave -> Lock
        self.ia_max = ia_simultaneas
        self.sem_ia = threading.BoundedSemaphore(ia_simultaneas)
        self.ia_em_uso = 0
        self.ia_aguardando = 0
        self.auditoria = deque(maxlen=300)

    # ------------------------------------------------------------------ seções críticas
    def lock_da_chave(self, chave):
        with self.lock:
            lk = self.locks_chave.get(chave)
            if lk is None:
                lk = self.locks_chave[chave] = threading.RLock()
            return lk

    # ------------------------------------------------------------------ login / tokens
    def segundos_bloqueado(self, usuario, agora=None):
        agora = agora or time.time()
        with self.lock:
            ate = self.bloqueios.get((usuario or "").lower(), 0)
            return max(0, int(ate - agora + 0.999)) if ate > agora else 0

    def registrar_falha(self, usuario, agora=None):
        """Retorna os segundos de bloqueio aplicados (0 se ainda não bloqueou)."""
        agora = agora or time.time()
        k = (usuario or "").lower()
        with self.lock:
            fs = [t for t in self.falhas_login.get(k, []) if agora - t < JANELA_FALHAS_S]
            fs.append(agora)
            self.falhas_login[k] = fs
            if len(fs) >= MAX_FALHAS_LOGIN:
                self.bloqueios[k] = agora + BLOQUEIO_LOGIN_S
                self.falhas_login[k] = []
                return BLOQUEIO_LOGIN_S
            return 0

    def limpar_falhas(self, usuario):
        k = (usuario or "").lower()
        with self.lock:
            self.falhas_login.pop(k, None)
            self.bloqueios.pop(k, None)

    def criar_token(self, usuario, papel):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self._limpar_tokens()
            self.tokens[_h(token)] = {"usuario": usuario, "papel": papel, "exp": time.time() + TTL_SESSAO_S}
        return token

    def validar_token(self, token):
        if not token or not isinstance(token, str):
            return None
        with self.lock:
            dados = self.tokens.get(_h(token))
            if not dados:
                return None
            if dados["exp"] < time.time():
                self.tokens.pop(_h(token), None)
                return None
            return dict(dados)

    def revogar_token(self, token):
        if token:
            with self.lock:
                self.tokens.pop(_h(token), None)

    def revogar_usuario(self, usuario):
        """Derruba todos os logins persistentes de um usuário (troca de senha / exclusão de conta)."""
        k = (usuario or "").lower()
        with self.lock:
            for h in [h for h, v in self.tokens.items() if v["usuario"].lower() == k]:
                self.tokens.pop(h, None)

    def _limpar_tokens(self):
        agora = time.time()
        for k in [k for k, v in self.tokens.items() if v["exp"] < agora]:
            self.tokens.pop(k, None)

    # ------------------------------------------------------------------ presença
    def batimento(self, sid, usuario, pagina, acao=None, norma=None):
        agora = time.time()
        with self.lock:
            p = self.presenca.get(sid)
            if p is None:
                p = self.presenca[sid] = {"desde": agora}
            p.update({"usuario": usuario, "pagina": pagina, "acao": acao or p.get("acao"), "norma": norma or p.get("norma"), "visto": agora})
            for s in [s for s, v in self.presenca.items() if agora - v["visto"] > TTL_PRESENCA_S * 4]:
                self.presenca.pop(s, None)

    def sair(self, sid):
        with self.lock:
            self.presenca.pop(sid, None)
            for c in [c for c, v in self.travas.items() if v.get("sid") == sid]:
                self.travas.pop(c, None)

    def online(self):
        agora = time.time()
        with self.lock:
            return sorted(
                [dict(v, sid=s) for s, v in self.presenca.items() if agora - v["visto"] <= TTL_PRESENCA_S],
                key=lambda v: (v.get("usuario") or "", v["desde"]),
            )

    def usuarios_online(self):
        """Uma entrada por usuário (a sessão mais recente), mesmo que ele tenha várias abas abertas."""
        por_usuario = {}
        for p in self.online():
            k = (p.get("usuario") or "").lower()
            if k not in por_usuario or p["visto"] > por_usuario[k]["visto"]:
                por_usuario[k] = p
        return list(por_usuario.values())

    # ------------------------------------------------------------------ trava branda por norma
    def adquirir_trava(self, chave, sid, usuario):
        """Marca a norma como 'em edição'. Nunca bloqueia: devolve (True, None) ou (False, dono_atual)."""
        agora = time.time()
        with self.lock:
            t = self.travas.get(chave)
            if t and agora - t["visto"] <= TTL_TRAVA_S and t["sid"] != sid:
                return False, dict(t)
            self.travas[chave] = {"usuario": usuario, "sid": sid, "desde": (t or {}).get("desde", agora) if t and t["sid"] == sid else agora, "visto": agora}
            return True, None

    def dono_da_trava(self, chave, sid):
        """Dono da trava SE for outra sessão; senão None."""
        agora = time.time()
        with self.lock:
            t = self.travas.get(chave)
            if t and agora - t["visto"] <= TTL_TRAVA_S and t["sid"] != sid:
                return dict(t)
            return None

    def liberar_trava(self, chave, sid):
        with self.lock:
            t = self.travas.get(chave)
            if t and t["sid"] == sid:
                self.travas.pop(chave, None)

    # ------------------------------------------------------------------ IA
    @contextmanager
    def vaga_ia(self, timeout=300):
        with self.lock:
            self.ia_aguardando += 1
        ok = self.sem_ia.acquire(timeout=timeout)
        with self.lock:
            self.ia_aguardando -= 1
            if ok:
                self.ia_em_uso += 1
        if not ok:
            raise TimeoutError("Fila de IA cheia: tempo de espera esgotado. Tente novamente em instantes.")
        try:
            yield
        finally:
            with self.lock:
                self.ia_em_uso -= 1
            self.sem_ia.release()

    # ------------------------------------------------------------------ auditoria
    def evento(self, usuario, acao, detalhe=""):
        reg = {"quando": time.time(), "usuario": usuario or "?", "acao": acao, "detalhe": str(detalhe)[:300]}
        with self.lock:
            self.auditoria.appendleft(reg)
        return reg


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


@st.cache_resource
def registro() -> Registro:
    n = IA_SIMULTANEAS_PADRAO
    try:
        n = int(st.secrets.get("limites", {}).get("ia_simultaneas", n))
    except Exception:
        pass
    return Registro(max(1, n))


# ---------------------------------------------------------------------- atalhos para as páginas
def id_sessao():
    if "_sid" not in st.session_state:
        st.session_state["_sid"] = secrets.token_hex(6)
    return st.session_state["_sid"]


def usuario_atual():
    return st.session_state.get("usuario") or ""


def eh_admin():
    return st.session_state.get("papel") == "admin"


def secao_critica(chave):
    """with secao_critica('base:PORTARIA 1'): ...  (serializa leitura+gravação da mesma chave)"""
    return registro().lock_da_chave(chave)


def vaga_ia():
    return registro().vaga_ia()


def batimento(pagina, acao=None, norma=None):
    if st.session_state.get("autenticado"):
        registro().batimento(id_sessao(), usuario_atual(), pagina, acao, norma)


def auditar(acao, detalhe=""):
    return registro().evento(usuario_atual(), acao, detalhe)


# ---------------------------------------------------------------------- autenticação de sessão
def iniciar_sessao(usuario, papel):
    st.session_state["autenticado"] = True
    st.session_state["usuario"] = usuario
    st.session_state["papel"] = papel
    token = registro().criar_token(usuario, papel)
    st.session_state["_token"] = token
    st.session_state["_gravar_cookie"] = token
    registro().batimento(id_sessao(), usuario, "inicio")
    registro().limpar_falhas(usuario)
    auditar("login", "")


def restaurar_sessao_por_cookie():
    """F5/nova aba: recupera o login a partir do cookie (validado no servidor). Retorna True se restaurou."""
    if st.session_state.get("autenticado"):
        return True
    try:
        token = st.context.cookies.get(COOKIE_SESSAO)
    except Exception:
        token = None
    dados = registro().validar_token(token)
    if not dados:
        return False
    st.session_state["autenticado"] = True
    st.session_state["usuario"] = dados["usuario"]
    st.session_state["papel"] = dados["papel"]
    st.session_state["_token"] = token
    registro().batimento(id_sessao(), dados["usuario"], "inicio")
    return True


def encerrar_sessao():
    reg = registro()
    sid = id_sessao()
    reg.revogar_token(st.session_state.get("_token"))
    reg.evento(usuario_atual(), "logout", "")
    reg.sair(sid)
    # limpa TUDO da sessão (resultados de análises, chaves digitadas, edições) para não vazar entre pessoas
    # que usem o mesmo navegador em sequência.
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state["autenticado"] = False
    st.session_state["_apagar_cookie"] = True
