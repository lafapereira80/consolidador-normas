import streamlit as st
import fitz  # PyMuPDF para ler os PDFs
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

# Importação para geração de arquivos Word (.docx)
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# Configuração da página web
st.set_page_config(page_title="Consolidador Dinâmico de Normas", layout="centered")

st.title("⚖️ Sistema Web Dinâmico de Consolidação Normativa")
st.write("Faça o upload da **Norma Original** e da **Norma Alteradora**. A IA fará a leitura, o cruzamento normativo e gerará os arquivos em PDF e Word (.docx) dinamicamente.")

# Configuração da API Key
api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    with st.sidebar:
        st.header("Configuração de IA")
        api_key = st.text_input("Chave da API do Google GenAI", type="password")
        st.markdown("[Obtenha sua chave gratuita no Google AI Studio](https://aistudio.google.com/)")

col1, col2 = st.columns(2)
with col1:
    pdf_original = st.file_uploader("1. Documento Original (PDF)", type=["pdf"], key="file_orig")
with col2:
    pdf_alteradora = st.file_uploader("2. Documento Alterador/Revogador (PDF)", type=["pdf"], key="file_alt")

def extrair_texto_de_upload(arquivo_uploaded):
    """Extrai o texto bruto do PDF enviado via web."""
    with fitz.open(stream=arquivo_uploaded.read(), filetype="pdf") as doc:
        texto = ""
        for pagina in doc:
            texto += pagina.get_text()
    return texto

# Estrutura Avançada Pydantic
class Dispositivo(BaseModel):
    tipo: str = Field(description="Ex: 'capitulo', 'artigo', 'paragrafo', ou 'tabela'")
    texto_alterada: str = Field(description="Texto antigo tachado em vermelho. Se não for tabela e tiver alteração, insira <br/><br/> e o texto novo logo após.")
    texto_novo_pos_tabela: Optional[str] = Field(default=None, description="APENAS se a tabela foi apagada/substituída: Coloque aqui o novo texto que deve vir após a matriz da tabela antiga.")
    texto_consolidado: str = Field(description="Texto limpo e atualizado para a versão consolidada. SE REVOGADO, coloque APENAS o identificador e a nota (ex: <b>Art. 9º</b> <font color='red'>(Revogado pelo art...)</font>).")
    is_tabela: bool = Field(description="Verdadeiro (true) SE o conteúdo for um quadro ou tabela.")
    tabela_linhas_alterada: Optional[List[List[str]]] = Field(default=None, description="Matriz da tabela da versão alterada. Se foi alterada/revogada, envolver células com <font color='red'><strike>...</strike></font>.")
    tabela_linhas_consolidada: Optional[List[List[str]]] = Field(default=None, description="Matriz limpa da tabela consolidada. Deixe null se a tabela foi revogada/apagada.")

class ResultadoConsolidacao(BaseModel):
    cabecalho_complemento: str = Field(description="Gere apenas o texto complemento do topo. Ex: 'Atualizada pela Portaria nº 103/PGJM, de 21/05/2026 (vigência: 21/05/2026)'.")
    orgaos_emissores: str = Field(description="Extraia o cabeçalho com os órgãos emissores da norma original.")
    titulo_portaria: str = Field(description="Apenas o nome e data da Norma Original.")
    ementa_preambulo: str = Field(description="O preâmbulo original.")
    assinatura_nome: str = Field(description="Nome da pessoa que assina o documento original.")
    assinatura_cargo: str = Field(description="Cargo da pessoa que assina o documento original.")
    dispositivos: List[Dispositivo] = Field(description="Lista sequencial estruturada de toda a norma.")

