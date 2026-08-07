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
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional

# Importação para Supabase
from supabase import create_client, Client

# Importação para geração de arquivos Word (.docx)
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(page_title="Autopilot Normativo", page_icon="⚖️", layout="wide")

# ----------------- LAYOUT MODERNO (CSS) -----------------
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 30px 20px;
        border-radius: 12px;
        color: white;
        text-align: center;
        box-shadow: 0 8px 16px rgba(0,0,0,0.15);
        margin-bottom: 25px;
    }
    .main-header h1 {
        color: #00FF87;
        font-weight: 800;
        font-size: 2.8rem;
        margin-bottom: 10px;
    }
    .main-header p {
        font-size: 1.2rem;
        color: #f1f1f1;
        margin-bottom: 0;
    }
</style>

<div class="main-header">
    <h1>⚖️ Autopilot Normativo</h1>
    <p>Consolidação Inteligente e Gestão de Portarias com IA (Memória Cumulativa Ativa)</p>
</div>
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

# ----------------- AUTO-DETECÇÃO DA PÁGINA HISTÓRICO -----------------
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
            st.markdown(f'''
                <a href="{nome_pagina}" target="_top" style="display: block; text-align: center; background-color: #ff4b4b; color: white !important; padding: 0.6rem 1rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold; font-family: sans-serif; box-shadow: 0 2px 5px rgba(0,0,0,0.2);">
                    ➡️ 🗄️ Acessar Banco de Dados
                </a>
            ''', unsafe_allow_html=True)
    else:
        st.warning("⚠️ **Atenção:** O Streamlit não encontrou a pasta `pages` ou o arquivo de histórico. Certifique-se de que a estrutura seja exata: `pages/1_Historico.py`.")

# ----------------- NAVEGAÇÃO E CONFIGURAÇÕES -----------------
col_info, col_nav = st.columns([2, 1])

with col_info:
    st.info("💡 **Inteligência Ativada:** Envie os novos arquivos. O sistema buscará automaticamente o texto base no Supabase se houver histórico.")

with col_nav:
    render_botao_historico()

st.markdown("---")

api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    with st.expander("⚙️ Configurações do Sistema (Chave API)", expanded=True):
        st.markdown("Para o sistema funcionar, insira sua chave da API do Google Gemini abaixo:")
        api_key = st.text_input("Chave da API", type="password", placeholder="Cole sua chave AI Studio aqui...")

# ----------------- ÁREA DE UPLOAD E PROCESSAMENTO -----------------
st.markdown("### 📥 Upload de Arquivos Normativos")
arquivos_enviados = st.file_uploader("Arraste todos os documentos de uma vez (PDF ou DOCX)", type=["pdf", "docx"], accept_multiple_files=True, key="uploader_lote")

# Estruturas Pydantic Gerais
class Dispositivo(BaseModel):
    tipo: str = Field(description="Ex: 'capitulo', 'artigo', 'paragrafo', 'inciso', etc.")
    texto_principal_alterada: str = Field(description="Texto da versão alterada. Manter <b> e <i>. Tache tudo em vermelho.")
    texto_principal_consolidada: str = Field(description="Texto limpo da versão consolidada. Manter <b> e <i>.")
    is_tabela: bool = Field(description="True se houver tabela associada.")
    tabela_alterada: Optional[List[List[str]]] = Field(default=None)
    tabela_consolidada: Optional[List[List[str]]] = Field(default=None)
    texto_pos_tabela_alterada: Optional[str] = Field(default=None)
    texto_pos_tabela_consolidada: Optional[str] = Field(default=None)
    nota_remissiva: Optional[str] = Field(default="", description="Ex: 'Alterado pelo art. X da Portaria Y'.")

class Consolidacao(BaseModel):
    arquivo_original_identificado: str
    arquivo_alterador_identificado: str
    nome_portaria_base: str
    ano_portaria_base: int
    ano_portaria_alteradora: int
    nome_portaria_alteradora: str
    cabecalho_complemento: str
    orgaos_emissores: str
    titulo_portaria: str
    ementa_preambulo: str
    assinatura_nome: str
    assinatura_cargo: str
    dispositivos: List[Dispositivo]

class ArquivoAvulso(BaseModel):
    nome_arquivo: str
    nome_portaria_identificada: str
    motivo: str

