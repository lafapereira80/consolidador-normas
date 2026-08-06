import streamlit as st
import fitz  # PyMuPDF para ler os PDFs
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io
import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List

# CORREÇÃO: O comando correto é st.set_page_config
st.set_page_config(page_title="Consolidador Dinâmico de Normas - MPM", layout="centered")

st.title("⚖️ Sistema Web Dinâmico de Consolidação Normativa")
st.write("Faça o upload da **Portaria Original** e da **Portaria Alteradora**. A IA fará a leitura, o cruzamento normativo e gerará os PDFs dinamicamente.")

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
    pdf_original = st.file_uploader("1. Portaria Original (PDF)", type=["pdf"])
with col2:
    pdf_alteradora = st.file_uploader("2. Portaria Alteradora/Revogadora (PDF)", type=["pdf"])

def extrair_texto_de_upload(arquivo_uploaded):
    """Extrai o texto bruto do PDF enviado via web."""
    with fitz.open(stream=arquivo_uploaded.read(), filetype="pdf") as doc:
        texto = ""
        for pagina in doc:
            texto += pagina.get_text()
    return texto

# Estrutura Pydantic para garantir que o Gemini responda exatamente no formato JSON esperado
class Dispositivo(BaseModel):
    tipo: str = Field(description="Tipo do item, ex: 'capitulo', 'artigo', 'paragrafo'")
    texto_alterada: str = Field(description="Texto para a Versão Alterada. Se foi alterado/revogado, coloque a versão antiga tachada em HTML (<font color='red'><strike>...</strike></font>) seguida da nova redação com nota remissiva. Se não mudou, coloque o texto normal.")
    texto_consolidado: str = Field(description="Texto limpo e atualizado para a Versão Consolidada, contendo apenas a redação vigente com a nota remissiva.")

class ResultadoConsolidacao(BaseModel):
    titulo_portaria: str = Field(description="Identificação da portaria original, ex: 'Portaria nº 130/PGJM, de 28 de junho de 2022.'")
    ementa_preambulo: str = Field(description="O preâmbulo completo da portaria original formatado com HTML básico (ex: <b>PROCURADOR-GERAL...</b>).")
    dispositivos: List[Dispositivo] = Field(description="Lista sequencial de capítulos e artigos da norma após a consolidação.")

