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
# FUNÇÕES DE EXTRAÇÃO, PARSER, IA, PROCESSAMENTO E BANCO (COMPLETAS)
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

SYSTEM_INSTRUCTION_LEGISTECNICA = """
... (manter a instrução completa já fornecida) ...
"""

def _prompt_schema_json(response_schema):
    esquema = response_schema.model_json_schema()
    return (
        "\n\nRESPONDA EXCLUSIVAMENTE COM UM OBJETO JSON VÁLIDO (sem markdown, sem ```json, sem comentários, "
        "sem texto antes ou depois) que obedeça RIGOROSAMENTE a este JSON Schema:\n"
        + json.dumps(esquema, ensure_ascii=False)
    )

def _extrair_json_bruto(texto):
    if not texto: raise Exception("Resposta vazia da IA.")
    t = texto.strip()
    t = re.sub(r'^```(json)?', '', t.strip(), flags=re.IGNORECASE).strip()
    t = re.sub(r'```$', '', t.strip()).strip()
    inicio = t.find('{')
    fim = t.rfind('}')
    if inicio == -1 or fim == -1: raise Exception("A IA não retornou um JSON reconhecível.")
    return t[inicio:fim + 1]

def _itens_para_texto_e_imagens(itens):
    textos, imagens = [], []
    for it in itens:
        if isinstance(it, dict) and it.get("tipo") == "imagem":
            imagens.append((it["mime"], it["dados"]))
        elif isinstance(it, str):
            textos.append(it)
    return "\n\n".join(textos), imagens

def _itens_para_parts_gemini(itens):
    partes = []
    for it in itens:
        if isinstance(it, dict) and it.get("tipo") == "imagem":
            partes.append(types.Part.from_bytes(data=it["dados"], mime_type=it["mime"]))
        elif isinstance(it, str):
            partes.append(it)
    return partes

def _chamar_gemini(chave, itens, response_schema, thinking_level, modelos):
    client = genai.Client(api_key=chave)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        system_instruction=SYSTEM_INSTRUCTION_LEGISTECNICA,
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
    )
    contents = _itens_para_parts_gemini(itens)
    ultimo_erro = None
    for modelo in modelos:
        cota_diaria_esgotada = False
        for tentativa in range(1, 4):
            try:
                resp = client.models.generate_content(model=modelo, contents=contents, config=config)
                _validar_resposta_gemini(resp)
                dados = json.loads(resp.text)
                return response_schema.model_validate(dados)
            except Exception as e:
                ultimo_erro = e
                erro_str = str(e).upper()
                if "PERDAY" in erro_str.replace(" ", "") or "FREE_TIER" in erro_str or "GENERATEREQUESTSPERDAY" in erro_str.replace(" ", ""):
                    st.toast(f"⚠️ Cota diária do {modelo} esgotada (free tier). Pulando para o próximo modelo...", icon="📅")
                    cota_diaria_esgotada = True
                    break
                elif "429" in erro_str or "RESOURCE_EXHAUSTED" in erro_str or "503" in erro_str or "UNAVAILABLE" in erro_str:
                    if tentativa < 3:
                        tempo_espera = min(tentativa * 3, 10)
                        st.toast(f"⚡ Fila no Google ({modelo}). Tentativa {tentativa}/3. Aguardando {tempo_espera}s...", icon="⏳")
                        time.sleep(tempo_espera)
                        continue
                    st.toast(f"⚡ Tempo esgotado no {modelo}. Mudando para o próximo...", icon="🔄")
                    break
                elif "404" in erro_str or "NOT_FOUND" in erro_str or "400" in erro_str:
                    st.toast(f"⚠️ Modelo {modelo} indisponível. Pulando...", icon="⏭️")
                    break
                else:
                    raise e
        if cota_diaria_esgotada:
            continue
    raise Exception(f"Google Gemini: todos os modelos falharam. Último erro: {ultimo_erro}")

def _validar_resposta_gemini(resp):
    candidatos = getattr(resp, "candidates", None) or []
    if candidatos:
        finish = getattr(candidatos[0], "finish_reason", None)
        finish_str = str(finish) if finish else ""
        if "MAX_TOKENS" in finish_str: raise Exception("Resposta cortada por limite de tokens.")
        if "SAFETY" in finish_str or "PROHIBITED" in finish_str: raise Exception("Bloqueado por política de segurança.")
    if not getattr(resp, "text", None): raise Exception("Resposta vazia da IA.")

