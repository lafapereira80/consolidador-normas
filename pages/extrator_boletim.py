import streamlit as st
import pdfplumber
import re
import io
from fpdf import FPDF

# Configuração da página
st.set_page_config(page_title="Extrator de Boletim", page_icon="✂️", layout="wide")

class PDFNormativo(FPDF):
    def __init__(self):
        # Inicializando em pontos (pt) para controle exato das medidas
        super().__init__(unit='pt', format='A4')
        self.set_margins(left=50, top=50, right=50)
        self.add_page()
        
    def header(self):
        # Inserção do Brasão centralizado (60x60 pt)
        largura_pagina = self.w
        posicao_x_brasao = (largura_pagina - 60) / 2
        
        try:
            self.image('brasao.png', x=posicao_x_brasao, y=40, w=60, h=60)
        except FileNotFoundError:
            # Caso a imagem não seja encontrada, deixa o espaço correspondente
            self.set_xy(posicao_x_brasao, 40)
            self.cell(60, 60, border=1)
            
        self.set_y(110)
        
        # Linha divisória horizontal superior
        self.set_line_width(1)
        self.line(50, self.get_y(), largura_pagina - 50, self.get_y())
        self.ln(15)

    def footer(self):
        # Rodapé estruturado de consulta a 50 pt do fundo
        self.set_y(-50)
        
        # Linha divisória horizontal inferior
        largura_pagina = self.w
        self.set_line_width(1)
        self.line(50, self.get_y(), largura_pagina - 50, self.get_y())
        self.ln(10)
        
        # Texto do rodapé de consulta
        self.set_font('Times', 'I', 9)
        texto_rodape = "Este texto não substitui o publicado no Boletim de Serviço ou Diário Oficial correspondente."
        self.cell(0, 10, texto_rodape, align='C')

def extrair_texto_pdf(arquivo_upload):
    texto_completo = ""
    with pdfplumber.open(arquivo_upload) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if texto:
                texto_completo += texto + "\n"
    return texto_completo

def identificar_atos(texto):
    # Regex básica para encontrar Portarias e Resoluções. 
    # Pode ser ajustada conforme a numeração e formatação específica do órgão.
    padrao = r'(PORTARIA|RESOLUÇÃO)\s+(PGJM\s+)?N[º°]?\s*\d+.*?([.?!](?=\s+(PORTARIA|RESOLUÇÃO|$)))'
    
    # Flags: DOTALL para o ponto casar com quebras de linha e IGNORECASE
    matches = re.finditer(padrao, texto, re.DOTALL | re.IGNORECASE)
    
    atos = []
    for match in matches:
        ato_texto = match.group(0).strip()
        # Pega a primeira linha como título
        titulo = ato_texto.split('\n')[0][:100] 
        atos.append({"titulo": titulo, "conteudo": ato_texto})
        
    return atos

def gerar_pdf_ato(ato_texto):
    pdf = PDFNormativo()
    
    # Definindo a fonte padrão do documento
    pdf.set_font('Times', '', 11)
    
    # Tratamento do texto para o FPDF (lidando com caracteres especiais)
    # Recomenda-se utilizar uma fonte TTF externa caso haja problemas de enconding complexos
    conteudo_limpo = ato_texto.encode('latin-1', 'replace').decode('latin-1')
    
    pdf.multi_cell(0, 15, conteudo_limpo, align='J')
    
    # Retorna o PDF como bytes
    return pdf.output(dest='S').encode('latin-1')

# --- Interface Streamlit ---

st.title("Extração e Geração de Atos do Boletim")

st.markdown("""
Faça o upload do Boletim de Serviço (PDF). O sistema tentará identificar e separar 
automaticamente os atos normativos presentes no documento.
""")

arquivo_boletim = st.file_uploader("Selecione o Boletim de Serviço (PDF)", type=["pdf"])

if arquivo_boletim is not None:
    with st.spinner("Lendo e extraindo texto do Boletim..."):
        texto_boletim = extrair_texto_pdf(arquivo_boletim)
        
    atos_encontrados = identificar_atos(texto_boletim)
    
    if not atos_encontrados:
        st.warning("Não foram encontrados atos normativos com o padrão esperado neste documento.")
        with st.expander("Ver texto extraído para depuração"):
            st.text(texto_boletim)
    else:
        st.success(f"Foram encontrados {len(atos_encontrados)} possíveis atos normativos.")
        
        st.write("### Selecione os atos para exportar")
        
        for i, ato in enumerate(atos_encontrados):
            with st.expander(f"Ato {i+1}: {ato['titulo']}"):
                st.text_area("Conteúdo", ato['conteudo'], height=200, key=f"texto_{i}")
                
                # Botão de download individual
                pdf_bytes = gerar_pdf_ato(ato['conteudo'])
                st.download_button(
                    label="Baixar Ato Formato PDF",
                    data=pdf_bytes,
                    file_name=f"Ato_{i+1}.pdf",
                    mime="application/pdf",
                    key=f"btn_{i}"
                )
