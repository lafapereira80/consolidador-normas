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
st.write("Faça o upload da **Portaria Original** e da **Portaria Alteradora**. A IA fará a leitura, o cruzamento normativo e gerará os PDFs dinamicamente com fidelidade rigorosa.")

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

# Estrutura Pydantic com Regras Rígidas
class Dispositivo(BaseModel):
    tipo: str = Field(description="Ex: 'capitulo', 'artigo', 'paragrafo', ou 'tabela'")
    texto_alterada: str = Field(description="Texto com redação antiga tachada em HTML (<font color='red'><strike>...</strike></font>) e a nova redação. Use <b> APENAS no identificador do artigo (ex: <b>Art. 1º</b>). O texto principal não pode ser negrito. DEVE incluir a nota remissiva ao final, ex: (Alterado pela Portaria...).")
    texto_consolidado: str = Field(description="Texto limpo e atualizado. Use <b> APENAS no identificador do artigo (ex: <b>Art. 1º</b>). O texto principal não pode ser negrito. DEVE incluir a nota remissiva ao final, ex: (Alterado pela Portaria...).")
    is_tabela: bool = Field(description="Verdadeiro (true) SE o conteúdo for um quadro ou tabela.")
    tabela_linhas_alterada: Optional[List[List[str]]] = Field(default=None, description="Matriz de dados da tabela (Versão Alterada).")
    tabela_linhas_consolidada: Optional[List[List[str]]] = Field(default=None, description="Matriz de dados da tabela (Versão Consolidada).")

class ResultadoConsolidacao(BaseModel):
    titulo_portaria: str = Field(description="Apenas o nome e data da Portaria Original. Ex: 'Portaria nº 130/PGJM, de 28 de junho de 2022.'")
    ementa_preambulo: str = Field(description="O preâmbulo original completo. OBRIGATÓRIO: Coloque a tag <b> apenas nas palavras-chave PROCURADOR-GERAL DE JUSTIÇA MILITAR, CONSIDERANDO e RESOLVE.")
    dispositivos: List[Dispositivo] = Field(description="Lista sequencial estruturada de toda a norma.")

