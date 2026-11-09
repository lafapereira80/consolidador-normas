# pages/4_Extrair_Boletim_BSe.py - Extração de atos do Boletim de Serviço Eletrônico (BSe)
import streamlit as st
import fitz  # PyMuPDF
import re
import os
import io
import base64
import hashlib
from html import escape
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

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from menu_utils import configurar_pagina, exigir_login, renderizar_cabecalho, renderizar_menu
import concorrencia as conc
import ui_theme as ui
import exportacao

configurar_pagina("Extrair BSe", "📋")
exigir_login()
renderizar_menu("bse")
renderizar_cabecalho("Extração de atos do Boletim (BSe)", "Envie o Boletim de Serviço Eletrônico em PDF. Os atos são separados com parágrafos, alinhamentos e tabelas, "
                     "e você edita um a um antes de gerar o PDF formatado.", etiqueta="Boletim de Serviço", icone_nome="news")

# --- BARRA DE FERRAMENTAS DO EDITOR RICO ---
QUILL_TOOLBAR = [
    ["bold", "italic", "underline", "strike"],
    [{"align": []}],
    [{"color": []}, {"background": []}],
    [{"list": "ordered"}, {"list": "bullet"}],
    ["clean"],
]

def obter_caminho_brasao() -> Optional[str]:
    candidatos = ["brasao.png", os.path.join(os.path.dirname(__file__), "..", "brasao.png"), os.path.join(os.path.dirname(__file__), "brasao.png")]
    for c in candidatos:
        if os.path.exists(c): return os.path.abspath(c)
    return None

