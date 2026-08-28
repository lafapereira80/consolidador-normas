import streamlit as st
import tempfile
import io
import json
import os
import re
import time
import copy
import hashlib
import base64
from html.parser import HTMLParser
from html import unescape
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional

from supabase import create_client, Client
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import fitz  # PyMuPDF
from auth_utils import gerar_hash_senha, verificar_senha
from streamlit_quill import st_quill

try:
    from groq import Groq
except ImportError:
    Groq = None
try:
    from mistralai import Mistral
except ImportError:
    try:
        from mistralai.client import Mistral
    except ImportError:
        Mistral = None
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ----------------- HUB MULTI-IA -----------------
PROVEDORES_IA = {
    "Google Gemini": {
        "motor": "gemini",
        "modelos": ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"],
        "secret": "GEMINI_API_KEY",
    },
    "Groq (Llama / GPT-OSS)": {
        "motor": "groq",
        "modelos": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"],
        "secret": "GROQ_API_KEY",
    },
    "OpenRouter (Qwen / DeepSeek / Llama)": {
        "motor": "openrouter",
        "modelos": ["deepseek/deepseek-v4-flash", "qwen/qwen3.5-plus", "meta-llama/llama-4-maverick"],
        "secret": "OPENROUTER_API_KEY",
    },
    "Mistral AI (Small / Nemo)": {
        "motor": "mistral",
        "modelos": ["mistral-small-latest", "open-mistral-nemo"],
        "secret": "MISTRAL_API_KEY",
    },
}

def submit_com_contexto(executor, fn, *args, **kwargs):
    ctx = get_script_run_ctx()
    def _wrapper(*a, **kw):
        if ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)
        return fn(*a, **kw)
    return executor.submit(_wrapper, *args, **kwargs)

def obter_chave_provedor(nome_provedor):
    cfg = PROVEDORES_IA[nome_provedor]
    try:
        return st.secrets[cfg["secret"]]
    except Exception:
        try:
            return st.secrets["api_keys"][cfg["secret"]]
        except Exception:
            return os.environ.get(cfg["secret"], "")

try:
    from weasyprint import HTML as WeasyHTML, CSS as WeasyCSS
    HAS_WEASYPRINT = True
except ImportError:
    HAS_WEASYPRINT = False

