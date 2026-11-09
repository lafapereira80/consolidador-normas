# pages/1_Historico.py - Histórico e gerenciamento do banco de dados
import json
import os
import re
import sys
from datetime import datetime
from html import escape

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from menu_utils import configurar_pagina, exigir_login, renderizar_cabecalho, renderizar_menu
from db_utils import obter_supabase, obter_repositorio
import concorrencia as conc
import ui_theme as ui
import exportacao

configurar_pagina("Histórico", "🗄️")
exigir_login("Você precisa fazer login na página principal para acessar o histórico.")
renderizar_menu("historico")
renderizar_cabecalho("Histórico e banco de dados", "Normas consolidadas, atos identificados, pendências, versões salvas e o aprendizado da IA, num só lugar.",
                     etiqueta="Arquivo", icone_nome="archive")

supabase = obter_supabase()
repo = obter_repositorio()
if not supabase:
    st.error("Não foi possível conectar ao Supabase.", icon=":material/cloud_off:")
    st.stop()

MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']


# ----------------------------------------------------------------------------- carregadores (colunas leves, cache curto)
# Antes: SELECT * (incluindo documento_consolidado_json e texto_integra de TODAS as linhas) + 1 consulta por item
# a cada interação. Agora: 1 consulta por tabela, só com as colunas exibidas, cache de 10 s compartilhado.
def _q(fn, padrao):
    try:
        return fn().data or padrao
    except Exception as e:
        st.warning(f"Falha ao consultar o banco: {e}")
        return padrao


@st.cache_data(ttl=10, show_spinner=False)
def carregar_bases():
    return _q(lambda: supabase.table("portarias_base").select("id, nome_padronizado, tipo_documento, numero_documento, orgao_emissor, data_assinatura")
              .order("data_assinatura", desc=True).execute(), [])


@st.cache_data(ttl=10, show_spinner=False)
def carregar_alteradoras():
    return _q(lambda: supabase.table("portarias_alteradoras").select("id, portaria_base_id, nome_padronizado, data_assinatura")
              .order("data_assinatura", desc=True).execute(), [])


@st.cache_data(ttl=10, show_spinner=False)
def carregar_atos():
    return _q(lambda: supabase.table("atos_importados").select(
        "id, nome_arquivo_original, tipo_documento, numero_documento, status, ato_base_referenciado_tipo, ato_base_referenciado_numero, estrutura_json, criado_em")
        .order("criado_em", desc=True).execute(), [])


@st.cache_data(ttl=10, show_spinner=False)
def carregar_versoes():
    try:
        return supabase.table("versoes_documentos").select("id, portaria_base_id, tipo_versao, descricao, alteradoras_aplicadas, criado_em, portarias_base(nome_padronizado)") \
            .order("criado_em", desc=True).execute().data or []
    except Exception:
        return []


@st.cache_data(ttl=10, show_spinner=False)
def carregar_memoria():
    return _q(lambda: supabase.table("memoria_de_correcoes").select("*").order("id", desc=True).limit(30).execute(), [])


def invalidar():
    for f in (carregar_bases, carregar_alteradoras, carregar_atos, carregar_versoes, carregar_memoria):
        f.clear()


