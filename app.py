import streamlit as st
import fitz  # PyMuPDF para ler os PDFs
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io
import json
import os
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional

# Configuração da página web
st.set_page_config(page_title="Consolidador Dinâmico de Normas - MPM", layout="centered")

st.title("⚖️ Sistema Web Dinâmico de Consolidação Normativa")
st.write("Faça o upload da **Portaria Original** e da **Portaria Alteradora**. A IA fará a leitura, o cruzamento normativo e gerará os PDFs dinamicamente com tabelas e negritos oficias.")

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

# Estrutura Avançada Pydantic (Agora Suporta Tabelas e Matrizes)
class Dispositivo(BaseModel):
    tipo: str = Field(description="Ex: 'capitulo', 'artigo', 'paragrafo', ou 'tabela'")
    texto_alterada: str = Field(description="Texto com redação antiga tachada (<font color='red'><strike>...</strike></font>) e nova redação. Use a tag <b> para negrito em destaques.")
    texto_consolidado: str = Field(description="Texto limpo e atualizado. Use a tag <b> para negrito em destaques.")
    is_tabela: bool = Field(description="Obrigatório ser verdadeiro (true) SE o conteúdo for um quadro ou tabela (como lotação e servidor).")
    tabela_linhas_alterada: Optional[List[List[str]]] = Field(default=None, description="Se for tabela, crie a matriz (linhas e colunas) da versão alterada. Pode usar <strike> nas células.")
    tabela_linhas_consolidada: Optional[List[List[str]]] = Field(default=None, description="Se for tabela, crie a matriz (linhas e colunas) da versão consolidada limpa.")

class ResultadoConsolidacao(BaseModel):
    titulo_portaria: str = Field(description="Apenas o nome e data da Portaria Original. Ex: 'Portaria nº 130/PGJM, de 28 de junho de 2022.' (NÃO inclua MINISTÉRIO PÚBLICO).")
    ementa_preambulo: str = Field(description="O preâmbulo original. OBRIGATÓRIO: Coloque a tag <b> nas palavras chaves como PROCURADOR-GERAL DE JUSTIÇA MILITAR, CONSIDERANDO e RESOLVE.")
    dispositivos: List[Dispositivo] = Field(description="Lista sequencial estruturada de toda a norma.")

