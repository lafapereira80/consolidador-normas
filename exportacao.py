# exportacao.py - Geração de HTML / PDF / DOCX das versões alterada e consolidada (compartilhado por Consolidar e Histórico).
# Código extraído, sem mudança de comportamento, de pages/3_Consolidar_Norma.py (antes duplicado/divergente no Histórico).
import io
import os
import re
from html import unescape
from html.parser import HTMLParser

import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

try:
    from weasyprint import HTML as WeasyHTML
    HAS_WEASYPRINT = True
except Exception:
    HAS_WEASYPRINT = False

_BRASAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brasao.png")


class QuillParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paragraphs = []
        self.current_html = []
        self.stack = []

    def _close_all_tags(self):
        res = ""
        for tags in reversed(self.stack):
            for t in reversed(tags):
                tag_name = t.split()[0]
                res += f"</{tag_name}>"
        return res

    def _open_all_tags(self):
        res = ""
        for tags in self.stack:
            for t in tags:
                res += f"<{t}>"
        return res

    def _break_paragraph(self):
        if self.current_html:
            p_text = "".join(self.current_html) + self._close_all_tags()
            if re.sub(r'<[^>]+>', '', p_text).strip():
                self.paragraphs.append(p_text.strip())
        self.current_html = []
        if self.stack:
            self.current_html.append(self._open_all_tags())

    def handle_starttag(self, tag, attrs):
        if tag in ('p', 'br', 'div'):
            self._break_paragraph()
            return

        attrs_dict = dict(attrs)
        style = attrs_dict.get('style', '').lower().replace(' ', '')
        cls = attrs_dict.get('class', '').lower()
        cor = attrs_dict.get('color', '').lower()
        
        added_tags = []
        if tag in ('b', 'strong') or 'font-weight:bold' in style or 'font-weight:700' in style:
            added_tags.append("b")
        if tag in ('i', 'em') or 'font-style:italic' in style:
            added_tags.append("i")
        if tag in ('s', 'strike', 'del') or 'text-decoration:line-through' in style or 'ql-strike' in cls:
            added_tags.append("strike")
        if ('color:rgb(230' in style or 'color:red' in style or 'color:#e6' in style or 'color:#f00' in style or 'color:#ff0000' in style) or (tag == 'font' and attrs_dict.get('color') in ('red', '#f00', '#ff0000')):
            added_tags.append('font color="red"')
        
        if added_tags:
            for t in added_tags:
                self.current_html.append(f"<{t}>")
            self.stack.append(added_tags)
        else:
            self.stack.append([])

    def handle_endtag(self, tag):
        if tag in ('p', 'br', 'div'):
            return 
        
        if self.stack:
            tags_to_close = self.stack.pop()
            for t in reversed(tags_to_close):
                tag_name = t.split()[0]
                self.current_html.append(f"</{tag_name}>")

    def handle_startendtag(self, tag, attrs):
        if tag in ('br',):
            self._break_paragraph()

    def handle_data(self, data):
        if not data: return
        data = data.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\xa0', '&nbsp;')
        self.current_html.append(data)

    def get_paragraphs(self):
        self._break_paragraph()
        return self.paragraphs

def editor_para_pdf(texto):
    if not texto: return ""
    parser = QuillParser()
    try:
        parser.feed(texto)
        return "<br/>".join(parser.get_paragraphs())
    except Exception:
        texto_limpo = re.sub(r'</?(span|div|p|ul|li|ol)[^>]*>', '', texto, flags=re.IGNORECASE)
        return texto_limpo

def limpar_texto_ia(texto):
    if not texto: return ""
    return re.sub(r' {2,}', ' ', str(texto)).strip()

def injetar_nota_remissiva(texto, nota):
    if nota and nota.strip():
        n_sem_parenteses = nota.strip("()").strip()
        n_fmt = f"({n_sem_parenteses})"
        texto_puro = re.sub(r'<[^>]+>', '', texto if texto else '')
        if n_sem_parenteses.lower() in texto_puro.lower(): return texto 
        if texto:
            texto_limpo = re.sub(r'(<br/?>|\s)+$', '', texto).strip()
            return f'{texto_limpo} &nbsp;<span style="color: red;">{n_fmt}</span>'
        return f'<span style="color: red;">{n_fmt}</span>'
    return texto