def analisar_normas_com_gemini_dinamico(texto_original, texto_alterador, key):
    """Solicita ao Gemini a extração rigorosa com comandos visuais."""
    client = genai.Client(api_key=key)
    prompt = f"""
    Atue como um especialista em técnica legislativa.
    Analise a Norma Original e a Norma Alteradora abaixo e gere o JSON.
    
    REGRAS RÍGIDAS DE FORMATAÇÃO E ESTRUTURAÇÃO:
    1. PROIBIDO LaTeX: NUNCA use LaTeX. Use textualmente "1º", "2º", "5º", "§", etc.
    2. TABELAS:
       - Reconstrua a matriz de dados da tabela original com perfeição.
       - Se a tabela inteira foi REVOGADA ou SUBSTITUÍDA por texto:
         * Em `tabela_linhas_alterada`: Extraia a matriz antiga completa e envolva o texto de TODAS as células com <font color='red'><strike>...</strike></font>.
         * Em `texto_novo_pos_tabela`: Coloque a nova redação + nota remissiva.
         * Em `tabela_linhas_consolidada`: Null/Vazio.
    3. VERSÃO CONSOLIDADA (`texto_consolidado`):
       - Se o dispositivo foi ALTERADO, mostre apenas o NOVO texto limpo + nota remissiva em vermelho no final.
       - Se o dispositivo foi REVOGADO, mostre APENAS o identificador original + nota remissiva em vermelho. Exemplo: <b>Art. 9º</b> <font color='red'>(Revogado pelo art. 2º da Portaria...)</font>. Não inclua o texto antigo.
    4. VERSÃO ALTERADA (`texto_alterada`):
       - Texto antigo DEVE estar tachado em vermelho <font color='red'><strike>...</strike></font>.
       - Se houve substituição por texto, coloque o texto tachado, seguido de <br/><br/> e a nova redação.
    5. NOTAS REMISSIVAS (OBRIGATÓRIO EM TODAS AS VERSÕES):
       - TODAS as notas remissivas DEVEM estar inteiramente na cor vermelha: <font color='red'>(Alterado pelo art...)</font> ou <font color='red'>(Revogado pelo art...)</font>.
    6. NEGRITOS E LIMPEZA: Mantenha as palavras em negrito originais (ex: <b>Art. 1º</b>). Remova quebras de linha (Enters) do meio de frases.
    
    NORMA ORIGINAL:
    {texto_original}
    
    NORMA ALTERADORA:
    {texto_alterador}
    """
    
    response = client.models.generate_content(
        model='gemini-3.5-pro',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ResultadoConsolidacao,
            temperature=0.0 
        ),
    )
    return json.loads(response.text)

def renderizar_paragrafos_pdf(story, texto_html, estilo):
    partes = re.split(r'(?:<br\s*/?>\s*)+', texto_html)
    for parte in partes:
        texto_limpo = parte.strip()
        if texto_limpo:
            story.append(Paragraph(texto_limpo, estilo))

def aplicar_html_no_docx(p, texto_html):
    tokens = re.split(r'(<[^>]+>)', texto_html)
    is_bold = False
    is_strike = False
    is_red = False
    
    for token in tokens:
        if not token:
            continue
        t_lower = token.lower()
        if t_lower == '<b>': is_bold = True
        elif t_lower == '</b>': is_bold = False
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
            if is_strike: run.font.strike = True
            if is_red: run.font.color.rgb = RGBColor(255, 0, 0)

def renderizar_paragrafos_docx(doc, texto_html, alignment, first_line_indent, space_after=Pt(6), bold_all=False):
    partes = re.split(r'(?:<br\s*/?>\s*)+', texto_html)
    for parte in partes:
        texto_limpo = parte.strip()
        if texto_limpo:
            p = doc.add_paragraph()
            p.alignment = alignment
            p.paragraph_format.first_line_indent = first_line_indent
            p.paragraph_format.space_after = space_after
            p.paragraph_format.line_spacing = 1.15
            if bold_all:
                run = p.add_run(texto_limpo)
                run.font.name = 'Times New Roman'
                run.font.size = Pt(10)
                run.bold = True
            else:
                aplicar_html_no_docx(p, texto_limpo)

