import streamlit as st
from utils import analisar_lote_arquivos, gerar_pdf_dinamico, gerar_docx_dinamico, salvar_no_supabase

st.set_page_config(page_title="Autopilot Normativo", layout="wide")

st.title("⚖️ Autopilot: Consolidador Normativo")
st.markdown("Arraste os arquivos normativos. O sistema cruza os dados com o histórico acumulado do Supabase.")
st.markdown("---")

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
        with st.spinner("🧠 Analisando lote e consultando histórico..."):
            try:
                resultados = analisar_lote_arquivos(arquivos_enviados, api_key.strip())
                st.session_state.dados_processados = resultados
                st.success("✨ Análise concluída!")
            except Exception as e:
                st.error(f"❌ Erro: {e}")

if st.session_state.dados_processados:
    st.markdown("---")
    consolidacoes = st.session_state.dados_processados.get("consolidacoes_geradas", [])
    for i, cons in enumerate(consolidacoes):
        with st.expander(f"📁 **{cons['nome_portaria_base']}** ({cons['ano_portaria_base']})", expanded=True):
            st.info(f"**Cadeia:** {cons['cabecalho_complemento']}")
            if st.button(f"💾 Salvar no Histórico", key=f"btn_{i}"):
                sucesso, msg = salvar_no_supabase(cons)
                if sucesso: st.success("Salvo com sucesso!")
                else: st.error(f"Erro: {msg}")
            
            c1, c2 = st.columns(2)
            c1.download_button("Baixar PDF Alterada", data=gerar_pdf_dinamico(cons, "alterada"), file_name=f"Alt_{i}.pdf", mime="application/pdf", key=f"pdf_alt_{i}")
            c2.download_button("Baixar PDF Consolidada", data=gerar_pdf_dinamico(cons, "consolidada"), file_name=f"Cons_{i}.pdf", mime="application/pdf", key=f"pdf_cons_{i}")
