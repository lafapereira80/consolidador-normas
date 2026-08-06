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

# Importação para geração de arquivos Word (.docx)
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# Configuração da página web
st.set_page_config(page_title="Consolidador Dinâmico Autopilot", layout="wide")

st.title("⚖️ Consolidador Dinâmico de Normas (Autopilot)")
st.markdown("Faça o upload de **quantos arquivos normativos quiser** (Original, Alteradores, ou até misturados). A Inteligência Artificial fará o cruzamento automático, descobrirá as relações entre eles e entregará os arquivos prontos.")

# Configuração da API Key
api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    with st.sidebar:
        st.header("Configuração de IA")
        api_key = st.text_input("Chave da API do Google GenAI", type="password")
        st.markdown("[Obtenha sua chave gratuita no Google AI Studio](https://aistudio.google.com/)")

st.markdown("---")
arquivos_enviados = st.file_uploader("📥 Arraste todos os documentos de uma vez (PDF ou DOCX)", type=["pdf", "docx"], accept_multiple_files=True)

# ----------------- ESTRUTURAS DE DADOS (Autopilot) -----------------
class Dispositivo(BaseModel):
    tipo: str = Field(description="Ex: 'capitulo', 'artigo', 'paragrafo', 'inciso', etc.")
    texto_principal_alterada: str = Field(description="Texto da versão alterada. OBRIGATÓRIO tachar TUDO que for substituído/revogado INCLUINDO o identificador original (Ex: <font color='red'><strike><b>Art. 1º</b> O texto...</strike></font>).")
    texto_principal_consolidada: str = Field(description="Texto limpo da versão consolidada. Se totalmente revogado, coloque apenas o identificador (ex: <b>Art 1º</b>).")
    is_tabela: bool = Field(description="True se houver uma tabela associada.")
    tabela_alterada: Optional[List[List[str]]] = Field(default=None, description="Matriz da tabela alterada.")
    tabela_consolidada: Optional[List[List[str]]] = Field(default=None, description="Matriz da tabela consolidada.")
    texto_pos_tabela_alterada: Optional[str] = Field(default=None)
    texto_pos_tabela_consolidada: Optional[str] = Field(default=None)
    nota_remissiva: Optional[str] = Field(default="", description="OBRIGATÓRIO se alterado/revogado. Ex: '(Alterado pelo art. X da Portaria Y)'. Não use HTML aqui.")

class Consolidacao(BaseModel):
    arquivo_original_identificado: str = Field(description="Nome do arquivo PDF/DOCX usado como norma base")
    arquivo_alterador_identificado: str = Field(description="Nome do arquivo PDF/DOCX usado como norma alteradora")
    nome_portaria_base: str = Field(description="Ex: Portaria nº 130/PGJM")
    nome_portaria_alteradora: str = Field(description="Ex: Portaria nº 103/PGJM")
    cabecalho_complemento: str = Field(description="Ex: 'Atualizada pela Portaria nº 103/PGJM...'")
    orgaos_emissores: str = Field(description="Órgãos emissores da norma original (use <br/>).")
    titulo_portaria: str = Field(description="Título da Norma Original.")
    ementa_preambulo: str = Field(description="Preâmbulo original.")
    assinatura_nome: str = Field(description="Nome de quem assina o original.")
    assinatura_cargo: str = Field(description="Cargo de quem assina.")
    dispositivos: List[Dispositivo] = Field(description="Lista de dispositivos combinados.")

class ArquivoAvulso(BaseModel):
    nome_arquivo: str = Field(description="Nome do arquivo enviado")
    nome_portaria_identificada: str = Field(description="A portaria que consta neste arquivo")
    motivo: str = Field(description="Ex: 'Não possui vínculo de alteração ou revogação com os outros arquivos enviados.'")

class AnaliseGlobal(BaseModel):
    consolidacoes_geradas: List[Consolidacao] = Field(description="Lista com os cruzamentos normativos identificados.")
    arquivos_nao_alterados: List[ArquivoAvulso] = Field(description="Lista de arquivos que não se conectam a nenhum outro do lote.")

