import streamlit as st
import sys
import os

# Garante que o script enxergue o utils.py na raiz
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import init_supabase

st.set_page_config(page_title="Gestão de Histórico - Supabase", layout="wide")

st.title("🗄️ Gestão Completa do Histórico Normativo")
st.markdown("Consulte, edite ou exclua portarias base e suas respectivas alterações armazenadas no Supabase.")

supabase = init_supabase()

if not supabase:
    st.error("⚠️ Conexão com o Supabase indisponível. Verifique as credenciais no arquivo `secrets.toml`.")
else:
    # Botão para atualizar dados em tempo real
    if st.button("🔄 Atualizar Lista do Histórico"):
        st.rerun()

    st.markdown("---")

    try:
        # Busca todas as portarias base e suas alteradoras vinculadas
        response = supabase.table("portarias_base").select("*, portarias_alteradoras(*)").order("ano_criacao", desc=True).execute()
        bases = response.data

        if not bases:
            st.info("📭 Nenhuma portaria cadastrada no histórico do Supabase até o momento.")
        else:
            for p in bases:
                base_id = p['id']
                nome_base = p['nome_portaria']
                ano_base = p['ano_criacao']
                titulo = p.get('titulo_original', 'N/D')
                orgaos = p.get('orgaos_emissores', 'N/D')
                alteradoras = p.get('portarias_alteradoras', [])

                with st.expander(f"📌 **{nome_base}** ({ano_base}) — {len(alteradoras)} alteração(ões) vinculada(s)"):
                    
                    # --- SEÇÃO DE ALTERAÇÃO / EDIÇÃO DOS DADOS DA BASE ---
                    with st.form(key=f"form_edit_{base_id}"):
                        st.subheader("Editar Dados da Portaria Base")
                        novo_nome = st.text_input("Nome da Portaria", value=nome_base)
                        novo_ano = st.number_input("Ano de Criação", value=int(ano_base), step=1)
                        novo_titulo = st.text_area("Título Original", value=titulo or "")
                        novo_orgao = st.text_input("Órgãos Emissores", value=orgaos or "")

                        col_btn1, col_btn2 = st.columns(2)
                        
                        # Botão para Salvar Alterações (Update)
                        atualizar = col_btn1.form_submit_button("💾 Salvar Alterações", use_container_width=True)
                        if atualizar:
                            try:
                                supabase.table("portarias_base").update({
                                    "nome_portaria": novo_nome,
                                    "ano_criacao": int(novo_ano),
                                    "titulo_original": novo_titulo,
                                    "orgaos_emissores": novo_orgao
                                }).eq("id", base_id).execute()
                                st.success("✅ Portaria base atualizada com sucesso!")
                                st.rerun()
                            except Exception as err:
                                st.error(f"Erro ao atualizar: {err}")

                        # Botão para Excluir o Registro (Delete)
                        excluir = col_btn2.form_submit_button("🗑️ Excluir Portaria Base e Vínculos", use_container_width=True)
                        if excluir:
                            try:
                                supabase.table("portarias_base").delete().eq("id", base_id).execute()
                                st.success("🗑️ Registro excluído do Supabase!")
                                st.rerun()
                            except Exception as err:
                                st.error(f"Erro ao excluir: {err}")

                    st.markdown("---")
                    st.markdown("#### 🔗 Portarias Alteradoras Vinculadas nesta Cadeia:")
                    if not alteradoras:
                        st.write("Nenhuma portaria alteradora registrada para esta base.")
                    else:
                        for alt in alteradoras:
                            st.markdown(f"- **{alt['nome_portaria_alteradora']}** (Ano: {alt['ano_alteracao']}) | *Arquivo original:* `{alt.get('arquivo_nome_original', 'N/D')}`")

    except Exception as e:
        st.error(f"❌ Erro ao carregar dados do Supabase: {e}")