def analisar_normas_com_gemini_dinamico(texto_original, texto_alterador, key):
    """Solicita ao Gemini a extração estruturada e o cruzamento dinâmico dos artigos."""
    client = genai.Client(api_key=key)
    prompt = f"""
    Atue como um especialista em técnica legislativa e consolidação de normas do Ministério Público Militar.
    Analise a Portaria Original e a Portaria Alteradora/Revogadora fornecidas abaixo.
    Faça o cruzamento normativo completo: identifique quais artigos foram alterados, revogados ou acrescentados.
    
    PORTARIA ORIGINAL:
    {texto_original}
    
    PORTARIA ALTERADORA / REVOGADORA:
    {texto_alterador}
    
    Retorne os dados estruturados estritamente no formato exigido pelo esquema.
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ResultadoConsolidacao,
            temperature=0.1
        ),
    )
    return json.loads(response.text)

def desenhar_cabecalho_rodape(canvas, doc):
    """Adiciona o rodapé padrão institucional em todas as páginas."""
    canvas.saveState()
    canvas.setFont('Helvetica-Oblique', 8)
    canvas.setFillColor(colors.HexColor('#555555'))
    nota = "Nota: Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial."
    canvas.drawCentredString(A4[0] / 2.0, 40, nota)
    canvas.restoreState()

def gerar_pdf_dinamico(titulo_versao, dados_json, tipo_versao):
    """Gera o PDF dinamicamente com base nos dados retornados pela IA."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72
    )
    story = []
    styles = getSampleStyleSheet()

    estilo_cabecalho = ParagraphStyle('CabecalhoVersao', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=1, textColor=colors.HexColor('#444444'), spaceAfter=20)
    estilo_orgaos = ParagraphStyle('Orgaos', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=25)
    estilo_titulo = ParagraphStyle('TituloPortaria', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=20)
    estilo_dispositivo = ParagraphStyle('Dispositivo', parent=styles['Normal'], fontName='Helvetica', fontSize=11, leading=15, alignment=4, firstLineIndent=30, spaceAfter=12)
    estilo_capitulo = ParagraphStyle('Capitulo', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=14, alignment=1, spaceBefore=20, spaceAfter=12, textTransform='uppercase')
    estilo_assinatura = ParagraphStyle('Assinatura', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=15, alignment=1, spaceBefore=50, spaceAfter=20)

    # 1. Cabeçalho de Controle de Versão
    story.append(Paragraph(titulo_versao, estilo_cabecalho))

    # 2. Brasão da República
    url_brasao = "https://www.gov.br/agricultura/pt-br/agroform/brasao-sem-fundo.png"
    try:
        img_brasao = Image(url_brasao, width=60, height=60)
        img_brasao.hAlign = 'CENTER'
        story.append(img_brasao)
        story.append(Spacer(1, 10))
    except:
        pass

    # 3. Órgãos Emissores
    story.append(Paragraph("MINISTÉRIO PÚBLICO DA UNIÃO<br/>MINISTÉRIO PÚBLICO MILITAR<br/>PROCURADORIA-GERAL DE JUSTIÇA MILITAR", estilo_orgaos))

    # 4. Título da Norma Extraído pela IA
    story.append(Paragraph(dados_json.get("titulo_portaria", "Portaria Normativa"), estilo_titulo))

    # 5. Preâmbulo Oficial
    story.append(Paragraph(dados_json.get("ementa_preambulo", ""), estilo_dispositivo))

    # 6. Inserção Dinâmica dos Dispositivos (Capítulos e Artigos)
    for item in dados_json.get("dispositivos", []):
        tipo = item.get("tipo", "").lower()
        if "capitulo" in tipo:
            story.append(Paragraph(item.get("texto_alterada", ""), estilo_capitulo))
        else:
            if tipo_versao == "alterada":
                texto_final = item.get("texto_alterada", "")
            else:
                texto_final = item.get("texto_consolidado", "")
            
            story.append(Paragraph(texto_final, estilo_dispositivo))

    # 7. Assinatura
    story.append(Paragraph("ANTÔNIO PEREIRA DUARTE<br/>Procurador-Geral da Justiça Militar", estilo_assinatura))

    doc.build(story, onFirstPage=desenhar_cabecalho_rodape, onLaterPages=desenhar_cabecalho_rodape)
    buffer.seek(0)
    return buffer.getvalue()

# Interface do Botão de Execução
if st.button("🚀 Processar Dinamicamente com IA e Gerar PDFs", type="primary"):
    if not api_key:
        st.error("⚠️ Insira sua chave da API do Google GenAI.")
    elif pdf_original and pdf_alteradora:
        with st.spinner("Lendo os PDFs, cruzando os atos e estruturando os dados dinamicamente..."):
            texto_orig = extrair_texto_de_upload(pdf_original)
            texto_alt = extrair_texto_de_upload(pdf_alteradora)
            
            # Chamada estruturada ao Gemini
            dados_estruturados = analisar_normas_com_gemini_dinamico(texto_orig, texto_alt, api_key)
            
            # Geração dos PDFs utilizando os dados reais processados pela IA
            pdf_alt_bytes = gerar_pdf_dinamico("VERSÃO ALTERADA - Dinâmica", dados_estruturados, "alterada")
            pdf_cons_bytes = gerar_pdf_dinamico("VERSÃO CONSOLIDADA - Dinâmica", dados_estruturados, "consolidada")
            
        st.success("✨ Processamento dinâmico concluído com sucesso!")
        st.divider()
        st.subheader("📥 Baixe os PDFs Oficiais Prontos:")
        
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.download_button(label="Baixar Versão Alterada (PDF)", data=pdf_alt_bytes, file_name="versao_alterada_dinamica.pdf", mime="application/pdf")
        with col_d2:
            st.download_button(label="Baixar Versão Consolidada (PDF)", data=pdf_cons_bytes, file_name="versao_consolidada_dinamica.pdf", mime="application/pdf")
    else:
        st.warning("⚠️ Envie ambos os arquivos PDF para iniciar.")