def analisar_normas_com_gemini_dinamico(texto_original, texto_alterador, key):
    """Solicita ao Gemini a extração rigorosa com comandos visuais e de inserção de notas remissivas."""
    client = genai.Client(api_key=key)
    prompt = f"""
    Atue como um especialista em técnica legislativa do Ministério Público Militar.
    Analise a Portaria Original e a Portaria Alteradora abaixo e gere o JSON da consolidação.
    
    REGRAS RÍGIDAS DE FORMATAÇÃO (OBRIGATÓRIO LER E CUMPRIR):
    1. PROIBIDO LaTeX: NUNCA use cifrões ou notações matemáticas (como $5^{{\circ}}$). Use textualmente "1º", "2º", "5º", "§", etc.
    2. REGRA DO NEGRITO EM ARTIGOS: NUNCA coloque todo o texto de um artigo acrescentado ou alterado em negrito. Aplique a tag <b> APENAS no identificador do dispositivo. Exemplo CORRETO: "<b>Art. 1º</b> O texto começa aqui sem negrito...".
    3. NOTAS REMISSIVAS (OBRIGATÓRIO): Se um artigo, parágrafo ou inciso foi alterado, revogado ou acrescentado, você DEVE extrair a informação da portaria alteradora e escrever a nota remissiva no FINAL do texto do respectivo dispositivo (tanto na versão alterada quanto consolidada). Exemplo: "O texto do dispositivo termina aqui. (Alterado pelo art. 1º da Portaria nº 103/PGJM, de 21/05/2026)"
    4. TABELAS: Se houver lista de Lotação/Servidor, extraia em matriz ativando 'is_tabela'. A primeira lista deve ser o cabeçalho.
    
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
            temperature=0.0
        ),
    )
    return json.loads(response.text)

def desenhar_cabecalho_rodape(canvas, doc):
    """Adiciona o rodapé padrão institucional com linha separadora e quebra de texto, utilizando Helvetica (padrão PDF para Arial)."""
    canvas.saveState()
    
    # Desenha a linha separadora acima do rodapé
    canvas.setLineWidth(0.5)
    canvas.setStrokeColor(colors.black)
    canvas.line(72, 65, A4[0] - 72, 65)
    
    # Configuração do Parágrafo do Rodapé (Para alinhar e quebrar o texto igual à imagem alvo)
    estilo_rodape = ParagraphStyle('Rodape', fontName='Helvetica-Oblique', fontSize=9, leading=12, alignment=0)
    texto_rodape = "<b>Nota:</b> Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado<br/>no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial."
    
    p = Paragraph(texto_rodape, estilo_rodape)
    w, h = p.wrap(A4[0] - 144, 50)
    p.drawOn(canvas, 72, 60 - h)
    
    canvas.restoreState()

def gerar_pdf_dinamico(dados_json, tipo_versao):
    """Gera o PDF com suporte a tabelas limpas, fontes Helvetica rigorosas e renderização HTML."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=90)
    story = []
    styles = getSampleStyleSheet()

    # Criação de estilos usando apenas Helvetica (padrão equivalente Arial no ReportLab interno)
    estilo_orgaos = ParagraphStyle('Orgaos', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=25)
    estilo_titulo = ParagraphStyle('TituloPortaria', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=20)
    estilo_dispositivo = ParagraphStyle('Dispositivo', parent=styles['Normal'], fontName='Helvetica', fontSize=11, leading=15, alignment=4, firstLineIndent=30, spaceAfter=12)
    estilo_celula = ParagraphStyle('Celula', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=12, alignment=0)
    estilo_capitulo = ParagraphStyle('Capitulo', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=14, alignment=1, spaceBefore=20, spaceAfter=12, textTransform='uppercase')
    estilo_assinatura = ParagraphStyle('Assinatura', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=15, alignment=1, spaceBefore=50, spaceAfter=20)

    # 1. Título do Topo ("VERSÃO ALTERADA...") foi removido do código.

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

    # 3. Órgãos Emissores
    story.append(Paragraph("MINISTÉRIO PÚBLICO DA UNIÃO<br/>MINISTÉRIO PÚBLICO MILITAR<br/>PROCURADORIA-GERAL DE JUSTIÇA MILITAR", estilo_orgaos))

    # 4. Título da Portaria
    titulo_texto = dados_json.get("titulo_portaria", "Portaria Normativa").replace("<br>", "<br/>").replace("\n", "<br/>")
    story.append(Paragraph(titulo_texto, estilo_titulo))

    # 5. Preâmbulo 
    preambulo_texto = dados_json.get("ementa_preambulo", "").replace("<br>", "<br/>").replace("\n", "<br/>")
    story.append(Paragraph(preambulo_texto, estilo_dispositivo))

    # 6. Inserção Dinâmica (Texto e TABELAS LIMPAS)
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
                        cel_texto = celula.replace('\n', '<br/>').replace('<br>', '<br/>')
                        linha_processada.append(Paragraph(cel_texto, estilo_celula))
                    tabela_processada.append(linha_processada)
                
                # Tabela Padrão (Sem bordas fechadas, apenas linha de cabeçalho, alinhada à esquerda)
                t = Table(tabela_processada, colWidths='*')
                t.setStyle(TableStyle([
                    ('TEXTCOLOR', (0,0), (-1,-1), colors.black),
                    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('LINEBELOW', (0,0), (-1,0), 0.5, colors.black), # Apenas uma linha fina sob o cabeçalho
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                ]))
                story.append(t)
                story.append(Spacer(1, 15))
            else:
                fallback = item.get(f"texto_{tipo_versao}", "")
                story.append(Paragraph(fallback.replace('\n', '<br/>'), estilo_dispositivo))
                
        else:
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
        with st.spinner("Lendo PDFs e aplicando regras rigorosas de formatação e notas remissivas..."):
            try:
                texto_orig = extrair_texto_de_upload(pdf_original)
                texto_alt = extrair_texto_de_upload(pdf_alteradora)
                
                chave_limpa = api_key.strip()
                dados_estruturados = analisar_normas_com_gemini_dinamico(texto_orig, texto_alt, chave_limpa)
                
                pdf_alt_bytes = gerar_pdf_dinamico(dados_estruturados, "alterada")
                pdf_cons_bytes = gerar_pdf_dinamico(dados_estruturados, "consolidada")
                
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
