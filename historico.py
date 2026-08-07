import streamlit as st
import sys
import os

from utils import init_supabase

def render_historico():
    st.title("🗄️ Histórico e Gestão de Portarias")
    st.markdown("Consulte o histórico de portarias base e suas respectivas alterações registradas no Supabase.")

    supabase = init_supabase()

    if not supabase:
        st.error("⚠️ Conexão com o Supabase indisponível. Verifique as credenciais.")
        return

    if st.button("🔄 Atualizar Dados"):
        st.rerun()
        
    try:
        response = supabase.table("portarias_base").select("*, portarias_alteradoras(*)").order("ano_criacao", desc=True).execute()
        bases = response.data
        
        if not bases:
            st.info("Nenhuma portaria cadastrada no histórico.")
        else:
            for p in bases:
                alteradoras = p.get('portarias_alteradoras', [])
                with st.expander(f"📌 {p['nome_portaria']} ({p['ano_criacao']}) — {len(alteradoras)} alteração(ões)"):
                    st.write(f"**Título:** {p.get('titulo_original', 'N/D')}")
                    
                    if st.button("🗑️ Apagar Base e Vínculos", key=f"del_{p['id']}"):
                        supabase.table("portarias_base").delete().eq("id", p['id']).execute()
                        st.success("Registro apagado!")
                        st.rerun()
                        
                    st.markdown("---")
                    st.markdown("**Portarias Alteradoras Vinculadas:**")
                    for alt in alteradoras:
                        st.write(f"- {alt['nome_portaria_alteradora']} (Ano: {alt['ano_alteracao']})")
    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")

if __name__ == "__main__":
    render_historico()
