# menu_utils.py - Menu de navegação, cabeçalho e proteção de acesso padronizados
import os
import streamlit as st

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# (chave, arquivo padrão relativo, palavra-chave p/ localizar, rótulo, ícone)
ITENS_MENU = [
    ("inicio", "app.py", None, "Identificar e Cruzar", "🏠"),
    ("bse", "pages/4_Extrair_Boletim_BSe.py", ("extrair", "boletim"), "Extrair BSe", "📋"),
    ("consolidar", "pages/3_Consolidar_Norma.py", ("consolidar",), "Consolidar Norma", "⚙️"),
    ("historico", "pages/1_Historico.py", ("historico",), "Histórico", "🗄️"),
    ("usuarios", "pages/usuarios.py", ("usuario",), "Usuários", "👥"),
    ("diagnostico", "pages/diagnostico.py", ("diagnostico",), "Diagnóstico", "🩺"),
]

CSS_BASE = """
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
    .menu-ativo {
        display: block; text-align: center; font-weight: 700; color: #1e3c72;
        background: #e3ebfa; border: 1px solid #2a5298; border-radius: 0.5rem;
        padding: 0.5rem; white-space: nowrap;
    }
    .menu-fallback {
        display: block; text-align: center; background: #f0f2f6; border: 1px solid #d0d4dc;
        color: #31333F !important; padding: 0.5rem; border-radius: 0.5rem;
        text-decoration: none; font-weight: 500; white-space: nowrap;
    }
</style>
"""


def _resolver_caminho(padrao, palavras):
    """Localiza o arquivo da página pela palavra-chave; usa o caminho padrão se não achar."""
    if not palavras:
        return padrao
    pasta = os.path.join(_BASE_DIR, "pages")
    if os.path.isdir(pasta):
        for f in sorted(os.listdir(pasta)):
            nome = f.lower()
            if nome.endswith(".py") and any(p in nome for p in palavras):
                return f"pages/{f}"
    return padrao


def configurar_pagina(titulo, icone):
    """Deve ser a PRIMEIRA chamada Streamlit da página."""
    st.set_page_config(page_title=titulo, page_icon=icone, layout="wide", initial_sidebar_state="collapsed")


def exigir_login(mensagem="Você precisa fazer login na página principal para acessar esta área."):
    if not st.session_state.get("autenticado", False):
        st.warning(f"⚠️ Acesso negado. {mensagem}")
        try:
            st.page_link("app.py", label="Ir para a Tela de Login", icon="🔒")
        except Exception:
            pass
        st.stop()


def renderizar_cabecalho(titulo_h1, css_extra=""):
    st.markdown(
        CSS_BASE
        + (f"<style>{css_extra}</style>" if css_extra else "")
        + f'<div class="main-header"><h1>{titulo_h1}</h1></div>',
        unsafe_allow_html=True,
    )


def renderizar_menu(ativa):
    """Menu superior padronizado. `ativa` é a chave da página atual."""
    colunas = st.columns([1.6, 1.3, 1.6, 1.3, 1.3, 1.3, 0.9])
    for col, (chave, padrao, palavras, rotulo, icone) in zip(colunas[:len(ITENS_MENU)], ITENS_MENU):
        with col:
            if chave == ativa:
                st.markdown(f'<div class="menu-ativo">{icone} {rotulo}</div>', unsafe_allow_html=True)
                continue
            caminho = _resolver_caminho(padrao, palavras)
            try:
                st.page_link(caminho, label=rotulo, icon=icone, use_container_width=True)
            except Exception:
                href = caminho.replace("pages/", "").replace(".py", "") if caminho != "app.py" else ""
                st.markdown(
                    f'<a class="menu-fallback" href="/{href}" target="_top">{icone} {rotulo}</a>',
                    unsafe_allow_html=True,
                )
    with colunas[len(ITENS_MENU)]:
        if st.button("🚪 Sair", key=f"btn_sair_{ativa}", type="secondary", use_container_width=True):
            st.session_state.autenticado = False
            try:
                st.switch_page("app.py")
            except Exception:
                st.rerun()
    st.markdown("---")
