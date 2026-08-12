import streamlit as st
import json
from supabase import create_client, Client
from typing import Optional

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(page_title="Histórico de Normas", page_icon="🗄️", layout="wide", initial_sidebar_state="collapsed")

# ----------------- PROTEÇÃO DE ACESSO -----------------
if "autenticado" not in st.session_state or not st.session_state.autenticado:
    st.warning("⚠️ Acesso negado. Por favor, faça o login na página inicial.")
    st.stop()

# ----------------- CSS GLOBAL (UX/UI PREMIUM) -----------------
st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    .block-container { padding-top: 2rem; max-width: 1400px; }
    .main-header {
        background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
        padding: 2.5rem 2rem;
        border-radius: 12px;
        color: white;
        text-align: center;
        box-shadow: 0 10px 20px rgba(0,0,0,0.1);
        margin-bottom: 2rem;
    }
    .main-header h1 { color: #00FF87; font-weight: 800; font-size: 2.5rem; margin-bottom: 0; letter-spacing: -0.5px; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header"><h1>🗄️ Histórico de Banco de Dados</h1></div>', unsafe_allow_html=True)

# --- MENU DE NAVEGAÇÃO SUPERIOR ALINHADO ---
nav_container = st.container()
with nav_container:
    col_home, col_usr, col_logout, _ = st.columns([1.5, 1.5, 1, 4])
    with col_home:
        st.page_link("app.py", label="⬅️ Voltar ao Início", use_container_width=True)
    with col_usr:
        try:
            st.page_link("pages/usuarios.py", label="👥 Painel de Usuários", use_container_width=True)
        except:
            st.button("👥 Painel de Usuários", disabled=True, use_container_width=True)
    with col_logout:
        if st.button("Sair", key="btn_sair_hist", type="primary", use_container_width=True):
            st.session_state.autenticado = False
            st.rerun()

st.markdown("---")

# ----------------- CONEXÃO SUPABASE -----------------
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
    st.error("⚠️ Falha na conexão com o Supabase.")
    st.stop()

# --- BARRA DE BUSCA ---
col_busca, _ = st.columns([2, 1])
with col_busca:
    termo_busca = st.text_input("🔍 Buscar norma (nome, número ou órgão)...", placeholder="Digite para filtrar...")

st.markdown("---")

res_base = supabase.table("portarias_base").select("*").order("data_assinatura", desc=True).execute()
portarias_base = res_base.data if res_base.data else []

if termo_busca:
    t = termo_busca.lower()
    portarias_base = [
        p for p in portarias_base 
        if t in str(p.get('nome_padronizado', '')).lower() 
        or t in str(p.get('numero_documento', '')).lower()
        or t in str(p.get('orgao_emissor', '')).lower()
    ]

if not portarias_base:
    st.info("Nenhuma norma encontrada.")
else:
    st.caption(f"**{len(portarias_base)}** norma(s) listada(s).")
    for pb in portarias_base:
        base_id = pb['id']
        nome_padrao = pb.get('nome_padronizado', f"Norma ID {base_id}")
        
        with st.expander(f"📁 {nome_padrao} | Data: {pb.get('data_assinatura', 'N/A')}"):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**Documento:** {pb.get('tipo_documento', '')} {pb.get('numero_documento', '')}<br>**Órgão:** {pb.get('orgao_emissor', '')}", unsafe_allow_html=True)
            with c2:
                if st.button("🗑️ Apagar Cascata", key=f"del_base_{base_id}", type="primary", use_container_width=True):
                    try:
                        supabase.table("portarias_alteradoras").delete().eq("portaria_base_id", base_id).execute()
                        supabase.table("portarias_base").delete().eq("id", base_id).execute()
                        st.success("Excluído com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")

            res_alt = supabase.table("portarias_alteradoras").select("*").eq("portaria_base_id", base_id).order("data_assinatura", desc=True).execute()
            if res_alt.data:
                st.markdown("#### 🔗 Portarias Alteradoras (Cascata)")
                for pa in res_alt.data:
                    ca1, ca2 = st.columns([4, 1])
                    with ca1: st.write(f"- {pa.get('nome_padronizado', '')} ({pa.get('data_assinatura', 'N/A')})")
                    with ca2:
                        if st.button("❌ Desvincular", key=f"del_alt_{pa['id']}", use_container_width=True):
                            try:
                                supabase.table("portarias_alteradoras").delete().eq("id", pa['id']).execute()
                                st.rerun()
                            except Exception as e: st.error(f"Erro: {e}")
            else:
                st.info("Nenhuma alteradora vinculada.")