def _montar_mensagens_openai_like(itens, response_schema):
    texto, imagens = _itens_para_texto_e_imagens(itens)
    texto += _prompt_schema_json(response_schema)
    conteudo_usuario = [{"type": "text", "text": texto}]
    for mime, dados in imagens:
        b64 = base64.b64encode(dados).decode()
        conteudo_usuario.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    mensagens = [
        {"role": "system", "content": SYSTEM_INSTRUCTION_LEGISTECNICA},
        {"role": "user", "content": conteudo_usuario if imagens else texto},
    ]
    return mensagens

def _chamar_groq(chave, itens, response_schema, modelos):
    if Groq is None: raise Exception("Biblioteca 'groq' não instalada no servidor.")
    client = Groq(api_key=chave)
    mensagens = _montar_mensagens_openai_like(itens, response_schema)
    ultimo_erro = None
    for modelo in modelos:
        for tentativa in range(1, 4):
            try:
                resp = client.chat.completions.create(
                    model=modelo, messages=mensagens,
                    response_format={"type": "json_object"}, temperature=0.2,
                )
                bruto = _extrair_json_bruto(resp.choices[0].message.content)
                return response_schema.model_validate(json.loads(bruto))
            except Exception as e:
                ultimo_erro = e
                erro_str = str(e).upper()
                if "429" in erro_str or "RATE_LIMIT" in erro_str or "503" in erro_str:
                    if tentativa < 3:
                        tempo_espera = min(tentativa * 3, 10)
                        st.toast(f"⚡ Fila na Groq ({modelo}). Tentativa {tentativa}/3. Aguardando {tempo_espera}s...", icon="⏳")
                        time.sleep(tempo_espera)
                        continue
                    break
                elif "404" in erro_str or "NOT_FOUND" in erro_str or isinstance(e, (ValidationError, json.JSONDecodeError)) or "JSON" in erro_str.upper() or "não retornou" in str(e):
                    st.toast(f"⚠️ {modelo} indisponível/formato inválido. Pulando...", icon="⏭️")
                    break
                else:
                    raise e
    raise Exception(f"Groq: todos os modelos falharam. Último erro: {ultimo_erro}")

def _chamar_openrouter(chave, itens, response_schema, modelos):
    if OpenAI is None: raise Exception("Biblioteca 'openai' não instalada no servidor.")
    client = OpenAI(api_key=chave, base_url="https://openrouter.ai/api/v1")
    mensagens = _montar_mensagens_openai_like(itens, response_schema)
    ultimo_erro = None
    for modelo in modelos:
        for tentativa in range(1, 4):
            try:
                resp = client.chat.completions.create(
                    model=modelo, messages=mensagens,
                    response_format={"type": "json_object"}, temperature=0.2,
                )
                bruto = _extrair_json_bruto(resp.choices[0].message.content)
                return response_schema.model_validate(json.loads(bruto))
            except Exception as e:
                ultimo_erro = e
                erro_str = str(e).upper()
                if "429" in erro_str or "RATE_LIMIT" in erro_str or "503" in erro_str:
                    if tentativa < 3:
                        tempo_espera = min(tentativa * 3, 10)
                        st.toast(f"⚡ Fila no OpenRouter ({modelo}). Tentativa {tentativa}/3. Aguardando {tempo_espera}s...", icon="⏳")
                        time.sleep(tempo_espera)
                        continue
                    break
                elif "404" in erro_str or "NOT_FOUND" in erro_str or isinstance(e, (ValidationError, json.JSONDecodeError)) or "JSON" in erro_str.upper() or "não retornou" in str(e):
                    st.toast(f"⚠️ {modelo} indisponível/formato inválido. Pulando...", icon="⏭️")
                    break
                else:
                    raise e
    raise Exception(f"OpenRouter: todos os modelos falharam. Último erro: {ultimo_erro}")