# ----------------- MOTOR DE IA E PROCESSAMENTO -----------------
def analisar_lote_arquivos(arquivos, key):
    client = genai.Client(api_key=key)
    caminhos_temporarios = []
    gemini_files_objs = []
    
    try:
        # 1. Salva e faz upload de todos os arquivos
        for arq in arquivos:
            ext = f".{arq.name.split('.')[-1]}"
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(arq.getvalue())
                caminhos_temporarios.append((tmp.name, arq.name))
                
        # Intercala texto com o objeto da API para a IA saber qual arquivo é qual
        conteudos_prompt = ["Analise as relações entre os seguintes arquivos normativos:"]
        for caminho_tmp, nome_original in caminhos_temporarios:
            g_file = client.files.upload(file=caminho_tmp)
            gemini_files_objs.append(g_file)
            conteudos_prompt.append(f"ARQUIVO: {nome_original}")
            conteudos_prompt.append(g_file)

        prompt_comandos = """
        Atue como um Especialista Sênior em Técnica Legislativa.
        
        Sua Missão:
        1. Ler todos os arquivos enviados e descobrir as relações entre eles.
        2. Identificar pares de (Norma Original + Norma Alteradora).
        3. Para CADA PAR identificado, gerar uma 'Consolidacao'.
        4. Se um arquivo não sofreu nem causou alterações no contexto dos documentos enviados, liste-o em 'arquivos_nao_alterados'.

        REGRAS CRÍTICAS PARA A CONSOLIDAÇÃO (INEGOCIÁVEIS):
        - TACHADO COMPLETO: Em `texto_principal_alterada`, se um dispositivo inteiro for substituído/revogado, você OBRIGATORIAMENTE deve tachar inclusive a nomenclatura inicial (Ex: <font color='red'><strike><b>Art. 1º</b> Texto antigo...</strike></font>).
        - TABELAS: Se foram substituídas por texto, a matriz antiga inteira vai em `tabela_alterada` e o texto novo em `texto_pos_tabela_alterada` e `texto_pos_tabela_consolidada`.
        - VERSÃO CONSOLIDADA: Mostre apenas o texto NOVO limpo. Se totalmente revogado, exiba APENAS o título original em negrito (Ex: <b>Art. 9º</b>).
        - NOTAS REMISSIVAS: Preencha SEMPRE o campo `nota_remissiva` com o texto cru (Ex: (Alterado pelo art. X da Portaria...)). Não coloque tags HTML na nota, o sistema fará isso.
        - Não use LaTeX para expressões ordinais. Separe listas (incisos/alíneas) obrigatoriamente com a tag <br/>.
        """
        conteudos_prompt.append(prompt_comandos)

        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=conteudos_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AnaliseGlobal,
                temperature=0.0 
            ),
        )
        return json.loads(response.text)
    
    finally:
        # Segurança e Limpeza (Google Cloud + Disco Local)
        for g_file in gemini_files_objs:
            try: client.files.delete(name=g_file.name)
            except: pass
        for caminho_tmp, _ in caminhos_temporarios:
            if os.path.exists(caminho_tmp): os.remove(caminho_tmp)

# ----------------- PARSERS E GERADORES -----------------
def extrair_paragrafos_seguros(texto_html):
    texto_html = texto_html.replace("</font></strike>", "</strike></font>")
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
        
    def abrir_todas(pilha_tags):
        return "".join(pilha_tags)
        
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
    """Injeta um espaço em branco claro antes de inserir a nota em vermelho, assegurando leitura perfeita."""
    if nota and nota.strip():
        texto_limpo = texto.rstrip('<br/>').rstrip('<br>').rstrip()
        return f"{texto_limpo} &nbsp;<font color='red'>{nota.strip()}</font>"
    return texto

def renderizar_paragrafos_pdf(story, texto_html, estilo):
    paragrafos = extrair_paragrafos_seguros(texto_html)
    for p in paragrafos:
        story.append(Paragraph(p, estilo))

def aplicar_html_no_docx(p, texto_html):
    tokens = re.split(r'(<[^>]+>)', texto_html.replace("&nbsp;", " "))
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
    paragrafos = extrair_paragrafos_seguros(texto_html)
    for p_html in paragrafos:
        p = doc.add_paragraph()
        p.alignment = alignment
        p.paragraph_format.first_line_indent = first_line_indent
        p.paragraph_format.space_after = space_after
        p.paragraph_format.line_spacing = 1.15
        if bold_all:
            run = p.add_run(re.sub(r'<[^>]+>', '', p_html).replace("&nbsp;", " "))
            run.font.name = 'Times New Roman'
            run.font.size = Pt(10)
            run.bold = True
        else:
            aplicar_html_no_docx(p, p_html)