class AnaliseGlobal(BaseModel):
    consolidacoes_geradas: List[Consolidacao]
    arquivos_nao_alterados: List[ArquivoAvulso]

# Estrutura Pydantic para a Pré-Análise
class IdentificadorDeAlvos(BaseModel):
    normas_base_identificadas: List[str] = Field(description="Lista exata de nomes de normas que os arquivos estão tentando alterar e que existem no banco de dados fornecido.")

def analisar_lote_arquivos(arquivos, key):
    client = genai.Client(api_key=key)
    caminhos_temporarios = []
    gemini_files_objs = []
    
    try:
        # Upload inicial para o Gemini
        for arq in arquivos:
            ext = f".{arq.name.split('.')[-1]}"
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(arq.getvalue())
                caminhos_temporarios.append((tmp.name, arq.name))
                
        conteudos_iniciais = []
        for caminho_tmp, nome_original in caminhos_temporarios:
            g_file = client.files.upload(file=caminho_tmp)
            gemini_files_objs.append(g_file)
            conteudos_iniciais.append(f"ARQUIVO: {nome_original}")
            conteudos_iniciais.append(g_file)

        # -------------------------------------------------------------------
        # ETAPA 1: Pré-Análise (O "Cérebro" procurando no Banco)
        # -------------------------------------------------------------------
        nomes_bd = []
        if supabase:
            try:
                res_bd = supabase.table("portarias_base").select("nome_portaria").execute()
                nomes_bd = [r["nome_portaria"] for r in res_bd.data]
            except: pass

        prompt_pre_analise = f"""
        Abaixo temos os documentos fornecidos pelo usuário. 
        Nós temos as seguintes normas salvas no nosso Banco de Dados de Histórico: {nomes_bd}
        
        Analise o texto dos arquivos PDF fornecidos e responda: Algum desses arquivos está fazendo uma alteração/revogação em alguma destas normas específicas do Banco de Dados?
        Se sim, liste os nomes exatos das normas base (iguais à lista) que estão sendo alvo de alteração.
        """
        
        st.toast("🔍 Cruzando dados com o Histórico do Supabase...", icon="⏳")
        
        resp_pre = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=conteudos_iniciais + [prompt_pre_analise],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=IdentificadorDeAlvos,
                temperature=0.0 
            )
        )
        
        alvos = json.loads(resp_pre.text).get("normas_base_identificadas", [])
        textos_historico = []
        
        # Fazendo Download do JSON Histórico do Supabase se encontrou vínculo
        if supabase and alvos:
            for alvo_nome in alvos:
                try:
                    res_json = supabase.table("portarias_base").select("nome_portaria, documento_consolidado_json").eq("nome_portaria", alvo_nome).execute()
                    if res_json.data and res_json.data[0].get("documento_consolidado_json"):
                        json_str = json.dumps(res_json.data[0]['documento_consolidado_json'])
                        textos_historico.append(f"JSON DA NORMA BASE '{alvo_nome}' (Memória Cumulativa):\n{json_str}")
                        st.toast(f"✅ Histórico carregado do banco para a norma: {alvo_nome}!", icon="🧠")
                except: pass

        # -------------------------------------------------------------------
        # ETAPA 2: Consolidação Final (Aplicando as mudanças no JSON ou criando do zero)
        # -------------------------------------------------------------------
        conteudos_prompt = ["Analise as relações normativas e gere a consolidação final:"]
        conteudos_prompt.extend(conteudos_iniciais)
        
        if textos_historico:
            conteudos_prompt.append("\n\nATENÇÃO MÁXIMA - HISTÓRICO ENCONTRADO NO BANCO DE DADOS:")
            conteudos_prompt.extend(textos_historico)

        prompt_comandos = """
        Atue como um Especialista Sênior em Técnica Legislativa.
        
        TAREFA PRINCIPAL:
        1. Identifique pares e gere 'Consolidacao'.
        2. Extraia o ano exato de criação da portaria base e da alteradora.
        3. Isole arquivos sem vínculo em 'arquivos_nao_alterados'.
        
        REGRAS DA MEMÓRIA CUMULATIVA (CASCATA DE ALTERAÇÕES):
        Se eu forneci o "JSON DA NORMA BASE (Memória Cumulativa)" nos dados acima, ISSO SIGNIFICA QUE A NORMA BASE JÁ FOI CONSOLIDADA ANTERIORMENTE. 
        Você NÃO deve extrair o texto original do PDF antigo se o JSON estiver disponível. 
        Você DEVE usar o conteúdo daquele JSON histórico como a "versão em vigor", ler o novo arquivo alterador, e aplicar as novas revogações e alterações EM CIMA daquele JSON. 
        O novo arquivo JSON gerado por você deve acumular todas as notas remissivas antigas + as novas notas remissivas do documento de hoje.
        
        REGRAS DE FORMATAÇÃO: Preserve <b> e <i>, quebras com <br/>, tachado completo em vermelho e notas remissivas exclusivamente no campo correspondente.
        """
        conteudos_prompt.append(prompt_comandos)

        st.toast("⚙️ Gerando Textos Consolidados Finais...", icon="⏳")

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=conteudos_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AnaliseGlobal,
                temperature=0.0 
            ),
        )
        return json.loads(response.text)
    finally:
        for g_file in gemini_files_objs:
            try: client.files.delete(name=g_file.name)
            except: pass
        for caminho_tmp, _ in caminhos_temporarios:
            if os.path.exists(caminho_tmp): os.remove(caminho_tmp)