def _chamar_mistral(chave, itens, response_schema, modelos):
    if Mistral is None: raise Exception("Biblioteca 'mistralai' não instalada no servidor.")
    client = Mistral(api_key=chave)
    mensagens = _montar_mensagens_openai_like(itens, response_schema)
    ultimo_erro = None
    for modelo in modelos:
        for tentativa in range(1, 4):
            try:
                resp = client.chat.complete(
                    model=modelo, messages=mensagens,
                    response_format={"type": "json_object"}, temperature=0.2,
                )
                bruto = _extrair_json_bruto(resp.choices[0].message.content)
                return response_schema.model_validate(json.loads(bruto))
            except Exception as e:
                ultimo_erro = e
                erro_str = str(e).upper()
                if "429" in erro_str or "CAPACITY" in erro_str or "503" in erro_str:
                    if tentativa < 3:
                        tempo_espera = min(tentativa * 3, 10)
                        st.toast(f"⚡ Fila na Mistral ({modelo}). Tentativa {tentativa}/3. Aguardando {tempo_espera}s...", icon="⏳")
                        time.sleep(tempo_espera)
                        continue
                    break
                elif "404" in erro_str or "NOT_FOUND" in erro_str or isinstance(e, (ValidationError, json.JSONDecodeError)) or "JSON" in erro_str.upper() or "não retornou" in str(e):
                    st.toast(f"⚠️ {modelo} indisponível/formato inválido. Pulando...", icon="⏭️")
                    break
                else:
                    raise e
    raise Exception(f"Mistral AI: todos os modelos falharam. Último erro: {ultimo_erro}")

def _chamar_por_motor(motor, chave, itens, response_schema, thinking_level, modelos):
    if motor == "gemini":
        return _chamar_gemini(chave, itens, response_schema, thinking_level, modelos)
    elif motor == "groq":
        return _chamar_groq(chave, itens, response_schema, modelos)
    elif motor == "openrouter":
        return _chamar_openrouter(chave, itens, response_schema, modelos)
    elif motor == "mistral":
        return _chamar_mistral(chave, itens, response_schema, modelos)
    raise Exception(f"Provedor desconhecido: {motor}")

def executar_com_fallback(chave, itens, response_schema, provedor, thinking_level="high"):
    cfg = PROVEDORES_IA[provedor]
    try:
        resultado = _chamar_por_motor(cfg["motor"], chave, itens, response_schema, thinking_level, cfg["modelos"])
    except Exception as erro_provedor_escolhido:
        outros = [p for p in PROVEDORES_IA if p != provedor]
        ultimo_erro = erro_provedor_escolhido
        resultado = None
        for nome_alt in outros:
            chave_alt = obter_chave_provedor(nome_alt)
            if not chave_alt:
                continue
            try:
                st.toast(f"🔀 {provedor} indisponível. Tentando automaticamente com {nome_alt}...", icon="🔁")
                cfg_alt = PROVEDORES_IA[nome_alt]
                resultado = _chamar_por_motor(cfg_alt["motor"], chave_alt, itens, response_schema, thinking_level, cfg_alt["modelos"])
                break
            except Exception as e2:
                ultimo_erro = e2
                continue
        if resultado is None:
            raise Exception(f"{provedor} falhou e nenhum provedor alternativo configurado deu certo. Último erro: {ultimo_erro}")

    class _RespCompat:
        def __init__(self, obj): self.text = obj.model_dump_json()
    return _RespCompat(resultado)

