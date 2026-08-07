import streamlit as st
import json
from supabase import create_client, Client
from typing import Optional

st.set_page_config(page_title="Histórico de Normas", page_icon="🗄️", layout="wide")

# PROTEÇÃO DE ACESSO
if "autenticado" not in st.session_state or not st.session_state.autenticado:
    st.warning("⚠️ Acesso negado. Você precisa fazer login na página principal para acessar o histórico.")
    st.page_link("app.py", label="Ir para a Tela de Login", icon="🔒")
    st.stop()

st.markdown("""
<style>
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
