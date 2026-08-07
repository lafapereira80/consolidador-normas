import streamlit as st
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Line
import io
import json
import os
import re
import time
from datetime import datetime
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional

# Importação para Supabase, Word e Leitura de PDF Determinística
from supabase import create_client, Client
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import fitz  # PyMuPDF

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(page_title="Autopilot Normativo", page_icon="⚖️", layout="wide")

# ----------------- LAYOUT E CSS -----------------
st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none; }
    .block-container { padding-top: 2rem; }
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 30px 20px;
        border-radius: 12px;
        color: white;
        text-align: center;
        box-shadow: 0 8px 16px rgba(0,0,0,0.15);
        margin-bottom: 25px;
    }
    .main-header h1 { color: #00FF87; font-weight: 800; font-size: 2.8rem; margin-bottom: 10px; }
    .main-header p { font-size: 1.2rem; color: #f1f1f1; margin-bottom: 0; }
</style>
<div class="main-header">
    <h1>⚖️ Autopilot Normativo</h1>
    <p>Motor Híbrido com OCR Estrutural e Preservação de Layout Original</p>
</div>
""", unsafe_allow_html=True)

# ----------------- CONEXÃO COM SUPABASE -----------------
@st.cache_resource
def init_supabase() -> Optional[Client]:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception:
        return None

supabase = init_supabase()

def render_botao_historico():
    caminho_real = None
    if os.path.exists("pages"):
        for arquivo in os.listdir("pages"):
            if "historico" in arquivo.lower() and arquivo.endswith(".py"):
                caminho_real = f"pages/{arquivo}"
                break
    if caminho_real:
        try:
            st.page_link(caminho_real, label="🗄️ Acessar Banco de Dados", icon="➡️")
        except Exception:
            nome_pagina = caminho_real.replace("pages/", "").replace(".py", "")
            st.markdown(f'<a href="{nome_pagina}" target="_top" style="display: block; text-align: center; background-color: #ff4b4b; color: white !important; padding: 0.6rem 1rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold;">➡️ 🗄️ Acessar Banco de Dados</a>', unsafe_allow_html=True)

col_info, col_nav = st.columns([2, 1])
with col_info:
    st.info("💡 **Leitura OCR Estrutural Ativada:** Preservação milimétrica da disposição de textos, ementas e preâmbulos.")
with col_nav:
    render_botao_historico()

st.markdown("---")

api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    with st.expander("⚙️ Configurações do Sistema (Chave API)", expanded=True):
        api_key = st.text_input("Chave da API", type="password", placeholder="Cole sua chave AI Studio aqui...")

st.markdown("### 📥 Upload de Arquivos Normativos")
arquivos_enviados = st.file_uploader("Arraste todos os documentos (PDF ou DOCX)", type=["pdf", "docx"], accept_multiple_files=True, key="uploader_lote")

# ----------------- FUNÇÃO DE FALLBACK COM 5 TENTATIVAS NO 3.6 -----------------
def executar_com_fallback(client, contents, response_schema):
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=response_schema, temperature=0.0)
    
    max_tentativas_36 = 5
    for tentativa in range(1, max_tentativas_36 + 1):
        try:
            return client.models.generate_content(
                model='gemini-3.6-flash',
                contents=contents,
                config=config
            )
        except Exception as e:
            mensagem_erro = str(e)
            if "429" in mensagem_erro or "RESOURCE_EXHAUSTED" in mensagem_erro:
                if tentativa < max_tentativas_36:
                    st.toast(f"⚡ Tentativa {tentativa}/{max_tentativas_36} no 3.6 esgotada. Tentando novamente...", icon="⏳")
                    time.sleep(3)
                    continue
                else:
                    st.toast("⚡ 5 tentativas esgotadas no Gemini 3.6. Alternando para o Gemini 3.5 Flash...", icon="🔄")
            else:
                raise e

    try:
        return client.models.generate_content(
            model='gemini-3.5-flash',
            contents=contents,
            config=config
        )
    except Exception as e_secundario:
        raise Exception(f"Erro crítico: O sistema tentou 5 vezes no Gemini 3.6 e falhou no 3.5 por cota. Detalhes: {e_secundario}")

# ----------------- CONVERSOR DE DATA SQL -----------------
def converter_para_iso(data_str):
    if not data_str: return None
    data_str = data_str.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', data_str):
        return data_str
    match_br = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', data_str)
    if match_br:
        d, m, a = match_br.groups()
        return f"{a}-{m}-{d}"
    try:
        dt = datetime.strptime(data_str, "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except:
        return None

# ----------------- EXTRAÇÃO DETERMINÍSTICA COM LAYOUT PRESERVADO (ESTILO OCR) -----------------
def extrair_texto_com_formatacao(file_bytes, nome_arquivo):
    if nome_arquivo.lower().endswith(".docx"):
        return f"ARQUIVO DOCX: {nome_arquivo}"
    
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        html_text = f"CONTEÚDO DO ARQUIVO {nome_arquivo}:\n\n"
        for page_num, page in enumerate(doc):
            html_text += f"--- PÁGINA {page_num + 1} ---\n"
            # Utiliza o modo block ordenado para respeitar rigorosamente a geometria visual original
            blocks = page.get_text("dict", sort=True).get("blocks", [])
            for b in blocks:
                if b.get('type') == 0:  # Bloco de texto
                    for l in b.get("lines", []):
                        line_text = ""
                        for s in l.get("spans", []):
                            texto = s.get("text", "")
                            if not texto: continue
                            flags = s.get("flags", 0)
                            is_bold = flags & 2**4
                            is_italic = flags & 2**1
                            
                            if is_bold: texto = f"<b>{texto}</b>"
                            if is_italic: texto = f"<i>{texto}</i>"
                            line_text += texto
                        if line_text.strip():
                            html_text += line_text + "<br/>\n"
                    html_text += "<br/>\n"  # Garante espaçamento limpo entre parágrafos
        return html_text
    except Exception as e:
        return f"Erro ao extrair PDF {nome_arquivo}: {str(e)}"

# ----------------- ESTRUTURAS PYDANTIC -----------------
class ArquivoClassificado(BaseModel):
    nome_arquivo_upload: str
    tipo: str = Field(description="'Base' ou 'Alteradora'")
    data_oficial_iso: str = Field(description="Data formatada estritamente em YYYY-MM-DD.")

class TriagemDocumentos(BaseModel):
    arquivos: List[ArquivoClassificado]

class MetadadosNorma(BaseModel):
    tipo_documento: str
    numero_documento: str
    orgao_emissor: str
    data_assinatura: str = Field(description="Data estritamente no formato YYYY-MM-DD.")
    nome_padronizado: str

class Dispositivo(BaseModel):
    tipo: str
    texto_principal_alterada: str = Field(description="Mantenha <b> e <i>. Use <br/> para separar parágrafos e incisos. NUNCA use '\\n'.")
    texto_principal_consolidada: str = Field(description="Texto limpo em vigor. Mantenha <b> e <i>. Use <br/> para quebras.")
    is_tabela: bool
    tabela_alterada: Optional[List[List[str]]] = None
    tabela_consolidada: Optional[List[List[str]]] = None
    texto_pos_tabela_alterada: Optional[List[List[str]]] = None
    texto_pos_tabela_consolidada: Optional[List[List[str]]] = None
    nota_remissiva: Optional[str] = Field(default="", description="Ex: '(Alterado por...)'")

class Consolidacao(BaseModel):
    arquivos_originais_identificados: List[str]
    arquivos_alteradores_identificados: List[str]
    norma_base: MetadadosNorma
    normas_alteradoras: List[MetadadosNorma]
    cabecalho_complemento: str
    orgaos_emissores: str
    titulo_portaria: str
    ementa_preambulo: str = Field(description="Ementa e preâmbulo mantendo o fluxo natural do documento original, separando blocos com <br/> e mantendo negritos intocados.")
    assinatura_nome: str
    assinatura_cargo: str
    dispositivos: List[Dispositivo]

class AnaliseGlobal(BaseModel):
    consolidacoes_geradas: List[Consolidacao]
    arquivos_nao_alterados: List[str]

# ----------------- FUNÇÃO DE LIMPEZA BLINDADA -----------------
def limpar_texto_ia(texto):
    if not texto: return ""
    texto = texto.replace('\\n', ' ').replace('\n', ' ')
    texto = texto.replace('<br>', '<br/>').replace('<br >', '<br/>')
    texto = re.sub(r' {2,}', ' ', texto).strip()
    return texto

def injetar_nota_remissiva(texto, nota):
    if nota and nota.strip():
        n = f"({nota.strip()})" if not nota.strip().startswith("(") else nota.strip()
        if texto:
            texto_limpo = re.sub(r'(<br/?>|\s)+$', '', texto).strip()
            return f"{texto_limpo} &nbsp;<font color='red'>{n}</font>"
        else:
            return f"<font color='red'>{n}</font>"
    return texto

# ----------------- PIPELINE DE EXECUÇÃO ROBUSTO PARA MÚLTIPLAS PORTARIAS -----------------
def analisar_lote_arquivos(arquivos, key):
    client = genai.Client(api_key=key)
    
    textos_extraidos = {}
    for arq in arquivos:
        textos_extraidos[arq.name] = extrair_texto_com_formatacao(arq.getvalue(), arq.name)

    prompt_triagem = f"""
    Analise os textos estruturados abaixo (extraídos preservando o layout original). 
    Identifique a Norma Base e TODAS as portarias alteradoras presentes no lote. Ordene e classifique cada uma, extraindo a data de assinatura no formato YYYY-MM-DD.
    TEXTOS: {" | ".join([f"[{k}]" for k in textos_extraidos.keys()])}
    """
    
    resp_triagem = executar_com_fallback(
        client=client,
        contents=[prompt_triagem] + list(textos_extraidos.values()),
        response_schema=TriagemDocumentos
    )
    
    triagem_dados = json.loads(resp_triagem.text).get("arquivos", [])
    arquivo_base = next((a for a in triagem_dados if a['tipo'] == 'Base'), None)
    arquivos_alteradores = [a for a in triagem_dados if a['tipo'] == 'Alteradora']
    arquivos_alteradores.sort(key=lambda x: x['data_oficial_iso'])
    
    if not arquivo_base and not arquivos_alteradores:
        raise ValueError("Não foi possível identificar a relação normativa entre os documentos.")

    estado_json_atual = None
    if arquivo_base and supabase:
        try:
            nome_hipotetico = arquivo_base.get('nome_arquivo_upload', '')
            res_bd = supabase.table("portarias_base").select("documento_consolidado_json").ilike("arquivo_original_identificado", f"%{nome_hipotetico}%").execute()
            if res_bd.data and res_bd.data[0].get("documento_consolidado_json"):
                estado_json_atual = json.dumps(res_bd.data[0]['documento_consolidado_json'])
        except: pass

    if not arquivos_alteradores:
        conteudo_loop = [f"Texto Base:\n{textos_extraidos[arquivo_base['nome_arquivo_upload']]}"]
        resp_loop = executar_com_fallback(
            client=client,
            contents=conteudo_loop + ["Gere o JSON consolidado preservando rigidamente o layout, ementa, preâmbulo e tags <b> e <br/>."],
            response_schema=AnaliseGlobal
        )
        return json.loads(resp_loop.text)
    
    else:
        for i, alt in enumerate(arquivos_alteradores):
            conteudo_loop = []
            if estado_json_atual:
                conteudo_loop.append(f"ESTADO ATUAL DO DOCUMENTO CONSOLIDADO (JSON):\n{estado_json_atual}")
            elif arquivo_base and i == 0:
                conteudo_loop.append(f"DOCUMENTO BASE ORIGINAL:\n{textos_extraidos[arquivo_base['nome_arquivo_upload']]}")
            
            nome_alt_atual = alt['nome_arquivo_upload']
            conteudo_loop.append(f"PORTARIA ALTERADORA Nº {i+1} A SER APLICADA ({nome_alt_atual}):\n{textos_extraidos[nome_alt_atual]}")
            
            prompt_loop = f"""
            Você está executando o passo {i+1} de {len(arquivos_alteradores)} no pipeline de consolidação em cascata.
            Pegue o Estado Atual do Documento e aplique cirurgicamente as modificações contidas nesta portaria alteradora.
            
            REGRAS OBRIGATÓRIAS DE LEIAUTE E FORMATAÇÃO (ESTILO OCR):
            1. PREÂMBULO E EMENTA: Mantenha o fluxo exato e limpo do texto original, separando os blocos (ementa, considerandos, 'Resolve:') com a tag `<br/>`. Preserve todos os negritos originais encontrados no topo do documento (ex: nomes de órgãos, ementas, etc).
            2. CASCATA COMPLETA: Processe integralmente esta portaria alteradora {i+1}, acumulando as revogações e alterações sobre o texto anterior sem omitir nenhuma diretriz.
            3. Use `<font color='red'><strike>texto revogado</strike></font>` para revogações e preserve todas as tags <b> e <i>.
            """
            conteudo_loop.append(prompt_loop)
            
            resp_loop = executar_com_fallback(
                client=client,
                contents=conteudo_loop,
                response_schema=AnaliseGlobal
            )
            estado_json_atual = resp_loop.text 

        return json.loads(resp_loop.text)

# --- FUNÇÕES DE RENDERIZAÇÃO PDF E DOCX ---
def extrair_paragrafos_seguros(texto_html):
    texto_html = limpar_texto_ia(texto_html)
    texto_html = re.sub(r'</?(span|div|p|ul|li|ol)[^>]*>', '', texto_html, flags=re.IGNORECASE)
    texto_html = texto_html.replace("</font></strike>", "</strike></font>").replace("</b></i>", "</i></b>")
    
    tokens = re.split(r'(<[^>]+>)', texto_html)
    paragrafos, pilha, texto_atual = [], [], ""
    def fechar_todas(p_tags):
        r = ""
        for tag in reversed(p_tags):
            t = tag.lower()
            if t.startswith("<font"): r += "</font>"
            elif t.startswith("<strike"): r += "</strike>"
            elif t == "<b>": r += "</b>"
            elif t == "<i>": r += "</i>"
        return r
    def abrir_todas(p_tags): return "".join(p_tags)
    for token in tokens:
        if not token: continue
        t = token.lower()
        if t in ["<br>", "<br/>", "<br />"]:
            texto_atual += fechar_todas(pilha)
            if re.sub(r'<[^>]+>', '', texto_atual).strip(): paragrafos.append(texto_atual.strip())
            texto_atual = abrir_todas(pilha)
        elif t.startswith("</"):
            rm = False
            for i in range(len(pilha)-1, -1, -1):
                pl = pilha[i].lower()
                if (t == "</font>" and pl.startswith("<font")) or (t == "</strike>" and pl.startswith("<strike")) or (t == "</b>" and pl == "<b>") or (t == "</i>" and pl == "<i>"):
                    pilha.pop(i)
                    rm = True
                    break
            if rm: texto_atual += token
        elif t.startswith("<font") or t.startswith("<strike") or t in ["<b>", "<i>"]:
            pilha.append(token)
            texto_atual += token
        else: texto_atual += token
    texto_atual += fechar_todas(pilha)
    if re.sub(r'<[^>]+>', '', texto_atual).strip(): paragrafos.append(texto_atual.strip())
    return paragrafos

def renderizar_paragrafos_pdf(story, texto_html, estilo):
    for p in extrair_paragrafos_seguros(texto_html): story.append(Paragraph(p, estilo))

def aplicar_html_no_docx(p, texto_html):
    texto_html = limpar_texto_ia(texto_html).replace("&nbsp;", "\xa0")
    texto_html = re.sub(r'</?(span|div|p|ul|li|ol)[^>]*>', '', texto_html, flags=re.IGNORECASE)
    tokens = re.split(r'(<[^>]+>)', texto_html)
    is_bold = is_strike = is_red = is_italic = False
    for token in tokens:
        if not token: continue
        t = token.lower()
        if t == '<b>': is_bold = True
        elif t == '</b>': is_bold = False
        elif t == '<i>': is_italic = True
        elif t == '</i>': is_italic = False
        elif t == '<strike>': is_strike = True
        elif t == '</strike>': is_strike = False
        elif "font color" in t and ("red" in t or "'red'" in t or '"red"' in t): is_red = True
        elif t == '</font>': is_red = False
        elif token.startswith('<'): pass
        else:
            run = p.add_run(token)
            run.font.name, run.font.size = 'Times New Roman', Pt(11)
            if is_bold: run.bold = True
            if is_italic: run.italic = True
            if is_strike: run.font.strike = True
            if is_red: run.font.color.rgb = RGBColor(255, 0, 0)

def renderizar_paragrafos_docx(doc, texto_html, alignment, first_line_indent, space_after=Pt(6), bold_all=False):
    for p_html in extrair_paragrafos_seguros(texto_html):
        p = doc.add_paragraph()
        p.alignment = alignment
        p.paragraph_format.first_line_indent = first_line_indent
        p.paragraph_format.space_after = space_after
        p.paragraph_format.line_spacing = 1.15
        if bold_all:
            run = p.add_run(re.sub(r'<[^>]+>', '', p_html).replace("&nbsp;", "\xa0"))
            run.font.name, run.font.size, run.bold = 'Times New Roman', Pt(10), True
        else: aplicar_html_no_docx(p, p_html)

def gerar_pdf_dinamico(consolidacao_dict, tipo_versao):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    story, styles = [], getSampleStyleSheet()
    estilos = {
        'topo': ParagraphStyle('Topo', parent=styles['Normal'], fontName='Times-Bold', fontSize=10, alignment=1, textColor=colors.HexColor('#444444'), spaceAfter=20),
        'orgaos': ParagraphStyle('Orgaos', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, alignment=1, spaceAfter=25),
        'tit': ParagraphStyle('Tit', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, alignment=1, spaceAfter=20),
        'disp': ParagraphStyle('Disp', parent=styles['Normal'], fontName='Times-Roman', fontSize=11, alignment=4, firstLineIndent=30, spaceAfter=12),
        'cel': ParagraphStyle('Cel', parent=styles['Normal'], fontName='Times-Roman', fontSize=10, alignment=0),
        'cap': ParagraphStyle('Cap', parent=styles['Normal'], fontName='Times-Bold', fontSize=10, alignment=1, spaceBefore=20, spaceAfter=12, textTransform='uppercase'),
        'ass': ParagraphStyle('Ass', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, alignment=1, spaceBefore=50, spaceAfter=20)
    }

    comp = consolidacao_dict.get("cabecalho_complemento", "")
    story.append(Paragraph(f"VERSÃO {'ALTERADA' if tipo_versao=='alterada' else 'CONSOLIDADA'} - {comp}", estilos['topo']))
    if os.path.exists("brasao.png"):
        img = Image("brasao.png", width=60, height=60); img.hAlign = 'CENTER'; story.append(img); story.append(Spacer(1, 10))

    story.append(Paragraph(limpar_texto_ia(consolidacao_dict.get("orgaos_emissores") or "").replace('\n', '<br/>'), estilos['orgaos']))
    story.append(Paragraph(limpar_texto_ia(consolidacao_dict.get("titulo_portaria") or "").replace('\n', '<br/>'), estilos['tit']))
    renderizar_paragrafos_pdf(story, (consolidacao_dict.get("ementa_preambulo") or "").replace('\n', '<br/>'), estilos['disp'])

    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva((item.get(f"texto_principal_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        if "capitulo" in t: story.append(Paragraph(t_prin, estilos['cap'])); continue
        if t_prin: renderizar_paragrafos_pdf(story, t_prin, estilos['disp'])
        
        if item.get("is_tabela"):
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas:
                tabela = [[Paragraph(c.replace('\n', '<br/>'), estilos['cel']) for c in l] for l in linhas]
                tb = Table(tabela, colWidths='*')
                tb.setStyle(TableStyle([('TEXTCOLOR',(0,0),(-1,-1),colors.black), ('ALIGN',(0,0),(-1,-1),'LEFT'), ('VALIGN',(0,0),(-1,-1),'MIDDLE'), ('GRID',(0,0),(-1,-1),0.5,colors.black), ('BOTTOMPADDING',(0,0),(-1,-1),6), ('TOPPADDING',(0,0),(-1,-1),6)]))
                story.append(tb); story.append(Spacer(1, 15))
            t_pos = injetar_nota_remissiva((item.get(f"texto_pos_tabela_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva"))
            if t_pos: renderizar_paragrafos_pdf(story, t_pos, estilos['disp'])

    story.append(Paragraph(f"{limpar_texto_ia(consolidacao_dict.get('assinatura_nome') or '')}<br/>{limpar_texto_ia(consolidacao_dict.get('assinatura_cargo') or '')}", estilos['ass']))
    doc.build(story); buffer.seek(0)
    return buffer.getvalue()

def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
    doc = docx.Document()
    for section in doc.sections: section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Inches(1)

    ph = doc.add_paragraph(); ph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rh = ph.add_run(f"VERSÃO {'ALTERADA' if tipo_versao=='alterada' else 'CONSOLIDADA'} - {consolidacao_dict.get('cabecalho_complemento', '')}")
    rh.font.name, rh.font.size, rh.bold, rh.font.color.rgb = 'Times New Roman', Pt(10), True, RGBColor(68, 68, 68)
    
    po = doc.add_paragraph(); po.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ro = po.add_run(limpar_texto_ia(consolidacao_dict.get("orgaos_emissores") or "").replace("<br/>", "\n"))
    ro.font.name, ro.font.size, ro.bold = 'Times New Roman', Pt(11), True

    ptit = doc.add_paragraph(); ptit.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rt = ptit.add_run(limpar_texto_ia(consolidacao_dict.get("titulo_portaria") or ""))
    rt.font.name, rt.font.size, rt.bold = 'Times New Roman', Pt(11), True

    renderizar_paragrafos_docx(doc, (consolidacao_dict.get("ementa_preambulo") or "").replace('\n', '<br/>'), WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))

    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva((item.get(f"texto_principal_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        if "capitulo" in t: renderizar_paragrafos_docx(doc, t_prin, WD_ALIGN_PARAGRAPH.CENTER, Inches(0), Pt(10), bold_all=True); continue
        if t_prin: renderizar_paragrafos_docx(doc, t_prin, WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))
        
        if item.get("is_tabela"):
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas:
                tb = doc.add_table(rows=len(linhas), cols=len(linhas[0])); tb.style = 'Table Grid'
                for r_idx, linha in enumerate(linhas):
                    for c_idx, celula in enumerate(linha):
                        aplicar_html_no_docx(tb.cell(r_idx, c_idx).paragraphs[0], celula.replace('\n', '<br/>'))
            t_pos = injetar_nota_remissiva((item.get(f"texto_pos_tabela_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva"))
            if t_pos: renderizar_paragrafos_docx(doc, t_pos, WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))

    pa = doc.add_paragraph(); pa.alignment = WD_ALIGN_PARAGRAPH.CENTER; pa.paragraph_format.space_before = Pt(36)
    ra = pa.add_run(f"{limpar_texto_ia(consolidacao_dict.get('assinatura_nome') or '')}\n{limpar_texto_ia(consolidacao_dict.get('assinatura_cargo') or '')}")
    ra.font.name, ra.font.size, ra.bold = 'Times New Roman', Pt(11), True
    buffer = io.BytesIO(); doc.save(buffer); buffer.seek(0)
    return buffer.getvalue()

def salvar_no_supabase(cons):
    if not supabase: st.error("⚠️ Supabase não configurado."); return False
    try:
        base = cons['norma_base']
        alteradoras = cons.get('normas_alteradoras', [])
        
        data_base_iso = converter_para_iso(base.get('data_assinatura'))
        
        res_busca = supabase.table("portarias_base").select("id").eq("nome_padronizado", base['nome_padronizado']).execute()
        
        if res_busca.data:
            base_id = res_busca.data[0]['id']
            supabase.table("portarias_base").update({"documento_consolidado_json": cons}).eq("id", base_id).execute()
        else:
            res_ins = supabase.table("portarias_base").insert({
                "tipo_documento": base['tipo_documento'],
                "numero_documento": base['numero_documento'],
                "orgao_emissor": base['orgao_emissor'],
                "data_assinatura": data_base_iso,
                "nome_padronizado": base['nome_padronizado'],
                "titulo_original": cons.get("titulo_portaria"),
                "orgaos_emissores": cons.get("orgaos_emissores"),
                "assinatura_nome": cons.get("assinatura_nome"),
                "assinatura_cargo": cons.get("assinatura_cargo"),
                "documento_consolidado_json": cons
            }).execute()
            base_id = res_ins.data[0]['id']
            
        for alt in alteradoras:
            res_alt = supabase.table("portarias_alteradoras").select("id").eq("portaria_base_id", base_id).eq("nome_padronizado", alt['nome_padronizado']).execute()
            
            if not res_alt.data:
                data_alt_iso = converter_para_iso(alt.get('data_assinatura'))
                
                supabase.table("portarias_alteradoras").insert({
                    "portaria_base_id": base_id,
                    "tipo_documento": alt['tipo_documento'],
                    "numero_documento": alt['numero_documento'],
                    "orgao_emissor": alt['orgao_emissor'],
                    "data_assinatura": data_alt_iso,
                    "nome_padronizado": alt['nome_padronizado'],
                    "arquivo_nome_original": "Múltiplos Documentos"
                }).execute()
                
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

# ----------------- FRONT-END -----------------
if "dados_processados" not in st.session_state: st.session_state.dados_processados = None
st.markdown("<br>", unsafe_allow_html=True)

if st.button("🚀 Iniciar Análise Autopilot", type="primary", use_container_width=True):
    if not api_key: 
        st.error("⚠️ Insira sua chave da API nas configurações.")
    elif not arquivos_enviados: 
        st.warning("⚠️ Envie os arquivos normativos primeiro.")
    else:
        with st.spinner("⚡ Executando OCR Estrutural e Varredura Completa de Múltiplas Portarias..."):
            try:
                st.session_state.dados_processados = analisar_lote_arquivos(arquivos_enviados, api_key.strip())
                st.success("✨ Processamento Concluído com Sucesso!")
            except Exception as e:
                mensagem_erro = str(e)
                st.error(f"❌ Ocorreu um erro crítico: {mensagem_erro}")

if st.session_state.dados_processados:
    st.markdown("---")
    dados = st.session_state.dados_processados
    for i, cons in enumerate(dados.get("consolidacoes_geradas", [])):
        nome_exibicao_base = cons['norma_base']['nome_padronizado']
        nomes_alteradoras = [alt['nome_padronizado'] for alt in cons.get('normas_alteradoras', [])]
        nome_exibicao_alt = " e ".join(nomes_alteradoras) if nomes_alteradoras else "Desconhecido"
        
        with st.expander(f"📁 **{nome_exibicao_base}** alterada por **{nome_exibicao_alt}**", expanded=True):
            if st.button(f"💾 Salvar Cascata Inteira no Supabase", key=f"btn_sup_{i}"):
                if salvar_no_supabase(cons): st.success(f"Banco atualizado com as alterações em cascata!")
            
            c1, c2 = st.columns(2)
            pdf_alt, docx_alt = gerar_pdf_dinamico(cons, "alterada"), gerar_docx_dinamico(cons, "alterada")
            pdf_cons, docx_cons = gerar_pdf_dinamico(cons, "consolidada"), gerar_docx_dinamico(cons, "consolidada")
            
            nome_arquivo_base = nome_exibicao_base.replace(' ', '_').replace('/', '-')
            c1.download_button("Baixar PDF (Alterada)", data=pdf_alt, file_name=f"{nome_arquivo_base}_Alt.pdf", mime="application/pdf", key=f"pa_{i}")
            c1.download_button("Baixar DOCX (Alterada)", data=docx_alt, file_name=f"{nome_arquivo_base}_Alt.docx", mime="application/vnd.openxmlformats", key=f"da_{i}")
            c2.download_button("Baixar PDF (Consolidada)", data=pdf_cons, file_name=f"{nome_arquivo_base}_Cons.pdf", mime="application/pdf", key=f"pc_{i}")
            c2.download_button("Baixar DOCX (Consolidada)", data=docx_cons, file_name=f"{nome_arquivo_base}_Cons.docx", mime="application/vnd.openxmlformats", key=f"dc_{i}")

    if st.button("🔄 Nova Análise", type="secondary"): st.session_state.dados_processados = None; st.rerun()