# ... [As funções auxiliares de PDF, DOCX e Texto continuam idênticas] ...
def extrair_paragrafos_seguros(texto_html):
    texto_html = (texto_html or "").replace("</font></strike>", "</strike></font>")
    texto_html = texto_html.replace("</b></i>", "</i></b>")
    texto_html = texto_html.replace('<em>', '<i>').replace('</em>', '</i>')
    texto_html = texto_html.replace('<strong>', '<b>').replace('</strong>', '</b>')
    texto_html = texto_html.replace('<s>', '<strike>').replace('</s>', '</strike>')
    tokens = re.split(r'(<[^>]+>)', texto_html)
    paragrafos, pilha = [], []
    texto_atual = ""
    def fechar_todas(pilha_tags):
        res = ""
        for tag in reversed(pilha_tags):
            tag_lower = tag.lower()
            if tag_lower.startswith("<font"): res += "</font>"
            elif tag_lower.startswith("<strike"): res += "</strike>"
            elif tag_lower == "<b>": res += "</b>"
            elif tag_lower == "<i>": res += "</i>"
        return res
    def abrir_todas(pilha_tags): return "".join(pilha_tags)
    for token in tokens:
        if not token: continue
        t_lower = token.lower()
        if t_lower in ["<br>", "<br/>", "<br />"]:
            texto_atual += fechar_todas(pilha)
            if re.sub(r'<[^>]+>', '', texto_atual).strip(): paragrafos.append(texto_atual.strip())
            texto_atual = abrir_todas(pilha)
        elif t_lower.startswith("</"):
            removido = False
            for i in range(len(pilha)-1, -1, -1):
                p_lower = pilha[i].lower()
                if (t_lower == "</font>" and p_lower.startswith("<font")) or \
                   (t_lower == "</strike>" and p_lower.startswith("<strike")) or \
                   (t_lower == "</b>" and p_lower == "<b>") or \
                   (t_lower == "</i>" and p_lower == "<i>"):
                    pilha.pop(i)
                    removido = True
                    break
            if removido: texto_atual += token
        elif t_lower.startswith("<font") or t_lower.startswith("<strike") or t_lower in ["<b>", "<i>"]:
            pilha.append(token)
            texto_atual += token
        else:
            texto_atual += token
    texto_atual += fechar_todas(pilha)
    if re.sub(r'<[^>]+>', '', texto_atual).strip(): paragrafos.append(texto_atual.strip())
    return paragrafos

def injetar_nota_remissiva(texto, nota):
    if nota and nota.strip():
        n = nota.strip()
        if not n.startswith("("): n = f"({n}"
        if not n.endswith(")"): n = f"{n})"
        if texto:
            texto_limpo = texto.rstrip('<br/>').rstrip('<br>').rstrip()
            return f"{texto_limpo} &nbsp;<font color='red'>{n}</font>"
        else:
            return f"<font color='red'>{n}</font>"
    return texto