def _json(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v or {}


def data_extenso(iso):
    try:
        dt = datetime.strptime(str(iso)[:10], "%Y-%m-%d")
        return f"{dt.day} de {MESES[dt.month - 1]} de {dt.year}"
    except Exception:
        return None


def extrair_data_referenciada(texto, numero_ref):
    if not texto or not numero_ref:
        return None
    try:
        padrao = re.compile(rf'{re.escape(numero_ref)}.*?(?:de|DE)\s+(\d{{1,2}})\s+(?:de|DE)\s+(\w+)\s+(?:de|DE)\s+(\d{{4}})', re.IGNORECASE | re.DOTALL)
        m = padrao.search(texto)
        if m:
            dia, mes_str, ano = m.groups()
            meses = {n: f"{i + 1:02d}" for i, n in enumerate(MESES)}
            mes = meses.get(mes_str.lower())
            if mes:
                return f"{ano}-{mes}-{int(dia):02d}"
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------------- ações
def _checkbox_cb(pend_id):
    concluido = st.session_state.get(f"chk_{pend_id}", False)
    try:
        supabase.table("atos_importados").update({"status": "concluido" if concluido else "pendente"}).eq("id", pend_id).execute()
        conc.auditar("pendencia_concluida" if concluido else "pendencia_reaberta", str(pend_id))
        invalidar()
    except Exception as e:
        st.session_state["_erro_hist"] = f"Erro ao atualizar: {e}"


@st.dialog("Confirmar exclusão")
def confirmar(titulo, acao, *args):
    st.markdown(f"Tem certeza que deseja excluir **{escape(titulo)}**? Esta ação não pode ser desfeita.", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("Cancelar", use_container_width=True):
        st.rerun()
    if c2.button("Excluir", type="primary", use_container_width=True, icon=":material/delete:"):
        try:
            acao(*args)
            invalidar()
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao excluir: {e}")


def _apagar_base(base_id, nome):
    repo.apagar_cascata(base_id, nome, conc.usuario_atual())


def _apagar_generico(tabela, _id, nome):
    supabase.table(tabela).delete().eq("id", _id).execute()
    conc.auditar(f"remover_{tabela}", nome)


if msg := st.session_state.pop("_erro_hist", None):
    st.error(msg)

# ----------------------------------------------------------------------------- dados
bases, alteradoras, atos = carregar_bases(), carregar_alteradoras(), carregar_atos()
identificados = [a for a in atos if a.get("status") == "identificado"]
pendencias = [a for a in atos if a.get("status") in ("pendente", "concluido")]
abertas = [a for a in pendencias if a.get("status") == "pendente"]

ui.kpis([
    ("Normas consolidadas", len(bases), "layers", "ok"),
    ("Alterações vinculadas", len(alteradoras), "link", "rosa"),
    ("Atos identificados", len(identificados), "file", "info"),
    ("Pendências abertas", len(abertas), "clock", "warn"),
])

c_busca, c_atual = st.columns([4, 1], vertical_alignment="bottom")
termo = c_busca.text_input("Buscar", placeholder="Buscar por nome, número ou órgão... ex.: Portaria 221, PGJM", icon=":material/search:", label_visibility="collapsed")
if c_atual.button("Atualizar", icon=":material/refresh:", use_container_width=True):
    invalidar()
    st.rerun()
tl = (termo or "").lower().strip()

tab_normas, tab_ident, tab_pend, tab_vers, tab_ia = st.tabs([
    f":material/layers: Normas ({len(bases)})", f":material/description: Identificados ({len(identificados)})",
    f":material/schedule: Pendências ({len(abertas)})", ":material/history: Versões", ":material/psychology: Aprendizado da IA"])

# ============================================================== NORMAS
with tab_normas:
    filtradas = [b for b in bases if not tl or tl in str(b.get("nome_padronizado", "")).lower() or tl in str(b.get("numero_documento", "")).lower()
                 or tl in str(b.get("orgao_emissor", "")).lower()]
    por_base = {}
    for a in alteradoras:
        por_base.setdefault(a.get("portaria_base_id"), []).append(a)
    if not filtradas:
        ui.vazio("Nenhuma norma encontrada", f"Nada para “{termo}”." if tl else "As normas consolidadas aparecerão aqui.", "archive")
    for pb in filtradas:
        base_id = pb["id"]
        alts = por_base.get(base_id, [])
        em_edicao = conc.registro().dono_da_trava(f"base:{pb.get('nome_padronizado')}", conc.id_sessao())
        titulo = f"{pb.get('nome_padronizado', f'Norma {base_id}')}"
        with st.expander(titulo, icon=":material/folder:"):
            if em_edicao:
                st.markdown(f'<div class="cn-aviso-trava">{ui.icone("users", 18)} {escape(em_edicao["usuario"])} está com esta norma aberta em Consolidar agora.</div>', unsafe_allow_html=True)
            c1, c2 = st.columns([4, 1.3])
            c1.markdown(f"**Documento:** {escape(str(pb.get('tipo_documento', '')))} {escape(str(pb.get('numero_documento', '')))}  \n"
                        f"**Órgão emissor:** {escape(str(pb.get('orgao_emissor', '')))}  \n**Assinatura:** {escape(str(pb.get('data_assinatura') or 'N/A'))}",
                        unsafe_allow_html=True)
            c1.markdown(ui.badge(f"{len(alts)} alteradora(s) aplicada(s)", "info" if alts else ""), unsafe_allow_html=True)
            if c2.button("Apagar cascata", key=f"del_base_{base_id}", type="primary", icon=":material/delete_forever:", use_container_width=True):
                confirmar(titulo, _apagar_base, base_id, titulo)
            # exportação sob demanda do estado consolidado salvo (antes: nada era gerado aqui)
            with c2.popover("Exportar", icon=":material/download:", use_container_width=True):
                chave = f"exp_{base_id}"
                if st.button("Preparar arquivos", key=f"prep_{base_id}", use_container_width=True):
                    try:
                        row = supabase.table("portarias_base").select("documento_consolidado_json").eq("id", base_id).execute().data[0]
                        estado = _json(row.get("documento_consolidado_json"))
                        st.session_state[chave] = {
                            "html_cons": exportacao.gerar_html_dinamico(estado, "consolidada"),
                            "html_alt": exportacao.gerar_html_dinamico(estado, "alterada"),
                            "pdf_cons": exportacao.gerar_pdf_dinamico(estado, "consolidada") if exportacao.HAS_WEASYPRINT else None,
                        }
                    except Exception as e:
                        st.error(f"Não foi possível gerar: {e}")
                arq = st.session_state.get(chave)
                if arq:
                    nome_arq = re.sub(r"[^\w.-]+", "_", titulo)
                    if arq.get("pdf_cons"):
                        st.download_button("PDF consolidada", arq["pdf_cons"], file_name=f"{nome_arq}_Cons.pdf", mime="application/pdf", key=f"dl_pdf_{base_id}", use_container_width=True)
                    st.download_button("HTML consolidada", arq["html_cons"], file_name=f"{nome_arq}_Cons.html", mime="text/html", key=f"dl_hc_{base_id}", use_container_width=True)
                    st.download_button("HTML alterada", arq["html_alt"], file_name=f"{nome_arq}_Alt.html", mime="text/html", key=f"dl_ha_{base_id}", use_container_width=True)
            if alts:
                st.markdown("##### Relacionamentos (atos alteradores)")
                for pa in alts:
                    ca1, ca2 = st.columns([4, 1.3], vertical_alignment="center")
                    ca1.markdown(f"{ui.icone('link', 15)} {escape(str(pa.get('nome_padronizado', '')))} "
                                 f"<span style='color:#64748B'>· {escape(str(pa.get('data_assinatura') or 'N/A'))}</span>", unsafe_allow_html=True)
                    if ca2.button("Desvincular", key=f"del_alt_{pa['id']}", icon=":material/link_off:", use_container_width=True):
                        confirmar(pa.get("nome_padronizado", "vínculo"), _apagar_generico, "portarias_alteradoras", pa["id"], pa.get("nome_padronizado", ""))
            else:
                st.caption("Nenhum ato alterador vinculado a esta norma.")

# ============================================================== IDENTIFICADOS
with tab_ident:
    ref_por_numero = {}
    for p in abertas:
        ref_por_numero.setdefault(str(p.get("ato_base_referenciado_numero") or "").strip().lower(), []).append(p)
    itens = []
    for it in identificados:
        est = _json(it.get("estrutura_json"))
        nome = est.get("nome_padronizado") or it.get("nome_arquivo_original", "Desconhecido")
        if tl and tl not in nome.lower() and tl not in str(it.get("numero_documento", "")).lower():
            continue
        itens.append((it, est, nome))
    if not itens:
        ui.vazio("Nenhum ato identificado", "Os atos lidos em Identificar e Cruzar aparecem aqui.", "file")
    for it, est, nome in itens:
        numero = (est.get("numero_documento") or it.get("numero_documento") or "").strip()
        refs = [p for k, ps in ref_por_numero.items() if numero and numero.lower() in k for p in ps]
        with st.expander(nome, icon=":material/description:"):
            c1, c2 = st.columns([4, 1.2])
            c1.markdown(f"**Tipo:** {escape(str(est.get('tipo_documento', '')))} · **Número:** {escape(numero)} · **Data:** {escape(str(est.get('data_assinatura', '')))}  \n"
                        f"**Arquivo:** {escape(str(it.get('nome_arquivo_original', 'N/A')))}", unsafe_allow_html=True)
            if refs:
                st.markdown(ui.badge(f"Referenciado por {len(refs)} pendência(s)", "warn"), unsafe_allow_html=True)
                for p in refs:
                    st.caption(f"• {p.get('nome_arquivo_original', 'N/A')}")
            else:
                st.markdown(ui.badge("Nenhuma pendência referencia este ato", "info"), unsafe_allow_html=True)
            if c2.button("Remover", key=f"del_ident_{it['id']}", icon=":material/delete:", use_container_width=True):
                confirmar(nome, _apagar_generico, "atos_importados", it["id"], nome)

# ============================================================== PENDÊNCIAS
with tab_pend:
    st.caption("Atos que aguardam a norma base. Marque como concluído depois de consolidar.")
    filtro = st.radio("Mostrar", ["Abertas", "Concluídas", "Todas"], horizontal=True, label_visibility="collapsed", key="filtro_pend")
    lista = [p for p in pendencias if filtro == "Todas" or (filtro == "Abertas") == (p.get("status") == "pendente")]
    if tl:
        lista = [p for p in lista if tl in str(p.get("nome_arquivo_original", "")).lower() or tl in str(p.get("ato_base_referenciado_numero", "")).lower()]
    if not lista:
        ui.vazio("Nada por aqui", "Nenhuma derivação nesta visão.", "check")
    for p in lista:
        pend_id = p["id"]
        tipo_ref, num_ref = p.get("ato_base_referenciado_tipo"), p.get("ato_base_referenciado_numero")
        est = _json(p.get("estrutura_json"))
        nome_deriv = est.get("nome_padronizado") or p.get("nome_arquivo_original", "Arquivo desconhecido")
        # CORREÇÃO: a versão original não buscava tipo_documento e, por isso, NUNCA encontrava a norma base.
        achada = None
        if tipo_ref and num_ref:
            for b in bases:
                if str(num_ref).strip().lower() in str(b.get("numero_documento", "")).lower() and str(b.get("tipo_documento", "")).upper() == str(tipo_ref).upper():
                    achada = b
                    break
        nome_base = achada["nome_padronizado"] if achada else (f"{tipo_ref} {num_ref}" if tipo_ref and num_ref else "Referência desconhecida")
        concluido = p.get("status") == "concluido"
        selo = ui.badge("Concluído", "ok") if concluido else (ui.badge("Base encontrada", "info", pulso=True) if achada else ui.badge("Base não encontrada", "warn"))
        with st.expander(f"{nome_deriv}  →  {nome_base}", icon=":material/task_alt:" if concluido else ":material/schedule:"):
            c1, c2, c3 = st.columns([3.2, 1.2, 1], vertical_alignment="center")
            c1.markdown(f"{selo}<br>**Arquivo:** {escape(str(p.get('nome_arquivo_original', 'N/A')))}<br>"
                        f"**Ato derivativo:** {escape(nome_deriv)}<br>**Ato base:** {escape(nome_base)}"
                        + ("" if achada else " <i>(não encontrado no banco)</i>"), unsafe_allow_html=True)
            if not achada and num_ref:
                try:
                    texto = supabase.table("atos_importados").select("texto_integra").eq("id", pend_id).execute().data[0].get("texto_integra", "")
                    d = data_extenso(extrair_data_referenciada(texto, num_ref))
                    if d:
                        c1.caption(f"Data do ato base extraída do texto: {d}")
                except Exception:
                    pass
            c2.checkbox("Concluído", value=concluido, key=f"chk_{pend_id}", on_change=_checkbox_cb, args=(pend_id,))
            if c3.button("", key=f"del_pend_{pend_id}", icon=":material/delete:", help="Remover pendência", use_container_width=True):
                confirmar(nome_deriv, _apagar_generico, "atos_importados", pend_id, nome_deriv)

# ============================================================== VERSÕES
with tab_vers:
    versoes = carregar_versoes()
    if not versoes:
        ui.vazio("Nenhuma versão salva", "Quando houver versões em versoes_documentos, elas aparecem aqui. Os arquivos só são gerados quando você pede.", "history")
    por_b = {}
    for v in versoes:
        por_b.setdefault(v["portaria_base_id"], []).append(v)
    for bid, lst in por_b.items():
        nome_b = (lst[0].get("portarias_base") or {}).get("nome_padronizado", f"Base {bid}")
        with st.expander(f"{nome_b} · {len(lst)} versão(ões)", icon=":material/folder:"):
            for v in lst:
                st.markdown(f"**{escape(str(v['tipo_versao']).upper())}** — {escape(str(v.get('descricao', '')))}  \n"
                            f"Alteradoras: {escape(', '.join(v.get('alteradoras_aplicadas') or []) or 'nenhuma')} · criada em {escape(str(v['criado_em']))}", unsafe_allow_html=True)
                chave = f"ver_{v['id']}"
                if st.button("Preparar arquivos", key=f"prepv_{v['id']}", icon=":material/build:"):
                    try:
                        estado = _json(supabase.table("versoes_documentos").select("estado_json").eq("id", v["id"]).execute().data[0].get("estado_json"))
                        st.session_state[chave] = {
                            "pdf_alt": exportacao.gerar_pdf_dinamico(estado, "alterada"), "pdf_cons": exportacao.gerar_pdf_dinamico(estado, "consolidada"),
                            "html_alt": exportacao.gerar_html_dinamico(estado, "alterada"), "html_cons": exportacao.gerar_html_dinamico(estado, "consolidada")}
                    except Exception as e:
                        st.error(f"Erro ao gerar arquivos para esta versão: {e}")
                if st.session_state.get(chave):
                    a = st.session_state[chave]
                    d = re.sub(r"[^\w.-]+", "_", str(v.get("descricao") or v["id"]))
                    cc = st.columns(4)
                    cc[0].download_button("PDF alterada", a["pdf_alt"], file_name=f"{d}_alterada.pdf", mime="application/pdf", key=f"vpa{v['id']}")
                    cc[1].download_button("PDF consolidada", a["pdf_cons"], file_name=f"{d}_consolidada.pdf", mime="application/pdf", key=f"vpc{v['id']}")
                    cc[2].download_button("HTML alterada", a["html_alt"], file_name=f"{d}_alterada.html", mime="text/html", key=f"vha{v['id']}")
                    cc[3].download_button("HTML consolidada", a["html_cons"], file_name=f"{d}_consolidada.html", mime="text/html", key=f"vhc{v['id']}")
                st.markdown("---")

# ============================================================== APRENDIZADO
with tab_ia:
    st.caption("Toda vez que alguém edita e salva um documento, a diferença entre o que a IA gerou e a correção é guardada aqui e usada nas próximas consolidações (compartilhado por toda a equipe).")
    mem = carregar_memoria()
    if not mem:
        ui.vazio("Nenhuma correção registrada", "As correções aparecem depois que alguém salva um documento editado.", "sparkles")
    for m in mem:
        with st.expander(f"Correção #{m.get('id')} · {str(m.get('data_registro') or m.get('created_at') or '')[:10]}", icon=":material/psychology:"):
            cA, cB = st.columns(2)
            cA.markdown("**Texto gerado pela IA**")
            cA.code(m.get("texto_ia") or "", language=None)
            cB.markdown("**Correção do usuário**")
            cB.code(m.get("texto_corrigido") or "", language=None)
            if st.button("Remover este aprendizado", key=f"del_mem_{m['id']}", icon=":material/delete:"):
                confirmar(f"correção #{m['id']}", _apagar_generico, "memoria_de_correcoes", m["id"], f"correção {m['id']}")