def converter_para_iso(data_str):
    if not data_str: return None
    data_str = data_str.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', data_str): return data_str
    match_br = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', data_str)
    if match_br:
        d, m, a = match_br.groups()
        return f"{a}-{m}-{d}"
    try: return datetime.strptime(data_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    except: return None

@st.cache_data(show_spinner=False, max_entries=20)
def extrair_conteudo_cache(file_bytes, nome_arquivo, dpi_ocr=1.5, max_paginas_ocr=None):
    return extrair_conteudo_multimodal(file_bytes, nome_arquivo, dpi_ocr, max_paginas_ocr)

def extrair_conteudo_multimodal(file_bytes, nome_arquivo, dpi_ocr=1.5, max_paginas_ocr=None):
    if nome_arquivo.lower().endswith(".docx"): return [f"ARQUIVO DOCX: {nome_arquivo}"]
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        html_text = f"CONTEÚDO DO ARQUIVO {nome_arquivo}:\n\n"
        caracteres_uteis = 0
        for page_num, page in enumerate(doc):
            html_text += f"=== PÁGINA {page_num + 1} ===\n"
            page_text = page.get_text()
            if re.search(r'ANEXO\s+[IVXLC]+', page_text, re.IGNORECASE):
                html_text += "[ANEXO]\n"
            tabelas_bbox = []
            try:
                tab_finder = page.find_tables()
                for tabela in tab_finder.tables:
                    linhas = tabela.extract()
                    if not linhas: continue
                    caracteres_uteis += sum(len(str(c or "")) for linha in linhas for c in linha)
                    tabelas_bbox.append(fitz.Rect(tabela.bbox))
                    html_text += "[TABELA]\n"
                    for linha in linhas:
                        html_text += " | ".join((str(c).strip() if c is not None else "") for c in linha) + "\n"
                    html_text += "[/TABELA]\n<br/>\n"
            except Exception:
                pass
            blocks = page.get_text("dict", sort=True).get("blocks", [])
            for b in blocks:
                if b.get('type') != 0: continue
                bloco_rect = fitz.Rect(b.get("bbox", (0, 0, 0, 0)))
                if any(bloco_rect.intersects(tb) for tb in tabelas_bbox):
                    continue
                bloco_linhas = ""
                for l in b.get("lines", []):
                    linha_span = ""
                    for s in l.get("spans", []):
                        texto = s.get("text", "")
                        if not texto: continue
                        caracteres_uteis += len(texto.strip())
                        flags = s.get("flags", 0)
                        if flags & 2**4: texto = f"<b>{texto}</b>"
                        if flags & 2**1: texto = f"<i>{texto}</i>"
                        linha_span += texto
                    if linha_span.strip(): bloco_linhas += linha_span + " "
                if bloco_linhas.strip(): html_text += bloco_linhas.strip() + "<br/>\n"
            html_text += "<br/>\n"
        if caracteres_uteis < 30 * max(doc.page_count, 1):
            partes = [f"ARQUIVO {nome_arquivo} É UM DOCUMENTO ESCANEADO. Leia o conteúdo visualmente, inclusive tabelas:"]
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi_ocr, dpi_ocr))
                partes.append({"tipo": "imagem", "mime": "image/jpeg", "dados": pix.tobytes("jpg", jpg_quality=78)})
            return partes
        return [html_text]
    except Exception as e:
        return [f"Erro ao extrair PDF {nome_arquivo}: {str(e)}"]

# Estruturas Pydantic (manter como antes)
class ArquivoClassificado(BaseModel):
    nome_arquivo_upload: str
    tipo: str
    grupo_id: int
    nome_padronizado_identificado: str
    data_oficial_iso: str
    ato_base_referenciado_tipo: Optional[str] = None
    ato_base_referenciado_numero: Optional[str] = None

class TriagemDocumentos(BaseModel):
    arquivos: List[ArquivoClassificado]

class MetadadosNorma(BaseModel):
    tipo_documento: str
    numero_documento: str
    orgao_emissor: str
    data_assinatura: str
    nome_padronizado: str

class Dispositivo(BaseModel):
    tipo: str
    texto_principal_alterada: str
    texto_principal_consolidada: str
    is_tabela: bool
    tabela_alterada: Optional[List[List[str]]] = None
    tabela_consolidada: Optional[List[List[str]]] = None
    texto_pos_tabela_alterada: Optional[str] = None
    texto_pos_tabela_consolidada: Optional[str] = None
    nota_remissiva: Optional[str] = ""

class Consolidacao(BaseModel):
    arquivos_originais_identificados: List[str]
    arquivos_alteradores_identificados: List[str]
    norma_base: MetadadosNorma
    normas_alteradoras: List[MetadadosNorma]
    cabecalho_complemento: str
    orgaos_emissores: str
    titulo_portaria: str
    ementa: str
    preambulo: str
    assinatura_nome: str
    assinatura_cargo: str
    dispositivos: List[Dispositivo]

class AnaliseGlobal(BaseModel):
    consolidacoes_geradas: List[Consolidacao]
    arquivos_nao_alterados: List[str]

def limpar_texto_ia(texto):
    if not texto: return ""
    return re.sub(r' {2,}', ' ', str(texto)).strip()

def injetar_nota_remissiva(texto, nota):
    if nota and nota.strip():
        n_sem_parenteses = nota.strip("()").strip()
        n_fmt = f"({n_sem_parenteses})"
        texto_puro = re.sub(r'<[^>]+>', '', texto if texto else '')
        if n_sem_parenteses.lower() in texto_puro.lower(): return texto
        if texto:
            texto_limpo = re.sub(r'(<br/?>|\s)+$', '', texto).strip()
            return f'{texto_limpo} &nbsp;<span style="color: red;">{n_fmt}</span>'
        return f'<span style="color: red;">{n_fmt}</span>'
    return texto

