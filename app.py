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
    pdf_original = st.file_uploader("1. Documento Original (PDF)", type=["pdf"])
with col2:
    pdf_alteradora = st.file_uploader("2. Documento Alterador/Revogador (PDF)", type=["pdf"])

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
    texto_alterada: str = Field(description="Obrigatório: Se alterado, TODO o dispositivo antigo (incluindo identificadores como Art., §) DEVE estar em <font color='red'><strike>...</strike></font>. Em seguida, insira <br/> para pular linha e adicione o texto novo mantendo o padrão de parágrafo. Adicione nota remissiva no final.")
    texto_consolidado: str = Field(description="Texto limpo e atualizado. Preserve negritos originais (ex: <b>Art. 1º</b>). OBRIGATÓRIO adicionar a nota remissiva no final (ex: (Alterado pela Portaria...)).")
    is_tabela: bool = Field(description="Verdadeiro (true) SE o conteúdo for um quadro ou tabela.")
    tabela_linhas_alterada: Optional[List[List[str]]] = Field(default=None, description="Se tabela alterada, células antigas devem usar <font color='red'><strike>...</strike></font> seguidas das novas.")
    tabela_linhas_consolidada: Optional[List[List[str]]] = Field(default=None, description="Matriz limpa da tabela consolidada.")

