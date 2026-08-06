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

# Configuração da página web
st.set_page_config(page_title="Consolidador Dinâmico de Normas", layout="centered")

st.title("⚖️ Sistema Web Dinâmico de Consolidação Normativa")
st.write("Faça o upload da **Norma Original** e da **Norma Alteradora**. A IA fará a leitura, o cruzamento normativo e gerará os PDFs dinamicamente com fidelidade visual.")

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
    texto_alterada: str = Field(description="Obrigatório: Se alterado, TODO o dispositivo antigo (incluindo identificadores como Art., §) DEVE estar em <font color='red'><strike>...</strike></font>. Em seguida, insira <br/> para pular linha e adicione o texto novo. Adicione nota remissiva no final.")
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
    4. REGRA DO VERMELHO TACHADO: Para itens alterados, TODO o dispositivo antigo (incluindo identificadores lidos no documento como Art. 1º, Parágrafo único, § 1º) DEVE estar dentro de <font color='red'><strike>TEXTO ANTIGO</strike></font>. Insira a tag HTML <br/> para quebrar a linha, e inicie o texto novo completo abaixo.
       Exemplo obrigatório de formatação de alteração:
       <font color='red'><strike><b>Art. 1º</b> Texto antigo...</strike></font><br/><b>Art. 1º</b> Texto novo... (Alterado pela Portaria...)
    5. REGRA DE REVOGAÇÃO: Texto inteiro revogado deve ficar em <font color='red'><strike>TEXTO REVOGADO</strike></font> seguido de (Revogado pela...).
    6. NOTAS REMISSIVAS: Se um dispositivo foi alterado, revogado ou acrescentado, é OBRIGATÓRIO incluir a nota remissiva ao FINAL do texto do dispositivo.
    7. NEGRITOS E ITÁLICOS: Mantenha as palavras que estavam em negrito no original (ex: <b>Art. 1º</b>, <b>Parágrafo único.</b>).
    8. TABELAS: Defina `is_tabela` como true e extraia como matriz.
    9. LIMPEZA: Remova quebras de linha (Enters) artificiais do meio das frases.
    
    NORMA ORIGINAL:
    {texto_original}
    
    NORMA ALTERADORA:
    {texto_alterador}
    """
    
    response = client.models.generate_content(
        model='gemini-3.6-flash', # MUDANÇA APLICADA PARA EVITAR O ERRO DE COTA (429)
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ResultadoConsolidacao,
            temperature=0.0 
        ),
    )
    return json.loads(response.text)

def gerar_pdf_dinamico(dados_json, tipo_versao):
    """Gera o PDF com suporte a tabelas, fontes dinâmicas e rodapé de última página."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    story = []
    styles = getSampleStyleSheet()

    # Utilizando Helvetica que é o mapeamento nativo padrão para Arial em PDFs
    estilo_cabecalho_topo = ParagraphStyle('CabecalhoTopo', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=1, textColor=colors.HexColor('#444444'), spaceAfter=20)
    estilo_orgaos = ParagraphStyle('Orgaos', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=25)
    estilo_titulo = ParagraphStyle('TituloPortaria', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, spaceAfter=20)
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
            # Preserva os HTMLs gerados e limpa os Enters
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

    # 8. Nota de Rodapé Exclusiva da Última Página (Desenhada no final do fluxo)
    story.append(Spacer(1, 40))
    # Desenha a linha separadora
    d = Drawing(A4[0] - 144, 10)
    d.add(Line(0, 5, A4[0] - 144, 5, strokeColor=colors.black, strokeWidth=0.5))
    story.append(d)
    story.append(Spacer(1, 5))
    # Adiciona o texto da nota SEM a quebra forçada
    texto_rodape = "<b>Nota:</b> Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial."
    story.append(Paragraph(texto_rodape, estilo_rodape))

    # Constrói o PDF sem repetição de rodapé em todas as páginas
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# Interface do Botão
if st.button("🚀 Processar Dinamicamente com IA e Gerar PDFs", type="primary"):
    if not api_key:
        st.error("⚠️ Insira sua chave da API do Google GenAI.")
    elif pdf_original and pdf_alteradora:
        with st.spinner("Analisando documentos, extraindo assinaturas e aplicando regras de consolidação..."):
            try:
                texto_orig = extrair_texto_de_upload(pdf_original)
                texto_alt = extrair_texto_de_upload(pdf_alteradora)
                
                chave_limpa = api_key.strip()
                dados_estruturados = analisar_normas_com_gemini_dinamico(texto_orig, texto_alt, chave_limpa)
                
                pdf_alt_bytes = gerar_pdf_dinamico(dados_estruturados, "alterada")
                pdf_cons_bytes = gerar_pdf_dinamico(dados_estruturados, "consolidada")
                
                st.success("✨ Processamento dinâmico concluído com sucesso!")
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
