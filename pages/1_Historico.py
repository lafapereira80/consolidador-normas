import streamlit as st
import sys
import os

# Adiciona o diretório pai ao path para encontrar o utils.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import init_supabase

st.set_page_config(page_title="Histórico", layout="wide")
st.title("🗄️ Histórico e Gestão de Portarias")

supabase = init_supabase()

if not supabase:
    st.error("⚠️ Conexão Supabase não configurada.")
else:
    # Consulta direta
    try:
        response = supabase.table("portarias_base").select("*, portarias_alteradoras(*)").order("ano_criacao", desc=True).execute()
        for p in response.data:
            with st.expander(f"📌 {p['nome_portaria']} ({p['ano_criacao']})"):
                st.write(f"Título: {p.get('titulo_original', 'N/D')}")
                if st.button("🗑️ Apagar", key=p['id']):
                    supabase.table("portarias_base").delete().eq("id", p['id']).execute()
                    st.rerun()
    except Exception as e:
        st.error(f"Erro ao carregar histórico: {e}")