def gerar_html_dinamico(consolidacao_dict, tipo_versao):
    titulo_doc = f"Versão {'Alterada' if tipo_versao=='alterada' else 'Consolidada'}"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{titulo_doc}</title>
        <style>
            @page {{
                size: A4;
                margin: 2.5cm 2cm;
                @bottom-center {{
                    content: "Nota: Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial.";
                    font-size: 9pt;
                    font-style: italic;
                    color: #333;
                }}
            }}
            body {{ font-family: 'Times New Roman', Times, serif; font-size: 11pt; line-height: 1.5; text-align: justify; }}
            .topo {{ text-align: center; color: #444; font-size: 10pt; font-weight: bold; margin-bottom: 20px; text-transform: uppercase; }}
            .brasao {{ text-align: center; margin-bottom: 10px; }}
            .brasao img {{ width: 45px; height: auto; display: block; margin: 0 auto; }}
            .orgaos {{ text-align: center; font-weight: bold; margin-bottom: 25px; }}
            .titulo {{ text-align: center; font-weight: bold; margin-bottom: 20px; }}
            .ementa {{ text-align: justify; margin-left: 45%; margin-bottom: 25px; font-weight: normal; }}
            .preambulo {{ text-align: justify; margin-bottom: 12px; text-indent: 0; }}
            .dispositivo {{ text-align: justify; text-indent: 40px; margin-bottom: 12px; }}
            .capitulo {{ text-align: center; font-weight: bold; margin-top: 20px; margin-bottom: 12px; text-transform: uppercase; }}
            .assinatura {{ text-align: center; font-weight: bold; margin-top: 50px; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 15px; }}
            td, th {{ border: 1px solid black; padding: 6px; text-align: left; vertical-align: middle; }}
            strike, s, del {{ text-decoration: line-through; }}
            b, strong {{ font-weight: bold; }}
            i, em {{ font-style: italic; }}
            font[color="red"], span[style*="color: red"], span[style*="color:rgb(230"] {{ color: red !important; }}
        </style>
    </head>
    <body>
        <div class="topo">{titulo_doc}</div>
    """
    if os.path.exists(_BRASAO):
        import base64
        with open(_BRASAO, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
            html += f"<div class='brasao'><img src='data:image/png;base64,{encoded_string}'/></div>"

    html += f"""
        <div class="orgaos">{limpar_texto_ia(consolidacao_dict.get("orgaos_emissores") or "").replace('<br/>', '<br>')}</div>
        <div class="titulo">{limpar_texto_ia(consolidacao_dict.get("titulo_portaria") or "").replace('<br/>', '<br>')}</div>
        <div class="ementa">{limpar_texto_ia(consolidacao_dict.get("ementa") or "").replace('<br/>', '<br>')}</div>
        <div class="preambulo">{limpar_texto_ia(consolidacao_dict.get("preambulo") or "").replace('<br/>', '<br>')}</div>
    """
    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva(item.get(f"texto_principal_{tipo_versao}"), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        eh_capitulo_ou_anexo = "capitulo" in t or "anexo" in t
        texto_puro = re.sub(r'<[^>]+>', '', t_prin or '')
        if eh_capitulo_ou_anexo and len(texto_puro) <= 150:
            # Título curto (ex.: "CAPÍTULO I", "ANEXO I"): mantém o destaque
            # centralizado/negrito/maiúsculo de sempre.
            html += f"<div class='capitulo'>{t_prin}</div>"
            if not item.get("is_tabela"):
                continue
        elif eh_capitulo_ou_anexo:
            # Bloco longo (ex.: corpo inteiro de um Anexo, não só o título):
            # força tudo em negrito/maiúsculo/centralizado deixava o texto
            # ilegível. Só a 1ª linha é o título; o resto vira parágrafo
            # normal, preservando negrito/itálico/riscado originais.
            partes_bloco = (t_prin or "").split("<br/>")
            if partes_bloco:
                html += f"<div class='capitulo'>{partes_bloco[0].strip()}</div>"
                for p in partes_bloco[1:]:
                    if p.strip():
                        html += f"<div class='dispositivo' style='text-indent:0;'>{p.strip()}</div>"
            if not item.get("is_tabela"):
                continue
        else:
            if t_prin:
                for p in t_prin.split("<br/>"):
                    if p.strip():
                        html += f"<div class='dispositivo'>{p.strip()}</div>"
        if item.get("is_tabela"):
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas:
                html += "<table>"
                for linha in linhas:
                    html += "<tr>"
                    for celula in linha: html += f"<td>{editor_para_pdf(celula)}</td>"
                    html += "</tr>"
                html += "</table>"
            t_pos = injetar_nota_remissiva(item.get(f"texto_pos_tabela_{tipo_versao}"), item.get("nota_remissiva"))
            if t_pos: 
                for p in t_pos.split("<br/>"):
                    if p.strip():
                        html += f"<div class='dispositivo'>{p.strip()}</div>"
    html += f"<div class='assinatura'>{limpar_texto_ia(consolidacao_dict.get('assinatura_nome') or '')}<br>{limpar_texto_ia(consolidacao_dict.get('assinatura_cargo') or '')}</div>"
    html += "</body></html>"
    return html

def gerar_pdf_dinamico(consolidacao_dict, tipo_versao):
    html_str = gerar_html_dinamico(consolidacao_dict, tipo_versao)
    if not HAS_WEASYPRINT:
        raise Exception("WeasyPrint não está disponível neste servidor.")
    buffer = io.BytesIO()
    WeasyHTML(string=html_str).write_pdf(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def aplicar_html_no_docx(p, texto_html, negrito_forcado=False, tamanho=11):
    texto_html = texto_html.replace("&nbsp;", "\xa0")
    tokens = re.split(r'(<[^>]+>)', texto_html)
    is_bold = is_strike = is_red = is_italic = False
    for token in tokens:
        if not token: continue
        t = token.lower()
        if t.startswith('<b') and not t.startswith('<br'): is_bold = True
        elif t == '</b>': is_bold = False
        elif t.startswith('<i'): is_italic = True
        elif t == '</i>': is_italic = False
        elif t.startswith('<strike') or t.startswith('<s') and not t.startswith('<span'): is_strike = True
        elif t == '</strike>' or t == '</s>': is_strike = False
        elif t.startswith('<font') and ('red' in t or '#f00' in t or '#e6' in t): is_red = True
        elif t.startswith('<span') and ('red' in t or '#f00' in t or '#e6' in t): is_red = True
        elif t == '</font>' or t == '</span>': is_red = False
        elif token.startswith('<'): pass
        else:
            token = unescape(token)
            run = p.add_run(token)
            run.font.name, run.font.size = 'Times New Roman', Pt(tamanho)
            if is_bold or negrito_forcado: run.bold = True
            if is_italic: run.italic = True
            if is_strike: run.font.strike = True
            if is_red: run.font.color.rgb = RGBColor(230, 0, 0)

def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
    doc = docx.Document()
    for section in doc.sections: section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Inches(1)
    ph = doc.add_paragraph(); ph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rh = ph.add_run(f"Versão {'Alterada' if tipo_versao=='alterada' else 'Consolidada'}")
    rh.font.name, rh.font.size, rh.bold, rh.font.color.rgb = 'Times New Roman', Pt(10), True, RGBColor(68, 68, 68)
    po = doc.add_paragraph(); po.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ro = po.add_run(limpar_texto_ia(consolidacao_dict.get("orgaos_emissores") or "").replace("<br/>", "\n"))
    ro.font.name, ro.font.size, ro.bold = 'Times New Roman', Pt(11), True
    ptit = doc.add_paragraph(); ptit.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rt = ptit.add_run(limpar_texto_ia(consolidacao_dict.get("titulo_portaria") or ""))
    rt.font.name, rt.font.size, rt.bold = 'Times New Roman', Pt(11), True

    def _render_docx_p(p_obj, texto_html, bold_all=False):
        if not texto_html: return
        for p_html in texto_html.split("<br/>"):
            if not p_html.strip(): continue
            if bold_all:
                aplicar_html_no_docx(p_obj, p_html, negrito_forcado=True, tamanho=10)
            else: 
                aplicar_html_no_docx(p_obj, p_html)
            p_obj.add_run("\n")

    p_ementa = doc.add_paragraph(); p_ementa.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; p_ementa.paragraph_format.left_indent = Inches(3)
    _render_docx_p(p_ementa, consolidacao_dict.get("ementa", ""))
    p_preambulo = doc.add_paragraph(); p_preambulo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; p_preambulo.paragraph_format.left_indent = Inches(0)
    _render_docx_p(p_preambulo, consolidacao_dict.get("preambulo", ""))

    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva(item.get(f"texto_principal_{tipo_versao}"), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        eh_capitulo_ou_anexo = "capitulo" in t or "anexo" in t
        texto_puro = re.sub(r'<[^>]+>', '', t_prin or '')
        if eh_capitulo_ou_anexo and len(texto_puro) <= 150:
            # Título curto: mantém o destaque centralizado/negrito de sempre.
            if "anexo" in t: doc.add_page_break()
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _render_docx_p(p, t_prin, bold_all=True)
            if not item.get("is_tabela"):
                continue
        elif eh_capitulo_ou_anexo:
            # Bloco longo: só a 1ª linha é o título (centralizado/negrito); o
            # resto vira parágrafo normal, preservando negrito/itálico/riscado
            # originais (bold_all=True apagava essas tags e forçava tudo em
            # negrito, deixando o corpo do Anexo desformatado).
            if "anexo" in t: doc.add_page_break()
            partes_bloco = (t_prin or "").split("<br/>")
            if partes_bloco:
                p_tit = doc.add_paragraph(); p_tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
                aplicar_html_no_docx(p_tit, partes_bloco[0], negrito_forcado=True, tamanho=10)
                corpo_restante = "<br/>".join(partes_bloco[1:]).strip()
                if corpo_restante:
                    p_corpo = doc.add_paragraph(); p_corpo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                    _render_docx_p(p_corpo, corpo_restante)
            if not item.get("is_tabela"):
                continue
        else:
            if t_prin:
                p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; p.paragraph_format.first_line_indent = Inches(0.4)
                _render_docx_p(p, t_prin)
        if item.get("is_tabela"):
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas:
                tb = doc.add_table(rows=len(linhas), cols=len(linhas[0])); tb.style = 'Table Grid'
                for r_idx, linha in enumerate(linhas):
                    for c_idx, celula in enumerate(linha):
                        _render_docx_p(tb.cell(r_idx, c_idx).paragraphs[0], celula.replace('\n', '<br/>'))
            t_pos = injetar_nota_remissiva(item.get(f"texto_pos_tabela_{tipo_versao}"), item.get("nota_remissiva"))
            if t_pos:
                p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; p.paragraph_format.first_line_indent = Inches(0.4)
                _render_docx_p(p, t_pos)

    pa = doc.add_paragraph(); pa.alignment = WD_ALIGN_PARAGRAPH.CENTER; pa.paragraph_format.space_before = Pt(36)
    ra = pa.add_run(f"{limpar_texto_ia(consolidacao_dict.get('assinatura_nome') or '')}\n{limpar_texto_ia(consolidacao_dict.get('assinatura_cargo') or '')}")
    ra.font.name, ra.font.size, ra.bold = 'Times New Roman', Pt(11), True

    p_nota = doc.add_paragraph(); p_nota.alignment = WD_ALIGN_PARAGRAPH.CENTER; p_nota.paragraph_format.space_before = Pt(30)
    r_nota = p_nota.add_run("Nota: Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial.")
    r_nota.font.name = 'Times New Roman'; r_nota.font.size = Pt(9); r_nota.italic = True

    buffer = io.BytesIO(); doc.save(buffer); buffer.seek(0)
    return buffer.getvalue()


_TAGS_PERIGOSAS = re.compile(r"<\s*(script|iframe|object|embed|style|link|meta|form)\b.*?(</\s*\1\s*>|$)", re.IGNORECASE | re.DOTALL)
_ATRIB_PERIGOSO = re.compile(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)


def sanitizar(html):
    """Remove scripts/iframes/atributos on*= de HTML vindo de PDF/IA antes de exibi-lo na tela."""
    h = _TAGS_PERIGOSAS.sub("", html or "")
    h = _ATRIB_PERIGOSO.sub("", h)
    return re.sub(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", "", h, flags=re.IGNORECASE)


def corpo_para_previa(consolidacao_dict, tipo_versao):
    """Corpo do documento (sem <html>/@page) saneado, para exibir na tela dentro de .cn-papel."""
    html = gerar_html_dinamico(consolidacao_dict, tipo_versao)
    m = re.search(r"<body>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    return sanitizar(m.group(1) if m else html)
