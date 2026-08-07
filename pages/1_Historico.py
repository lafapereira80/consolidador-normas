import streamlit as st
from supabase import create_client, Client
from typing import Optional

st.set_page_config(page_title="Gestão de Histórico Supabase", layout="wide")

# ----------------- CONEXÃO COM SUPABASE -----------------
@st.cache_resource
def init_supabase() -> Optional[Client]:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        return None

supabase = init_supabase()

st.header("🗄️ Gestão do Histórico de Portarias (Supabase)")
st.markdown("Consulte as portarias base salvas, veja quais portarias as alteraram, insira novos registros manualmente, edite nomes/anos ou remova itens.")

if not supabase:
    st.error("⚠️ Conexão com o Supabase indisponível. Verifique as configurações nos segredos do Streamlit.")
else:
    sub_consulta, sub_inserir = st.tabs(["📋 Consultar & Gerenciar Existentes", "➕ Inserir Nova Portaria Base"])
    
    with sub_consulta:
        if st.button("🔄 Atualizar Lista do Banco"):
            st.rerun()
            
        try:
            response = supabase.table("portarias_base").select("*, portarias_alteradoras(*)").order("ano_criacao", desc=True).execute()
            bases = response.data
            
            if not bases or len(bases) == 0:
                st.info("Nenhuma portaria base cadastrada no histórico do Supabase até o momento.")
            else:
                for portaria in bases:
                    p_id = portaria['id']
                    p_nome = portaria['nome_portaria']
                    p_ano = portaria['ano_criacao']
                    p_titulo = portaria.get('titulo_original', 'Sem título')
                    alteradoras = portaria.get('portarias_alteradoras', [])
                    
                    with st.expander(f"📌 {p_nome} ({p_ano}) — {len(alteradoras)} alteração(ões) registrada(s)"):
                        st.write(f"**Título / Ementa:** {p_titulo}")
                        st.write(f"**Órgãos Emissores:** {portaria.get('orgaos_emissores', 'Não informado')}")
                        
                        st.markdown("---")
                        st.markdown("#### 🛠️ Gerenciar esta Portaria Base")
                        
                        with st.form(key=f"form_edit_{p_id}"):
                            c_ed1, c_ed2 = st.columns(2)
                            novo_nome = c_ed1.text_input("Novo Nome da Portaria", value=p_nome)
                            novo_ano = c_ed2.number_input("Novo Ano de Criação", value=int(p_ano), step=1)
                            
                            btn_atualizar = st.form_submit_button("✏️ Salvar Alterações")
                            if btn_atualizar:
                                try:
                                    supabase.table("portarias_base").update({
                                        "nome_portaria": novo_nome,
                                        "ano_criacao": int(novo_ano)
                                    }).eq("id", p_id).execute()
                                    st.success("Portaria atualizada com sucesso!")
                                    st.rerun()
                                except Exception as err:
                                    st.error(f"Erro ao atualizar: {err}")

                        if st.button(f"🗑️ Apagar Portaria Base e Histórico", key=f"btn_del_{p_id}"):
                            try:
                                supabase.table("portarias_base").delete().eq("id", p_id).execute()
                                st.success("Portaria e seus vínculos apagados com sucesso!")
                                st.rerun()
                            except Exception as err:
                                st.error(f"Erro ao apagar: {err}")

                        st.markdown("---")
                        st.markdown("#### 📜 Portarias Alteradoras Vinculadas:")
                        if not alteradoras or len(alteradoras) == 0:
                            st.write("Nenhuma portaria alteradora registrada para esta base.")
                        else:
                            for alt in alteradoras:
                                st.markdown(f"- **{alt['nome_portaria_alteradora']}** (Ano: {alt['ano_alteracao']}) | *Arquivo Ref:* `{alt.get('arquivo_nome_original', 'N/D')}`")
                                
        except Exception as e:
            st.error(f"Erro ao carregar dados do Supabase: {e}")

    with sub_inserir:
        st.subheader("Adicionar Portaria Base Manualmente")
        with st.form(key="form_inserir_manual"):
            m_nome = st.text_input("Nome da Portaria (Ex: Portaria nº 130/PGJM)")
            m_ano = st.number_input("Ano de Criação", min_value=1900, max_value=2100, value=2026, step=1)
            m_titulo = st.text_area("Título / Ementa Opcional")
            m_orgaos = st.text_input("Órgãos Emissores Opcional", value="MINISTÉRIO PÚBLICO DA UNIÃO<br/>MINISTÉRIO PÚBLICO MILITAR")
            
            btn_salvar_manual = st.form_submit_button("💾 Inserir no Supabase")
            if btn_salvar_manual:
                if not m_nome.strip():
                    st.warning("O nome da portaria é obrigatório.")
                else:
                    try:
                        supabase.table("portarias_base").insert({
                            "nome_portaria": m_nome.strip(),
                            "ano_criacao": int(m_ano),
                            "titulo_original": m_titulo.strip(),
                            "orgaos_emissores": m_orgaos.strip()
                        }).execute()
                        st.success(f"Portaria '{m_nome}' inserida manualmente com sucesso!")
                    except Exception as err:
                        st.error(f"Erro ao inserir (verifique se já existe portaria com esse nome e ano): {err}")