# ----------------- GERADORES DE DOCUMENTOS -----------------
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

    comp = consolidacao_dict.get("cabecalho_complemento", "")
    topo_texto = f"VERSÃO ALTERADA - {comp}" if tipo_versao == "alterada" else f"VERSÃO CONSOLIDADA - {comp}"
    story.append(Paragraph(topo_texto, estilo_cabecalho_topo))

    caminho_imagem = "brasao.png"
    if os.path.exists(caminho_imagem):
        try:
            img_brasao = Image(caminho_imagem, width=60, height=60)
            img_brasao.hAlign = 'CENTER'
            story.append(img_brasao)
            story.append(Spacer(1, 10))
        except: pass

    story.append(Paragraph(consolidacao_dict.get("orgaos_emissores", "").replace("\n", "").replace("<br>", "<br/>"), estilo_orgaos))
    story.append(Paragraph(consolidacao_dict.get("titulo_portaria", "").replace("<br>", "<br/>").replace("\n", "<br/>"), estilo_titulo))
    renderizar_paragrafos_pdf(story, consolidacao_dict.get("ementa_preambulo", "").replace("\n", ""), estilo_dispositivo)

    for item in consolidacao_dict.get("dispositivos", []):
        tipo = item.get("tipo", "").lower()
        is_tabela = item.get("is_tabela", False)
        nota = item.get("nota_remissiva", "")
        
        texto_principal = item.get(f"texto_principal_{tipo_versao}", "")
        texto_pos = item.get(f"texto_pos_tabela_{tipo_versao}", "")
        
        if not is_tabela and not texto_pos:
            texto_principal = injetar_nota_remissiva(texto_principal, nota)
        elif texto_pos:
            texto_pos = injetar_nota_remissiva(texto_pos, nota)
            
        if "capitulo" in tipo:
            story.append(Paragraph(texto_principal.replace('\n', ' '), estilo_capitulo))
            continue

        if texto_principal:
            renderizar_paragrafos_pdf(story, texto_principal.replace("\n", " "), estilo_dispositivo)
            
        if is_tabela:
            linhas = item.get(f"tabela_{tipo_versao}", [])
            if linhas and len(linhas) > 0:
                tabela_processada = []
                for linha in linhas:
                    linha_processada = [Paragraph(celula.replace('\n', ' '), estilo_celula) for celula in linha]
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
            renderizar_paragrafos_pdf(story, texto_pos.replace("\n", " "), estilo_dispositivo)

    bloco_assinatura = f"{consolidacao_dict.get('assinatura_nome', '')}<br/>{consolidacao_dict.get('assinatura_cargo', '')}"
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

