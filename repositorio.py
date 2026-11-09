# repositorio.py - Acesso ao banco (Supabase) isolado das páginas, seguro para vários usuários simultâneos.
#
# Problemas do desenho original que este módulo resolve:
#   1. "verifica e depois grava" sem trava  -> registros duplicados quando 2 usuários processam o mesmo ato.
#   2. salvar_no_supabase = upsert "última gravação vence" -> a consolidação de um usuário apagava a do outro.
#   3. memória de correções gravada várias vezes (cada clique em Salvar duplicava os mesmos registros).
#   4. consultas N+1 e SELECT * trazendo texto integral (até 100 mil caracteres) de todos os atos.
import json
import re
import threading
from datetime import datetime

from concorrencia import registro as _registro


def converter_para_iso(data_str):
    if not data_str:
        return None
    data_str = str(data_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', data_str):
        return data_str
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', data_str)
    if m:
        d, mes, a = m.groups()
        return f"{a}-{mes}-{d}"
    try:
        return datetime.strptime(data_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        return None


def _erro_duplicado(e):
    s = str(e).lower()
    return "duplicate key" in s or "unique constraint" in s or "23505" in s


def _como_dict(valor):
    if isinstance(valor, dict):
        return valor
    if isinstance(valor, str):
        try:
            v = json.loads(valor)
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}
    return {}


class ResultadoSalvar:
    def __init__(self, ok, mensagem="", conflito=None, base_id=None):
        self.ok, self.mensagem, self.conflito, self.base_id = ok, mensagem, conflito, base_id

    def __bool__(self):
        return self.ok


class Repositorio:
    def __init__(self, sb, reg=None):
        self.sb = sb
        self.reg = reg or _registro()
        self._corr_vistas = set()           # hashes de correções já gravadas neste processo
        self._corr_lock = threading.Lock()
        self._auditoria_db_ok = True

    # ================================================================== KPIs (contagens leves, sem trazer linhas)
    def _contar(self, tabela, **filtros):
        try:
            q = self.sb.table(tabela).select("id", count="exact")
            for k, v in filtros.items():
                q = q.eq(k, v)
            r = q.limit(1).execute()
            return int(getattr(r, "count", None) or 0)
        except Exception:
            return None

    def contagens(self):
        return {
            "normas": self._contar("portarias_base"),
            "alteradoras": self._contar("portarias_alteradoras"),
            "identificados": self._contar("atos_importados", status="identificado"),
            "pendentes": self._contar("atos_importados", status="pendente"),
            "usuarios": self._contar("usuarios"),
        }

    # ================================================================== cruzamento (Identificar e Cruzar)
    def localizar_no_banco(self, numero_ref, tipo_ref=None):
        numero_limpo = str(numero_ref or "").strip()
        if not numero_limpo:
            return None, None
        try:
            res = self.sb.table("portarias_base").select(
                "id, nome_padronizado, tipo_documento, numero_documento, data_assinatura"
            ).ilike("numero_documento", f"%{numero_limpo}%").execute()
            if res.data:
                return "portarias_base", res.data[0]
        except Exception:
            pass
        try:
            res2 = self.sb.table("atos_importados").select(
                "id, nome_arquivo_original, tipo_documento, numero_documento, status"
            ).ilike("numero_documento", f"%{numero_limpo}%").execute()
            if res2.data:
                return "atos_importados", res2.data[0]
        except Exception:
            pass
        return None, None

    def buscar_dependentes_pendentes(self, numero_documento):
        numero_limpo = str(numero_documento or "").strip()
        if not numero_limpo:
            return []
        try:
            res = self.sb.table("atos_importados").select(
                "id, nome_arquivo_original, tipo_documento, numero_documento, status"
            ).eq("status", "pendente").ilike("ato_base_referenciado_numero", f"%{numero_limpo}%").execute()
            return res.data or []
        except Exception:
            return []

    def _existe_pendente(self, numero_documento, numero_ato_afetado):
        try:
            res = self.sb.table("atos_importados").select("id").eq("status", "pendente").eq(
                "numero_documento", numero_documento
            ).eq("ato_base_referenciado_numero", numero_ato_afetado).execute()
            return bool(res.data)
        except Exception:
            return False

    def _existe_leitura(self, numero_documento):
        try:
            res = self.sb.table("atos_importados").select("id").eq(
                "numero_documento", numero_documento
            ).is_("ato_base_referenciado_numero", "null").execute()
            return bool(res.data)
        except Exception:
            return False

    def salvar_pendencia(self, nome_arquivo, texto_integra, identificacao, ref):
        """True se gravou; False se já existia (ou se outro usuário gravou no mesmo instante)."""
        chave = f"pend:{identificacao.get('numero_documento')}|{ref.get('numero_ato_afetado')}"
        with self.reg.lock_da_chave(chave):
            if self._existe_pendente(identificacao["numero_documento"], ref["numero_ato_afetado"]):
                return False
            try:
                self.sb.table("atos_importados").insert({
                    "nome_arquivo_original": nome_arquivo,
                    "texto_integra": (texto_integra or "")[:100000],
                    "tipo_documento": identificacao.get("tipo_documento"),
                    "numero_documento": identificacao.get("numero_documento"),
                    "data_assinatura": converter_para_iso(identificacao.get("data_assinatura")),
                    "orgao_emissor": identificacao.get("orgao_emissor"),
                    "ato_base_referenciado_tipo": ref.get("tipo_ato_afetado"),
                    "ato_base_referenciado_numero": ref.get("numero_ato_afetado"),
                    "status": "pendente",
                    "estrutura_json": identificacao,
                }).execute()
                return True
            except Exception as e:
                if _erro_duplicado(e):
                    return False
                raise

    def salvar_leitura(self, nome_arquivo, texto_integra, identificacao):
        chave = f"leitura:{identificacao.get('numero_documento')}"
        with self.reg.lock_da_chave(chave):
            if self._existe_leitura(identificacao.get("numero_documento")):
                return False
            try:
                self.sb.table("atos_importados").insert({
                    "nome_arquivo_original": nome_arquivo,
                    "texto_integra": (texto_integra or "")[:100000],
                    "tipo_documento": identificacao.get("tipo_documento"),
                    "numero_documento": identificacao.get("numero_documento"),
                    "data_assinatura": converter_para_iso(identificacao.get("data_assinatura")),
                    "orgao_emissor": identificacao.get("orgao_emissor"),
                    "ato_base_referenciado_tipo": None,
                    "ato_base_referenciado_numero": None,
                    "status": "identificado",
                    "estrutura_json": identificacao,
                }).execute()
                return True
            except Exception as e:
                if _erro_duplicado(e):
                    return False
                raise

    # ================================================================== consolidação
    def resgatar_memoria(self):
        try:
            res = self.sb.table("memoria_de_correcoes").select("texto_ia, texto_corrigido").order("id", desc=True).limit(5).execute()
            if res.data:
                memoria = "\n\n⚠️ HISTÓRICO DE CORREÇÕES (Não repita os erros da IA):\n"
                for m in res.data:
                    memoria += f"- Erro: {m['texto_ia']}\n- Correção: {m['texto_corrigido']}\n\n"
                return memoria
        except Exception:
            pass
        return ""

    def consultar_estado_e_historico(self, nome_padrao):
        if not nome_padrao:
            return None, []
        try:
            res_bd = self.sb.table("portarias_base").select("id, documento_consolidado_json").eq("nome_padronizado", nome_padrao).execute()
            if not res_bd.data:
                return None, []
            base_id = res_bd.data[0]['id']
            estado = res_bd.data[0].get("documento_consolidado_json")
            res_alt = self.sb.table("portarias_alteradoras").select("nome_padronizado").eq("portaria_base_id", base_id).execute()
            ja = [r['nome_padronizado'] for r in (res_alt.data or []) if r.get('nome_padronizado')]
            return (json.dumps(estado) if estado else None), ja
        except Exception:
            return None, []

    def localizar_base(self, tipo_ref, numero_ref):
        if not numero_ref or not str(numero_ref).strip():
            return None
        try:
            numero_limpo = str(numero_ref).strip()
            query = self.sb.table("portarias_base").select("id, nome_padronizado, tipo_documento, numero_documento, documento_consolidado_json")
            candidatos = query.ilike("numero_documento", f"%{numero_limpo}%").execute().data or []
            if not candidatos and tipo_ref:
                candidatos = query.ilike("nome_padronizado", f"%{numero_limpo}%").execute().data or []
            if not candidatos:
                return None
            if tipo_ref:
                for c in candidatos:
                    if str(c.get('tipo_documento', '')).strip().lower() == str(tipo_ref).strip().lower():
                        return c
            return candidatos[0]
        except Exception:
            return None

    def _nomes_alteradoras_no_banco(self, base_id, estado_db):
        """{nome em minúsculas: nome original} das alteradoras já gravadas para a base."""
        nomes = {}
        for a in (_como_dict(estado_db).get("normas_alteradoras") or []):
            n = str(a.get("nome_padronizado", "")).strip()
            if n:
                nomes[n.lower()] = n
        try:
            res = self.sb.table("portarias_alteradoras").select("nome_padronizado").eq("portaria_base_id", base_id).execute()
            for r in (res.data or []):
                n = str(r.get("nome_padronizado", "")).strip()
                if n:
                    nomes.setdefault(n.lower(), n)
        except Exception:
            pass
        return nomes

    def detectar_conflito(self, cons):
        """Há alterações no banco que a versão em memória NÃO contém? (gravar agora as apagaria)"""
        nome = (cons.get("norma_base") or {}).get("nome_padronizado")
        if not nome:
            return None
        try:
            res = self.sb.table("portarias_base").select("id, documento_consolidado_json").eq("nome_padronizado", nome).execute()
        except Exception:
            return None
        if not res.data:
            return None
        row = res.data[0]
        no_banco = self._nomes_alteradoras_no_banco(row["id"], row.get("documento_consolidado_json"))
        na_tela = {str(a.get("nome_padronizado", "")).strip().lower() for a in (cons.get("normas_alteradoras") or [])}
        faltando = sorted(orig for low, orig in no_banco.items() if low not in na_tela)
        return {"base_id": row["id"], "nome": nome, "faltando": faltando} if faltando else None

    def _registrar_correcoes(self, cons, cons_original):
        if not cons_original:
            return 0
        novas = []

        def _reg(campo, original, editado):
            if original != editado and (original or editado):
                ia = json.dumps(original, ensure_ascii=False) if not isinstance(original, str) else original
                cor = json.dumps(editado, ensure_ascii=False) if not isinstance(editado, str) else editado
                novas.append({"texto_ia": ia, "texto_corrigido": cor})

        _reg("ementa", cons_original.get('ementa'), cons.get('ementa'))
        _reg("preambulo", cons_original.get('preambulo'), cons.get('preambulo'))
        for j, disp_editado in enumerate(cons.get("dispositivos", [])):
            if j >= len(cons_original.get("dispositivos", [])):
                break
            disp_original = cons_original["dispositivos"][j]
            for campo in ["texto_principal_alterada", "texto_principal_consolidada", "tabela_alterada", "tabela_consolidada",
                          "texto_pos_tabela_alterada", "texto_pos_tabela_consolidada", "nota_remissiva"]:
                _reg(campo, disp_original.get(campo), disp_editado.get(campo))
        gravadas = 0
        import hashlib
        for n in novas:
            h = hashlib.sha256((n["texto_ia"] + "\x00" + n["texto_corrigido"]).encode()).hexdigest()
            with self._corr_lock:
                if h in self._corr_vistas:
                    continue
                self._corr_vistas.add(h)
            try:
                self.sb.table("memoria_de_correcoes").insert(n).execute()
                gravadas += 1
            except Exception:
                with self._corr_lock:
                    self._corr_vistas.discard(h)
        return gravadas

    def salvar_consolidacao(self, cons, cons_original=None, sobrescrever=False, usuario=""):
        base = cons['norma_base']
        nome = base['nome_padronizado']
        with self.reg.lock_da_chave(f"base:{nome}"):
            conflito = self.detectar_conflito(cons)
            if conflito and not sobrescrever:
                return ResultadoSalvar(False, "conflito", conflito)
            try:
                corr = self._registrar_correcoes(cons, cons_original)
                alteradoras = cons.get('normas_alteradoras', [])
                res = self.sb.table("portarias_base").upsert({
                    "tipo_documento": base['tipo_documento'], "numero_documento": base['numero_documento'],
                    "orgao_emissor": base['orgao_emissor'], "data_assinatura": converter_para_iso(base.get('data_assinatura')),
                    "nome_padronizado": nome, "titulo_original": cons.get("titulo_portaria"),
                    "orgaos_emissores": cons.get("orgaos_emissores"), "assinatura_nome": cons.get("assinatura_nome"),
                    "assinatura_cargo": cons.get("assinatura_cargo"), "documento_consolidado_json": cons,
                }, on_conflict="nome_padronizado").execute()
                if res.data:
                    base_id = res.data[0]['id']
                else:
                    base_id = self.sb.table("portarias_base").select("id").eq("nome_padronizado", nome).execute().data[0]['id']
                existentes = {str(r.get("nome_padronizado", "")).strip().lower() for r in (
                    self.sb.table("portarias_alteradoras").select("nome_padronizado").eq("portaria_base_id", base_id).execute().data or [])}
                for alt in alteradoras:
                    if str(alt['nome_padronizado']).strip().lower() in existentes:
                        continue
                    try:
                        self.sb.table("portarias_alteradoras").insert({
                            "portaria_base_id": base_id, "tipo_documento": alt['tipo_documento'], "numero_documento": alt['numero_documento'],
                            "orgao_emissor": alt['orgao_emissor'], "data_assinatura": converter_para_iso(alt.get('data_assinatura')),
                            "nome_padronizado": alt['nome_padronizado'], "arquivo_nome_original": "Múltiplos Documentos",
                        }).execute()
                    except Exception as e:
                        if not _erro_duplicado(e):
                            raise
                self.reg.evento(usuario, "salvar_consolidacao", f"{nome} (+{len(alteradoras)} alteradora(s), {corr} correção(ões))")
                self._auditar_db(usuario, "salvar_consolidacao", nome)
                return ResultadoSalvar(True, "ok", None, base_id)
            except Exception as e:
                return ResultadoSalvar(False, f"erro: {e}")

    def apagar_cascata(self, base_id, nome="", usuario=""):
        self.sb.table("portarias_alteradoras").delete().eq("portaria_base_id", base_id).execute()
        self.sb.table("portarias_base").delete().eq("id", base_id).execute()
        self.reg.evento(usuario, "apagar_cascata", nome or base_id)
        self._auditar_db(usuario, "apagar_cascata", nome or base_id)

    def _auditar_db(self, usuario, acao, detalhe):
        if not self._auditoria_db_ok:
            return
        try:
            self.sb.table("auditoria").insert({"usuario": usuario, "acao": acao, "detalhe": str(detalhe)[:500]}).execute()
        except Exception:
            self._auditoria_db_ok = False   # tabela opcional não existe: não insiste