def analisar_normas_com_gemini_dinamico(texto_original, texto_alterador, key):
    """Solicita ao Gemini a extração rigorosa com comandos visuais."""
    client = genai.Client(api_key=key)
    prompt = f"""
    Atue como um especialista em técnica legislativa do Ministério Público Militar.
    Analise a Portaria Original e a Portaria Alteradora abaixo e gere o JSON.
    
    REGRAS RÍGIDAS DE FORMATAÇÃO E ESTRUTURAÇÃO:
    1. PROIBIDO LaTeX: NUNCA use LaTeX (como $5^{{\circ}}$). Use textualmente "1º", "2º", "5º", "§", etc.
    2. NEGRITOS INSTITUCIONAIS: No preâmbulo, envolva obrigatoriamente com a tag <b> os termos "<b>PROCURADOR-GERAL DE JUSTIÇA MILITAR</b>", "<b>CONSIDERANDO</b>", "<b>RESOLVE:</b>".
    3. TABELAS: Se houver uma lista correlacionada (ex: Ofício Geral X Servidor/Nome), você DEVE definir `is_tabela` como true e extrair as informações em formato de matriz de dados (`tabela_linhas_alterada` e `tabela_linhas_consolidada`). A primeira lista (linha) deve ser o cabeçalho.
    4. LIXO DE EXTRAÇÃO: IGNORE e não inclua no JSON textos soltos como "Este documento possui caráter estritamente consultivo e informativo...".
    
    PORTARIA ORIGINAL:
    {texto_original}
    
    PORTARIA ALTERADORA:
    {texto_alterador}
    """
    
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ResultadoConsolidacao,
            temperature=0.0 # Temperatura zerada para forçar obediência extrema às regras
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
    """Gera o PDF com suporte a criação gráfica de Tabelas e renderização de HTML."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    story = []
    styles = getSampleStyleSheet()

    estilo_cabecalho = ParagraphStyle('CabecalhoVersao', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=1, textColor=colors.HexColor('#444444'), spaceAfter=20)
    estilo_orgaos = ParagraphStyle('Orgaos', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=25)
    estilo_titulo = ParagraphStyle('TituloPortaria', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=20)
    estilo_dispositivo = ParagraphStyle('Dispositivo', parent=styles['Normal'], fontName='Helvetica', fontSize=11, leading=15, alignment=4, firstLineIndent=30, spaceAfter=12)
    # Estilo especial sem recuo para jogar dentro das células da tabela
    estilo_celula = ParagraphStyle('Celula', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=12, alignment=0)
    estilo_capitulo = ParagraphStyle('Capitulo', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=14, alignment=1, spaceBefore=20, spaceAfter=12, textTransform='uppercase')
    estilo_assinatura = ParagraphStyle('Assinatura', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=15, alignment=1, spaceBefore=50, spaceAfter=20)

    # 1. Cabeçalho de Versão
    story.append(Paragraph(titulo_versao, estilo_cabecalho))

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

    # 3. Órgãos Emissores (Fixos e Limpos)
    story.append(Paragraph("MINISTÉRIO PÚBLICO DA UNIÃO<br/>MINISTÉRIO PÚBLICO MILITAR<br/>PROCURADORIA-GERAL DE JUSTIÇA MILITAR", estilo_orgaos))

    # 4. Título da Portaria
    titulo_texto = dados_json.get("titulo_portaria", "Portaria Normativa").replace("<br>", "<br/>").replace("\n", "<br/>")
    story.append(Paragraph(titulo_texto, estilo_titulo))

    # 5. Preâmbulo (Agora com negritos renderizados)
    preambulo_texto = dados_json.get("ementa_preambulo", "").replace("<br>", "<br/>").replace("\n", "<br/>")
    story.append(Paragraph(preambulo_texto, estilo_dispositivo))

    # 6. Inserção Dinâmica (Texto e TABELAS!)
    for item in dados_json.get("dispositivos", []):
        is_tabela = item.get("is_tabela", False)
        tipo = item.get("tipo", "").lower()
        
        if is_tabela:
            # Puxa os dados da tabela gerada pela IA
            chave_tabela = f"tabela_linhas_{tipo_versao}"
            linhas = item.get(chave_tabela, [])
            
            if linhas and len(linhas) > 0:
                tabela_processada = []
                # Converte o texto simples das células para Paragraph, permitindo <strike> e <b> dentro da tabela
                for linha in linhas:
                    linha_processada = []
                    for celula in linha:
                        cel_texto = celula.replace('\n', '<br/>').replace('<br>', '<br/>')
                        linha_processada.append(Paragraph(cel_texto, estilo_celula))
                    tabela_processada.append(linha_processada)
                
                # Monta a tabela geométrica do ReportLab
                t = Table(tabela_processada, colWidths='*')
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F2F2F2')), # Fundo cinza claro no cabeçalho
                    ('TEXTCOLOR', (0,0), (-1,0), colors.black),
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CCCCCC')),
                    ('BOX', (0,0), (-1,-1), 1, colors.black),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                    ('TOPPADDING', (0,0), (-1,-1), 8),
                ]))
                story.append(t)
                story.append(Spacer(1, 15))
            else:
                # Fallback de segurança se a IA marcou tabela, mas enviou texto
                fallback = item.get(f"texto_{tipo_versao}", "")
                story.append(Paragraph(fallback.replace('\n', '<br/>'), estilo_dispositivo))
                
        else:
            # Renderização de texto normal
            texto_final = item.get(f"texto_{tipo_versao}", "").replace("<br>", "<br/>").replace("\n", "<br/>")
            if "capitulo" in tipo:
                story.append(Paragraph(texto_final, estilo_capitulo))
            else:
                story.append(Paragraph(texto_final, estilo_dispositivo))

    # 7. Assinatura
    story.append(Paragraph("ANTÔNIO PEREIRA DUARTE<br/>Procurador-Geral da Justiça Militar", estilo_assinatura))

    doc.build(story, onFirstPage=desenhar_cabecalho_rodape, onLaterPages=desenhar_cabecalho_rodape)
    buffer.seek(0)
    return buffer.getvalue()

# Interface do Botão
if st.button("🚀 Processar Dinamicamente com IA e Gerar PDFs", type="primary"):
    if not api_key:
        st.error("⚠️ Insira sua chave da API do Google GenAI.")
    elif pdf_original and pdf_alteradora:
        with st.spinner("Estruturando normas, renderizando negritos e montando tabelas geometricamente..."):
            try:
                texto_orig = extrair_texto_de_upload(pdf_original)
                texto_alt = extrair_texto_de_upload(pdf_alteradora)
                
                chave_limpa = api_key.strip()
                dados_estruturados = analisar_normas_com_gemini_dinamico(texto_orig, texto_alt, chave_limpa)
                
                pdf_alt_bytes = gerar_pdf_dinamico("VERSÃO ALTERADA - Dinâmica", dados_estruturados, "alterada")
                pdf_cons_bytes = gerar_pdf_dinamico("VERSÃO CONSOLIDADA - Dinâmica", dados_estruturados, "consolidada")
                
                st.success("✨ Processamento dinâmico concluído com fidelidade visual!")
                st.divider()
                st.subheader("📥 Baixe os PDFs Oficiais Prontos:")
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button(label="Baixar Versão Alterada (PDF)", data=pdf_alt_bytes, file_name="versao_alterada_dinamica.pdf", mime="application/pdf")
                with col_d2:
                    st.download_button(label="Baixar Versão Consolidada (PDF)", data=pdf_cons_bytes, file_name="versao_consolidada_dinamica.pdf", mime="application/pdf")
            
            except Exception as e:
                st.error("❌ Ocorreu um erro.")
                st.code(str(e))
    else:
        st.warning("⚠️ Envie ambos os arquivos PDF.")
