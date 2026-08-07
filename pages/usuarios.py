import streamlit as st
import hashlib
import time
from supabase import create_client, Client
from typing import Optional

# Esconde a barra lateral desde o carregamento
st.set_page_config(page_title="Gerenciar Usuários", page_icon="👥", layout="wide", initial_sidebar_state="collapsed")

# PROTEÇÃO DE ACESSO
if "autenticado" not in st.session_state or not st.session_state.autenticado:
    st.warning("⚠️ Acesso negado. Você precisa fazer login na página principal para acessar o painel de usuários.")
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
    <h1>👥 Gerenciamento de Usuários</h1>
</div>
""", unsafe_allow_html=True)

# --- MENU DE NAVEGAÇÃO SUPERIOR FIXO ---
col_home, col_hist, col_logout, col_vazio = st.columns([1.5, 1.5, 1, 4])

with col_home:
    st.page_link("app.py", label="Início (Upload)", icon="⬅️")

with col_hist:
    try:
        st.page_link("pages/historico.py", label="Histórico", icon="🗄️")
    except:
        st.markdown('<a href="historico" target="_top" style="display: block; text-align: center; background-color: #f0f2f6; border: 1px solid #d0d4dc; color: #31333F !important; padding: 0.5rem; border-radius: 0.5rem; text-decoration: none; font-weight: 500;">🗄️ Histórico</a>', unsafe_allow_html=True)

with col_logout:
    if st.button("Sair", key="btn_sair_usr", type="secondary", use_container_width=True):
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

def gerar_hash(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

tab_lista, tab_novo = st.tabs(["📋 Lista de Usuários", "➕ Cadastrar Novo Usuário"])

# --- ABA 1: LISTAGEM E EDIÇÃO ---
with tab_lista:
    st.markdown("### Usuários Cadastrados no Sistema")
    try:
        res = supabase.table("usuarios").select("*").order("id").execute()
        usuarios = res.data if res.data else []
    except Exception as e:
        st.error(f"Erro ao carregar usuários: {e}")
        usuarios = []

    if not usuarios:
        st.info("Nenhum usuário encontrado.")
    else:
        for usr in usuarios:
            user_id = usr['id']
            username = usr['username']
            data_criacao = usr.get('created_at', 'N/A')
            if data_criacao != 'N/A':
                data_criacao = data_criacao[:10]

            with st.expander(f"👤 {username} (Criado em: {data_criacao})"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**🔑 Redefinir Senha**")
                    with st.form(key=f"form_senha_{user_id}"):
                        nova_senha = st.text_input("Nova Senha", type="password", key=f"ns_{user_id}")
                        if st.form_submit_button("Atualizar Senha", type="primary"):
                            if nova_senha.strip():
                                hash_novo = gerar_hash(nova_senha)
                                try:
                                    supabase.table("usuarios").update({"password_hash": hash_novo}).eq("id", user_id).execute()
                                    st.success(f"Senha de '{username}' atualizada com sucesso!")
                                except Exception as e:
                                    st.error(f"Erro ao atualizar: {e}")
                            else:
                                st.warning("A senha não pode ficar em branco.")
                with c2:
                    st.markdown("**🗑️ Excluir Conta**")
                    if username.lower() == 'admin':
                        st.info("⚠️ O usuário 'admin' principal está protegido contra exclusão para garantir seu acesso contínuo ao sistema.")
                    else:
                        if st.button(f"Excluir '{username}'", key=f"del_usr_{user_id}"):
                            try:
                                supabase.table("usuarios").delete().eq("id", user_id).execute()
                                st.success(f"Usuário '{username}' apagado permanentemente!")
                                time.sleep(1.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao excluir: {e}")

# --- ABA 2: CRIAÇÃO ---
with tab_novo:
    st.markdown("### ➕ Criar Nova Conta de Acesso")
    with st.form("form_novo_usuario"):
        novo_login = st.text_input("Nome de Usuário (Login)", placeholder="Ex: joao.silva")
        nova_senha_input = st.text_input("Senha de Acesso", type="password", placeholder="Digite uma senha segura")
        btn_criar = st.form_submit_button("Cadastrar Usuário", type="primary", use_container_width=True)

        if btn_criar:
            if not novo_login.strip() or not nova_senha_input.strip():
                st.warning("Preencha todos os campos corretamente.")
            else:
                hash_criado = gerar_hash(nova_senha_input)
                try:
                    supabase.table("usuarios").insert({
                        "username": novo_login.strip(),
                        "password_hash": hash_criado
                    }).execute()
                    st.success(f"✅ Usuário '{novo_login}' criado com sucesso! Ele já pode acessar o sistema.")
                except Exception as e:
                    mensagem_erro = str(e).lower()
                    if "duplicate key" in mensagem_erro or "unique constraint" in mensagem_erro:
                        st.error(f"❌ O nome de usuário '{novo_login}' já está em uso.")
                    else:
                        st.error(f"❌ Ocorreu um erro interno: {e}")
