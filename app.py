import streamlit as st
from utils import analisar_lote_arquivos, gerar_pdf_dinamico, gerar_docx_dinamico, salvar_no_supabase

st.set_page_config(page_title="Autopilot Normativo", layout="wide")

# Barra lateral com link rápido de navegação
with st.sidebar:
    st.header("Navegação")
    st.page_link("pages/1_Historico.py", label="Acessar Histórico", icon="🗄️")
    st.markdown("---")

# Cabeçalho principal com link direto
col_titulo, col_link = st.columns([3, 1])
with col_titulo:
    st.title("⚖️ Autopilot: Consolidador Normativo")
with col_link:
    st.markdown("<br>", unsafe_allow_html=True)
    st.page_link("pages/1_Historico.py", label="Ver Histórico Supabase", icon="🗄️")

st.markdown("Arraste os arquivos normativos. O sistema cruzará os dados considerando o histórico salvo no Supabase.")
st.markdown("---")

# Configuração da API
api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    with st.sidebar:
        st.header("Configuração de IA")
        api_key = st.text_input("Chave da API do Google GenAI", type="password")

arquivos_enviados = st.file_uploader("📥 Arraste os arquivos (PDF ou DOCX)", type=["pdf", "docx"], accept_multiple_files=True)

if "dados_processados" not in st.session_state:
    st.session_state.dados_processados = None

if st.button("🚀 Iniciar Análise Autopilot", type="primary", use_container_width=True):
    if not api_key:
        st.error("⚠️ Insira sua chave da API do Google GenAI.")
    elif not arquivos_enviados:
        st.warning("⚠️ Envie pelo menos um arquivo.")
    else:
        with st.spinner("🧠 Analisando com contexto do histórico..."):
            try:
                resultados = analisar_lote_arquivos(arquivos_enviados, api_key.strip())
                st.session_state.dados_processados = resultados
                st.success("✨ Análise concluída!")
            except Exception as e:
                st.error(f"❌ Erro: {e}")

if st.session_state.dados_processados:
    st.markdown("---")
    consolidacoes = st.session_state.dados_processados.get("consolidacoes_geradas", [])
    avulsos = st.session_state.dados_processados.get("arquivos_nao_alterados", [])
    
    if len(consolidacoes) > 0:
        st.header("📑 Documentos Consolidados Prontos")
        for i, cons in enumerate(consolidacoes):
            with st.expander(f"📁 **{cons['nome_portaria_base']}** ({cons['ano_portaria_base']}) atualizada pela **{cons['nome_portaria_alteradora']}** ({cons['ano_portaria_alteradora']})", expanded=True):
                st.info(f"**Cadeia:** {cons['cabecalho_complemento']}")
                
                if st.button(f"💾 Salvar no Histórico", key=f"btn_{i}"):
                    sucesso, msg = salvar_no_supabase(cons)
                    if sucesso:
                        st.success("Histórico salvo/atualizado com sucesso no Supabase!")
                    else:
                        st.error(f"Erro: {msg}")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("#### Versão Alterada")
                    st.download_button("Baixar PDF", data=gerar_pdf_dinamico(cons, "alterada"), file_name=f"Alt_{i}.pdf", mime="application/pdf", key=f"pdf_alt_{i}")
                    st.download_button("Baixar DOCX", data=gerar_docx_dinamico(cons, "alterada"), file_name=f"Alt_{i}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"docx_alt_{i}")
                with c2:
                    st.markdown("#### Versão Consolidada")
                    st.download_button("Baixar PDF", data=gerar_pdf_dinamico(cons, "consolidada"), file_name=f"Cons_{i}.pdf", mime="application/pdf", key=f"pdf_cons_{i}")
                    st.download_button("Baixar DOCX", data=gerar_docx_dinamico(cons, "consolidada"), file_name=f"Cons_{i}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"docx_cons_{i}")

    if len(avulsos) > 0:
        st.header("🗂️ Arquivos Sem Alteração Detectada")
        for avulso in avulsos:
            st.warning(f"**Arquivo:** `{avulso.get('nome_arquivo')}` | **Portaria:** {avulso.get('nome_portaria_identificada')}")

    st.markdown("---")
    if st.button("🔄 Nova Análise"):
        st.session_state.dados_processados = None
        st.rerun()