def gerar_pdf_dinamico(dados_json, tipo_versao):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    story = []
    styles = getSampleStyleSheet()

    estilo_cabecalho_topo = ParagraphStyle('CabecalhoTopo', parent=styles['Normal'], fontName='Times-Bold', fontSize=10, leading=12, alignment=1, textColor=colors.HexColor('#444444'), spaceAfter=20)
    estilo_orgaos = ParagraphStyle('Orgaos', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=25)
    estilo_titulo = ParagraphStyle('TituloPortaria', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=20)
    estilo_dispositivo = ParagraphStyle('Dispositivo', parent=styles['Normal'], fontName='Times-Roman', fontSize=11, leading=15, alignment=4, firstLineIndent=30, spaceAfter=12)
    estilo_celula = ParagraphStyle('Celula', parent=styles['Normal'], fontName='Times-Roman', fontSize=10, leading=12, alignment=0)
    estilo_capitulo = ParagraphStyle('Capitulo', parent=styles['Normal'], fontName='Times-Bold', fontSize=10, leading=14, alignment=1, spaceBefore=20, spaceAfter=12, textTransform='uppercase')
    estilo_assinatura = ParagraphStyle('Assinatura', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, leading=15, alignment=1, spaceBefore=50, spaceAfter=20)
    estilo_rodape = ParagraphStyle('Rodape', parent=styles['Normal'], fontName='Times-Italic', fontSize=9, leading=12, alignment=0)

    # 1. Cabeçalho
    comp = dados_json.get("cabecalho_complemento", "")
    topo_texto = f"VERSÃO ALTERADA - {comp}" if tipo_versao == "alterada" else f"VERSÃO CONSOLIDADA - {comp}"
    story.append(Paragraph(topo_texto, estilo_cabecalho_topo))

    # 2. Brasão
    caminho_imagem = "brasao.png"
    if os.path.exists(caminho_imagem):
        try:
            img_brasao = Image(caminho_imagem, width=60, height=60)
            img_brasao.hAlign = 'CENTER'
            story.append(img_brasao)
            story.append(Spacer(1, 10))
        except: pass

    # 3. Topo e Preâmbulo
    story.append(Paragraph(dados_json.get("orgaos_emissores", "").replace("\n", "").replace("<br>", "<br/>"), estilo_orgaos))
    story.append(Paragraph(dados_json.get("titulo_portaria", "").replace("<br>", "<br/>").replace("\n", "<br/>"), estilo_titulo))
    renderizar_paragrafos_pdf(story, dados_json.get("ementa_preambulo", "").replace("\n", ""), estilo_dispositivo)

    # 4. Dispositivos e Tabelas
    for item in dados_json.get("dispositivos", []):
        is_tabela = item.get("is_tabela", False)
        tipo = item.get("tipo", "").lower()
        
        if is_tabela:
            if tipo_versao == "alterada":
                intro = item.get("texto_alterada", "")
                if intro: renderizar_paragrafos_pdf(story, intro.replace("\n", " "), estilo_dispositivo)
            else:
                intro = item.get("texto_consolidado", "")
                if intro: renderizar_paragrafos_pdf(story, intro.replace("\n", " "), estilo_dispositivo)
            
            chave_tabela = f"tabela_linhas_{tipo_versao}"
            linhas = item.get(chave_tabela, [])
            
            if linhas and len(linhas) > 0:
                tabela_processada = []
                for linha in linhas:
                    linha_processada = []
                    for celula in linha:
                        linha_processada.append(Paragraph(celula.replace('\n', ' '), estilo_celula))
                    tabela_processada.append(linha_processada)
                
                t = Table(tabela_processada, colWidths='*')
                # CORREÇÃO: Aplicação da borda total com 'GRID'
                t.setStyle(TableStyle([
                    ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                ]))
                story.append(t)
                story.append(Spacer(1, 15))
            
            if tipo_versao == "alterada":
                novo_pos = item.get("texto_novo_pos_tabela", "")
                if novo_pos: renderizar_paragrafos_pdf(story, novo_pos.replace('\n', ' '), estilo_dispositivo)
        else:
            texto_final = item.get(f"texto_{tipo_versao}", "").replace("\n", " ")
            if "capitulo" in tipo:
                story.append(Paragraph(texto_final, estilo_capitulo))
            else:
                renderizar_paragrafos_pdf(story, texto_final, estilo_dispositivo)

    # 5. Assinatura e Rodapé
    bloco_assinatura = f"{dados_json.get('assinatura_nome', '')}<br/>{dados_json.get('assinatura_cargo', '')}"
    story.append(Paragraph(bloco_assinatura, estilo_assinatura))

    story.append(Spacer(1, 40))
    d = Drawing(A4[0] - 144, 10)
    d.add(Line(0, 5, A4[0] - 144, 5, strokeColor=colors.black, strokeWidth=0.5))
    story.append(d)
    story.append(Spacer(1, 5))
    story.append(Paragraph("<b>Nota:</b> Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial.", estilo_rodape))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_docx_dinamico(dados_json, tipo_versao):
    doc = docx.Document()
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # 1. Cabeçalho de Versão
    p_head = doc.add_paragraph()
    p_head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    comp = dados_json.get("cabecalho_complemento", "")
    texto_head = f"VERSÃO ALTERADA - {comp}" if tipo_versao == "alterada" else f"VERSÃO CONSOLIDADA - {comp}"
    r_head = p_head.add_run(texto_head)
    r_head.font.name = 'Times New Roman'
    r_head.font.size = Pt(10)
    r_head.bold = True
    r_head.font.color.rgb = RGBColor(68, 68, 68)
    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # 2. Órgãos Emissores
    p_org = doc.add_paragraph()
    p_org.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_org.paragraph_format.space_after = Pt(18)
    r_org = p_org.add_run(dados_json.get("orgaos_emissores", "").replace("<br/>", "\n").replace("<br>", "\n"))
    r_org.font.name = 'Times New Roman'
    r_org.font.size = Pt(11)
    r_org.bold = True

    # 3. Título da Portaria
    p_tit = doc.add_paragraph()
    p_tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_tit.paragraph_format.space_after = Pt(14)
    r_tit = p_tit.add_run(dados_json.get("titulo_portaria", ""))
    r_tit.font.name = 'Times New Roman'
    r_tit.font.size = Pt(11)
    r_tit.bold = True

    # 4. Preâmbulo
    renderizar_paragrafos_docx(doc, dados_json.get("ementa_preambulo", "").replace("\n", " "), alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_indent=Inches(0.4))

    # 5. Dispositivos e Tabelas
    for item in dados_json.get("dispositivos", []):
        is_tabela = item.get("is_tabela", False)
        tipo = item.get("tipo", "").lower()
        
        if is_tabela:
            if tipo_versao == "alterada":
                intro = item.get("texto_alterada", "")
                if intro: renderizar_paragrafos_docx(doc, intro.replace('\n', ' '), alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_indent=Inches(0.4))
            else:
                intro = item.get("texto_consolidado", "")
                if intro: renderizar_paragrafos_docx(doc, intro.replace('\n', ' '), alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_indent=Inches(0.4))
            
            chave_tabela = f"tabela_linhas_{tipo_versao}"
            linhas = item.get(chave_tabela, [])
            if linhas and len(linhas) > 0:
                table = doc.add_table(rows=len(linhas), cols=len(linhas[0]))
                table.style = 'Table Grid'
                for r_idx, linha in enumerate(linhas):
                    for c_idx, celula in enumerate(linha):
                        cell = table.cell(r_idx, c_idx)
                        cell.text = "" 
                        p = cell.paragraphs[0]
                        p.paragraph_format.space_after = Pt(2)
                        aplicar_html_no_docx(p, celula.replace("\n", " "))
                doc.add_paragraph().paragraph_format.space_after = Pt(12)
            
            if tipo_versao == "alterada":
                novo_pos = item.get("texto_novo_pos_tabela", "")
                if novo_pos: renderizar_paragrafos_docx(doc, novo_pos.replace('\n', ' '), alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_indent=Inches(0.4))
        else:
            texto_final = item.get(f"texto_{tipo_versao}", "").replace("\n", " ")
            if "capitulo" in tipo:
                renderizar_paragrafos_docx(doc, texto_final, alignment=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=Inches(0), space_after=Pt(10), bold_all=True)
            else:
                renderizar_paragrafos_docx(doc, texto_final, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_indent=Inches(0.4))

    # 6. Assinatura e Rodapé
    p_assinatura = doc.add_paragraph()
    p_assinatura.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_assinatura.paragraph_format.space_before = Pt(36)
    p_assinatura.paragraph_format.space_after = Pt(24)
    r_ass = p_assinatura.add_run(f"{dados_json.get('assinatura_nome', '')}\n{dados_json.get('assinatura_cargo', '')}")
    r_ass.font.name = 'Times New Roman'
    r_ass.font.size = Pt(11)
    r_ass.bold = True

    p_rod = doc.add_paragraph()
    p_rod.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_rod.paragraph_format.space_before = Pt(24)
    r_nota_label = p_rod.add_run("Nota: ")
    r_nota_label.font.name = 'Times New Roman'
    r_nota_label.font.size = Pt(9)
    r_nota_label.bold = True
    r_nota_label.italic = True
    r_nota_text = p_rod.add_run("Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial.")
    r_nota_text.font.name = 'Times New Roman'
    r_nota_text.font.size = Pt(9)
    r_nota_text.italic = True

    buffer_docx = io.BytesIO()
    doc.save(buffer_docx)
    buffer_docx.seek(0)
    return buffer_docx.getvalue()

