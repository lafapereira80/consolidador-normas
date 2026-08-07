import streamlit as st
from supabase import create_client, Client
from typing import Optional

st.set_page_config(page_title="Gestão de Histórico Supabase", layout="wide")

st.markdown("""
    <style>
        [data-testid="stSidebar"] { display: none; }
        .block-container { padding-top: 2rem; }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def init_supabase() -> Optional[Client]:
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except: return None

supabase = init_supabase()

col_titulo, col_voltar = st.columns([4, 1])
with col_titulo:
    st.header("🗄️ Gestão Inteligente do Histórico Normativo")
with col_voltar:
    st.write("") 
    try: st.page_link("app.py", label="⬅️ Voltar ao Autopilot", use_container_width=True)
    except: st.markdown('<a href="/" target="_self" style="display: block; text-align: center; background-color: #2a5298; color: white !important; padding: 0.6rem 1rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold;">⬅️ Voltar</a>', unsafe_allow_html=True)

st.markdown("---")

if not supabase:
    st.error("⚠️ Conexão com o Supabase indisponível.")
else:
    # ----------------- ÁREA DE FILTROS -----------------
    st.subheader("🔍 Filtros de Busca Avançada")
    with st.container(border=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        f_tipo = c1.selectbox("Tipo de Documento", ["Todos", "Portaria", "Lei", "Decreto", "Outro"])
        f_orgao = c2.text_input("Órgão Emissor (Ex: PGJM)")
        f_texto = c3.text_input("Busca livre (Nome padronizado ou Ementa)")

    if st.button("🔄 Buscar Dados", type="primary"):
        st.rerun()

    st.markdown("---")

    try:
        # Busca Completa no Banco
        query = supabase.table("portarias_base").select("*, portarias_alteradoras(*)").order("data_assinatura", desc=True)
        response = query.execute()
        bases = response.data
        
        # Filtragem Inteligente via Python (Memória)
        resultados_filtrados = []
        for p in bases:
            t = p.get('tipo_documento', '') or ''
            o = p.get('orgao_emissor', '') or ''
            n = p.get('nome_padronizado', '') or ''
            e = p.get('titulo_original', '') or ''
            
            if f_tipo != "Todos" and f_tipo.lower() not in t.lower(): continue
            if f_orgao and f_orgao.lower() not in o.lower(): continue
            if f_texto and (f_texto.lower() not in n.lower() and f_texto.lower() not in e.lower()): continue
            
            resultados_filtrados.append(p)

        if not resultados_filtrados:
            st.info("📭 Nenhum documento encontrado com os filtros aplicados.")
        else:
            st.success(f"Encontrado(s) {len(resultados_filtrados)} documento(s).")
            for portaria in resultados_filtrados:
                p_id = portaria['id']
                p_nome = portaria['nome_padronizado']
                p_data = portaria.get('data_assinatura', 'Sem Data')
                alteradoras = portaria.get('portarias_alteradoras', [])
                
                with st.expander(f"📌 {p_nome} — {len(alteradoras)} alteração(ões)"):
                    st.write(f"**Data de Assinatura:** {p_data}")
                    st.write(f"**Órgãos Emissores:** {portaria.get('orgaos_emissores', 'Não informado')}")
                    
                    st.markdown("---")
                    st.markdown("#### 🛠️ Gerenciar Registro Base")
                    
                    with st.form(key=f"form_edit_{p_id}"):
                        novo_nome = st.text_input("Nome Padronizado", value=p_nome)
                        col_ed1, col_ed2 = st.columns(2)
                        novo_tipo = col_ed1.text_input("Tipo", value=portaria.get('tipo_documento', ''))
                        novo_orgao = col_ed2.text_input("Órgão", value=portaria.get('orgao_emissor', ''))
                        
                        if st.form_submit_button("✏️ Salvar Alterações"):
                            supabase.table("portarias_base").update({
                                "nome_padronizado": novo_nome,
                                "tipo_documento": novo_tipo,
                                "orgao_emissor": novo_orgao
                            }).eq("id", p_id).execute()
                            st.success("✅ Atualizado!")
                            st.rerun()

                    if st.button(f"🗑️ Apagar Documento Base", key=f"del_{p_id}"):
                        supabase.table("portarias_base").delete().eq("id", p_id).execute()
                        st.success("🗑️ Apagado com sucesso!")
                        st.rerun()

                    st.markdown("#### 📜 Portarias Alteradoras Vinculadas:")
                    if not alteradoras: st.write("Nenhuma alteração registrada.")
                    else:
                        for alt in alteradoras:
                            st.markdown(f"- **{alt['nome_padronizado']}** (Data: {alt.get('data_assinatura','N/D')})")
                            
    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
