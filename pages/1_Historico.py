import streamlit as st
from utils import init_supabase

st.set_page_config(page_title="Gestão de Histórico Supabase", layout="wide")

st.title("🗄️ Histórico e Gestão de Portarias (Supabase)")
st.markdown("Consulte registros, altere dados ou cadastre novas portarias base manualmente.")

supabase = init_supabase()

if not supabase:
    st.error("⚠️ Conexão com o Supabase indisponível. Verifique as credenciais nos segredos.")
else:
    sub_consulta, sub_inserir = st.tabs(["📋 Consultar & Gerenciar", "➕ Inserir Manualmente"])
    
    with sub_consulta:
        if st.button("🔄 Atualizar Dados"):
            st.rerun()
            
        try:
            response = supabase.table("portarias_base").select("*, portarias_alteradoras(*)").order("ano_criacao", desc=True).execute()
            bases = response.data
            
            if not bases:
                st.info("Nenhuma portaria base cadastrada.")
            else:
                for portaria in bases:
                    p_id = portaria['id']
                    p_nome = portaria['nome_portaria']
                    p_ano = portaria['ano_criacao']
                    alteradoras = portaria.get('portarias_alteradoras', [])
                    
                    with st.expander(f"📌 {p_nome} ({p_ano}) — {len(alteradoras)} alteração(ões)"):
                        st.write(f"**Título:** {portaria.get('titulo_original', 'N/D')}")
                        
                        # Edição
                        with st.form(key=f"form_edit_{p_id}"):
                            c1, c2 = st.columns(2)
                            novo_nome = c1.text_input("Nome", value=p_nome)
                            novo_ano = c2.number_input("Ano", value=int(p_ano), step=1)
                            if st.form_submit_button("✏️ Atualizar"):
                                supabase.table("portarias_base").update({"nome_portaria": novo_nome, "ano_criacao": int(novo_ano)}).eq("id", p_id).execute()
                                st.success("Atualizado!")
                                st.rerun()
                                
                        if st.button("🗑️ Apagar Base e Vínculos", key=f"del_{p_id}"):
                            supabase.table("portarias_base").delete().eq("id", p_id).execute()
                            st.success("Apagado!")
                            st.rerun()
                            
                        st.markdown("---")
                        st.markdown("**Alteradoras vinculadas:**")
                        for alt in alteradoras:
                            st.write(f"- {alt['nome_portaria_alteradora']} (Ano: {alt['ano_alteracao']})")
        except Exception as e:
            st.error(f"Erro ao consultar: {e}")

    with sub_inserir:
        with st.form("manual"):
            m_nome = st.text_input("Nome da Portaria (Ex: Portaria nº 130/PGJM)")
            m_ano = st.number_input("Ano", value=2026, step=1)
            m_titulo = st.text_area("Título / Ementa")
            if st.form_submit_button("💾 Salvar"):
                try:
                    supabase.table("portarias_base").insert({"nome_portaria": m_nome.strip(), "ano_criacao": int(m_ano), "titulo_original": m_titulo.strip()}).execute()
                    st.success("Inserido com sucesso!")
                except Exception as err:
                    st.error(f"Erro: {err}")