def renderizar_paragrafos_pdf(story, texto_html, estilo):
    for p in extrair_paragrafos_seguros(texto_html):
        story.append(Paragraph(p, estilo))

def aplicar_html_no_docx(p, texto_html):
    texto_html = (texto_html or "").replace("&nbsp;", "\xa0")
    tokens = re.split(r'(<[^>]+>)', texto_html)
    is_bold, is_strike, is_red, is_italic = False, False, False, False
    for token in tokens:
        if not token: continue
        t_lower = token.lower()
        if t_lower == '<b>': is_bold = True
        elif t_lower == '</b>': is_bold = False
        elif t_lower == '<i>': is_italic = True
        elif t_lower == '</i>': is_italic = False
        elif t_lower == '<strike>': is_strike = True
        elif t_lower == '</strike>': is_strike = False
        elif "font color" in t_lower and ("red" in t_lower or "'red'" in t_lower or '"red"' in t_lower): is_red = True
        elif t_lower == '</font>': is_red = False
        elif token.startswith('<'): pass
        else:
            run = p.add_run(token)
            run.font.name = 'Times New Roman'
            run.font.size = Pt(11)
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
            run.font.name = 'Times New Roman'
            run.font.size = Pt(10)
            run.bold = True
        else:
            aplicar_html_no_docx(p, p_html)