class ResultadoConsolidacao(BaseModel):
    cabecalho_versao_alterada: str = Field(description="Gere o texto exato: 'VERSÃO ALTERADA — Atualizada pela [Nome/Número da Norma Alteradora], [Data por extenso]'.")
    orgaos_emissores: str = Field(description="Extraia o cabeçalho com os órgãos emissores da norma original. Use a tag <br/> para separar as linhas.")
    titulo_portaria: str = Field(description="Apenas o nome e data da Norma Original.")
    ementa_preambulo: str = Field(description="O preâmbulo original. Preserve as palavras em negrito originais (ex: <b>RESOLVE:</b>).")
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
    1. PROIBIDO LaTeX: NUNCA use LaTeX (como $5^{{\circ}}$). Use textualmente "1º", "2º", "5º", "§", etc.
    2. EXTRAÇÃO DINÂMICA: Extraia corretamente o Órgão Emissor e quem assina (Nome e Cargo) do documento original.
    3. CABEÇALHO ALTERADO: Crie o título dinâmico da versão alterada (Ex: 'VERSÃO ALTERADA — Atualizada pela Portaria nº 103/PGJM, 21 de maio de 2026').
    4. REGRA DO VERMELHO TACHADO: Para itens alterados, TODO o dispositivo antigo (incluindo identificadores lidos no documento como Art. 1º, Parágrafo único, § 1º) DEVE estar dentro de <font color='red'><strike>TEXTO ANTIGO</strike></font>. Insira a tag HTML <br/> para quebrar a linha, e inicie o texto novo completo abaixo, obedecendo rigorosamente à mesma formatação de parágrafo.
       Exemplo obrigatório de formatação de alteração:
       <font color='red'><strike><b>Art. 1º</b> Texto antigo...</strike></font><br/><b>Art. 1º</b> Texto novo... (Alterado pela Portaria...)
    5. REGRA DE REVOGAÇÃO: Texto inteiro revogado deve ficar em <font color='red'><strike>TEXTO REVOGADO</strike></font> seguido de (Revogado pela...).
    6. NOTAS REMISSIVAS: Se um dispositivo foi alterado, revogado ou acrescentado, é OBRIGATÓRIO incluir a nota remissiva ao FINAL do texto do dispositivo.
    7. NEGRITOS E ITÁLICOS: Mantenha as palavras que estavam em negrito no original (ex: <b>Art. 1º</b>, <b>Parágrafo único.</b>).
    8. TABELAS: Defina `is_tabela` como true e extraia como matriz.
    9. LIMPEZA: Remova quebras de linha (Enters) artificiais do meio das frases para manter os parágrafos uniformes.
    
    NORMA ORIGINAL:
    {texto_original}
    
    NORMA ALTERADORA:
    {texto_alterador}
    """
    
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ResultadoConsolidacao,
            temperature=0.0 
        ),
    )
    return json.loads(response.text)

def gerar_pdf_dinamico(dados_json, tipo_versao):
    """Gera o PDF com suporte a tabelas, fontes dinâmicas, recuos padronizados e rodapé de última página."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    story = []
    styles = getSampleStyleSheet()

    estilo_cabecalho_topo = ParagraphStyle('CabecalhoTopo', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=1, textColor=colors.HexColor('#444444'), spaceAfter=20)
    estilo_orgaos = ParagraphStyle('Orgaos', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=25)
    estilo_titulo = ParagraphStyle('TituloPortaria', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=20)
    # Recuo de primeira linha uniforme (30 pontos) para manter a formatação de parágrafo correta
    estilo_dispositivo = ParagraphStyle('Dispositivo', parent=styles['Normal'], fontName='Helvetica', fontSize=11, leading=15, alignment=4, firstLineIndent=30, spaceAfter=12)
    estilo_celula = ParagraphStyle('Celula', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=12, alignment=0)
    estilo_capitulo = ParagraphStyle('Capitulo', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=14, alignment=1, spaceBefore=20, spaceAfter=12, textTransform='uppercase')
    estilo_assinatura = ParagraphStyle('Assinatura', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=15, alignment=1, spaceBefore=50, spaceAfter=20)
    estilo_rodape = ParagraphStyle('Rodape', fontName='Helvetica-Oblique', fontSize=9, leading=12, alignment=0)

    # 1. Cabeçalho Dinâmico da Versão
    if tipo_versao == "alterada":
        cabecalho_texto = dados_json.get("cabecalho_versao_alterada", "VERSÃO ALTERADA")
        story.append(Paragraph(cabecalho_texto, estilo_cabecalho_topo))
    else:
        story.append(Paragraph("VERSÃO CONSOLIDADA", estilo_cabecalho_topo))

    # 2. Brasão da República
    caminho_imagem = "brasao.png"
    if os.path.exists(caminho_imagem):
        try:
            img_brasao = Image(caminho_imagem, width=60, height=60)
            img_brasao.hAlign = 'CENTER'
            story.append(img_brasao)
            story.append(Spacer(1, 10))
        except:
            pass

    # 3. Órgãos Emissores Dinâmicos
    orgaos_texto = dados_json.get("orgaos_emissores", "").replace("\n", "").replace("<br>", "<br/>")
    story.append(Paragraph(orgaos_texto, estilo_orgaos))

    # 4. Título da Norma
    titulo_texto = dados_json.get("titulo_portaria", "").replace("<br>", "<br/>").replace("\n", "<br/>")
    story.append(Paragraph(titulo_texto, estilo_titulo))

    # 5. Preâmbulo 
    preambulo_texto = dados_json.get("ementa_preambulo", "").replace("<br>", "<br/>").replace("\n", "<br/>")
    story.append(Paragraph(preambulo_texto, estilo_dispositivo))

    # 6. Inserção Dinâmica (Texto e TABELAS)
    for item in dados_json.get("dispositivos", []):
        is_tabela = item.get("is_tabela", False)
        tipo = item.get("tipo", "").lower()
        
        if is_tabela:
            chave_tabela = f"tabela_linhas_{tipo_versao}"
            linhas = item.get(chave_tabela, [])
            
            if linhas and len(linhas) > 0:
                tabela_processada = []
                for linha in linhas:
                    linha_processada = []
                    for celula in linha:
                        cel_texto = celula.replace('\n', ' ').replace('<br>', '<br/>')
                        linha_processada.append(Paragraph(cel_texto, estilo_celula))
                    tabela_processada.append(linha_processada)
                
                t = Table(tabela_processada, colWidths='*')
                t.setStyle(TableStyle([
                    ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('LINEBELOW', (0,0), (-1,0), 0.5, colors.black),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                ]))
                story.append(t)
                story.append(Spacer(1, 15))
            else:
                fallback = item.get(f"texto_{tipo_versao}", "")
                story.append(Paragraph(fallback.replace('\n', ' ').replace('<br>', '<br/>'), estilo_dispositivo))
                
        else:
            texto_final = item.get(f"texto_{tipo_versao}", "").replace("\n", " ").replace("<br>", "<br/>")
            if "capitulo" in tipo:
                story.append(Paragraph(texto_final, estilo_capitulo))
            else:
                story.append(Paragraph(texto_final, estilo_dispositivo))

    # 7. Assinatura Dinâmica Extraída pela IA
    nome_assinatura = dados_json.get("assinatura_nome", "")
    cargo_assinatura = dados_json.get("assinatura_cargo", "")
    bloco_assinatura = f"{nome_assinatura}<br/>{cargo_assinatura}"
    story.append(Paragraph(bloco_assinatura, estilo_assinatura))

    # 8. Nota de Rodapé Exclusiva da Última Página
    story.append(Spacer(1, 40))
    d = Drawing(A4[0] - 144, 10)
    d.add(Line(0, 5, A4[0] - 144, 5, strokeColor=colors.black, strokeWidth=0.5))
    story.append(d)
    story.append(Spacer(1, 5))
    texto_rodape = "<b>Nota:</b> Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial."
    story.append(Paragraph(texto_rodape, estilo_rodape))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_docx_dinamico(dados_json, tipo_versao):
    """Gera um documento Word (.docx) formatado com fontes Arial, parágrafos justificados e recuos."""
    doc = docx.Document()
    
    # Configurações de Margens (1 polegada / 72pt)
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # Função auxiliar para aplicar estilo padrão Arial em parágrafos
    def adicionar_paragrafo_formatado(texto, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_indent=Inches(0.4), space_after=Pt(6), bold_title_tags=False):
        p = doc.add_paragraph()
        p.alignment = alignment
        p.paragraph_format.first_line_indent = first_line_indent
        p.paragraph_format.space_after = space_after
        p.paragraph_format.line_spacing = 1.15
        
        # Limpeza básica de tags HTML básicas para o Word
        # Substitui quebras HTML por quebras normais de linha
        partes = texto.replace("<br>", "\n").replace("<br/>", "\n").split("<b>")
        for i, parte in enumerate(partes):
            if not parte:
                continue
            if "</b>" in parte:
                sub_partes = parte.split("</b>")
                run_bold = p.add_run(sub_partes[0])
                run_bold.font.name = 'Arial'
                run_bold.font.size = Pt(11)
                run_bold.bold = True
                
                # Tratamento de fonte vermelha tachada se houver <strike>
                if "<strike>" in sub_partes[1] or "<font color='red'>" in sub_partes[1]:
                    texto_limpo = sub_partes[1].replace("<font color='red'>", "").replace("</font>", "").replace("<strike>", "").replace("</strike>", "")
                    run_normal = p.add_run(texto_limpo)
                    run_normal.font.name = 'Arial'
                    run_normal.font.size = Pt(11)
                    run_normal.font.color.rgb = RGBColor(255, 0, 0)
                    run_normal.font.strike = True
                else:
                    run_normal = p.add_run(sub_partes[1])
                    run_normal.font.name = 'Arial'
                    run_normal.font.size = Pt(11)
            else:
                if "<strike>" in parte or "<font color='red'>" in parte:
                    texto_limpo = parte.replace("<font color='red'>", "").replace("</font>", "").replace("<strike>", "").replace("</strike>", "")
                    run_normal = p.add_run(texto_limpo)
                    run_normal.font.name = 'Arial'
                    run_normal.font.size = Pt(11)
                    run_normal.font.color.rgb = RGBColor(255, 0, 0)
                    run_normal.font.strike = True
                else:
                    run_normal = p.add_run(parte)
                    run_normal.font.name = 'Arial'
                    run_normal.font.size = Pt(11)
        return p

    # 1. Cabeçalho de Versão
    if tipo_versao == "alterada":
        cabecalho_texto = dados_json.get("cabecalho_versao_alterada", "VERSÃO ALTERADA")
        p_head = doc.add_paragraph()
        p_head.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_head = p_head.add_run(cabecalho_texto)
        r_head.font.name = 'Arial'
        r_head.font.size = Pt(10)
        r_head.bold = True
        r_head.font.color.rgb = RGBColor(68, 68, 68)
        doc.add_paragraph().paragraph_format.space_after = Pt(12)
    else:
        p_head = doc.add_paragraph()
        p_head.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_head = p_head.add_run("VERSÃO CONSOLIDADA")
        r_head.font.name = 'Arial'
        r_head.font.size = Pt(10)
        r_head.bold = True
        r_head.font.color.rgb = RGBColor(68, 68, 68)
        doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # 2. Órgãos Emissores
    orgaos_texto = dados_json.get("orgaos_emissores", "").replace("<br/>", "\n").replace("<br>", "\n")
    p_org = doc.add_paragraph()
    p_org.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_org.paragraph_format.space_after = Pt(18)
    r_org = p_org.add_run(orgaos_texto)
    r_org.font.name = 'Arial'
    r_org.font.size = Pt(11)
    r_org.bold = True

    # 3. Título da Portaria
    titulo_texto = dados_json.get("titulo_portaria", "")
    p_tit = doc.add_paragraph()
    p_tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_tit.paragraph_format.space_after = Pt(14)
    r_tit = p_tit.add_run(titulo_texto)
    r_tit.font.name = 'Arial'
    r_tit.font.size = Pt(11)
    r_tit.bold = True

    # 4. Preâmbulo
    preambulo_texto = dados_json.get("ementa_preambulo", "")
    adicionar_paragrafo_formatado(preambulo_texto, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_indent=Inches(0.4))

    # 5. Dispositivos e Tabelas
    for item in dados_json.get("dispositivos", []):
        is_tabela = item.get("is_tabela", False)
        tipo = item.get("tipo", "").lower()
        
        if is_tabela:
            chave_tabela = f"tabela_linhas_{tipo_versao}"
            linhas = item.get(chave_tabela, [])
            if linhas and len(linhas) > 0:
                table = doc.add_table(rows=len(linhas), cols=len(linhas[0]))
                table.style = 'Table Grid'
                for r_idx, linha in enumerate(linhas):
                    for c_idx, celula in enumerate(linha):
                        cell = table.cell(r_idx, c_idx)
                        cell.text = celula.replace("<br>", "\n").replace("<br/>", "\n")
                        for p in cell.paragraphs:
                            p.paragraph_format.space_after = Pt(2)
                            for run in p.runs:
                                run.font.name = 'Arial'
                                run.font.size = Pt(10)
                                if "<font color='red'>" in celula or "<strike>" in celula:
                                    run.font.color.rgb = RGBColor(255, 0, 0)
                                    run.font.strike = True
                doc.add_paragraph().paragraph_format.space_after = Pt(12)
        else:
            texto_final = item.get(f"texto_{tipo_versao}", "").replace("\n", " ")
            if "capitulo" in tipo:
                p_cap = doc.add_paragraph()
                p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_cap.paragraph_format.space_before = Pt(18)
                p_cap.paragraph_format.space_after = Pt(10)
                r_cap = p_cap.add_run(texto_final)
                r_cap.font.name = 'Arial'
                r_cap.font.size = Pt(10)
                r_cap.bold = True
            else:
                adicionar_paragrafo_formatado(texto_final, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_indent=Inches(0.4))

    # 6. Assinatura
    nome_assinatura = dados_json.get("assinatura_nome", "")
    cargo_assinatura = dados_json.get("assinatura_cargo", "")
    p_assinatura = doc.add_paragraph()
    p_assinatura.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_assinatura.paragraph_format.space_before = Pt(36)
    p_assinatura.paragraph_format.space_after = Pt(24)
    r_ass = p_assinatura.add_run(f"{nome_assinatura}\n{cargo_assinatura}")
    r_ass.font.name = 'Arial'
    r_ass.font.size = Pt(11)
    r_ass.bold = True

    # 7. Nota de Rodapé na última página
    p_rod = doc.add_paragraph()
    p_rod.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_rod.paragraph_format.space_before = Pt(24)
    r_nota_label = p_rod.add_run("Nota: ")
    r_nota_label.font.name = 'Arial'
    r_nota_label.font.size = Pt(9)
    r_nota_label.bold = True
    r_nota_label.italic = True
    
    r_nota_text = p_rod.add_run("Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial.")
    r_nota_text.font.name = 'Arial'
    r_nota_text.font.size = Pt(9)
    r_nota_text.italic = True

    buffer_docx = io.BytesIO()
    doc.save(buffer_docx)
    buffer_docx.seek(0)
    return buffer_docx.getvalue()

