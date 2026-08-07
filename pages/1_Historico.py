import streamlit as st
from supabase import create_client, Client
from typing import Optional

st.set_page_config(page_title="Gestão de Histórico Supabase", layout="wide")

# ----------------- REMOÇÃO DO MENU LATERAL (CSS) -----------------
st.markdown("""
    <style>
        /* Esconde a barra lateral padrão do Streamlit */
        [data-testid="stSidebar"] {
            display: none;
        }
        
        /* Ajusta o espaçamento superior para ficar mais limpo */
        .block-container {
            padding-top: 2rem;
        }
    </style>
""", unsafe_allow_html=True)

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

# ----------------- CABEÇALHO E BOTÃO DE VOLTAR -----------------
col_titulo, col_voltar = st.columns([4, 1])

with col_titulo:
    st.header("🗄️ Gestão do Histórico de Portarias")
    st.markdown("Consulte as portarias base salvas, gerencie as alterações, edite ou remova registros do Supabase.")

with col_voltar:
    st.write("") # Espaçamento vertical para alinhar o botão
    # Tentativa nativa de navegação para a página principal
    try:
        st.page_link("app.py", label="⬅️ Voltar ao Autopilot", use_container_width=True)
    except Exception:
        # Fallback de segurança HTML caso o app esteja na nuvem e perca a referência do app.py
        st.markdown('''
            <a href="/" target="_self" style="display: block; text-align: center; background-color: #2a5298; color: white !important; padding: 0.6rem 1rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold; font-family: sans-serif; box-shadow: 0 2px 5px rgba(0,0,0,0.2);">
                ⬅️ Voltar ao Autopilot
            </a>
        ''', unsafe_allow_html=True)

st.markdown("---")

# ----------------- ÁREA DE GESTÃO (CRUD) -----------------
if not supabase:
    st.error("⚠️ Conexão com o Supabase indisponível. Verifique as configurações nos segredos do Streamlit.")
else:
    sub_consulta, sub_inserir = st.tabs(["📋 Consultar & Gerenciar Existentes", "➕ Inserir Nova Portaria Base"])
    
    with sub_consulta:
        if st.button("🔄 Atualizar Lista do Banco", type="primary"):
            st.rerun()
            
        try:
            # Busca todas as portarias e suas alteradoras
            response = supabase.table("portarias_base").select("*, portarias_alteradoras(*)").order("ano_criacao", desc=True).execute()
            bases = response.data
            
            if not bases or len(bases) == 0:
                st.info("📭 Nenhuma portaria base cadastrada no histórico do Supabase até o momento.")
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
                        st.markdown("#### 🛠️ Editar ou Apagar Registro Base")
                        
                        with st.form(key=f"form_edit_{p_id}"):
                            c_ed1, c_ed2 = st.columns(2)
                            novo_nome = c_ed1.text_input("Nome da Portaria", value=p_nome)
                            novo_ano = c_ed2.number_input("Ano de Criação", value=int(p_ano), step=1)
                            
                            btn_atualizar = st.form_submit_button("✏️ Salvar Alterações")
                            if btn_atualizar:
                                try:
                                    supabase.table("portarias_base").update({
                                        "nome_portaria": novo_nome,
                                        "ano_criacao": int(novo_ano)
                                    }).eq("id", p_id).execute()
                                    st.success("✅ Portaria atualizada com sucesso!")
                                    st.rerun()
                                except Exception as err:
                                    st.error(f"Erro ao atualizar: {err}")

                        # Botão de exclusão (fora do form)
                        if st.button(f"🗑️ Apagar Portaria Base e todo seu Histórico", key=f"btn_del_{p_id}"):
                            try:
                                supabase.table("portarias_base").delete().eq("id", p_id).execute()
                                st.success("🗑️ Portaria e vínculos apagados com sucesso!")
                                st.rerun()
                            except Exception as err:
                                st.error(f"Erro ao apagar: {err}")

                        st.markdown("---")
                        st.markdown("#### 📜 Portarias Alteradoras Vinculadas à Base:")
                        if not alteradoras or len(alteradoras) == 0:
                            st.write("Nenhuma portaria alteradora foi registrada no banco para esta norma.")
                        else:
                            for alt in alteradoras:
                                st.markdown(f"- **{alt['nome_portaria_alteradora']}** (Ano: {alt['ano_alteracao']}) | *Documento Lido:* `{alt.get('arquivo_nome_original', 'N/D')}`")
                                
        except Exception as e:
            st.error(f"Erro ao carregar dados do Supabase: {e}")

    with sub_inserir:
        st.subheader("Adicionar Portaria Base Manualmente")
        with st.form(key="form_inserir_manual"):
            m_nome = st.text_input("Nome da Portaria (Ex: Portaria nº 130/PGJM)")
            m_ano = st.number_input("Ano de Criação", min_value=1900, max_value=2100, value=2026, step=1)
            m_titulo = st.text_area("Título / Ementa (Opcional)")
            m_orgaos = st.text_input("Órgãos Emissores (Opcional)", value="MINISTÉRIO PÚBLICO DA UNIÃO<br/>MINISTÉRIO PÚBLICO MILITAR")
            
            btn_salvar_manual = st.form_submit_button("💾 Inserir no Supabase")
            if btn_salvar_manual:
                if not m_nome.strip():
                    st.warning("⚠️ O nome da portaria é obrigatório.")
                else:
                    try:
                        supabase.table("portarias_base").insert({
                            "nome_portaria": m_nome.strip(),
                            "ano_criacao": int(m_ano),
                            "titulo_original": m_titulo.strip(),
                            "orgaos_emissores": m_orgaos.strip()
                        }).execute()
                        st.success(f"✅ Portaria '{m_nome}' inserida manualmente com sucesso!")
                    except Exception as err:
                        st.error(f"Erro ao inserir (verifique se já existe portaria com esse nome/ano): {err}")