def gerar_pdf_dinamico(consolidacao_dict, tipo_versao):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    story, styles = [], getSampleStyleSheet()
    estilo_cabecalho_topo = ParagraphStyle('CabecalhoTopo', parent=styles['Normal'], fontName='Times-Bold', fontSize=10, leading=12, alignment=1, textColor=colors.HexColor('#444444'), spaceAfter=20)
    estilo_orgaos = ParagraphStyle('Orgaos', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=25)
    estilo_titulo = ParagraphStyle('TituloPortaria', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=20)
    estilo_dispositivo = ParagraphStyle('Dispositivo', parent=styles['Normal'], fontName='Times-Roman', fontSize=11, leading=15, alignment=4, firstLineIndent=30, spaceAfter=12)
    estilo_celula = ParagraphStyle('Celula', parent=styles['Normal'], fontName='Times-Roman', fontSize=10, leading=12, alignment=0)
    estilo_capitulo = ParagraphStyle('Capitulo', parent=styles['Normal'], fontName='Times-Bold', fontSize=10, leading=14, alignment=1, spaceBefore=20, spaceAfter=12, textTransform='uppercase')
    estilo_assinatura = ParagraphStyle('Assinatura', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, leading=15, alignment=1, spaceBefore=50, spaceAfter=20)
    estilo_rodape = ParagraphStyle('Rodape', parent=styles['Normal'], fontName='Times-Italic', fontSize=9, leading=12, alignment=0)

    comp = (consolidacao_dict.get("cabecalho_complemento") or "")
    topo_texto = f"VERSÃO ALTERADA - {comp}" if tipo_versao == "alterada" else f"VERSÃO CONSOLIDADA - {comp}"
    story.append(Paragraph(topo_texto, estilo_cabecalho_topo))

    orgs = (consolidacao_dict.get("orgaos_emissores") or "").replace('\n', '<br/>')
    tit = (consolidacao_dict.get("titulo_portaria") or "").replace('\n', '<br/>')
    preamb = (consolidacao_dict.get("ementa_preambulo") or "").replace('\n', '<br/>')
    
    story.append(Paragraph(orgs, estilo_orgaos))
    story.append(Paragraph(tit, estilo_titulo))
    renderizar_paragrafos_pdf(story, preamb, estilo_dispositivo)

    for item in consolidacao_dict.get("dispositivos", []):
        tipo = (item.get("tipo") or "").lower()
        is_tabela = item.get("is_tabela", False)
        nota = item.get("nota_remissiva") or ""
        
        texto_principal = (item.get(f"texto_principal_{tipo_versao}") or "").replace('\n', '<br/>')
        texto_pos = (item.get(f"texto_pos_tabela_{tipo_versao}") or "").replace('\n', '<br/>')
        
        if is_tabela:
            if not texto_pos and nota: texto_pos = injetar_nota_remissiva("", nota)
            else: texto_pos = injetar_nota_remissiva(texto_pos, nota)
        else:
            texto_principal = injetar_nota_remissiva(texto_principal, nota)
            
        if "capitulo" in tipo:
            story.append(Paragraph(texto_principal, estilo_capitulo))
            continue

        if texto_principal:
            renderizar_paragrafos_pdf(story, texto_principal, estilo_dispositivo)
            
        if is_tabela:
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas and len(linhas) > 0:
                tabela_processada = []
                for linha in linhas:
                    linha_processada = [Paragraph(celula.replace('\n', '<br/>'), estilo_celula) for celula in linha]
                    tabela_processada.append(linha_processada)
                t = Table(tabela_processada, colWidths='*')
                t.setStyle(TableStyle([
                    ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6), ('TOPPADDING', (0,0), (-1,-1), 6),
                ]))
                story.append(t)
                story.append(Spacer(1, 15))
                
        if texto_pos:
            renderizar_paragrafos_pdf(story, texto_pos, estilo_dispositivo)

    bloco_assinatura = f"{(consolidacao_dict.get('assinatura_nome') or '')}<br/>{(consolidacao_dict.get('assinatura_cargo') or '')}"
    story.append(Paragraph(bloco_assinatura, estilo_assinatura))

    story.append(Spacer(1, 40))
    d = Drawing(A4[0] - 144, 10)
    d.add(Line(0, 5, A4[0] - 144, 5, strokeColor=colors.black, strokeWidth=0.5))
    story.append(d)
    story.append(Spacer(1, 5))
    story.append(Paragraph("<b>Nota:</b> Este documento possui caráter estritamente consultivo e informativo.", estilo_rodape))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
    doc = docx.Document()
    for section in doc.sections:
        section.top_margin, section.bottom_margin = Inches(1), Inches(1)
        section.left_margin, section.right_margin = Inches(1), Inches(1)

    p_head = doc.add_paragraph()
    p_head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    comp = consolidacao_dict.get("cabecalho_complemento") or ""
    texto_head = f"VERSÃO ALTERADA - {comp}" if tipo_versao == "alterada" else f"VERSÃO CONSOLIDADA - {comp}"
    r_head = p_head.add_run(texto_head)
    r_head.font.name, r_head.font.size, r_head.bold = 'Times New Roman', Pt(10), True
    r_head.font.color.rgb = RGBColor(68, 68, 68)
    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    p_org = doc.add_paragraph()
    p_org.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_org.paragraph_format.space_after = Pt(18)
    r_org = p_org.add_run((consolidacao_dict.get("orgaos_emissores") or "").replace("<br/>", "\n").replace("<br>", "\n"))
    r_org.font.name, r_org.font.size, r_org.bold = 'Times New Roman', Pt(11), True

    p_tit = doc.add_paragraph()
    p_tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_tit.paragraph_format.space_after = Pt(14)
    r_tit = p_tit.add_run(consolidacao_dict.get("titulo_portaria") or "")
    r_tit.font.name, r_tit.font.size, r_tit.bold = 'Times New Roman', Pt(11), True

    preamb = (consolidacao_dict.get("ementa_preambulo") or "").replace('\n', '<br/>')
    renderizar_paragrafos_docx(doc, preamb, WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))

    for item in consolidacao_dict.get("dispositivos", []):
        tipo = (item.get("tipo") or "").lower()
        is_tabela = item.get("is_tabela", False)
        nota = item.get("nota_remissiva") or ""
        texto_principal = (item.get(f"texto_principal_{tipo_versao}") or "").replace('\n', '<br/>')
        texto_pos = (item.get(f"texto_pos_tabela_{tipo_versao}") or "").replace('\n', '<br/>')
        
        if is_tabela:
            if not texto_pos and nota: texto_pos = injetar_nota_remissiva("", nota)
            else: texto_pos = injetar_nota_remissiva(texto_pos, nota)
        else:
            texto_principal = injetar_nota_remissiva(texto_principal, nota)

        if "capitulo" in tipo:
            renderizar_paragrafos_docx(doc, texto_principal, WD_ALIGN_PARAGRAPH.CENTER, Inches(0), Pt(10), bold_all=True)
            continue

        if texto_principal:
            renderizar_paragrafos_docx(doc, texto_principal, WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))
            
        if is_tabela:
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas and len(linhas) > 0:
                table = doc.add_table(rows=len(linhas), cols=len(linhas[0]))
                table.style = 'Table Grid'
                for r_idx, linha in enumerate(linhas):
                    for c_idx, celula in enumerate(linha):
                        cell = table.cell(r_idx, c_idx)
                        cell.text = "" 
                        p = cell.paragraphs[0]
                        p.paragraph_format.space_after = Pt(2)
                        aplicar_html_no_docx(p, celula.replace('\n', '<br/>'))
                doc.add_paragraph().paragraph_format.space_after = Pt(12)
                
        if texto_pos:
            renderizar_paragrafos_docx(doc, texto_pos, WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))

    p_assinatura = doc.add_paragraph()
    p_assinatura.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_assinatura.paragraph_format.space_before, p_assinatura.paragraph_format.space_after = Pt(36), Pt(24)
    r_ass = p_assinatura.add_run(f"{(consolidacao_dict.get('assinatura_nome') or '')}\n{(consolidacao_dict.get('assinatura_cargo') or '')}")
    r_ass.font.name, r_ass.font.size, r_ass.bold = 'Times New Roman', Pt(11), True

    p_rod = doc.add_paragraph()
    p_rod.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_rod.paragraph_format.space_before = Pt(24)
    r_nota_label = p_rod.add_run("Nota: ")
    r_nota_label.font.name, r_nota_label.font.size, r_nota_label.bold, r_nota_label.italic = 'Times New Roman', Pt(9), True, True
    r_nota_text = p_rod.add_run("Este documento possui caráter estritamente consultivo e informativo.")
    r_nota_text.font.name, r_nota_text.font.size, r_nota_text.italic = 'Times New Roman', Pt(9), True

    buffer_docx = io.BytesIO()
    doc.save(buffer_docx)
    buffer_docx.seek(0)
    return buffer_docx.getvalue()

