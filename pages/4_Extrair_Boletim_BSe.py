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

# --- BARRA DE FERRAMENTAS COMPLETA DO EDITOR RICO ---
QUILL_TOOLBAR = [
    ["bold", "italic", "underline", "strike"],
    [{"align": []}],  
    [{"color": []}, {"background": []}],
    [{"list": "ordered"}, {"list": "bullet"}],
    ["clean"],
]

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

# --- EXTRAÇÃO ESTRUTURADA DE BLOCOS, PARÁGRAFOS E TABELAS ---
def extrair_texto_boletim_estruturado(pdf_bytes: bytes) -> str:
    """Extrai o texto preservando integridade de parágrafos e detecção avançada de tabelas."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    html_paginas = []
    
    for page in doc:
        page_width = page.rect.width
        tabelas_bbox = []
        html_tabelas = {}
        
        # 1. Extração robusta de tabelas (Trata PDFs antigos sem bordas)
        tabelas_encontradas = []
        try:
            # Tenta estratégia baseada em linhas (para tabelas desenhadas)
            tf_lines = page.find_tables(strategy="lines")
            if tf_lines.tables:
                tabelas_encontradas = tf_lines.tables
            else:
                # Fallback: Tenta estratégia de alinhamento de texto (para tabelas invisíveis/antigas)
                tf_text = page.find_tables(strategy="text")
                if tf_text.tables:
                    tabelas_encontradas = tf_text.tables
        except TypeError:
            # Fallback para versões mais antigas do PyMuPDF
            tf_default = page.find_tables()
            if tf_default.tables:
                tabelas_encontradas = tf_default.tables
        except Exception as e:
            print(f"Aviso de leitura de tabela: {e}")

        for tabela in tabelas_encontradas:
            rect = fitz.Rect(tabela.bbox)
            tabelas_bbox.append(rect)
            
            linhas = tabela.extract()
            if not linhas:
                continue
                
            tab_html = '<table border="1" style="border-collapse: collapse; width: 100%; margin: 15px 0; font-size: 10pt;">'
            for idx_r, linha in enumerate(linhas):
                tab_html += '<tr>'
                tag = 'th' if idx_r == 0 else 'td'
                bg = ' background-color: #f2f2f2;' if idx_r == 0 else ''
                for celula in linha:
                    texto_cel = str(celula).strip() if celula is not None else ''
                    texto_cel = texto_cel.replace('\n', '<br/>')
                    tab_html += f'<{tag} style="border: 1px solid #000; padding: 6px 8px;{bg}">{texto_cel}</{tag}>'
                tab_html += '</tr>'
            tab_html += '</table>'
            
            html_tabelas[rect.y0] = (rect, tab_html)

        # 2. Leitura por Blocos do PyMuPDF
        blocks = page.get_text("dict", sort=True).get("blocks", [])
        elementos = []
        
        x0_min = page_width
        for b in blocks:
            if b.get("type") == 0:
                b_rect = fitz.Rect(b.get("bbox", (0, 0, 0, 0)))
                # Ignora blocos que fazem parte de uma tabela para não duplicar texto
                in_table = False
                for tb in tabelas_bbox:
                    if b_rect.intersect(tb).get_area() > (b_rect.get_area() * 0.4):
                        in_table = True
                        break
                if not in_table and b_rect.x0 < x0_min:
                    x0_min = b_rect.x0
                    
        if x0_min == page_width:
            x0_min = 50.0

        for b in blocks:
            if b.get("type") != 0:
                continue
                
            bloco_rect = fitz.Rect(b.get("bbox", (0, 0, 0, 0)))
            
            # Validação de interseção com tabelas (proteção contra quebra de layout)
            in_table = False
            for tb in tabelas_bbox:
                if bloco_rect.intersect(tb).get_area() > (bloco_rect.get_area() * 0.4):
                    in_table = True
                    break
            if in_table:
                continue
            
            linhas_bloco = []
            for line in b.get("lines", []):
                linha_spans_html = ""
                for span in line.get("spans", []):
                    txt = span.get("text", "")
                    if not txt:
                        continue
                    txt_esc = txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    flags = span.get("flags", 0)
                    font_name = str(span.get("font", "")).lower()
                    
                    is_bold = bool(flags & 2**4) or "bold" in font_name or "black" in font_name
                    is_italic = bool(flags & 2**1) or "italic" in font_name or "oblique" in font_name
                    
                    if is_bold:
                        txt_esc = f"<strong>{txt_esc}</strong>"
                    if is_italic:
                        txt_esc = f"<em>{txt_esc}</em>"
                    linha_spans_html += txt_esc
                
                if linha_spans_html.strip():
                    linhas_bloco.append((line, linha_spans_html))

            if not linhas_bloco:
                continue

            primeira_linha_box = linhas_bloco[0][0].get("bbox", (0, 0, 0, 0))
            lx0, ly0, lx1, ly1 = primeira_linha_box
            line_center = (lx0 + lx1) / 2.0
            line_width = lx1 - lx0

            is_centered = abs(line_center - (page_width / 2.0)) < 30 and line_width < (page_width * 0.75)
            is_right = lx0 > (page_width * 0.5) and lx1 > (page_width - 80) and line_width < (page_width * 0.45)
            is_indented = (lx0 - x0_min) > 15

            texto_bloco = " ".join([l[1] for l in linhas_bloco]).strip()
            texto_puro = re.sub(r'<[^>]+>', '', texto_bloco).strip()
            is_pattern = bool(re.match(r'^(Art\.|§|Parágrafo|Inciso|[I|V|X|L|C]+|\d+[\.\º\°]|a\)|b\)|c\)|[A-Z\s]{4,}:)', texto_puro))

            if is_centered:
                align_class = "ql-align-center"
                indent_style = ""
            elif is_right:
                align_class = "ql-align-right"
                indent_style = ""
            else:
                align_class = "ql-align-justify"
                indent_style = ' style="text-indent: 1.25cm;"' if (is_indented or is_pattern) else ""

            p_html = f'<p class="{align_class}"{indent_style}>{texto_bloco}</p>'
            elementos.append((bloco_rect.y0, p_html))

        # Reordena verticalmente parágrafos e tabelas extraídas
        for y0, (rect, tab_html) in html_tabelas.items():
            elementos.append((y0, tab_html))

        elementos.sort(key=lambda x: x[0])
        for _, html_elem in elementos:
            html_paginas.append(html_elem)

    return "\n".join(html_paginas)

def identificar_autoridade(texto_html: str) -> Dict[str, str]:
    texto_puro = re.sub(r'<[^>]+>', '', texto_html)
    padrao = re.search(r'([A-Z\s]{5,50})\n\s*(Procurador-Geral de Justiça Militar)', texto_puro, re.IGNORECASE)
    if padrao:
        nome = padrao.group(1).strip()
        cargo = padrao.group(2).strip()
        return {"nome": nome, "cargo": cargo}
    return {"nome": "JAIME DE CASSIO MIRANDA", "cargo": "Procurador-Geral de Justiça Militar"}

def extrair_atos_normativos_html(texto_html: str) -> List[Dict[str, str]]:
    padrao_ato = re.compile(
        r'((?:<p[^>]*>)?\s*(?:<strong>|<b>)?\s*(?:Portaria|RESOLUÇÃO|ATO)\s+nº?\s*[\d\w/-]+[^\n<]*.*?)(?=(?:<p[^>]*>)?\s*(?:<strong>|<b>)?\s*(?:Portaria|RESOLUÇÃO|ATO)\s+nº?\s*[\d\w/-]+|\Z)',
        re.DOTALL | re.IGNORECASE
    )
    
    matches = padrao_ato.findall(texto_html)
    atos = []
    
    for idx, bloco_html in enumerate(matches):
        bloco_html_limpo = bloco_html.strip()
        bloco_html_limpo = re.sub(r'<p[^>]*>\s*Boletim de Serviço nº \d+.*?</p>', '', bloco_html_limpo, flags=re.IGNORECASE)
        
        nota_publicacao = ""
        match_pub = re.search(r'(\(Publicada no DOU[^\)]+\))', bloco_html_limpo, re.IGNORECASE)
        if match_pub:
            nota_publicacao = match_pub.group(1)
            bloco_html_limpo = bloco_html_limpo.replace(nota_publicacao, "").strip()

        texto_puro_bloco = re.sub(r'<[^>]+>', '', bloco_html_limpo).strip()
        primeira_linha = texto_puro_bloco.split('\n')[0][:120] if texto_puro_bloco else f"Ato {idx+1}"

        atos.append({
            "id": idx + 1,
            "titulo": primeira_linha,
            "corpo_html": bloco_html_limpo,
            "nota_publicacao": nota_publicacao
        })
        
    return atos

# --- GERADOR DE PDF FORMATADO ---
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
            
            .ql-align-center {{ text-align: center !important; text-indent: 0 !important; }}
            .ql-align-right {{ text-align: right !important; text-indent: 0 !important; }}
            .ql-align-justify {{ text-align: justify !important; }}
            .ql-align-left {{ text-align: left !important; text-indent: 0 !important; }}
            
            p {{ margin-top: 0px; margin-bottom: 6px; text-align: justify; orphans: 3; widows: 3; }}
            p.ql-align-justify {{ text-indent: 1.25cm; }}
            
            table {{ width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 10pt; page-break-inside: auto; }}
            tr {{ page-break-inside: avoid; page-break-after: auto; }}
            th, td {{ border: 1px solid #000000; padding: 6px 8px; text-align: left; vertical-align: top; }}
            th {{ background-color: #f2f2f2; font-weight: bold; text-align: center; }}
            
            .header-brasao {{ text-align: center; margin-bottom: 12px; }}
            .header-brasao img {{ width: 60pt; height: 60pt; }}
            .header-texto {{ text-align: center; font-weight: bold; font-size: 11pt; text-transform: uppercase; margin-bottom: 20px; }}
            
            .assinatura-container {{ margin-top: 40px; text-align: center; page-break-inside: avoid; }}
            .assinatura-nome {{ font-weight: bold; font-size: 11pt; text-transform: uppercase; margin-bottom: 2px; }}
            .assinatura-cargo {{ font-size: 11pt; }}
            .nota-publicacao {{ font-size: 9pt; font-style: italic; margin-top: 25px; text-align: left; page-break-inside: avoid; }}
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
Envie o arquivo do **Boletim de Serviço Eletrônico (PDF)**. O sistema extrairá os Atos normativos identificando
**parágrafos, alinhamentos e tabelas**, permitindo edição antes de gerar o PDF.
""")