st.set_page_config(page_title="Autopilot Normativo", page_icon="⚖️", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    .block-container { padding-top: 2rem; }
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 30px 20px; border-radius: 12px; color: white; text-align: center;
        box-shadow: 0 8px 16px rgba(0,0,0,0.15); margin-bottom: 25px;
    }
    .main-header h1 { color: #00FF87; font-weight: 800; font-size: 2.8rem; margin-bottom: 10px; }
    .main-header p { font-size: 1.2rem; color: #f1f1f1; margin-bottom: 0; }
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def init_supabase() -> Optional[Client]:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception:
        return None

supabase = init_supabase()

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

def verificar_login(username, password):
    if not supabase:
        st.error("⚠️ Erro de conexão com o Banco de Dados.")
        return False
    try:
        res = supabase.table("usuarios").select("id, password_hash").eq("username", username).execute()
        if res.data and len(res.data) > 0:
            ok, precisa_migrar = verificar_senha(password, res.data[0]['password_hash'])
            if ok and precisa_migrar:
                try:
                    supabase.table("usuarios").update({"password_hash": gerar_hash_senha(password)}).eq("id", res.data[0]['id']).execute()
                except Exception:
                    pass
            return ok
    except Exception as e:
        st.error(f"Erro ao verificar credenciais: {e}")
    return False

if not st.session_state.autenticado:
    st.markdown("""
    <style>
        div[data-testid="stAppViewContainer"] { display: flex; align-items: center; }
        .st-key-login_card {
            max-width: 420px; margin: 4rem auto; padding: 1.5rem 2rem;
            background: #ffffff; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.12);
        }
        .login-title { text-align: center; color: #1e3c72; font-weight: 800; font-size: 1.8rem; margin-bottom: 0.3rem; }
        .login-subtitle { text-align: center; color: #666; margin-bottom: 1.5rem; }
    </style>
    """, unsafe_allow_html=True)

    _, col_login, _ = st.columns([1, 1.3, 1])
    with col_login:
        with st.container(border=True, key="login_card"):
            st.markdown('<div class="login-title">⚖️ Autopilot Normativo</div>', unsafe_allow_html=True)
            st.markdown('<div class="login-subtitle">Acesso Restrito ao Sistema</div>', unsafe_allow_html=True)
            with st.form("form_login"):
                usuario = st.text_input("Usuário")
                senha = st.text_input("Senha", type="password")
                btn_login = st.form_submit_button("Entrar", use_container_width=True)
                if btn_login:
                    if verificar_login(usuario, senha):
                        st.session_state.autenticado = True
                        st.rerun()
                    else:
                        st.error("❌ Usuário ou senha incorretos.")
    st.stop()

st.markdown("""
<div class="main-header">
    <h1>⚖️ Autopilot Normativo</h1>
    <p>Motor Híbrido OCR com Editor Visual e Aprendizado Contínuo</p>
</div>
""", unsafe_allow_html=True)

col_info, col_hist, col_usr, col_logout = st.columns([3, 1.5, 1.5, 1])
with col_info:
    st.info("💡 **Sistema Autenticado:** Proteção de dados ativa.")

hist_path = "pages/historico.py"
usr_path = "pages/usuarios.py"
if os.path.exists("pages"):
    for f in os.listdir("pages"):
        if "historico" in f.lower() and f.endswith(".py"): hist_path = f"pages/{f}"
        if "usuario" in f.lower() and f.endswith(".py"): usr_path = f"pages/{f}"

with col_hist:
    try:
        st.page_link(hist_path, label="🗄️ Histórico", icon="➡️")
    except:
        nome_pagina = hist_path.replace("pages/", "").replace(".py", "")
        st.markdown(f'<a href="{nome_pagina}" target="_top" style="display: block; text-align: center; background-color: #f0f2f6; border: 1px solid #d0d4dc; color: #31333F !important; padding: 0.5rem; border-radius: 0.5rem; text-decoration: none; font-weight: 500;">➡️ 🗄️ Histórico</a>', unsafe_allow_html=True)

with col_usr:
    try:
        st.page_link(usr_path, label="👥 Usuários", icon="➡️")
    except:
        nome_pagina = usr_path.replace("pages/", "").replace(".py", "")
        st.markdown(f'<a href="{nome_pagina}" target="_top" style="display: block; text-align: center; background-color: #f0f2f6; border: 1px solid #d0d4dc; color: #31333F !important; padding: 0.5rem; border-radius: 0.5rem; text-decoration: none; font-weight: 500;">➡️ 👥 Usuários</a>', unsafe_allow_html=True)

with col_logout:
    if st.button("Sair", type="secondary", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

st.markdown("---")

provedor_escolhido = st.selectbox("🧠 Motor de IA (Hub Multi-IA)", list(PROVEDORES_IA.keys()), key="provedor_ia_select")
fluxo_inteligente = st.checkbox("🧠 Usar novo fluxo inteligente (recomendado)", value=True,
                               help="Permite cadastrar atos individualmente e detectar automaticamente derivações.")
modo_processamento = st.radio("⚡ Modo de Processamento", ["Equilibrado", "Rápido", "Máxima Qualidade"], index=0, horizontal=True)
cfg_provedor = PROVEDORES_IA[provedor_escolhido]
api_key = obter_chave_provedor(provedor_escolhido)
if not api_key:
    api_key = st.text_input(f"Chave da API ({cfg_provedor['secret']} não encontrada)", type="password")
st.caption(f"Modelos: {' → '.join(cfg_provedor['modelos'])}")

st.markdown("### 📥 Upload de Arquivos Normativos")
st.caption("Aceita Leis, Decretos, Resoluções, Enunciados, Portarias e demais atos normativos, em PDF.")
arquivos_enviados = st.file_uploader("Arraste todos os documentos (PDF)", type=["pdf"], accept_multiple_files=True, key="uploader_lote")

# =====================================================================
# PARSER HTML / XML
# =====================================================================

class QuillParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paragraphs = []
        self.current_html = []
        self.stack = []

    def _close_all_tags(self):
        res = ""
        for tags in reversed(self.stack):
            for t in reversed(tags):
                tag_name = t.split()[0]
                res += f"</{tag_name}>"
        return res

    def _open_all_tags(self):
        res = ""
        for tags in self.stack:
            for t in tags:
                res += f"<{t}>"
        return res

    def _break_paragraph(self):
        if self.current_html:
            p_text = "".join(self.current_html) + self._close_all_tags()
            if re.sub(r'<[^>]+>', '', p_text).strip():
                self.paragraphs.append(p_text.strip())
        self.current_html = []
        if self.stack:
            self.current_html.append(self._open_all_tags())

    def handle_starttag(self, tag, attrs):
        if tag in ('p', 'br', 'div'):
            self._break_paragraph()
            return

        attrs_dict = dict(attrs)
        style = attrs_dict.get('style', '').lower().replace(' ', '')
        cls = attrs_dict.get('class', '').lower()
        cor = attrs_dict.get('color', '').lower()
        
        added_tags = []
        if tag in ('b', 'strong') or 'font-weight:bold' in style or 'font-weight:700' in style:
            added_tags.append("b")
        if tag in ('i', 'em') or 'font-style:italic' in style:
            added_tags.append("i")
        if tag in ('s', 'strike', 'del') or 'text-decoration:line-through' in style or 'ql-strike' in cls:
            added_tags.append("strike")
        if ('color:rgb(230' in style or 'color:red' in style or 'color:#e6' in style or 'color:#f00' in style or 'color:#ff0000' in style) or (tag == 'font' and attrs_dict.get('color') in ('red', '#f00', '#ff0000')):
            added_tags.append('font color="red"')
        
        if added_tags:
            for t in added_tags:
                self.current_html.append(f"<{t}>")
            self.stack.append(added_tags)
        else:
            self.stack.append([])

    def handle_endtag(self, tag):
        if tag in ('p', 'br', 'div'):
            return 
        if self.stack:
            tags_to_close = self.stack.pop()
            for t in reversed(tags_to_close):
                tag_name = t.split()[0]
                self.current_html.append(f"</{tag_name}>")

    def handle_startendtag(self, tag, attrs):
        if tag in ('br',):
            self._break_paragraph()

    def handle_data(self, data):
        if not data: return
        data = data.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\xa0', '&nbsp;')
        self.current_html.append(data)

    def get_paragraphs(self):
        self._break_paragraph()
        return self.paragraphs

def ia_para_editor(texto):
    if not texto: return ""
    # Corrigido: substitui quebras de linha reais por <br/>
    texto = re.sub(r'(\r\n|\r|\n)', '<br/>', texto)
    texto = texto.replace("<br/>", "</p><p>").replace("<br>", "</p><p>")
    if not texto.startswith("<p>"): texto = f"<p>{texto}</p>"
    texto = re.sub(r'<(strike|del)\b[^>]*>', '<s>', texto, flags=re.IGNORECASE)
    texto = re.sub(r'</(strike|del)>', '</s>', texto, flags=re.IGNORECASE)
    texto = re.sub(r'<font[^>]*color=[\'"]?(red|#f00|#ff0000|rgb\([^)]+\))[\'"]?[^>]*>', '<span style="color: rgb(230, 0, 0);">', texto, flags=re.IGNORECASE)
    texto = re.sub(r'</font>', '</span>', texto, flags=re.IGNORECASE)
    texto = re.sub(r'<b\b[^>]*>', '<strong>', texto, flags=re.IGNORECASE)
    texto = re.sub(r'</b>', '</strong>', texto, flags=re.IGNORECASE)
    texto = re.sub(r'<i\b[^>]*>', '<em>', texto, flags=re.IGNORECASE)
    texto = re.sub(r'</i>', '</em>', texto, flags=re.IGNORECASE)
    return texto.replace("<p></p>", "")

_QUILL_TOOLBAR = [
    ["bold", "italic", "underline", "strike"],
    [{"color": []}, {"background": []}],
    [{"list": "ordered"}, {"list": "bullet"}],
    ["clean"],
]

def editor_rico(value, key):
    try:
        return st_quill(value=value, html=True, toolbar=_QUILL_TOOLBAR, key=key)
    except Exception:
        st.caption("⚠️ Editor visual indisponível no momento — editando o HTML diretamente.")
        return st.text_area("HTML", value=value, key=f"{key}_fallback", label_visibility="collapsed", height=150)

def editor_para_pdf(texto):
    if not texto: return ""
    parser = QuillParser()
    try:
        parser.feed(texto)
        return "<br/>".join(parser.get_paragraphs())
    except Exception:
        texto_limpo = re.sub(r'</?(span|div|p|ul|li|ol)[^>]*>', '', texto, flags=re.IGNORECASE)
        return texto_limpo

# =====================================================================
# INSTRUÇÃO DA IA
# =====================================================================

SYSTEM_INSTRUCTION_LEGISTECNICA = """
Você é um Especialista Sênior em Técnica Legislativa do Poder Público brasileiro, apto a trabalhar com
QUALQUER espécie normativa: Leis, Decretos, Resoluções, Portarias, Enunciados, Instruções Normativas etc.
Nunca assuma que o documento é necessariamente uma Portaria. Regras obrigatórias:

1. FIDELIDADE ABSOLUTA: transcreva com exatidão o conteúdo de cada dispositivo, preservando formatação (<b>, <i>, quebras <br/>).
2. SEPARAÇÃO ESTRUTURAL OBRIGATÓRIA:
   - 'ementa': Resumo descritivo do objeto da norma.
   - 'preambulo': Autoridade expedidora e os Considerandos.
3. TABELAS: quando o dispositivo contiver uma tabela (identificada por marcadores [TABELA]...[/TABELA] no
   texto de origem), transcreva TODAS as linhas e colunas com fidelidade absoluta em 'tabela_alterada' e
   'tabela_consolidada' (uma lista de listas, uma sublista por linha, mantendo a ordem exata de colunas).
   NUNCA descreva a tabela em prosa, NUNCA a omita, e NUNCA resuma seu conteúdo — reproduza célula a célula,
   mesmo que a tabela seja grande. Se um ato alterador modifica um conteúdo e dentro desse conteúdo existe
   uma tabela (acrescenta, remove ou muda linhas/colunas) ela deve ser taxada, com  <strike><font color="red"> Célula </font></strike>, 'tabela_alterada' deve conter a tabela NOVA e COMPLETA (com todas as
   linhas, alteradas ou não), e o campo 'texto_pos_tabela_alterada' deve trazer a nota
   "(Nova redação dada pelo Art. <N> da <TIPO> Nº <NÚMERO>/<SIGLA>, <DATA>)" logo abaixo da tabela.
   'tabela_consolidada' sempre reflete a versão vigente (mais recente) da tabela, a nova redação no caso de alterada deve vir após a tabela ou texto, verifique o que vem por último e após isso que deve vir a nova redação.
4. CRITÉRIO RIGOROSO DE ALTERAÇÃO E REVOGAÇÃO — formato EXATO e obrigatório (siga rigorosamente a
   pontuação, os parênteses e a ordem abaixo; NUNCA misture os dois casos):

   a) DISPOSITIVO ALTERADO (nova redação) — na versão ALTERADA (`texto_principal_alterada`), escreva em
      DUAS LINHAS separadas por quebra de parágrafo dupla `<br/><br/>` (nunca concatenadas na mesma linha):

      Linha 1 — identificador + texto ANTIGO INTEGRAL riscado em vermelho, seguido IMEDIATAMENTE (fora do
      risco, na mesma linha) da nota "(Alterada pelo Art. <N> da <TIPO> Nº <NÚMERO>/<SIGLA>, <DATA>)":
        <strike><font color="red">X - texto antigo integral, incluindo tabelas ...</font></strike> (Alterada pelo Art. 8 da
        PORTARIA Nº 1/PGJCG, de 01 JUNHO DE 2026) ou o texto continua.
      <br/><br/>
      Linha 2 — repita o MESMO identificador + a NOVA redação vigente por extenso, sem riscar, seguida da
      nota "(Redação dada pelo Art. <N> da <TIPO> Nº <NÚMERO>/<SIGLA>, <DATA>).":
        X - texto novo integral... (Redação dada pelo Art. 8 da PORTARIA Nº 1/PGJCG, de 01 JUNHO DE 2026).

      Exemplo completo (copie exatamente este padrão, adaptando o conteúdo):
        <strike><font color="red">X - apresentar ao final do período de instrutoria "Relatório das
        Atividades desenvolvidas durante o processo de Instrutoria", conforme modelo padrão.</font></strike>
        (Alterada pelo Art. 8 da PORTARIA Nº 1/PGJCG, de 01 JUNHO DE 2026)<br/><br/>X - apresentar trimestralmente
        relatórios de atividade ao(à) instruendo(a), conforme modelo anexo; (Redação dada pelo Art. 8 da
        PORTARIA Nº 1/PGJCG, de 01 JUNHO DE 2026).

      Para dispositivos com tabela, siga as regras do item 6.

   b) DISPOSITIVO REVOGADO — na versão ALTERADA, UMA ÚNICA LINHA (NÃO repita/acrescente uma segunda linha):
      identificador + texto INTEGRAL riscado em vermelho, seguido IMEDIATAMENTE da nota
      "(Revogado pelo Art. <N> da <TIPO> Nº <NÚMERO>/<SIGLA>, <DATA>);":
        <strike><font color="red">X - apresentar ao final do período de instrutoria "Relatório das
        Atividades desenvolvidas durante o processo de Instrutoria", conforme modelo padrão.</font></strike>
        (Revogado pelo Art. 8 da PORTARIA Nº 1/PGJCG, de 01 JUNHO DE 2026);

      Na versão CONSOLIDADA do mesmo dispositivo, mostre APENAS o identificador + a nota de revogação,
      sem repetir o texto revogado:
        X - (Revogado pelo Art. 8 da PORTARIA Nº 1/PGJCG, de 01 JUNHO DE 2026).

   c) As notas "(Alterada pelo ...)", "(Redação dada pelo ...)" e "(Revogado pelo ...)" vão SEMPRE
      embutidas diretamente no texto de 'texto_principal_alterada'/'texto_principal_consolidada' (não em
      campo separado), citando o ARTIGO ESPECÍFICO do ato alterador que promoveu a mudança — nunca cite
      só o ato inteiro sem o artigo. Preencha também 'nota_remissiva' com o mesmo trecho da citação (sem
      parênteses), só para fins de indexação/auditoria — mas isso é redundante ao texto, não substitui.
   d) NUNCA deixe de taxar o dispositivo correto, e NUNCA junte texto antigo e novo na mesma linha sem a
      quebra de parágrafo dupla `<br/><br/>` entre eles, exceto no caso de revogação (que é uma única linha).
5. GENERALIDADE: as regras acima valem para qualquer espécie normativa (Lei, Decreto, Resolução, Portaria,
   Enunciado, Instrução Normativa etc.) e para qualquer tipo de dispositivo (Artigo, Parágrafo, Parágrafo
   Único, Inciso, Alínea, Item).

6. REGRAS ESPECÍFICAS PARA DISPOSITIVOS COM TABELA (is_tabela=True)
   Quando um dispositivo normativo contiver uma tabela (campo is_tabela=True) e for objeto de alteração
   por um ato modificador, siga rigorosamente as regras abaixo:

   6.1. Estrutura geral na versão ALTERADA:
   - O texto ANTIGO (riscado) fica no campo 'texto_principal_alterada', **sem a nota de alteração**.
   - A nota "(Alterada pelo Art. N da TIPO Nº NÚMERO/ANO - SIGLA)" DEVE ser colocada **no início do campo
     'texto_pos_tabela_alterada'**, logo após a tabela, antes de qualquer nova redação.
   - A tabela ALTERADA (com as células taxadas quando houver mudança) fica no campo 'tabela_alterada'.
   - A NOVA REDAÇÃO completa (texto novo, se houver, e a nota "(Redação dada pelo Art. N da TIPO Nº
     NÚMERO/ANO - SIGLA)") fica NO MESMO CAMPO 'texto_pos_tabela_alterada', logo após a nota de alteração,
     separada por um espaço ou quebra de linha, conforme necessário.
   - A ordem final no campo 'texto_pos_tabela_alterada' deve ser:
     "(Alterada pelo Art. ...) <br/> X - texto novo... (Redação dada pelo Art. ...)"
     ou, se não houver nova redação, apenas a nota de alteração.

   6.2. Casos específicos:
   a) Dispositivo com texto introdutório + tabela + texto final:
      - 'texto_principal_alterada': contém o texto antigo completo (introdução + referência à tabela +
        texto final) riscado, SEM a nota de alteração.
      - 'tabela_alterada': a tabela completa, com células taxadas se alteradas.
      - 'texto_pos_tabela_alterada': inicia com a nota "(Alterada pelo Art. ...)", seguida da NOVA redação
        do dispositivo inteiro (introdução nova, se aplicável, descrição da tabela, texto final novo) e da
        nota "(Redação dada pelo...)".
        Exemplo:
          texto_principal_alterada = "<strike><font color='red'>Art. 5º - O prazo para entrega é de 30 dias,
          conforme tabela abaixo:</font></strike>"
          tabela_alterada = [["Item", "Prazo"], ["Documento", "10 dias"], ["Relatório", "20 dias"]]
          texto_pos_tabela_alterada = "(Alterada pelo Art. 2 da PORTARIA Nº 5/PGJ, de 10 de maio de 2025)<br/>Art. 5º - O prazo para entrega é de 60 dias, conforme tabela abaixo: (Redação dada pelo Art. 2 da PORTARIA Nº 5/PGJ, de 10 de maio de 2025)"

   b) Dispositivo que contém APENAS a tabela (sem texto antes ou depois):
      - 'texto_principal_alterada': conterá apenas o identificador do dispositivo (ex.: "Art. 7º") riscado,
        sem a nota de alteração.
      - 'tabela_alterada': a tabela completa, com alterações taxadas.
      - 'texto_pos_tabela_alterada': inicia com a nota "(Alterada pelo...)", seguida da nova redação da
        tabela em forma de texto descritivo (caso a tabela tenha sido substituída por texto) ou apenas a
        nota se a tabela foi apenas modificada e não há texto adicional.
        Importante: se a tabela foi substituída por texto, descreva-a em texto_pos_tabela_alterada;
        caso contrário, deixe apenas a nota.

   c) Alteração que NÃO afeta a tabela, mas afeta o texto ao redor:
      - Nesse caso, o campo 'is_tabela' deve ser False se a tabela em si não faz parte da alteração.
        Ou seja, se a tabela permanece intacta e apenas o texto muda, trate como um dispositivo normal
        (is_tabela=False) e coloque a Linha 2 em 'texto_principal_alterada' normalmente.

   6.3. Versão CONSOLIDADA:
   - 'texto_principal_consolidada': deve conter a versão vigente do dispositivo (sem riscados).
     Se houver texto antes da tabela, ele deve estar aqui; se não, apenas o identificador.
   - 'tabela_consolidada': a tabela na versão vigente (sem taxações).
   - 'texto_pos_tabela_consolidada': se existir texto após a tabela na versão vigente, ele deve ser
     colocado aqui. Caso contrário, deixe vazio.
   - A nota "(Redação dada pelo...)" pode aparecer em 'texto_principal_consolidada' ou em
     'texto_pos_tabela_consolidada', conforme a posição natural do texto novo, mas nunca duplicada.

   6.4. A nota de redação deve sempre aparecer **fora** da tabela, nunca dentro de uma célula.

7. ANEXOS E CONTEÚDO PÓS-ASSINATURA:
   O documento pode conter ANEXOS e tabelas APÓS a assinatura. É OBRIGATÓRIO ler e transcrever TODO o
   conteúdo que aparecer após a assinatura, incluindo qualquer anexo (ex.: "ANEXO I", "ANEXO II") e suas
   respectivas tabelas. NÃO pare a leitura na assinatura. Se houver anexos, eles devem ser considerados
   como dispositivos (com tipo "Anexo") e suas tabelas incluídas normalmente.

8. REVOGAÇÃO INTEGRAL:
   Quando um ato alterador REVOGA integralmente outro ato, TODOS os dispositivos do ato revogado
   (artigos, parágrafos, incisos, anexos, tabelas) devem ser integralmente taxados na versão ALTERADA:
   - Cada dispositivo deve ter seu texto antigo inteiro riscado em vermelho com a nota
     "(Revogado pelo Art. <N> da <TIPO> Nº <NÚMERO>/<SIGLA>, <DATA>);".
   - Se o dispositivo contém tabela (is_tabela=True), a tabela deve ser integralmente taxada
     (todas as células com <strike><font color="red">) no campo 'tabela_alterada', e o texto antes/depois
     deve ser taxado normalmente no campo 'texto_principal_alterada'.
   - Na versão CONSOLIDADA, cada dispositivo deve conter APENAS a nota de revogação
     (ex.: "Art. X - (Revogado pelo Art. ...)"), sem reproduzir o texto revogado e sem tabela.
   - Se o ato revogado possui ANEXOS, cada anexo também deve ser tratado como dispositivo revogado,
     com todo o seu conteúdo taxado na versão alterada, e na consolidada apenas a nota de revogação.
   - NÃO omita nenhum dispositivo, anexo ou tabela nesse processo.
"""

# =====================================================================
# FUNÇÕES DE SCHEMA E CHAMADA DE IA (mantidas iguais)
# =====================================================================

# ... (todas as funções de _prompt_schema_json, _extrair_json_bruto, etc. permanecem as mesmas da última versão completa) ...

# =====================================================================
# EXTRAÇÃO DE PDF (mantida igual)
# =====================================================================

@st.cache_data(show_spinner=False, max_entries=20)
def extrair_conteudo_cache(file_bytes, nome_arquivo, dpi_ocr=1.5, max_paginas_ocr=None):
    return extrair_conteudo_multimodal(file_bytes, nome_arquivo, dpi_ocr, max_paginas_ocr)

def extrair_conteudo_multimodal(file_bytes, nome_arquivo, dpi_ocr=1.5, max_paginas_ocr=None):
    # ... (código completo já fornecido) ...
    pass

# =====================================================================
# ESTRUTURAS PYDANTIC
# =====================================================================

# ... (classes já definidas) ...

# =====================================================================
# FUNÇÕES DE BANCO DE DADOS
# =====================================================================

def salvar_ato_pendente(tipo_ref, numero_ref, nome_arquivo, texto_integra, estrutura_json=None):
    if not supabase:
        return False
    try:
        data = {
            "nome_arquivo_original": nome_arquivo,
            "texto_integra": texto_integra,
            "ato_base_referenciado_tipo": tipo_ref,
            "ato_base_referenciado_numero": numero_ref,
            "status": "pendente"
        }
        if estrutura_json:
            data["estrutura_json"] = estrutura_json
        supabase.table("atos_importados").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar pendência: {e}")
        return False

def verificar_pendencias_para_base(tipo_doc, numero_doc):
    if not supabase:
        return []
    try:
        res = supabase.table("atos_importados").select("*")\
            .eq("status", "pendente")\
            .eq("ato_base_referenciado_tipo", tipo_doc)\
            .eq("ato_base_referenciado_numero", numero_doc).execute()
        return res.data or []
    except:
        return []

def _localizar_base_no_banco(tipo_ref, numero_ref):
    if not supabase or not numero_ref or not str(numero_ref).strip():
        return None
    try:
        numero_limpo = str(numero_ref).strip()
        query = supabase.table("portarias_base").select("id, nome_padronizado, tipo_documento, numero_documento, documento_consolidado_json")
        res = query.ilike("numero_documento", f"%{numero_limpo}%").execute()
        candidatos = res.data or []
        if not candidatos and tipo_ref:
            res2 = query.ilike("nome_padronizado", f"%{numero_limpo}%").execute()
            candidatos = res2.data or []
        if not candidatos:
            return None
        if tipo_ref:
            for c in candidatos:
                if str(c.get('tipo_documento', '')).strip().lower() == str(tipo_ref).strip().lower():
                    return c
        return candidatos[0]
    except Exception:
        return None

def salvar_ato_integral(nome_arquivo, texto_integra, estrutura_json=None):
    if not supabase:
        return None
    try:
        data = {
            "nome_arquivo_original": nome_arquivo,
            "texto_integra": texto_integra,
            "status": "importado"
        }
        if estrutura_json:
            data["estrutura_json"] = estrutura_json
        res = supabase.table("atos_importados").insert(data).execute()
        if res.data:
            return res.data[0]['id']
        else:
            return None
    except Exception as e:
        st.error(f"Erro ao salvar ato: {e}")
        return None

def salvar_no_supabase(cons, cons_original):
    if not supabase: return False
    try:
        if cons_original:
            def _registrar(campo, original, editado):
                if original != editado and (original or editado):
                    try: supabase.table("memoria_de_correcoes").insert({"texto_ia": json.dumps(original) if not isinstance(original, str) else original, "texto_corrigido": json.dumps(editado) if not isinstance(editado, str) else editado}).execute()
                    except: pass

            _registrar("ementa", cons_original.get('ementa'), cons.get('ementa'))
            _registrar("preambulo", cons_original.get('preambulo'), cons.get('preambulo'))
            for j, disp_editado in enumerate(cons.get("dispositivos", [])):
                if j >= len(cons_original.get("dispositivos", [])): break
                disp_original = cons_original["dispositivos"][j]
                for campo in ["texto_principal_alterada", "texto_principal_consolidada", "tabela_alterada", "tabela_consolidada", "texto_pos_tabela_alterada", "texto_pos_tabela_consolidada", "nota_remissiva"]:
                    _registrar(campo, disp_original.get(campo), disp_editado.get(campo))
        
        base = cons['norma_base']
        alteradoras = cons.get('normas_alteradoras', [])
        data_base_iso = converter_para_iso(base.get('data_assinatura'))
        res_upsert = supabase.table("portarias_base").upsert({
            "tipo_documento": base['tipo_documento'], "numero_documento": base['numero_documento'],
            "orgao_emissor": base['orgao_emissor'], "data_assinatura": data_base_iso,
            "nome_padronizado": base['nome_padronizado'], "titulo_original": cons.get("titulo_portaria"),
            "orgaos_emissores": cons.get("orgaos_emissores"), "assinatura_nome": cons.get("assinatura_nome"),
            "assinatura_cargo": cons.get("assinatura_cargo"), "documento_consolidado_json": cons,
            "documento_alterado_json": cons,
        }, on_conflict="nome_padronizado").execute()
        if res_upsert.data:
            base_id = res_upsert.data[0]['id']
        else:
            base_id = supabase.table("portarias_base").select("id").eq("nome_padronizado", base['nome_padronizado']).execute().data[0]['id']

        # Inserir versões na nova tabela
        alteradoras_nomes = [alt['nome_padronizado'] for alt in alteradoras] if alteradoras else []
        descricao = f"{base['nome_padronizado']}" + (f" + {', '.join(alteradoras_nomes)}" if alteradoras_nomes else "")
        
        supabase.table("versoes_documentos").insert({
            "portaria_base_id": base_id,
            "tipo_versao": "alterada",
            "estado_json": cons,
            "alteradoras_aplicadas": alteradoras_nomes,
            "descricao": descricao
        }).execute()
        
        supabase.table("versoes_documentos").insert({
            "portaria_base_id": base_id,
            "tipo_versao": "consolidada",
            "estado_json": cons,
            "alteradoras_aplicadas": alteradoras_nomes,
            "descricao": descricao
        }).execute()

        for alt in alteradoras:
            res_alt = supabase.table("portarias_alteradoras").select("id").eq("portaria_base_id", base_id).eq("nome_padronizado", alt['nome_padronizado']).execute()
            if not res_alt.data:
                data_alt_iso = converter_para_iso(alt.get('data_assinatura'))
                supabase.table("portarias_alteradoras").insert({"portaria_base_id": base_id, "tipo_documento": alt['tipo_documento'], "numero_documento": alt['numero_documento'], "orgao_emissor": alt['orgao_emissor'], "data_assinatura": data_alt_iso, "nome_padronizado": alt['nome_padronizado'], "arquivo_nome_original": "Múltiplos Documentos"}).execute()
        return True
    except: return False

# =====================================================================
# ANÁLISE DE LOTE E PROCESSAMENTO
# =====================================================================

# ... (funções classificar_arquivo_unico, processar_derivacoes_arquivo_unico, analisar_lote_arquivos, _processar_cascata_grupo, _consultar_estado_e_historico) ...

# =====================================================================
# EXPORTAÇÃO
# =====================================================================

def gerar_html_dinamico(consolidacao_dict, tipo_versao):
    titulo_doc = f"Versão {'Alterada' if tipo_versao=='alterada' else 'Consolidada'}"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{titulo_doc}</title>
        <style>
            @page {{ size: A4; margin: 2.5cm 2cm; @bottom-center {{ content: "Nota: Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial."; font-size: 9pt; font-style: italic; color: #333; }} }}
            body {{ font-family: 'Times New Roman', Times, serif; font-size: 11pt; line-height: 1.5; text-align: justify; }}
            .topo {{ text-align: center; color: #444; font-size: 10pt; font-weight: bold; margin-bottom: 20px; text-transform: uppercase; }}
            .orgaos {{ text-align: center; font-weight: bold; margin-bottom: 25px; }}
            .titulo {{ text-align: center; font-weight: bold; margin-bottom: 20px; }}
            .ementa {{ text-align: justify; margin-left: 45%; margin-bottom: 25px; font-weight: normal; }}
            .preambulo {{ text-align: justify; margin-bottom: 12px; text-indent: 0; }}
            .dispositivo {{ text-align: justify; text-indent: 40px; margin-bottom: 12px; }}
            .capitulo {{ text-align: center; font-weight: bold; margin-top: 20px; margin-bottom: 12px; text-transform: uppercase; }}
            .assinatura {{ text-align: center; font-weight: bold; margin-top: 50px; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 15px; }}
            td, th {{ border: 1px solid black; padding: 6px; text-align: left; vertical-align: middle; }}
            strike, s, del {{ text-decoration: line-through; }}
            b, strong {{ font-weight: bold; }}
            i, em {{ font-style: italic; }}
            font[color="red"], span[style*="color: red"], span[style*="color:rgb(230"] {{ color: red !important; }}
        </style>
    </head>
    <body>
        <div class="topo">{titulo_doc}</div>
        <div class="orgaos">{limpar_texto_ia(consolidacao_dict.get("orgaos_emissores") or "").replace('<br/>', '<br>')}</div>
        <div class="titulo">{limpar_texto_ia(consolidacao_dict.get("titulo_portaria") or "").replace('<br/>', '<br>')}</div>
        <div class="ementa">{limpar_texto_ia(consolidacao_dict.get("ementa") or "").replace('<br/>', '<br>')}</div>
        <div class="preambulo">{limpar_texto_ia(consolidacao_dict.get("preambulo") or "").replace('<br/>', '<br>')}</div>
    """
    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva(item.get(f"texto_principal_{tipo_versao}"), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        if "capitulo" in t or "anexo" in t:
            html += f"<div class='capitulo'>{t_prin}</div>"
            if not item.get("is_tabela"):
                continue
        else:
            if t_prin:
                for p in t_prin.split("<br/>"):
                    if p.strip():
                        html += f"<div class='dispositivo'>{p.strip()}</div>"
        if item.get("is_tabela"):
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas:
                html += "<table>"
                for linha in linhas:
                    html += "<tr>"
                    for celula in linha: html += f"<td>{editor_para_pdf(celula)}</td>"
                    html += "</tr>"
                html += "</table>"
            t_pos = injetar_nota_remissiva(item.get(f"texto_pos_tabela_{tipo_versao}"), item.get("nota_remissiva"))
            if t_pos:
                for p in t_pos.split("<br/>"):
                    if p.strip():
                        html += f"<div class='dispositivo'>{p.strip()}</div>"
    html += f"<div class='assinatura'>{limpar_texto_ia(consolidacao_dict.get('assinatura_nome') or '')}<br>{limpar_texto_ia(consolidacao_dict.get('assinatura_cargo') or '')}</div>"
    html += "</body></html>"
    return html

def gerar_pdf_dinamico(consolidacao_dict, tipo_versao):
    html_str = gerar_html_dinamico(consolidacao_dict, tipo_versao)
    if not HAS_WEASYPRINT:
        raise Exception("WeasyPrint não está disponível.")
    buffer = io.BytesIO()
    WeasyHTML(string=html_str).write_pdf(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def aplicar_html_no_docx(p, texto_html):
    # ... (mantida igual) ...
    pass

def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
    # ... (mantida igual) ...
    pass

# =====================================================================
# FRONTEND
# =====================================================================

if "dados_processados" not in st.session_state: st.session_state.dados_processados = None
if "dados_originais_ia" not in st.session_state: st.session_state.dados_originais_ia = None
if "confirmacao_pendente" not in st.session_state: st.session_state.confirmacao_pendente = None
if "pendencia_salvar" not in st.session_state: st.session_state.pendencia_salvar = None
if "arquivo_unico_estrutura" not in st.session_state: st.session_state.arquivo_unico_estrutura = None
if "arquivo_unico_id" not in st.session_state: st.session_state.arquivo_unico_id = None
if "arquivo_unico_classificacao" not in st.session_state: st.session_state.arquivo_unico_classificacao = None

# ... (código do fluxo inteligente e fluxo antigo, já completo nas respostas anteriores) ...

# Certifique-se de que as funções não definidas aqui (ex: limpar_texto_ia, injetar_nota_remissiva, editor_para_pdf) estejam definidas acima.
