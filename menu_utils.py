# menu_utils.py - Cabeçalho, navegação superior, presença de usuários e proteção de acesso padronizados.
import os
from html import escape

import streamlit as st

import ui_theme
import concorrencia as conc

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# (chave, arquivo padrão, palavras p/ localizar, rótulo, ícone material, ícone svg, só_admin)
ITENS_MENU = [
    ("inicio", "app.py", None, "Identificar", ":material/travel_explore:", "search", False),
    ("bse", "pages/4_Extrair_Boletim_BSe.py", ("extrair", "boletim"), "Extrair BSe", ":material/newspaper:", "news", False),
    ("consolidar", "pages/3_Consolidar_Norma.py", ("consolidar",), "Consolidar", ":material/merge_type:", "merge", False),
    ("historico", "pages/1_Historico.py", ("historico",), "Histórico", ":material/inventory_2:", "archive", False),
    ("usuarios", "pages/usuarios.py", ("usuario",), "Usuários", ":material/group:", "users", True),
    ("diagnostico", "pages/diagnostico.py", ("diagnostico",), "Diagnóstico", ":material/monitor_heart:", "activity", False),
]
ROTULOS = {i[0]: i[3] for i in ITENS_MENU}


def _resolver_caminho(padrao, palavras):
    """Localiza o arquivo da página pela palavra-chave; usa o caminho padrão se não achar."""
    if not palavras:
        return padrao
    pasta = os.path.join(_BASE_DIR, "pages")
    if os.path.isdir(pasta):
        for f in sorted(os.listdir(pasta)):
            nome = f.lower()
            if nome.endswith(".py") and any(p in nome for p in palavras):
                return f"pages/{f}"
    return padrao


def configurar_pagina(titulo, icone="⚖️"):
    """Deve ser a PRIMEIRA chamada Streamlit da página."""
    st.set_page_config(page_title=f"{titulo} · Autopilot Normativo", page_icon=icone, layout="wide", initial_sidebar_state="collapsed")
    ui_theme.aplicar_tema()