# ----------------- FUNÇÃO DE SALVAMENTO ATUALIZADA (COM JSON) -----------------
def salvar_no_supabase(cons):
    if not supabase:
        st.error("⚠️ Supabase não configurado corretamente nos segredos.")
        return False
    try:
        nome_base = cons['nome_portaria_base']
        ano_base = cons['ano_portaria_base']
        
        res_busca = supabase.table("portarias_base").select("id").eq("nome_portaria", nome_base).eq("ano_criacao", ano_base).execute()
        
        if res_busca.data and len(res_busca.data) > 0:
            base_id = res_busca.data[0]['id']
            # ATUALIZAÇÃO DA MEMÓRIA CUMULATIVA: Salva o novo JSON por cima do antigo!
            supabase.table("portarias_base").update({
                "documento_consolidado_json": cons,
                "titulo_original": cons.get("titulo_portaria"),
                "orgaos_emissores": cons.get("orgaos_emissores")
            }).eq("id", base_id).execute()
        else:
            # INSERÇÃO INICIAL COM A MEMÓRIA CUMULATIVA
            res_ins = supabase.table("portarias_base").insert({
                "nome_portaria": nome_base,
                "ano_criacao": ano_base,
                "titulo_original": cons.get("titulo_portaria"),
                "orgaos_emissores": cons.get("orgaos_emissores"),
                "assinatura_nome": cons.get("assinatura_nome"),
                "assinatura_cargo": cons.get("assinatura_cargo"),
                "documento_consolidado_json": cons  # <--- Aqui está a mágica da Memória
            }).execute()
            base_id = res_ins.data[0]['id']
            
        nome_alt = cons['nome_portaria_alteradora']
        ano_alt = cons['ano_portaria_alteradora']
        
        res_alt_check = supabase.table("portarias_alteradoras").select("id").eq("portaria_base_id", base_id).eq("nome_portaria_alteradora", nome_alt).execute()
        
        if not res_alt_check.data or len(res_alt_check.data) == 0:
            supabase.table("portarias_alteradoras").insert({
                "portaria_base_id": base_id,
                "nome_portaria_alteradora": nome_alt,
                "ano_alteracao": ano_alt,
                "arquivo_nome_original": cons.get("arquivo_alterador_identificado")
            }).execute()
            
        return True
    except Exception as e:
        st.error(f"Erro ao salvar no banco: {e}")
        return False

