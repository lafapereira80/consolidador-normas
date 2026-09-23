import streamlit as st
import fitz  # PyMuPDF
import re
import os
import io
import base64
from typing import List, Dict, Optional

try:
    from streamlit_quill import st_quill
    HAS_QUILL = True
except ImportError:
    HAS_QUILL = False

try:
    from weasyprint import HTML
    HAS_WEASYPRINT = True
exceptPara garantir a separação correta e a fluidez dos parágrafos, o código abaixo ajusta o processamento para isolar cada quebra de linha em tags HTML independentes, evitando que o texto fique aglomerado. Os controles de alinhamento foram integrados diretamente à interface.

```python
import streamlit as st

# Configuração das opções de alinhamento
opcoes_alinhamento = {
    "Esquerda": "left",
    "Direita": "right",
    "Centralizado": "center",
    "Justificado": "justify"
}

st.subheader("Editor de Documentos")

# Controles do Editor
col1, col2 = st.columns([1, 3])
with col1:
    alinhamento_escolhido = st.selectbox(
        "Alinhamento do Texto",
        options=list(opcoes_alinhamento.keys()),
        index=3 # Define "Justificado" como padrão
    )

# Área de edição
texto_inserido = st.text_area("Insira o texto:", height=300)

# Lógica de reprodução aprimorada
if texto_inserido:
    st.markdown("---")
    st.markdown("### Visualização Formatada")
    
    alinhamento_css = opcoes_alinhamento[alinhamento_escolhido]
    
    # Divide o texto considerando as quebras de linha reais
    paragrafos = texto_inserido.split('\n')
    
    # Reconstrói o documento com fonte Times New Roman 11pt
    html_output = f"""
    <div style='
        text-align: {alinhamento_css}; 
        font-family: "Times New Roman", Times, serif; 
        font-size: 11pt; 
        line-height: 1.5;
    '>
    """
    
    for p in paragrafos:
        if p.strip(): # Ignora linhas totalmente vazias no HTML final
            html_output += f"<p style='margin-bottom: 12px;'>{p.strip()}</p>"
            
    html_output += "</div>"
    
    # Renderiza o resultado com as formatações aplicadas
    st.markdown(html_output, unsafe_allow_html=True)