def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
    doc = docx.Document()
    for section in doc.sections:
        section.top_margin, section.bottom_margin = Inches(1), Inches(1)
        section.left_margin, section.right_margin = Inches(1), Inches(1)

    p_head = doc.add_paragraph()
    p_head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    comp = consolidacao_dict.get("cabecalho_complemento", "")
    texto_head = f"VERSÃO ALTERADA - {comp}" if tipo_versao == "alterada" else f"VERSÃO CONSOLIDADA - {comp}"
    r_head = p_head.add_run(texto_head)
    r_head.font.name, r_head.font.size, r_head.bold = 'Times New Roman', Pt(10), True
    r_head.font.color.rgb = RGBColor(68, 68, 68)
    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    p_org = doc.add_paragraph()
    p_org.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_org.paragraph_format.space_after = Pt(18)
    r_org = p_org.add_run(consolidacao_dict.get("orgaos_emissores", "").replace("<br/>", "\n").replace("<br>", "\n"))
    r_org.font.name, r_org.font.size, r_org.bold = 'Times New Roman', Pt(11), True

    p_tit = doc.add_paragraph()
    p_tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_tit.paragraph_format.space_after = Pt(14)
    r_tit = p_tit.add_run(consolidacao_dict.get("titulo_portaria", ""))
    r_tit.font.name, r_tit.font.size, r_tit.bold = 'Times New Roman', Pt(11), True

    renderizar_paragrafos_docx(doc, consolidacao_dict.get("ementa_preambulo", "").replace("\n", " "), WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))

    for item in consolidacao_dict.get("dispositivos", []):
        tipo = item.get("tipo", "").lower()
        is_tabela = item.get("is_tabela", False)
        nota = item.get("nota_remissiva", "")
        
        texto_principal = item.get(f"texto_principal_{tipo_versao}", "")
        texto_pos = item.get(f"texto_pos_tabela_{tipo_versao}", "")
        
        if not is_tabela and not texto_pos: texto_principal = injetar_nota_remissiva(texto_principal, nota)
        elif texto_pos: texto_pos = injetar_nota_remissiva(texto_pos, nota)

        if "capitulo" in tipo:
            renderizar_paragrafos_docx(doc, texto_principal.replace("\n", " "), WD_ALIGN_PARAGRAPH.CENTER, Inches(0), Pt(10), bold_all=True)
            continue

        if texto_principal:
            renderizar_paragrafos_docx(doc, texto_principal.replace('\n', ' '), WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))
            
        if is_tabela:
            linhas = item.get(f"tabela_{tipo_versao}", [])
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
                
        if texto_pos:
            renderizar_paragrafos_docx(doc, texto_pos.replace('\n', ' '), WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))

    p_assinatura = doc.add_paragraph()
    p_assinatura.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_assinatura.paragraph_format.space_before, p_assinatura.paragraph_format.space_after = Pt(36), Pt(24)
    r_ass = p_assinatura.add_run(f"{consolidacao_dict.get('assinatura_nome', '')}\n{consolidacao_dict.get('assinatura_cargo', '')}")
    r_ass.font.name, r_ass.font.size, r_ass.bold = 'Times New Roman', Pt(11), True

    p_rod = doc.add_paragraph()
    p_rod.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_rod.paragraph_format.space_before = Pt(24)
    r_nota_label = p_rod.add_run("Nota: ")
    r_nota_label.font.name, r_nota_label.font.size, r_nota_label.bold, r_nota_label.italic = 'Times New Roman', Pt(9), True, True
    r_nota_text = p_rod.add_run("Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial.")
    r_nota_text.font.name, r_nota_text.font.size, r_nota_text.italic = 'Times New Roman', Pt(9), True

    buffer_docx = io.BytesIO()
    doc.save(buffer_docx)
    buffer_docx.seek(0)
    return buffer_docx.getvalue()

# ----------------- INICIALIZAÇÃO DA SESSÃO E INTERFACE -----------------
if "dados_processados" not in st.session_state:
    st.session_state.dados_processados = None

if st.button("🚀 Iniciar Análise Autopilot", type="primary", use_container_width=True):
    if not api_key:
        st.error("⚠️ Insira sua chave da API do Google GenAI no menu lateral.")
    elif not arquivos_enviados or len(arquivos_enviados) < 1:
        st.warning("⚠️ Envie pelo menos um arquivo normativo.")
    else:
        with st.spinner("🧠 Lendo os arquivos, descobrindo relações e processando formatações..."):
            try:
                chave_limpa = api_key.strip()
                resultados = analisar_lote_arquivos(arquivos_enviados, chave_limpa)
                st.session_state.dados_processados = resultados
                st.success("✨ Processamento em Lote Concluído!")
            except Exception as e:
                st.error("❌ Ocorreu um erro. Verifique seus limites na API.")
                st.code(str(e))

# ----------------- RENDERIZAÇÃO DOS RESULTADOS -----------------
if st.session_state.dados_processados is not None:
    st.markdown("---")
    
    dados = st.session_state.dados_processados
    consolidacoes = dados.get("consolidacoes_geradas", [])
    avulsos = dados.get("arquivos_nao_alterados", [])
    
    if len(consolidacoes) > 0:
        st.header("📑 Documentos Consolidados Prontos")
        
        for i, cons in enumerate(consolidacoes):
            with st.expander(f"📁 **{cons['nome_portaria_base']}** atualizada pela **{cons['nome_portaria_alteradora']}**", expanded=True):
                st.info(f"**Original Identificado:** `{cons['arquivo_original_identificado']}`\n\n**Alterador Identificado:** `{cons['arquivo_alterador_identificado']}`")
                
                # Gera os binários exclusivos desta consolidação
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
        st.header("🗂️ Arquivos Sem Alteração Detectada neste Lote")
        for avulso in avulsos:
            st.warning(f"**Arquivo:** `{avulso.get('nome_arquivo', 'Desconhecido')}`\n\n**Portaria/Norma:** {avulso.get('nome_portaria_identificada', 'Não identificada')}\n\n**Motivo:** {avulso.get('motivo', '')}")

    st.markdown("---")
    if st.button("🔄 Reiniciar e Realizar Nova Análise", type="secondary"):
        st.session_state.dados_processados = None
        st.rerun()
