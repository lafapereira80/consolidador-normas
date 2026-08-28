import streamlit as st
import json
from supabase import create_client, Client
from typing import Optional
from collections import defaultdict

# Esconde a barra lateral desde o carregamento
st.set_page_config(page_title="Histórico de Normas", page_icon="🗄️", layout="wide", initial_sidebar_state="collapsed")

# PROTEÇÃO DE ACESSO
if "autenticado" not in st.session_state or not st.session_state.autenticado:
    st.warning("⚠️ Acesso negado. Você precisa fazer login na página principal para acessar o histórico.")
    st.page_link("app.py", label="Ir para a Tela de Login", icon="🔒")
    st.stop()

# BLOQUEIO DO MENU LATERAL E ESTILOS
st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 20px 20px;
        border-radius: 12px;
        color: white;
        text-align: center;
        margin-bottom: 25px;
    }
    .main-header h1 { color: #00FF87; font-weight: 800; font-size: 2.2rem; margin-bottom: 0px; }
</style>
<div class="main-header">
    <h1>🗄️ Histórico e Gerenciamento de Banco de Dados</h1>
</div>
""", unsafe_allow_html=True)

# --- MENU DE NAVEGAÇÃO SUPERIOR FIXO ---
col_home, col_usr, col_logout, col_vazio = st.columns([1.5, 1.5, 1, 4])

with col_home:
    st.page_link("app.py", label="Início (Upload)", icon="⬅️")

with col_usr:
    try:
        st.page_link("pages/usuarios.py", label="Usuários", icon="👥")
    except:
        st.markdown('<a href="usuarios" target="_top" style="display: block; text-align: center; background-color: #f0f2f6; border: 1px solid #d0d4dc; color: #31333F !important; padding: 0.5rem; border-radius: 0.5rem; text-decoration: none; font-weight: 500;">👥 Usuários</a>', unsafe_allow_html=True)

with col_logout:
    if st.button("Sair", key="btn_sair_hist", type="secondary", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

st.markdown("---")

# CONEXÃO COM BANCO DE DADOS
@st.cache_resource
def init_supabase() -> Optional[Client]:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception:
        return None

supabase = init_supabase()

if not supabase:
    st.error("⚠️ Não foi possível conectar ao Supabase.")
    st.stop()

# --- BARRA DE BUSCA ---
c_busca, c_vazio = st.columns([2, 1])
with c_busca:
    termo_busca = st.text_input("🔍 Buscar norma (nome, número ou órgão)...", placeholder="Ex: Portaria 221, PGJM...")

st.markdown("---")

res_base = supabase.table("portarias_base").select("*").order("data_assinatura", desc=True).execute()
portarias_base = res_base.data if res_base.data else []

if termo_busca:
    termo_lower = termo_busca.lower()
    portarias_base = [
        pb for pb in portarias_base 
        if termo_lower in str(pb.get('nome_padronizado', '')).lower() 
        or termo_lower in str(pb.get('numero_documento', '')).lower()
        or termo_lower in str(pb.get('orgao_emissor', '')).lower()
    ]

if not portarias_base:
    if termo_busca:
        st.warning(f"Nenhum resultado encontrado para a busca: **{termo_busca}**.")
    else:
        st.info("Nenhuma norma encontrada no banco de dados.")
else:
    st.caption(f"Exibindo {len(portarias_base)} norma(s) encontrada(s).")
    
    for pb in portarias_base:
        base_id = pb['id']
        nome_padrao = pb.get('nome_padronizado', f"Norma ID {base_id}")
        
        with st.expander(f"📁 {nome_padrao} (Data: {pb.get('data_assinatura', 'N/A')})"):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**Documento:** {pb.get('tipo_documento', '')} {pb.get('numero_documento', '')}")
                st.markdown(f"**Órgão Emissor:** {pb.get('orgao_emissor', '')}")
            
            with c2:
                if st.button(f"🗑️ Apagar Cascata Completa", key=f"del_base_{base_id}", type="primary"):
                    try:
                        supabase.table("portarias_alteradoras").delete().eq("portaria_base_id", base_id).execute()
                        supabase.table("portarias_base").delete().eq("id", base_id).execute()
                        st.success("Cascata apagada com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao apagar: {e}")

            res_alt = supabase.table("portarias_alteradoras").select("*").eq("portaria_base_id", base_id).order("data_assinatura", desc=True).execute()
            alteradoras = res_alt.data if res_alt.data else []
            
            if alteradoras:
                st.markdown("#### 🔗 Relacionamentos (Portarias Alteradoras)")
                for pa in alteradoras:
                    alt_id = pa['id']
                    ca1, ca2 = st.columns([4, 1])
                    with ca1:
                        st.write(f"- {pa.get('nome_padronizado', '')} (Assinatura: {pa.get('data_assinatura', 'N/A')})")
                    with ca2:
                        if st.button("❌ Desvincular", key=f"del_alt_{alt_id}"):
                            try:
                                supabase.table("portarias_alteradoras").delete().eq("id", alt_id).execute()
                                st.success("Relacionamento apagado com sucesso!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao apagar relacionamento: {e}")
            else:
                st.info("Nenhuma portaria alteradora vinculada a esta norma base.")

# =====================================================================
# SEÇÃO: DERIVAÇÕES PENDENTES
# =====================================================================
st.markdown("---")
st.markdown("### 📋 Derivações Pendentes")
st.caption("Atos que foram importados como derivados, mas cuja norma base ainda não foi cadastrada ou processada. Quando a base for cadastrada e a análise executada, esses registros serão automaticamente vinculados e sairão da lista de pendências.")

try:
    res_pend = supabase.table("atos_importados").select("*").eq("status", "pendente").order("criado_em", desc=True).execute()
    pendencias = res_pend.data if res_pend.data else []
    if not pendencias:
        st.info("Nenhuma derivação pendente no momento.")
    else:
        st.caption(f"Exibindo {len(pendencias)} pendência(s).")
        for p in pendencias:
            with st.expander(f"🕒 Pendência: {p.get('nome_arquivo_original', 'N/A')} - Referência: {p.get('ato_base_referenciado_tipo', 'N/A')} {p.get('ato_base_referenciado_numero', 'N/A')}"):
                st.markdown(f"**Arquivo original:** {p.get('nome_arquivo_original', 'N/A')}")
                st.markdown(f"**Referência de base:** {p.get('ato_base_referenciado_tipo', 'N/A')} {p.get('ato_base_referenciado_numero', 'N/A')}")
                st.markdown(f"**Status:** {p.get('status', 'pendente')}")
                if st.button("🗑️ Remover pendência", key=f"del_pend_{p['id']}"):
                    try:
                        supabase.table("atos_importados").delete().eq("id", p['id']).execute()
                        st.success("Pendência removida com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao remover pendência: {e}")
except Exception as e:
    st.warning(f"Não foi possível carregar as derivações pendentes: {e}")

# =====================================================================
# SEÇÃO: VERSÕES SALVAS (SNAPSHOTS)
# =====================================================================
st.markdown("---")
st.markdown("### 📚 Versões Salvas")
st.caption("Histórico de todas as versões (alterada e consolidada) geradas para cada norma. Permite resgatar qualquer combinação de alterações e exportar em PDF ou HTML.")

try:
    res_versoes = supabase.table("versoes_documentos").select("*, portarias_base(nome_padronizado)").order("criado_em", desc=True).execute()
    versoes = res_versoes.data if res_versoes.data else []
    if not versoes:
        st.info("Nenhuma versão salva até o momento.")
    else:
        versoes_por_base = defaultdict(list)
        for v in versoes:
            base_id = v['portaria_base_id']
            versoes_por_base[base_id].append(v)

        for base_id, lista_versoes in versoes_por_base.items():
            nome_base = lista_versoes[0]['portarias_base']['nome_padronizado'] if lista_versoes[0].get('portarias_base') else f"Base ID {base_id}"
            with st.expander(f"📁 {nome_base}"):
                st.markdown(f"**Total de versões salvas:** {len(lista_versoes)}")
                for v in lista_versoes:
                    descricao = v.get('descricao', '')
                    alteradoras = v.get('alteradoras_aplicadas') or []
                    alteradoras_str = ", ".join(alteradoras) if alteradoras else "Nenhuma"
                    st.markdown(f"**Versão:** {v['tipo_versao'].upper()} - {descricao}")
                    st.markdown(f"**Alteradoras aplicadas:** {alteradoras_str}")
                    st.markdown(f"**Criada em:** {v['criado_em']}")

                    col_pdf_alt, col_pdf_cons, col_html_alt, col_html_cons = st.columns(4)
                    estado = v['estado_json']
                    try:
                        # Importa funções de exportação do app.py (ou define localmente)
                        # Para evitar import circular, definimos aqui cópias das funções necessárias
                        # (gerar_html_dinamico, gerar_pdf_dinamico)
                        # Elas são idênticas às do app.py.
                        def gerar_html_dinamico(consolidacao_dict, tipo_versao):
                            titulo_doc = f"Versão {'Alterada' if tipo_versao=='alterada' else 'Consolidada'}"
                            html = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{titulo_doc}</title><style>@page{{size:A4;margin:2.5cm 2cm;@bottom-center{{content:'Nota: Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial.';font-size:9pt;font-style:italic;color:#333;}}}}body{{font-family:'Times New Roman',serif;font-size:11pt;line-height:1.5;text-align:justify;}}.topo{{text-align:center;color:#444;font-size:10pt;font-weight:bold;margin-bottom:20px;text-transform:uppercase;}}.orgaos{{text-align:center;font-weight:bold;margin-bottom:25px;}}.titulo{{text-align:center;font-weight:bold;margin-bottom:20px;}}.ementa{{text-align:justify;margin-left:45%;margin-bottom:25px;font-weight:normal;}}.preambulo{{text-align:justify;margin-bottom:12px;text-indent:0;}}.dispositivo{{text-align:justify;text-indent:40px;margin-bottom:12px;}}.capitulo{{text-align:center;font-weight:bold;margin-top:20px;margin-bottom:12px;text-transform:uppercase;}}.assinatura{{text-align:center;font-weight:bold;margin-top:50px;margin-bottom:20px;}}table{{width:100%;border-collapse:collapse;margin-top:15px;margin-bottom:15px;}}td,th{{border:1px solid black;padding:6px;text-align:left;vertical-align:middle;}}strike,s,del{{text-decoration:line-through;}}b,strong{{font-weight:bold;}}i,em{{font-style:italic;}}font[color='red'],span[style*='color: red'],span[style*='color:rgb(230']{{color:red!important;}}</style></head><body><div class='topo'>{titulo_doc}</div><div class='orgaos'>{consolidacao_dict.get('orgaos_emissores','')}</div><div class='titulo'>{consolidacao_dict.get('titulo_portaria','')}</div><div class='ementa'>{consolidacao_dict.get('ementa','')}</div><div class='preambulo'>{consolidacao_dict.get('preambulo','')}</div>"
                            for item in consolidacao_dict.get('dispositivos', []):
                                t = (item.get('tipo') or '').lower()
                                t_prin = item.get(f'texto_principal_{tipo_versao}', '')
                                if 'capitulo' in t or 'anexo' in t:
                                    html += f"<div class='capitulo'>{t_prin}</div>"
                                    if not item.get('is_tabela'):
                                        continue
                                else:
                                    if t_prin:
                                        for p in t_prin.split('<br/>'):
                                            if p.strip(): html += f"<div class='dispositivo'>{p.strip()}</div>"
                                if item.get('is_tabela'):
                                    linhas = item.get(f'tabela_{tipo_versao}') or []
                                    if linhas:
                                        html += "<table>"
                                        for linha in linhas:
                                            html += "<tr>"
                                            for celula in linha:
                                                html += f"<td>{celula}</td>"
                                            html += "</tr>"
                                        html += "</table>"
                                    t_pos = item.get(f'texto_pos_tabela_{tipo_versao}')
                                    if t_pos:
                                        for p in t_pos.split('<br/>'):
                                            if p.strip(): html += f"<div class='dispositivo'>{p.strip()}</div>"
                            html += f"<div class='assinatura'>{consolidacao_dict.get('assinatura_nome','')}<br>{consolidacao_dict.get('assinatura_cargo','')}</div></body></html>"
                            return html

                        def gerar_pdf_dinamico(consolidacao_dict, tipo_versao):
                            from weasyprint import HTML
                            html_str = gerar_html_dinamico(consolidacao_dict, tipo_versao)
                            buffer = io.BytesIO()
                            HTML(string=html_str).write_pdf(buffer)
                            buffer.seek(0)
                            return buffer.getvalue()

                        pdf_alt = gerar_pdf_dinamico(estado, "alterada")
                        pdf_cons = gerar_pdf_dinamico(estado, "consolidada")
                        html_alt = gerar_html_dinamico(estado, "alterada")
                        html_cons = gerar_html_dinamico(estado, "consolidada")

                        with col_pdf_alt:
                            st.download_button("📄 PDF Alterada", pdf_alt, file_name=f"{descricao}_alterada.pdf", mime="application/pdf")
                        with col_pdf_cons:
                            st.download_button("📄 PDF Consolidada", pdf_cons, file_name=f"{descricao}_consolidada.pdf", mime="application/pdf")
                        with col_html_alt:
                            st.download_button("🌐 HTML Alterada", html_alt, file_name=f"{descricao}_alterada.html", mime="text/html")
                        with col_html_cons:
                            st.download_button("🌐 HTML Consolidada", html_cons, file_name=f"{descricao}_consolidada.html", mime="text/html")
                    except Exception as e:
                        st.error(f"Erro ao gerar arquivos para esta versão: {e}")
                    st.markdown("---")
except Exception as e:
    st.warning(f"Não foi possível carregar as versões: {e}")

st.markdown("---")
st.markdown("### 🧠 Aprendizado da IA (correções registradas)")
st.caption("Toda vez que você edita e salva um documento, a diferença entre o que a IA gerou e o que você corrigiu é guardada aqui e usada como referência nas próximas consolidações.")
try:
    res_mem = supabase.table("memoria_de_correcoes").select("*").order("id", desc=True).limit(30).execute()
    memorias = res_mem.data if res_mem.data else []
    if not memorias:
        st.info("Nenhuma correção registrada ainda.")
    else:
        st.caption(f"Exibindo as {len(memorias)} correções mais recentes.")
        for m in memorias:
            with st.expander(f"Correção de {m.get('data_registro', 'N/A')}"):
                cA, cB = st.columns(2)
                with cA:
                    st.markdown("**❌ Texto gerado pela IA**")
                    st.code(m.get('texto_ia') or "", language=None)
                with cB:
                    st.markdown("**✅ Correção do usuário**")
                    st.code(m.get('texto_corrigido') or "", language=None)
                if st.button("🗑️ Remover este aprendizado", key=f"del_mem_{m['id']}"):
                    try:
                        supabase.table("memoria_de_correcoes").delete().eq("id", m['id']).execute()
                        st.success("Removido.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao remover: {e}")
except Exception as e:
    st.warning(f"Não foi possível carregar o histórico de aprendizado: {e}")