arquivo_bse = st.file_uploader("Selecione o Boletim de Serviço (PDF)", type=["pdf"], key="uploader_bse")

if arquivo_bse is not None:
    pdf_bytes = arquivo_bse.getvalue()
    
    with st.spinner("⚡ Lendo e analisando o Boletim de Serviço (processando tabelas sem bordas e parágrafos)..."):
        texto_boletim_html = extrair_texto_boletim_estruturado(pdf_bytes)
        autoridade = identificar_autoridade(texto_boletim_html)
        atos = extrair_atos_normativos_html(texto_boletim_html)

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
            with st.expander(f"📄 {ato['titulo']}", expanded=False):
                
                tem_tabela = "<table" in ato['corpo_html'].lower()
                if tem_tabela:
                    st.warning("⚠️ **Tabela Detectada neste Ato!** O editor visual pode desconfigurar tabelas extraídas. O modo 'Código-Fonte HTML' foi selecionado por padrão para proteger a formatação.")
                
                # Permite trocar entre o Editor Visual e o Editor de HTML puro
                modo_edicao = st.radio(
                    "Modo de Edição:",
                    ["Visual (Texto Rico)", "Código-Fonte HTML (Preserva Tabelas)"],
                    key=f"modo_{ato['id']}",
                    horizontal=True,
                    index=1 if tem_tabela else 0
                )
                
                if modo_edicao == "Visual (Texto Rico)" and HAS_QUILL:
                    conteudo_editado_html = st_quill(
                        value=ato['corpo_html'],
                        html=True,
                        toolbar=QUILL_TOOLBAR,
                        key=f"quill_editor_{ato['id']}"
                    )
                else:
                    if not HAS_QUILL and modo_edicao == "Visual (Texto Rico)":
                        st.warning("Biblioteca 'streamlit-quill' não encontrada. Exibindo código-fonte.")
                    
                    conteudo_editado_html = st.text_area("Edite o HTML diretamente", value=ato['corpo_html'], height=350, key=f"ta_{ato['id']}")
                    
                    with st.expander("👁️ Pré-visualização da Impressão (HTML Renderezado)"):
                        st.markdown(conteudo_editado_html, unsafe_allow_html=True)

                st.markdown("**Nota de Publicação (DOU)**")
                nota_editada = st.text_input("Nota de Publicação", value=ato['nota_publicacao'], key=f"nota_{ato['id']}")

                st.markdown("<br/>", unsafe_allow_html=True)
                
                if conteudo_editado_html:
                    try:
                        pdf_individual = gerar_pdf_fiel_sei(
                            conteudo_editado_html, nome_autoridade, cargo_autoridade, nota_editada
                        )
                        st.download_button(
                            label="📄 Gerar e Baixar este Ato em PDF Formatado",
                            data=pdf_individual,
                            file_name=f"{ato['titulo'].replace('/', '_').replace(' ', '_')}.pdf",
                            mime="application/pdf",
                            type="primary",
                            key=f"btn_dl_{ato['id']}"
                        )
                    except Exception as e:
                        st.error(f"Erro ao gerar PDF do ato: {e}")