def _iframe_html(html, height=0):
    """Compatível com versões novas (st.iframe) e antigas (components.html) do Streamlit. Só para HTML PRÓPRIO, nunca de usuário/IA."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=max(height, 1))
    else:
        import streamlit.components.v1 as components
        components.html(html, height=height)


def _cookie(valor, max_age):
    """Grava/apaga o cookie de sessão no navegador (o token é validado no servidor; o cookie sozinho não autentica)."""
    js = (f"<script>try{{var s=(window.parent.location.protocol==='https:')?'; Secure':'';"
          f"window.parent.document.cookie='{conc.COOKIE_SESSAO}={valor}; Path=/; Max-Age={max_age}; SameSite=Strict'+s;}}catch(e){{}}</script>")
    with st.container(key="cn_cookie"):
        _iframe_html(js)


def processar_cookies():
    if st.session_state.pop("_apagar_cookie", False):
        _cookie("", 0)
    token = st.session_state.pop("_gravar_cookie", None)
    if token:
        _cookie(token, conc.TTL_SESSAO_S)


def exigir_login(mensagem="Você precisa fazer login na página principal para acessar esta área.", somente_admin=False):
    conc.restaurar_sessao_por_cookie()
    if not st.session_state.get("autenticado", False):
        ui_theme.vazio("Acesso restrito", mensagem, "lock")
        try:
            st.page_link("app.py", label="Ir para a tela de login", icon=":material/lock:")
        except Exception:
            pass
        st.stop()
    processar_cookies()
    if somente_admin and not conc.eh_admin():
        ui_theme.vazio("Área restrita a administradores", "Seu usuário não tem permissão para acessar esta página.", "shield")
        try:
            st.page_link("app.py", label="Voltar ao início", icon=":material/arrow_back:")
        except Exception:
            pass
        st.stop()


def renderizar_cabecalho(titulo_h1, descricao="", etiqueta="", icone_nome="sparkles", css_extra=""):
    if css_extra:
        st.markdown(f"<style>{css_extra}</style>", unsafe_allow_html=True)
    ui_theme.hero(titulo_h1, descricao, etiqueta, icone_nome)


@st.fragment(run_every=30)
def _presenca(ativa):
    conc.batimento(ativa)
    reg = conc.registro()
    meu = conc.id_sessao()
    meu_usuario = (conc.usuario_atual() or "").lower()
    outros = [p for p in reg.usuarios_online() if (p.get("usuario") or "").lower() != meu_usuario]
    if not outros:
        st.markdown('<div class="cn-presenca"><span style="width:8px;height:8px;border-radius:50%;background:#94A3B8;display:inline-block"></span> '
                    'Você é o único usuário online agora.</div>', unsafe_allow_html=True)
        return
    chips = "".join(
        f'<span class="cn-chip" title="{escape(p.get("usuario") or "")} · {escape(ROTULOS.get(p.get("pagina"), p.get("pagina") or ""))}">'
        f'{ui_theme.avatar(p.get("usuario") or "?")}<span class="cn-dot"></span>'
        f'<span><b>{escape(p.get("usuario") or "?")}</b> · {escape(ROTULOS.get(p.get("pagina"), p.get("pagina") or ""))}</span></span>'
        for p in outros)
    st.markdown(f'<div class="cn-presenca">{ui_theme.icone("users", 15)} Equipe online agora: {chips}</div>', unsafe_allow_html=True)


def _sair():
    conc.encerrar_sessao()
    try:
        st.switch_page("app.py")
    except Exception:
        st.rerun()


def renderizar_menu(ativa):
    """Barra superior fixa. `ativa` é a chave da página atual."""
    st.session_state["_pagina"] = ativa
    conc.batimento(ativa)
    itens = [i for i in ITENS_MENU if (not i[6]) or conc.eh_admin()]
    with st.container(key="topbar"):
        pesos = [2.35] + [1.18] * len(itens) + [1.5]
        cols = st.columns(pesos, vertical_alignment="center")
        with cols[0]:
            st.markdown(ui_theme.marca(), unsafe_allow_html=True)
        for col, (chave, padrao, palavras, rotulo, ic_mat, ic_svg, _adm) in zip(cols[1:1 + len(itens)], itens):
            with col:
                if chave == ativa:
                    st.markdown(f'<div class="cn-nav-ativo" aria-current="page">{ui_theme.icone(ic_svg, 17)} {escape(rotulo)}</div>', unsafe_allow_html=True)
                    continue
                caminho = _resolver_caminho(padrao, palavras)
                try:
                    st.page_link(caminho, label=rotulo, icon=ic_mat, use_container_width=True)
                except Exception:
                    href = caminho.replace("pages/", "").replace(".py", "") if caminho != "app.py" else ""
                    st.markdown(f'<a class="cn-nav-ativo" style="background:#EEF3FB;color:#1E3C72;text-decoration:none" href="/{href}" target="_top">{escape(rotulo)}</a>', unsafe_allow_html=True)
        with cols[-1]:
            nome = conc.usuario_atual() or "Usuário"
            with st.popover(nome, icon=":material/account_circle:", use_container_width=True):
                papel = "Administrador" if conc.eh_admin() else "Usuário"
                st.markdown(f'<div class="cn-usr">{ui_theme.avatar(nome)}<div><b>{escape(nome)}</b><br>'
                            f'{ui_theme.badge(papel, "info" if conc.eh_admin() else "")}</div></div>', unsafe_allow_html=True)
                st.caption("Sessão ativa neste navegador. Outras pessoas logadas em outras abas/computadores têm sessões independentes.")
                if st.button("Sair do sistema", key=f"btn_sair_{ativa}", type="secondary", use_container_width=True, icon=":material/logout:"):
                    _sair()
    _presenca(ativa)
