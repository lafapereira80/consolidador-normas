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

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from menu_utils import configurar_pagina, exigir_login, renderizar_cabecalho, renderizar_menu

configurar_pagina("Extrair do Boletim de Serviço", "📋")
exigir_login()
renderizar_cabecalho("📋 Extração de Atos do Boletim de Serviço (BSe)")
renderizar_menu("bse")

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
                        # Expressão regular corrigida para n.º na ignorar tabelas de cabeçalho
                        if re.search(r'(Portaria|RESOLUÇÃO|ATO)\s+n\.?[º°o]?\s*\d+', texto_tabela, re.IGNORECASE): continue
                        if re.search(r'(Art\.\s*\d+|§\s*\d+|Parágrafo único)', texto_tabela, re.IGNORECASE): continue
                        if any(len(str(c)) > 250 for linha in linhas for c in linha if c): continue
                            
                        rect_text = fitz.Rect(tb.bbox)
                        sobrepoe = False
                        for t_val in tabelas_validas:
                            if rect_text.intersect(fitz.Rect(t_val.bbox)).get_area() > 0:
                                sobrepoe = True
                                break
                        if not sobrepoe: tabelas_validas.append(tb)
        except Exception: pass
        except TypeError:
            tf_default = page.find_tables()
            if tf_default.tables: tabelas_validas.extend(tf_default.tables)

        for tabela in tabelas_validas:
            rect = fitz.Rect(tabela.bbox)
            tabelas_bbox.append(rect)
            linhas = tabela.extract()
            if not linhas: continue
            tab_html = '