# ----------------- FRONT-END -----------------
if "dados_processados" not in st.session_state:
    st.session_state.dados_processados = None

st.markdown("<br>", unsafe_allow_html=True)

if st.button("🚀 Iniciar Análise Autopilot", type="primary", use_container_width=True):
    if not api_key:
        st.error("⚠️ Insira sua chave da API do Google GenAI em 'Configurações do Sistema'.")
    elif not arquivos_enviados or len(arquivos_enviados) < 1:
        st.warning("⚠️ Envie pelo menos um arquivo normativo.")
    else:
        with st.spinner("🧠 Ativando Autopilot e buscando conexões no Supabase..."):
            try:
                chave_limpa = api_key.strip()
                resultados = analisar_lote_arquivos(arquivos_enviados, chave_limpa)
                st.session_state.dados_processados = resultados
                st.success("✨ Processamento em Lote Concluído!")
            except Exception as e:
                st.error(f"❌ Ocorreu um erro na API da Inteligência Artificial: {e}")

if st.session_state.dados_processados is not None:
    st.markdown("---")
    dados = st.session_state.dados_processados
    consolidacoes = dados.get("consolidacoes_geradas", [])
    avulsos = dados.get("arquivos_nao_alterados", [])
    
    if len(consolidacoes) > 0:
        st.header("📑 Documentos Consolidados Prontos")
        for i, cons in enumerate(consolidacoes):
            with st.expander(f"📁 **{cons['nome_portaria_base']}** ({cons['ano_portaria_base']}) atualizada pela **{cons['nome_portaria_alteradora']}** ({cons['ano_portaria_alteradora']})", expanded=True):
                st.info(f"**Original / Base no Banco:** `{cons['arquivo_original_identificado']}`\n\n**Novo Documento Alterador:** `{cons['arquivo_alterador_identificado']}`")
                
                if st.button(f"💾 Salvar Consolidação Atualizada no Supabase", key=f"btn_sup_{i}"):
                    sucesso = salvar_no_supabase(cons)
                    if sucesso:
                        st.success(f"Histórico da {cons['nome_portaria_base']} atualizado! O texto no banco agora contempla a {cons['nome_portaria_alteradora']}.")
                
                pdf_alt_bytes = gerar_pdf_dinamico(cons, "alterada")
                pdf_cons_bytes = gerar_pdf_dinamico(cons, "consolidada")
                docx_alt_bytes = gerar_docx_dinamico(cons, "alterada")
                docx_cons_bytes = gerar_docx_dinamico(cons, "consolidada")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"#### Versão Alterada")
                    st.download_button("Baixar PDF", data=pdf_alt_bytes, file_name=f"{cons['nome_portaria_base'].replace(' ', '_').replace('/', '-')}_Alterada.pdf", mime="application/pdf", key=f"dl_pdf_alt_{i}")
                    st.download_button("Baixar DOCX", data=docx_alt_bytes, file_name=f"{cons['nome_portaria_base'].replace(' ', '_').replace('/', '-')}_Alterada.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"dl_docx_alt_{i}")
                with c2:
                    st.markdown(f"#### Versão Consolidada")
                    st.download_button("Baixar PDF", data=pdf_cons_bytes, file_name=f"{cons['nome_portaria_base'].replace(' ', '_').replace('/', '-')}_Consolidada.pdf", mime="application/pdf", key=f"dl_pdf_cons_{i}")
                    st.download_button("Baixar DOCX", data=docx_cons_bytes, file_name=f"{cons['nome_portaria_base'].replace(' ', '_').replace('/', '-')}_Consolidada.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"dl_docx_cons_{i}")

    if len(avulsos) > 0:
        st.header("🗂️ Arquivos Sem Alteração Detectada")
        for avulso in avulsos:
            st.warning(f"**Arquivo:** `{avulso.get('nome_arquivo', 'Desconhecido')}`\n\n**Portaria/Norma:** {avulso.get('nome_portaria_identificada', 'Não identificada')}\n\n**Motivo:** {avulso.get('motivo', '')}")

    st.markdown("---")
    if st.button("🔄 Realizar Nova Análise", type="secondary"):
        st.session_state.dados_processados = None
        st.rerun()
