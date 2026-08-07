import streamlit as st
from utils import analisar_lote_arquivos, gerar_pdf_dinamico, gerar_docx_dinamico, salvar_no_supabase

st.set_page_config(page_title="Autopilot Normativo", layout="wide")

# Cabeçalho com navegação rápida para a página de histórico
col_titulo, col_link = st.columns([3, 1])
with col_titulo:
    st.title("⚖️ Autopilot: Consolidador Normativo & Histórico")
with col_link:
    st.markdown("<br>", unsafe_allow_html=True)
    # Link direto para a página dentro da pasta pages/
    st.page_link("pages/1_Historico.py", label="📜 Acessar Histórico", icon="🗄️")

st.markdown("Arraste todos os documentos normativos de uma vez. O sistema cruzará os dados considerando o histórico acumulado salvo no Supabase.")
st.markdown("---")

# Configuração da API Key
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
    elif not arquivos_enviados or len(arquivos_enviados) < 1:
        st.warning("⚠️ Envie pelo menos um arquivo.")
    else:
        with st.spinner("🧠 Analisando lote, cruzando com histórico do Supabase..."):
            try:
                resultados = analisar_lote_arquivos(arquivos_enviados, api_key.strip())
                st.session_state.dados_processados = resultados
                st.success("✨ Análise concluída com sucesso!")
            except Exception as e:
                st.error(f"❌ Erro no processamento: {e}")

if st.session_state.dados_processados is not None:
    st.markdown("---")
    dados = st.session_state.dados_processados
    consolidacoes = dados.get("consolidacoes_geradas", [])
    avulsos = dados.get("arquivos_nao_alterados", [])
    
    if len(consolidacoes) > 0:
        st.header("📑 Documentos Consolidados Prontos")
        for i, cons in enumerate(consolidacoes):
            with st.expander(f"📁 **{cons['nome_portaria_base']}** ({cons['ano_portaria_base']}) atualizada pela **{cons['nome_portaria_alteradora']}** ({cons['ano_portaria_alteradora']})", expanded=True):
                st.info(f"**Cabeçalho Calculado (Cadeia):** `{cons['cabecalho_complemento']}`")
                
                if st.button(f"💾 Salvar no Histórico Supabase", key=f"btn_sup_{i}"):
                    sucesso, msg = salvar_no_supabase(cons)
                    if sucesso:
                        st.success("Histórico salvo/atualizado com sucesso no Supabase!")
                    else:
                        st.error(f"Erro: {msg}")
                
                pdf_alt_bytes = gerar_pdf_dinamico(cons, "alterada")
                pdf_cons_bytes = gerar_pdf_dinamico(cons, "consolidada")
                docx_alt_bytes = gerar_docx_dinamico(cons, "alterada")
                docx_cons_bytes = gerar_docx_dinamico(cons, "consolidada")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("#### Versão Alterada")
                    st.download_button("Baixar PDF", data=pdf_alt_bytes, file_name=f"Alterada_{i}.pdf", mime="application/pdf", key=f"pdf_alt_{i}")
                    st.download_button("Baixar DOCX", data=docx_alt_bytes, file_name=f"Alterada_{i}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"docx_alt_{i}")
                with c2:
                    st.markdown("#### Versão Consolidada")
                    st.download_button("Baixar PDF", data=pdf_cons_bytes, file_name=f"Consolidada_{i}.pdf", mime="application/pdf", key=f"pdf_cons_{i}")
                    st.download_button("Baixar DOCX", data=docx_cons_bytes, file_name=f"Consolidada_{i}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"docx_cons_{i}")

    if len(avulsos) > 0:
        st.header("🗂️ Arquivos Sem Alteração Detectada")
        for avulso in avulsos:
            st.warning(f"**Arquivo:** `{avulso.get('nome_arquivo')}` | **Portaria:** {avulso.get('nome_portaria_identificada')}")

    st.markdown("---")
    if st.button("🔄 Nova Análise"):
        st.session_state.dados_processados = None
        st.rerun()