# Inicialização da Sessão
if "dados_processados" not in st.session_state:
    st.session_state.dados_processados = None

# Interface do Botão de Execução
if st.button("🚀 Processar Dinamicamente com IA e Gerar Documentos", type="primary"):
    if not api_key:
        st.error("⚠️ Insira sua chave da API do Google GenAI.")
    elif pdf_original and pdf_alteradora:
        with st.spinner("Analisando documentos e formatando versões consolidadas..."):
            try:
                texto_orig = extrair_texto_de_upload(pdf_original)
                texto_alt = extrair_texto_de_upload(pdf_alteradora)
                
                chave_limpa = api_key.strip()
                dados_estruturados = analisar_normas_com_gemini_dinamico(texto_orig, texto_alt, chave_limpa)
                
                st.session_state.dados_processados = dados_estruturados
                st.success("✨ Processamento dinâmico concluído com sucesso!")
            except Exception as e:
                st.error("❌ Ocorreu um erro.")
                st.code(str(e))
    else:
        st.warning("⚠️ Envie ambos os arquivos PDF.")

# Exibição dos botões de download
if st.session_state.dados_processados is not None:
    st.divider()
    st.subheader("📥 Baixe os Documentos Oficiais Prontos:")
    
    pdf_alt_bytes = gerar_pdf_dinamico(st.session_state.dados_processados, "alterada")
    pdf_cons_bytes = gerar_pdf_dinamico(st.session_state.dados_processados, "consolidada")
    docx_alt_bytes = gerar_docx_dinamico(st.session_state.dados_processados, "alterada")
    docx_cons_bytes = gerar_docx_dinamico(st.session_state.dados_processados, "consolidada")
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.markdown("### Versão Alterada")
        st.download_button(label="Baixar em PDF", data=pdf_alt_bytes, file_name="versao_alterada_dinamica.pdf", mime="application/pdf", key="dl_pdf_alt")
        st.download_button(label="Baixar em Word (.docx)", data=docx_alt_bytes, file_name="versao_alterada_dinamica.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="dl_docx_alt")
    with col_d2:
        st.markdown("### Versão Consolidada")
        st.download_button(label="Baixar em PDF", data=pdf_cons_bytes, file_name="versao_consolidada_dinamica.pdf", mime="application/pdf", key="dl_pdf_cons")
        st.download_button(label="Baixar em Word (.docx)", data=docx_cons_bytes, file_name="versao_consolidada_dinamica.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="dl_docx_cons")

    st.markdown("---")
    if st.button("🔄 Realizar Nova Análise", type="secondary"):
        st.session_state.dados_processados = None
        st.rerun()
