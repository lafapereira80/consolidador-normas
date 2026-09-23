import streamlit as st
import fitz  # PyMuPDF
import re
import os
import io
import base64
from typing import List, Dict, Optional

try:
    from streamlit_quill import st_quill
    HAS_QUILL = True
except ImportError:
    HAS_QUILL = False

try:
    from weasyprint import HTML
    HAS_WEASYPRINT = True
except ImportError:
    HAS_WEASYPRINT = False

st.set_page_config(page_title="Extrair do Boletim de Serviço", page_icon="📋", layout="wide", initial_sidebar_state="collapsed")

# --- PROTEÇÃO DE ACESSO ---
if "autenticado" not in st.session_state or not st.session_state.autenticado:
    st.warning("⚠️ Acesso negado. Você precisa fazer login na página principal para acessar esta área.")
    st.page_link("app.py", label="Ir para a Tela de Login", icon="🔑")
    st.stop()

# --- ESTILIZAÇÃO E CABEÇALHO ---
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
    <h1>📋 Extração de Atos do Boletim de Serviço (BSe)</h1>
</div>
""", unsafe_allow_html=True)

# --- MENU DE NAVEGAÇÃO SUPERIOR FIXO ---
col_home, col_ext, col_cons, col_hist, col_usr, col_logout = st.columns([1.2, 1.5, 1.5, 1.2, 1.2, 1])

with col_home:
    try:
        st.page_link("app.py", label="Início", icon="🏠")
    except Exception:
        st.markdown('🏠 **Início**')

with col_ext:
    st.markdown("📋 **Extrair BSe**")

with col_cons:
    cons_path = "pages/3_Consolidar_Norma.py"
    if os.path.exists("pages"):
        for f in os.listdir("pages"):
            if "consolidar" in f.lower() and f.endswith(".py"):
                cons_path = f"pages/{f}"
                break
    try:
        st.page_link(cons_path, label="⚙️ Consolidar Norma", icon="➡️")
    except Exception:
        st.markdown(f'<a href="{cons_path.replace("pages/", "").replace(".py", "")}" target="_top" style="display:block;text-align:center;background:#f0f2f6;border:1px solid #d0d4dc;color:#31333F !important;padding:0.5rem;border-radius:0.5rem;text-decoration:none;font-weight:500;">➡️ ⚙️ Consolidar</a>', unsafe_allow_html=True)

with col_hist:
    hist_path = "pages/1_Historico.py"
    if os.path.exists("pages"):
        for f in os.listdir("pages"):
            if "historico" in f.lower() and f.endswith(".py"):
                hist_path = f"pages/{f}"
                break
    try:
        st.page_link(hist_path, label="🗄️ Histórico", icon="➡️")
    except Exception:
        st.markdown(f'<a href="{hist_path.replace("pages/", "").replace(".py", "")}" target="_top" style="display:block;text-align:center;background:#f0f2f6;border:1px solid #d0d4dc;color:#31333F !important;padding:0.5rem;border-radius:0.5rem;text-decoration:none;font-weight:500;">➡️ 🗄️ Histórico</a>', unsafe_allow_html=True)

with col_usr:
    usr_path = "pages/usuarios.py"
    if os.path.exists("pages"):
        for f in os.listdir("pages"):
            if "usuario" in f.lower() and f.endswith(".py"):
                usr_path = f"pages/{f}"
                break
    try:
        st.page_link(usr_path, label="👥 Usuários", icon="➡️")
    except Exception:
        st.markdown(f'<a href="{usr_path.replace("pages/", "").replace(".py", "")}" target="_top" style="display:block;text-align:center;background:#f0f2f6;border:1px solid #d0d4dc;color:#31333F !important;padding:0.5rem;border-radius:0.5rem;text-decoration:none;font-weight:500;">➡️ 👥 Usuários</a>', unsafe_allow_html=True)

with col_logout:
    if st.button("Sair", key="btn_sair_bse", type="secondary", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

st.markdown("---")


# --- CONFIGURAÇÃO DA BARRA DE FERRAMENTAS DO EDITOR RICO ---
QUILL_TOOLBAR = [
    ["bold", "italic", "underline", "strike"],
    [{"align": []}],  # Alinhamentos: Esquerda, Centro, Direita, Justificado
    [{"color": []}, {"background": []}],
    [{"list": "ordered"}, {"list": "bullet"}],
    ["clean"],
]


# --- FUNÇÕES DE EXTRAÇÃO DE TEXTO E BUSCA DA AUTORIDADE ---
def obter_caminho_brasao() -> Optional[str]:
    candidatos = [
        "brasao.png",
        os.path.join(os.path.dirname(__file__), "..", "brasao.png"),
        os.path.join(os.path.dirname(__file__), "brasao.png")
    ]
    for c in candidatos:
        if os.path.exists(c):
            return os.path.abspath(c)
    return None

def extrair_texto_boletim(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texto_completo = []
    for page in doc:
        texto_completo.append(page.get_text())
    return "\n".join(texto_completo)

def identificar_autoridade(texto: str) -> Dict[str, str]:
    padrao = re.search(r'([A-Z\s]{5,50})\n\s*(Procurador-Geral de Justiça Militar)', texto, re.IGNORECASE)
    if padrao:
        nome = padrao.group(1).strip()
        cargo = padrao.group(2).strip()
        return {"nome": nome, "cargo": cargo}
    return {"nome": "JAIME DE CASSIO MIRANDA", "cargo": "Procurador-Geral de Justiça Militar"}

def extrair_atos_normativos(texto: str) -> List[Dict[str, str]]:
    texto_limpo = re.sub(r'\r\n', '\n', texto)
    
    padrao_ato = re.compile(
        r'((?:Portaria|RESOLUÇÃO|ATO)\s+nº?\s*[\d\w/-]+[^\n]*\n)(.*?)(?=(?:Portaria|RESOLUÇÃO|ATO)\s+nº?\s*[\d\w/-]+|\Z)',
        re.DOTALL | re.IGNORECASE
    )
    
    matches = padrao_ato.findall(texto_limpo)
    atos = []
    
    for idx, (titulo, corpo) in enumerate(matches):
        titulo_limpo = titulo.strip()
        corpo_limpo = corpo.strip()
        
        corpo_limpo = re.sub(r'Boletim de Serviço nº \d+.*?\n', '', corpo_limpo, flags=re.IGNORECASE)
        
        nota_publicacao = ""
        match_pub = re.search(r'(\(Publicada no DOU[^\)]+\))', corpo_limpo, re.IGNORECASE)
        if match_pub:
            nota_publicacao = match_pub.group(1)
            corpo_limpo = corpo_limpo.replace(nota_publicacao, "").strip()

        atos.append({
            "id": idx + 1,
            "titulo": titulo_limpo,
            "corpo": corpo_limpo,
            "nota_publicacao": nota_publicacao
        })
        
    return atos

def texto_para_html_inicial(titulo: str, corpo: str) -> str:
    linhas = [l.strip() for l in corpo.split('\n') if l.strip()]
    paragraphs = [f'<p class="ql-align-center"><strong>{titulo}</strong></p>']
    
    for linha in linhas:
        if linha.isupper() and len(linha) < 100:
            paragraphs.append(f'<p class="ql-align-center"><strong>{linha}</strong></p>')
        else:
            paragraphs.append(f'<p class="ql-align-justify">{linha}</p>')
            
    return "".join(paragraphs)


# --- GERADOR DE PDF FORMATADO (FIEL À EDIÇÃO DO USUÁRIO) ---
def gerar_pdf_fiel_sei(html_conteudo: str, autoridade_nome: str, autoridade_cargo: str, nota_pub: str = "") -> bytes:
    if not HAS_WEASYPRINT:
        raise Exception("Biblioteca 'WeasyPrint' não está disponível no ambiente.")

    brasao_base64 = ""
    caminho_brasao = obter_caminho_brasao()
    if caminho_brasao and os.path.exists(caminho_brasao):
        with open(caminho_brasao, "rb") as img_f:
            brasao_base64 = base64.b64encode(img_f.read()).decode("utf-8")

    html_template = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                /* Reduzida margem superior de 2cm para 1.2cm para puxar o texto para cima */
                margin: 1.2cm 2cm 2.5cm 2cm;
                @bottom-center {{
                    content: "Este texto não substitui o publicado no Boletim de Serviço Eletrônico.";
                    font-family: 'Times New Roman', serif;
                    font-size: 8pt;
                    font-style: italic;
                    color: #555555;
                    border-top: 1px solid #cccccc;
                    width: 100%;
                    padding-top: 4px;
                }}
            }}
            body {{
                font-family: 'Times New Roman', Times, serif;
                font-size: 11pt;
                line-height: 1.35;
                color: #000000;
            }}
            
            /* Suporte completo aos alinhamentos do Quill */
            .ql-align-center {{ text-align: center !important; }}
            .ql-align-right {{ text-align: right !important; }}
            .ql-align-justify {{ text-align: justify !important; }}
            .ql-align-left {{ text-align: left !important; }}
            
            p {{
                margin-top: 0px;
                margin-bottom: 6px;
                text-align: justify;
                /* Evita linhas solitárias no final ou início de páginas (Viúvas e Órfãs) */
                orphans: 3;
                widows: 3;
            }}
            p.ql-align-justify {{
                text-indent: 1.25cm;
            }}
            p.ql-align-center, p.ql-align-right {{
                text-indent: 0;
            }}
            
            .header-brasao {{
                text-align: center;
                margin-bottom: 12px;
            }}
            .header-brasao img {{
                width: 60pt;
                height: 60pt;
            }}
            .header-texto {{
                text-align: center;
                font-weight: bold;
                font-size: 11pt;
                text-transform: uppercase;
                margin-bottom: 20px;
            }}
            
            /* Mantém a assinatura unida e evita que quebre de forma indesejada */
            .assinatura-container {{
                margin-top: 40px;
                text-align: center;
                page-break-inside: avoid;
                break-inside: avoid;
            }}
            .assinatura-nome {{
                font-weight: bold;
                font-size: 11pt;
                text-transform: uppercase;
                margin-bottom: 2px;
            }}
            .assinatura-cargo {{
                font-size: 11pt;
            }}
            .nota-publicacao {{
                font-size: 9pt;
                font-style: italic;
                margin-top: 25px;
                text-align: left;
                page-break-inside: avoid;
            }}
        </style>
    </head>
    <body>
        <div class="header-brasao">
            {"<img src='data:image/png;base64," + brasao_base64 + "'/>" if brasao_base64 else ""}
        </div>
        <div class="header-texto">
            MINISTÉRIO PÚBLICO DA UNIÃO<br/>
            MINISTÉRIO PÚBLICO MILITAR<br/>
            PROCURADORIA-GERAL DE JUSTIÇA MILITAR
        </div>

        <div class="conteudo-editado">
            {html_conteudo}
        </div>

        <div class="assinatura-container">
            <div class="assinatura-nome">{autoridade_nome}</div>
            <div class="assinatura-cargo">{autoridade_cargo}</div>
        </div>

        {f'<div class="nota-publicacao">{nota_pub}</div>' if nota_pub else ''}
    </body>
    </html>
    """

    buffer = io.BytesIO()
    HTML(string=html_template).write_pdf(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# --- INTERFACE PRINCIPAL ---
st.markdown("""
Envie o arquivo do **Boletim de Serviço Eletrônico (PDF)**. O sistema extrairá os Atos normativos
e permitirá que você abra individualmente cada um em um **editor de texto rico** (com negrito, itálico, sublinhado e alinhamento) antes de gerar o PDF.
""")

arquivo_bse = st.file_uploader("Selecione o Boletim de Serviço (PDF)", type=["pdf"], key="uploader_bse")

if arquivo_bse is not None:
    pdf_bytes = arquivo_bse.getvalue()
    
    with st.spinner("⚡ Lendo e analisando o Boletim de Serviço..."):
        texto_boletim = extrair_texto_boletim(pdf_bytes)
        autoridade = identificar_autoridade(texto_boletim)
        atos = extrair_atos_normativos(texto_boletim)

    st.success(f"✅ Análise concluída! Identificados **{len(atos)}** atos normativos no Boletim de Serviço.")

    col_aut1, col_aut2 = st.columns(2)
    with col_aut1:
        nome_autoridade = st.text_input("Signatário Identificado (Nome)", value=autoridade["nome"])
    with col_aut2:
        cargo_autoridade = st.text_input("Cargo", value=autoridade["cargo"])

    st.markdown("---")
    st.markdown("### 📜 Atos Encontrados (Clique para expandir e editar)")

    if not atos:
        st.warning("Nenhum ato normativo no padrão reconhecido foi identificado automaticamente.")
    else:
        for ato in atos:
            expander_title = f"📄 {ato['titulo']}"
            
            with st.expander(expander_title, expanded=False):
                st.markdown("**Editor de Texto Rico (Negrito, Itálico, Sublinhado, Alinhamentos e Formatação)**")
                
                html_inicial = texto_para_html_inicial(ato['titulo'], ato['corpo'])
                
                if HAS_QUILL:
                    conteudo_editado_html = st_quill(
                        value=html_inicial,
                        html=True,
                        toolbar=QUILL_TOOLBAR,
                        key=f"quill_editor_{ato['id']}"
                    )
                else:
                    st.warning("⚠️ Biblioteca 'streamlit-quill' não encontrada. Exibindo área de texto simples.")
                    conteudo_editado_html = st.text_area("Conteúdo", value=ato['corpo'], height=350, key=f"ta_{ato['id']}")

                st.markdown("**Nota de Publicação (DOU)**")
                nota_editada = st.text_input("Nota de Publicação", value=ato['nota_publicacao'], key=f"nota_{ato['id']}")

                st.markdown("<br/>", unsafe_allow_html=True)
                
                if conteudo_editado_html:
                    try:
                        pdf_individual = gerar_pdf_fiel_sei(
                            conteudo_editado_html, nome_autoridade, cargo_autoridade, nota_editada
                        )
                        nome_arquivo_pdf = f"{ato['titulo'].replace('/', '_').replace(' ', '_')}.pdf"
                        
                        st.download_button(
                            label="📄 Gerar e Baixar este Ato em PDF Formatado",
                            data=pdf_individual,
                            file_name=nome_arquivo_pdf,
                            mime="application/pdf",
                            type="primary",
                            key=f"btn_dl_{ato['id']}"
                        )
                    except Exception as e:
                        st.error(f"Erro ao gerar PDF do ato: {e}")