# --- EXTRAÇÃO ESTRUTURADA DE BLOCOS E TABELAS ---
def extrair_texto_boletim_estruturado(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    html_paginas = []
    
    for page in doc:
        page_width = page.rect.width
        tabelas_bbox = []
        html_tabelas = {}
        tabelas_validas = []
        
        try:
            tf_lines = page.find_tables(strategy="lines")
            if tf_lines.tables: tabelas_validas.extend(tf_lines.tables)
                
            tf_text = page.find_tables(strategy="text")
            if tf_text.tables:
                for tb in tf_text.tables:
                    if tb.col_count > 1 and tb.row_count > 1:
                        linhas = tb.extract()
                        if not linhas: continue
                        texto_tabela = " ".join([str(c) for linha in linhas for c in linha if c])
                        if re.search(r'(Portaria|RESOLUÇÃO|ATO)(?:\s+[A-Z0-9/-]+)?\s+n[.\s]*[º°oO0]?[.\s]*\d+', texto_tabela, re.IGNORECASE): continue 
                        if re.search(r'(Art\.\s*\d+|§\s*\d+|Parágrafo único)', texto_tabela, re.IGNORECASE): continue
                        if any(len(str(c)) > 250 for linha in linhas for c in linha if c): continue
                            
                        rect_text = fitz.Rect(tb.bbox)
                        sobrepoe = False
                        for t_val in tabelas_validas:
                            if rect_text.intersect(fitz.Rect(t_val.bbox)).get_area() > 0:
                                sobrepoe = True
                                break
                        if not sobrepoe: tabelas_validas.append(tb)
        except TypeError:
            # versões antigas do PyMuPDF não aceitam 'strategy'. (Na versão original este ramo era inalcançável.)
            tf_default = page.find_tables()
            if tf_default.tables: tabelas_validas.extend(tf_default.tables)
        except Exception: pass

        for tabela in tabelas_validas:
            rect = fitz.Rect(tabela.bbox)
            tabelas_bbox.append(rect)
            linhas = tabela.extract()
            if not linhas: continue
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

        blocks = page.get_text("dict", sort=True).get("blocks", [])
        elementos = []
        x0_min = page_width
        
        for b in blocks:
            if b.get("type") == 0:
                b_rect = fitz.Rect(b.get("bbox", (0, 0, 0, 0)))
                in_table = any(b_rect.intersect(tb).get_area() > (b_rect.get_area() * 0.4) for tb in tabelas_bbox)
                if not in_table and b_rect.x0 < x0_min: x0_min = b_rect.x0
                    
        if x0_min == page_width: x0_min = 50.0

        for b in blocks:
            if b.get("type") != 0: continue
            bloco_rect = fitz.Rect(b.get("bbox", (0, 0, 0, 0)))
            if any(bloco_rect.intersect(tb).get_area() > (bloco_rect.get_area() * 0.4) for tb in tabelas_bbox): continue
            
            linhas_bloco = []
            for line in b.get("lines", []):
                linha_spans_html = ""
                for span in line.get("spans", []):
                    txt = span.get("text", "")
                    if not txt: continue
                    txt_esc = txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    flags = span.get("flags", 0)
                    font_name = str(span.get("font", "")).lower()
                    if bool(flags & 2**4) or "bold" in font_name or "black" in font_name: txt_esc = f"<strong>{txt_esc}</strong>"
                    if bool(flags & 2**1) or "italic" in font_name or "oblique" in font_name: txt_esc = f"<em>{txt_esc}</em>"
                    linha_spans_html += txt_esc
                
                if linha_spans_html.strip(): linhas_bloco.append((line, linha_spans_html))

            if not linhas_bloco: continue

            lx0, ly0, lx1, ly1 = linhas_bloco[0][0].get("bbox", (0, 0, 0, 0))
            line_center = (lx0 + lx1) / 2.0
            line_width = lx1 - lx0
            is_centered = abs(line_center - (page_width / 2.0)) < 30 and line_width < (page_width * 0.75)
            is_right = lx0 > (page_width * 0.5) and lx1 > (page_width - 80) and line_width < (page_width * 0.45)
            is_indented = (lx0 - x0_min) > 15
            texto_bloco = " ".join([l[1] for l in linhas_bloco]).strip()
            texto_puro = re.sub(r'<[^>]+>', '', texto_bloco).strip()
            is_pattern = bool(re.match(r'^(Art\.|§|Parágrafo|Inciso|[I|V|X|L|C]+|\d+[\.\º\°]|a\)|b\)|c\)|[A-Z\s]{4,}:)', texto_puro))

            if is_centered: align_class, indent_style = "ql-align-center", ""
            elif is_right: align_class, indent_style = "ql-align-right", ""
            else:
                align_class = "ql-align-justify"
                indent_style = ' style="text-indent: 1.25cm;"' if (is_indented or is_pattern) else ""

            elementos.append((bloco_rect.y0, f'<p class="{align_class}"{indent_style}>{texto_bloco}</p>'))

        for y0, (rect, tab_html) in html_tabelas.items(): elementos.append((y0, tab_html))
        elementos.sort(key=lambda x: x[0])
        html_paginas.extend([html_elem for _, html_elem in elementos])

    return "\n".join(html_paginas)

def extrair_atos_normativos_html(texto_html: str) -> List[Dict[str, str]]:
    texto_topo = re.sub(r'<[^>]+>', '\n', texto_html[:5000])
    linhas_topo = [l.strip() for l in texto_topo.split('\n') if l.strip()]
    
    autoridade_pgjm = ""
    autoridade_dg = ""
    
    for i, linha in enumerate(linhas_topo):
        linha_upper = linha.upper()
        if "PROCURADOR-GERAL DE JUSTIÇA MILITAR" in linha_upper and i > 0:
            if not autoridade_pgjm: autoridade_pgjm = linhas_topo[i-1]
        elif ("DIRETOR-GERAL DO MINISTÉRIO PÚBLICO MILITAR" in linha_upper or "DIRETOR-GERAL" == linha_upper) and i > 0:
            if not autoridade_dg: autoridade_dg = linhas_topo[i-1]

    elementos = re.split(r'(?=<p|<table|<ul|<div)', texto_html)
    atos = []
    ato_atual = ""
    
    def is_inicio_ato(elem_html: str) -> bool:
        texto_puro = re.sub(r'<[^>]+>', '', elem_html).strip()
        # Regex flexível para capturar espaços invisíveis, acrônimos intermediários e variações entre o "n", o ponto e o símbolo ordinal
        match_padrao = re.search(r'(Portaria|RESOLUÇÃO|ATO)(?:\s+[A-Z0-9/-]+)?\s+n[.\s]*[º°oO0]?[.\s]*\d+', texto_puro, re.IGNORECASE)
        match_isolado = re.search(r'(?:^|\n)\s*(N[.\s]*[º°oO0]?[.\s]*\d+)\s*(?:\n|$)', texto_puro, re.IGNORECASE)
        
        if match_padrao:
            start_idx = match_padrao.start()
            if start_idx < 5: return True
            prefixo = texto_puro[:start_idx].strip().upper()
            prefixos_permitidos = ["ATOS", "PROCURADORIA", "DIRETORIA", "GABINETE", "MINISTÉRIO", "MPM"]
            return len(prefixo) < 150 and any(p in prefixo for p in prefixos_permitidos)
        elif match_isolado:
            return True
        return False

    for elem in elementos:
        if not elem.strip(): continue
        if is_inicio_ato(elem):
            if ato_atual: atos.append(ato_atual)
            ato_atual = elem
        else:
            if ato_atual: ato_atual += "\n" + elem
                
    if ato_atual: atos.append(ato_atual)
        
    atos_formatados = []
    for idx, corpo in enumerate(atos):
        corpo_limpo = corpo.strip()
        corpo_limpo = re.sub(r'<p[^>]*>\s*Boletim de Serviço nº \d+.*?</p>', '', corpo_limpo, flags=re.IGNORECASE)
        corpo_limpo = re.sub(r'<p[^>]*>\s*Portarias?/(?:DG|PGJM).*?</p>', '', corpo_limpo, flags=re.IGNORECASE)
        
        nota_publicacao = ""
        match_pub = re.search(r'(\(Publicada no DOU[^\)]+\))', corpo_limpo, re.IGNORECASE)
        if match_pub:
            nota_publicacao = match_pub.group(1)
            corpo_limpo = corpo_limpo.replace(nota_publicacao, "").strip()

        texto_puro = re.sub(r'<[^>]+>', '', corpo_limpo).strip()
        
        # Busca restrita aos primeiros 300 caracteres para evitar pegar menções de outras portarias no meio do texto
        texto_inicio = texto_puro[:300]
        
        match_titulo = re.search(r'((?:Portaria|RESOLUÇÃO|ATO)(?:\s+[A-Z0-9/-]+)?\s+n[.\s]*[º°oO0]?[.\s]*\d+.*?)(?:\n|$)', texto_inicio, re.IGNORECASE)
        match_numero = re.search(r'(?:^|\n)\s*(N[.\s]*[º°oO0]?[.\s]*\d+)(?:\n|$)', texto_inicio, re.IGNORECASE)
        
        idx_titulo = match_titulo.start() if match_titulo else 9999
        idx_numero = match_numero.start() if match_numero else 9999
        
        # O padrão que ocorrer primeiro no início do texto será adotado como título
        if match_numero and idx_numero <= idx_titulo:
            primeira_linha = match_numero.group(1).strip()[:120]
        elif match_titulo:
            primeira_linha = match_titulo.group(1).strip()[:120]
        else:
            primeira_linha = f"Ato {idx+1}"

        cargo_autoridade = ""
        nome_autoridade = ""
        
        texto_inicio_upper = texto_puro[:500].upper()
        if "PROCURADOR-GERAL" in texto_inicio_upper and "RESOLVE" in texto_inicio_upper:
            cargo_autoridade = "Procurador-Geral de Justiça Militar"
            nome_autoridade = autoridade_pgjm
            if not match_titulo and match_numero:
                primeira_linha = f"Portaria {primeira_linha}/PGJM"
        elif "DIRETOR-GERAL" in texto_inicio_upper and "RESOLVE" in texto_inicio_upper:
            cargo_autoridade = "Diretor-Geral do Ministério Público Militar"
            nome_autoridade = autoridade_dg
            if not match_titulo and match_numero:
                primeira_linha = f"Portaria {primeira_linha}/DG"
        else:
            if "/PGJM" in primeira_linha.upper():
                cargo_autoridade = "Procurador-Geral de Justiça Militar"
                nome_autoridade = autoridade_pgjm
            elif "/DG" in primeira_linha.upper():
                cargo_autoridade = "Diretor-Geral do Ministério Público Militar"
                nome_autoridade = autoridade_dg
                
        match_assinatura = re.search(r'\(a\)\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]+)', texto_puro)
        if match_assinatura:
            nome_extraido = match_assinatura.group(1).strip().split('\n')[0].strip()
            if len(nome_extraido) > 5 and not "MINISTÉRIO" in nome_extraido:
                nome_autoridade = nome_extraido

        atos_formatados.append({
            "id": idx + 1,
            "titulo": primeira_linha,
            "corpo_html": corpo_limpo,
            "nota_publicacao": nota_publicacao,
            "nome_autoridade": nome_autoridade,
            "cargo_autoridade": cargo_autoridade
        })
        
    return atos_formatados

# --- CACHE CENTRAL (Impede travamentos ao digitar na interface) ---
@st.cache_data(show_spinner=False)
def processar_boletim_pdf(pdf_bytes: bytes) -> List[Dict]:
    texto_boletim_html = extrair_texto_boletim_estruturado(pdf_bytes)
    return extrair_atos_normativos_html(texto_boletim_html)

# --- GERADOR DE PDF ---
def gerar_pdf_fiel_sei(html_conteudo: str, autoridade_nome: str, autoridade_cargo: str, nota_pub: str = "") -> bytes:
    if not HAS_WEASYPRINT: raise Exception("Biblioteca 'WeasyPrint' não está disponível.")

    brasao_base64 = ""
    caminho_brasao = obter_caminho_brasao()
    if caminho_brasao and os.path.exists(caminho_brasao):
        with open(caminho_brasao, "rb") as img_f: brasao_base64 = base64.b64encode(img_f.read()).decode("utf-8")

    html_template = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4; margin: 1.2cm 2cm 2.5cm 2cm;
                @bottom-center {{
                    content: "Este texto não substitui o publicado no Boletim de Serviço Eletrônico.";
                    font-family: 'Times New Roman', serif; font-size: 8pt; font-style: italic; color: #555555; border-top: 1px solid #cccccc; width: 100%; padding-top: 4px;
                }}
            }}
            body {{ font-family: 'Times New Roman', Times, serif; font-size: 11pt; line-height: 1.35; color: #000000; }}
            .ql-align-center {{ text-align: center !important; text-indent: 0 !important; }}
            .ql-align-right {{ text-align: right !important; text-indent: 0 !important; }}
            .ql-align-justify {{ text-align: justify !important; }}
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
        <div class="header-brasao">{"<img src='data:image/png;base64," + brasao_base64 + "'/>" if brasao_base64 else ""}</div>
        <div class="header-texto">MINISTÉRIO PÚBLICO DA UNIÃO<br/>MINISTÉRIO PÚBLICO MILITAR<br/>PROCURADORIA-GERAL DE JUSTIÇA MILITAR</div>
        <div class="conteudo-editado">{html_conteudo}</div>
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
ss = st.session_state
ss.setdefault("bse_ver", 0)
ss.setdefault("bse_edicoes", {})      # id do ato -> {"html","nome","cargo","nota"}  (sobrevive à troca de ato)
ss.setdefault("bse_pdfs", {})         # id do ato -> (hash_das_entradas, bytes)

with st.container(border=True):
    arquivo_bse = st.file_uploader("Selecione o Boletim de Serviço (PDF)", type=["pdf"], key=f"uploader_bse_{ss.bse_ver}")

ui.fluxo(["Enviar boletim", "Separar atos", "Editar", "Gerar PDF"], 2 if arquivo_bse else 0)

if arquivo_bse is None:
    ui.vazio("Envie um boletim para começar", "Cada ato normativo encontrado vira um item editável, com tabelas preservadas.", "news")
    st.stop()

with st.spinner("Analisando o boletim (parágrafos, tabelas e assinaturas)..."):
    atos = processar_boletim_pdf(arquivo_bse.getvalue())

if not atos:
    st.warning("Nenhum ato normativo no padrão reconhecido foi identificado automaticamente.", icon=":material/search_off:")
    st.stop()

n_tab = sum(1 for a in atos if "<table" in a["corpo_html"].lower())
n_ass = sum(1 for a in atos if a["nome_autoridade"])
ui.kpis([("Atos encontrados", len(atos), "file", "info"), ("Com tabelas", n_tab, "layers", "warn"), ("Signatário detectado", n_ass, "check", "ok"),
         ("Editados nesta sessão", len(ss.bse_edicoes), "sparkles", "rosa")])

rotulos = {a["id"]: f"{a['id']:02d} · {a['titulo']}" for a in atos}
ids = [a["id"] for a in atos]
ss.setdefault("bse_sel", ids[0])
if ss.bse_sel not in ids:
    ss.bse_sel = ids[0]


def _nav(delta):
    i = ids.index(ss.bse_sel)
    ss.bse_sel = ids[(i + delta) % len(ids)]


c_sel, c_prev, c_next = st.columns([6, 1, 1], vertical_alignment="bottom")
c_sel.selectbox("Ato para editar (digite para filtrar)", ids, format_func=lambda i: rotulos[i], key="bse_sel")
c_prev.button("", icon=":material/chevron_left:", on_click=_nav, args=(-1,), use_container_width=True, help="Ato anterior")
c_next.button("", icon=":material/chevron_right:", on_click=_nav, args=(1,), use_container_width=True, help="Próximo ato")

ato = next(a for a in atos if a["id"] == ss.bse_sel)
ed = ss.bse_edicoes.get(ato["id"], {})
tem_tabela = "<table" in ato["corpo_html"].lower()

# PERFORMANCE: só o ato selecionado renderiza editor (antes: um editor Quill + um PDF WeasyPrint POR ATO a cada interação).
if tem_tabela:
    st.warning("Tabela detectada neste ato: o modo **Código-fonte HTML** vem selecionado para proteger a formatação.", icon=":material/table:")
modo = st.radio("Modo de edição", ["Visual (texto rico)", "Código-fonte HTML (preserva tabelas)"], horizontal=True,
                index=1 if tem_tabela else 0, key=f"modo_{ato['id']}")
visual = modo.startswith("Visual") and HAS_QUILL

chave_sel = (ato["id"], visual)
if ss.get("_bse_chave") != chave_sel:       # mudou de ato/modo: fixa o valor inicial do editor
    ss["_bse_chave"] = chave_sel
    ss["_bse_ini"] = ed.get("html", ato["corpo_html"])
    ss["_bse_nonce"] = ss.get("_bse_nonce", 0) + 1

tab_ed, tab_pv = st.tabs([":material/edit: Editar", ":material/visibility: Prévia"])
with tab_ed:
    if visual:
        html_ed = st_quill(value=ss["_bse_ini"], html=True, toolbar=QUILL_TOOLBAR, key=f"quill_{ato['id']}_{ss['_bse_nonce']}")
        if html_ed is None:
            html_ed = ss["_bse_ini"]
    else:
        html_ed = st.text_area("HTML do ato", value=ss["_bse_ini"], height=360, key=f"ta_{ato['id']}_{ss['_bse_nonce']}")

    st.markdown("##### Assinatura e publicação")
    c1, c2 = st.columns(2)
    nome_ed = c1.text_input("Signatário (nome)", value=ed.get("nome", ato["nome_autoridade"]), key=f"nome_{ato['id']}")
    cargo_ed = c2.text_input("Cargo", value=ed.get("cargo", ato["cargo_autoridade"]), key=f"cargo_{ato['id']}")
    nota_ed = st.text_input("Nota de publicação (opcional)", value=ed.get("nota", ato["nota_publicacao"]), key=f"nota_{ato['id']}")
    ss.bse_edicoes[ato["id"]] = {"html": html_ed, "nome": nome_ed, "cargo": cargo_ed, "nota": nota_ed}

with tab_pv:
    st.markdown(f'<div class="cn-papel-barra"><i></i><i></i><i></i>&nbsp;{escape(ato["titulo"])}</div><div class="cn-papel">{exportacao.sanitizar(html_ed)}'
                f'<div class="cn-assinatura"><b>{escape(nome_ed or "")}</b><br>{escape(cargo_ed or "")}</div></div>', unsafe_allow_html=True)

st.markdown("---")
assinatura = hashlib.sha256("|".join([html_ed or "", nome_ed or "", cargo_ed or "", nota_ed or ""]).encode()).hexdigest()
c_g, c_d = st.columns(2)
if c_g.button("Gerar PDF formatado deste ato", type="primary", icon=":material/picture_as_pdf:", use_container_width=True):
    try:
        with st.spinner("Gerando PDF..."):
            ss.bse_pdfs[ato["id"]] = (assinatura, gerar_pdf_fiel_sei(html_ed, nome_ed, cargo_ed, nota_ed))
        conc.auditar("bse_pdf", ato["titulo"])
    except Exception as e:
        st.error(f"Erro ao gerar PDF do ato: {e}")
pronto = ss.bse_pdfs.get(ato["id"])
if pronto and pronto[0] == assinatura:
    c_d.download_button("Baixar PDF", data=pronto[1], file_name=f"{ato['titulo'].replace('/', '_').replace(' ', '_')}.pdf", mime="application/pdf",
                        icon=":material/download:", use_container_width=True, key=f"btn_dl_{ato['id']}")
elif pronto:
    c_d.caption("O ato foi editado depois do último PDF. Gere novamente.")

if st.button("Novo boletim", icon=":material/restart_alt:"):
    for k in ("bse_edicoes", "bse_pdfs", "bse_sel", "_bse_chave"):
        ss.pop(k, None)
    ss.bse_ver += 1
    st.rerun()