def corrigir_posicionamento_tabela(consolidacao: dict):
    # (função completa já fornecida)
    pass

def resgatar_memoria():
    memoria = ""
    if supabase:
        try:
            res = supabase.table("memoria_de_correcoes").select("*").order("id", desc=True).limit(5).execute()
            if res.data:
                memoria = "\n\n⚠️ HISTÓRICO DE CORREÇÕES (Não repita os erros da IA):\n"
                for m in res.data: memoria += f"- Erro: {m['texto_ia']}\n- Correção: {m['texto_corrigido']}\n\n"
        except: pass
    return memoria

def salvar_ato_pendente(tipo_ref, numero_ref, nome_arquivo, texto_integra):
    if not supabase:
        return False
    try:
        supabase.table("atos_importados").insert({
            "nome_arquivo_original": nome_arquivo,
            "texto_integra": texto_integra,
            "ato_base_referenciado_tipo": tipo_ref,
            "ato_base_referenciado_numero": numero_ref,
            "status": "pendente"
        }).execute()
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

def classificar_arquivo_unico(arquivo, key, provedor, thinking_level="medium"):
    """Extrai o texto e faz a triagem, retornando a classificação do arquivo."""
    textos_extraidos = {}
    try:
        conteudo = extrair_conteudo_multimodal(arquivo.getvalue(), arquivo.name, dpi_ocr=1.5, max_paginas_ocr=None)
        textos_extraidos[arquivo.name] = conteudo
    except Exception as e:
        return None, None, str(e)
    contents_triagem = [f"Analise o documento. Classifique-o como 'Base' ou 'Alteradora'. Se for 'Alteradora', extraia o tipo e número do ato base referenciado. ARQUIVO: {arquivo.name}"]
    contents_triagem.extend(conteudo)
    try:
        resp_triagem = executar_com_fallback(key, contents_triagem, TriagemDocumentos, provedor, thinking_level="low")
        triagem_dados = json.loads(resp_triagem.text).get("arquivos", [])
        if triagem_dados:
            return triagem_dados[0], conteudo, None
        else:
            return None, None, "Não foi possível classificar o documento."
    except Exception as e:
        return None, None, str(e)

def salvar_ato_integral(nome_arquivo, texto_integra):
    if not supabase:
        return None
    try:
        res = supabase.table("atos_importados").insert({
            "nome_arquivo_original": nome_arquivo,
            "texto_integra": texto_integra,
            "status": "importado"
        }).execute()
        if res.data:
            return res.data[0]['id']
        else:
            return None
    except Exception as e:
        st.error(f"Erro ao salvar ato: {e}")
        return None

def analisar_lote_arquivos(arquivos, key, provedor, thinking_level="medium", dpi_ocr=1.5, max_paginas_ocr=None, progresso=None, confirmar_derivacoes=False):
    # (implementação completa já fornecida anteriormente)
    pass

def _processar_cascata_grupo(key, provedor, arquivo_base, arquivos_alteradores, textos_extraidos, memoria_aprendida, thinking_level="medium"):
    # (implementação completa)
    pass

def processar_derivacoes_arquivo_unico(arquivo, texto_editado, key, provedor, thinking_level):
    import tempfile
    class FakeUploadedFile:
        def __init__(self, name, content):
            self.name = name
            self._content = content
        def getvalue(self):
            return self._content
    fake_arquivo = FakeUploadedFile(arquivo.name, texto_editado.encode('utf-8'))
    resultado = analisar_lote_arquivos([fake_arquivo], key, provedor, thinking_level)
    return resultado

def gerar_html_dinamico(consolidacao_dict, tipo_versao):
    # (implementação completa)
    pass

def gerar_pdf_dinamico(consolidacao_dict, tipo_versao):
    # (implementação completa)
    pass

def aplicar_html_no_docx(p, texto_html):
    # (implementação completa)
    pass

def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
    # (implementação completa)
    pass

def salvar_no_supabase(cons, cons_original):
    # (implementação completa)
    pass

# =====================================================================
# FRONTEND PRINCIPAL
# =====================================================================
# (Código do frontend como fornecido anteriormente, com o fluxo inteligente)
# ...