# Interface do Botão
if st.button("🚀 Processar Dinamicamente com IA e Gerar Documentos", type="primary"):
    if not api_key:
        st.error("⚠️ Insira sua chave da API do Google GenAI.")
    elif pdf_original and pdf_alteradora:
        with st.spinner("Analisando documentos, extraindo assinaturas e formatando parágrafos e tabelas..."):
            try:
                texto_orig = extrair_texto_de_upload(pdf_original)
                texto_alt = extrair_texto_de_upload(pdf_alteradora)
                
                chave_limpa = api_key.strip()
                dados_estruturados = analisar_normas_com_gemini_dinamico(texto_orig, texto_alt, chave_limpa)
                
                # Geração de PDFs
                pdf_alt_bytes = gerar_pdf_dinamico(dados_estruturados, "alterada")
                pdf_cons_bytes = gerar_pdf_dinamico(dados_estruturados, "consolidada")
                
                # Geração de Word (.docx)
                docx_alt_bytes = gerar_docx_dinamico(dados_estruturados, "alterada")
                docx_cons_bytes = gerar_docx_dinamico(dados_estruturados, "consolidada")
                
                st.success("✨ Processamento dinâmico concluído com sucesso!")
                st.divider()
                st.subheader("📥 Baixe os Documentos Oficiais Prontos:")
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.markdown("### Versão Alterada")
                    st.download_button(label="Baixar em PDF", data=pdf_alt_bytes, file_name="versao_alterada_dinamica.pdf", mime="application/pdf")
                    st.download_button(label="Baixar em Word (.docx)", data=docx_alt_bytes, file_name="versao_alterada_dinamica.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                with col_d2:
                    st.markdown("### Versão Consolidada")
                    st.download_button(label="Baixar em PDF", data=pdf_cons_bytes, file_name="versao_consolidada_dinamica.pdf", mime="application/pdf")
                    st.download_button(label="Baixar em Word (.docx)", data=docx_cons_bytes, file_name="versao_consolidada_dinamica.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            
            except Exception as e:
                st.error("❌ Ocorreu um erro.")
                st.code(str(e))
    else:
        st.warning("⚠️ Envie ambos os arquivos PDF.")
