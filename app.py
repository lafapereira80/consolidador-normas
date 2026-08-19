import streamlit as st
import tempfile
import io
import json
import os
import re
import time
import copy
import hashlib
from html.parser import HTMLParser
from html import unescape
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict

# Provedores de IA
from google import genai
from google.genai import types as genai_types
from groq import Groq
from openai import OpenAI

# Importação para Supabase, Word, Leitura de PDF e Editor Web
from supabase import create_client, Client
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import fitz  # PyMuPDF
from streamlit_quill import st_quill
from auth_utils import gerar_hash_senha, verificar_senha

# Tenta carregar o WeasyPrint (Gerador de PDF Avançado)
try:
    from weasyprint import HTML as WeasyHTML, CSS as WeasyCSS
    HAS_WEASYPRINT = True
except ImportError:
    HAS_WEASYPRINT = False

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(page_title="Autopilot Normativo - Multi-IA Hub", page_icon="⚖️", layout="wide", initial_sidebar_state="collapsed")

# ----------------- CSS GLOBAL -----------------
st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    
    .block-container { padding-top: 2rem; }
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 30px 20px;
        border-radius: 12px;
        color: white;
        text-align: center;
        box-shadow: 0 8px 16px rgba(0,0,0,0.15);
        margin-bottom: 25px;
    }
    .main-header h1 { color: #00FF87; font-weight: 800; font-size: 2.8rem; margin-bottom: 10px; }
    .main-header p { font-size: 1.2rem; color: #f1f1f1; margin-bottom: 0; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONEXÃO COM SUPABASE -----------------
@st.cache_resource
def init_supabase() -> Optional[Client]:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception:
        return None

supabase = init_supabase()

# ----------------- SISTEMA DE AUTENTICAÇÃO (LOGIN) -----------------
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
            max-width: 420px;
            margin: 4rem auto;
            padding: 1.5rem 2rem;
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.12);
        }
        .st-key-login_card [data-testid="stForm"] { border: none; padding: 0; }
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
                usuario = st.text_input("Usuário", placeholder="Digite seu usuário")
                senha = st.text_input("Senha", type="password", placeholder="Digite sua senha")
                btn_login = st.form_submit_button("Entrar no Sistema", use_container_width=True)

                if btn_login:
                    if verificar_login(usuario, senha):
                        st.session_state.autenticado = True
                        st.rerun()
                    else:
                        st.error("❌ Usuário ou senha incorretos.")
    st.stop()

# =====================================================================
# ÁREA AUTENTICADA DO SISTEMA
# =====================================================================

st.markdown("""
<div class="main-header">
    <h1>⚖️ Autopilot Normativo</h1>
    <p>Motor Multi-IA: Groq (Llama 3.3), Google Gemini, OpenRouter e Mistral</p>
</div>
""", unsafe_allow_html=True)

col_info, col_hist, col_usr, col_logout = st.columns([3, 1.5, 1.5, 1])

with col_info:
    st.info("💡 **Sistema Autenticado:** Proteção de dados ativa.")

hist_path = "pages/1_Historico.py"
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

# =====================================================================
# SELETOR DE PROVEDORES DE IA
# =====================================================================

PROVEDORES_CONFIG = {
    "⚡ Groq (Llama 3.3 70B - Velocidade Máxima)": {
        "id": "groq",
        "model": "llama-3.3-70b-versatile",
        "secret_key": "GROQ_API_KEY",
        "help": "Execução quase instantânea (~250-300 tokens/s). Ideal para PDFs textuais.",
        "placeholder": "gsk_..."
    },
    "🧠 Google Gemini (Flash - Multimodal & OCR)": {
        "id": "gemini",
        "model": "gemini-2.5-flash",
        "secret_key": "GEMINI_API_KEY",
        "help": "Excelente para documentos escaneados com OCR visual integrado.",
        "placeholder": "AIzaSy..."
    },
    "🌐 OpenRouter (Qwen 2.5 72B / R1)": {
        "id": "openrouter",
        "model": "qwen/qwen-2.5-72b-instruct:free",
        "secret_key": "OPENROUTER_API_KEY",
        "help": "Modelos avançados de código aberto via roteamento público.",
        "placeholder": "sk-or-v1-..."
    },
    "🌪️ Mistral AI (Mistral Small)": {
        "id": "mistral",
        "model": "mistral-small-latest",
        "secret_key": "MISTRAL_API_KEY",
        "help": "Excelente controle sintático e aderência estrita de JSON.",
        "placeholder": "..."
    }
}

with st.container(border=True):
    st.markdown("### 🎛️ Motor de Inteligência Artificial")
    col_sel_ia, col_key_ia = st.columns([1.2, 1.8])
    
    with col_sel_ia:
        provedor_selecionado = st.selectbox(
            "Selecione o Provedor de IA:",
            options=list(PROVEDORES_CONFIG.keys()),
            index=0
        )
        conf_atual = PROVEDORES_CONFIG[provedor_selecionado]
        st.caption(f"💡 {conf_atual['help']}")

    with col_key_ia:
        chave_secreta_padrao = ""
        try:
            chave_secreta_padrao = st.secrets.get(conf_atual["secret_key"], "")
        except:
            pass
        
        api_key_input = st.text_input(
            f"Chave da API ({conf_atual['secret_key']})",
            value=chave_secreta_padrao,
            type="password",
            placeholder=f"Insira sua chave {conf_atual['placeholder']}"
        )

st.markdown("### 📥 Upload de Arquivos Normativos")
arquivos_enviados = st.file_uploader("Arraste todos os documentos (PDF) — um ato original e todos os seus derivativos", type=["pdf"], accept_multiple_files=True, key="uploader_lote")

# =====================================================================
# MOTOR DE PARSER HTML/XML (ÁRVORE SINTÁTICA AST)
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

def editor_para_pdf(texto):
    if not texto: return ""
    parser = QuillParser()
    try:
        parser.feed(texto)
        return "<br/>".join(parser.get_paragraphs())
    except Exception:
        return re.sub(r'</?(span|div|p|ul|li|ol)[^>]*>', '', texto, flags=re.IGNORECASE)

# =====================================================================
# ESTRUTURAS PYDANTIC
# =====================================================================

class ArquivoClassificado(BaseModel):
    nome_arquivo_upload: str
    tipo: str = Field(description="'Base' ou 'Alteradora'")
    grupo_id: int = Field(description="Identificador da família normativa (comece em 1).")
    nome_padronizado_identificado: str = Field(description="Nome padronizado da norma (tipo, número, órgão e data)")
    data_oficial_iso: str = Field(description="Data formatada estritamente em YYYY-MM-DD.")
    ato_base_referenciado_tipo: Optional[str] = Field(default=None)
    ato_base_referenciado_numero: Optional[str] = Field(default=None)

class TriagemDocumentos(BaseModel):
    arquivos: List[ArquivoClassificado]

class MetadadosNorma(BaseModel):
    tipo_documento: str; numero_documento: str; orgao_emissor: str; data_assinatura: str; nome_padronizado: str

class Dispositivo(BaseModel):
    tipo: str; texto_principal_alterada: str; texto_principal_consolidada: str; is_tabela: bool
    tabela_alterada: Optional[List[List[str]]] = None; tabela_consolidada: Optional[List[List[str]]] = None
    texto_pos_tabela_alterada: Optional[str] = None; texto_pos_tabela_consolidada: Optional[str] = None
    nota_remissiva: Optional[str] = Field(default="")

class Consolidacao(BaseModel):
    arquivos_originais_identificados: List[str]; arquivos_alteradores_identificados: List[str]
    norma_base: MetadadosNorma; normas_alteradoras: List[MetadadosNorma]
    cabecalho_complemento: str; orgaos_emissores: str; titulo_portaria: str; ementa: str; preambulo: str
    assinatura_nome: str; assinatura_cargo: str; dispositivos: List[Dispositivo]

SYSTEM_INSTRUCTION_LEGISTECNICA = """
Você é um Especialista Sênior em Técnica Legislativa do Poder Público brasileiro. Regras obrigatórias:

1. FIDELIDADE ABSOLUTA: transcreva com exatidão o conteúdo de cada dispositivo, preservando formatação (<b>, <i>, quebras <br/>).
2. SEPARAÇÃO ESTRUTURAL OBRIGATÓRIA:
   - 'ementa': Resumo descritivo do objeto da norma.
   - 'preambulo': Autoridade expedidora e os Considerandos.
3. CRITÉRIO RIGOROSO DE ALTERAÇÃO E REVOGAÇÃO: 
   - Analise cirurgicamente o texto original do ato base em confronto com a portaria alteradora.
   - Na versão ALTERADA (`texto_principal_alterada`), todo dispositivo modificado ou revogado DEVE obrigatoriamente aparecer envelopado com: `<strike><font color="red">texto antigo alterado ou revogado</font></strike>` seguido imediatamente pelo texto novo vigente.
   - Na versão CONSOLIDADA (`texto_principal_consolidada`) de dispositivo ALTERADO, exiba o identificador (ex.: "Art. 5º", "§ 3º") seguido da NOVA REDAÇÃO VIGENTE por extenso, sem riscos.
   - Na versão CONSOLIDADA de dispositivo REVOGADO, mantenha o identificador seguido de "(Revogado)", SEM riscar e SEM repetir o texto revogado.
4. NOTA REMISSIVA: a nota indicando o ato alterador vai EXCLUSIVAMENTE no campo 'nota_remissiva', SEM parênteses, com o nome do documento em CAIXA ALTA (ex.: "Redação dada pela PORTARIA Nº 108/PGJM, DE 28 DE MAIO DE 2026."). NUNCA repita a nota remissiva dentro do texto principal.
"""

# =====================================================================
# CLIENTE UNIFICADO MULTI-IA
# =====================================================================

def executar_chamada_ia(provedor_id: str, api_key: str, modelo: str, user_prompt: Any, schema_model: type[BaseModel]) -> dict:
    schema_json = json.dumps(schema_model.model_json_schema(), ensure_ascii=False)
    
    # 1. GOOGLE GEMINI
    if provedor_id == "gemini":
        client = genai.Client(api_key=api_key)
        config = genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema_model,
            system_instruction=SYSTEM_INSTRUCTION_LEGISTECNICA,
            thinking_config=genai_types.ThinkingConfig(thinking_level="low")
        )
        contents = user_prompt if isinstance(user_prompt, list) else [user_prompt]
        resp = client.models.generate_content(model=modelo, contents=contents, config=config)
        return json.loads(resp.text)

    # 2. PROVEDORES VIA PROTOCOLO COMPATÍVEL OPENAI (GROQ, OPENROUTER, MISTRAL)
    if provedor_id == "groq":
        client_openai = Groq(api_key=api_key)
    elif provedor_id == "openrouter":
        client_openai = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    elif provedor_id == "mistral":
        client_openai = OpenAI(base_url="https://api.mistral.ai/v1", api_key=api_key)
    else:
        raise ValueError(f"Provedor '{provedor_id}' não reconhecido.")

    # Converte listas de partes em texto puro se vier do extrator multimodal
    if isinstance(user_prompt, list):
        textos_limpos = []
        for item in user_prompt:
            if isinstance(item, str): textos_limpos.append(item)
            elif hasattr(item, "text"): textos_limpos.append(item.text)
        user_prompt_str = "\n".join(textos_limpos)
    else:
        user_prompt_str = str(user_prompt)

    system_prompt = (
        f"{SYSTEM_INSTRUCTION_LEGISTECNICA}\n\n"
        f"IMPORTANTE: Você deve responder APENAS um objeto JSON válido que obedeça rigorosamente a este schema JSON Schema:\n"
        f"{schema_json}\n"
        f"Não inclua markdown em volta do JSON (sem ```json), apenas retorne o JSON puro."
    )

    max_tentativas = 3
    for tentativa in range(1, max_tentativas + 1):
        try:
            chat_completion = client_openai.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt_str}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            raw_text = chat_completion.choices[0].message.content.strip()
            
            # Limpeza de markdown
            if raw_text.startswith("```"):
                raw_text = re.sub(r'^```(?:json)?\s*', '', raw_text, flags=re.IGNORECASE)
                raw_text = re.sub(r'\s*```$', '', raw_text)
                
            return json.loads(raw_text.strip())
        except Exception as e:
            if tentativa < max_tentativas:
                time.sleep(tentativa * 2)
                continue
            raise e

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

def extrair_conteudo_arquivo(file_bytes, nome_arquivo, modo_gemini=False):
    if nome_arquivo.lower().endswith(".docx"): 
        return [f"ARQUIVO DOCX: {nome_arquivo}"] if modo_gemini else f"ARQUIVO DOCX: {nome_arquivo}"
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        html_text = f"CONTEÚDO DO ARQUIVO {nome_arquivo}:\n\n"
        caracteres_uteis = 0
        for page_num, page in enumerate(doc):
            html_text += f"=== PÁGINA {page_num + 1} ===\n"
            blocks = page.get_text("dict", sort=True).get("blocks", [])
            for b in blocks:
                if b.get('type') == 0:
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

        if modo_gemini and caracteres_uteis < 30 * max(doc.page_count, 1):
            partes = [f"ARQUIVO {nome_arquivo} ESCANEADO:"]
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                partes.append(genai_types.Part.from_bytes(data=pix.tobytes("jpg", jpg_quality=78), mime_type="image/jpeg"))
            return partes

        return [html_text] if modo_gemini else html_text
    except Exception as e:
        erro = f"Erro ao extrair PDF {nome_arquivo}: {str(e)}"
        return [erro] if modo_gemini else erro

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

def _localizar_base_no_banco(tipo_ref, numero_ref):
    if not supabase or not numero_ref or not str(numero_ref).strip(): return None
    try:
        numero_limpo = str(numero_ref).strip()
        query = supabase.table("portarias_base").select("id, nome_padronizado, tipo_documento, numero_documento, documento_consolidado_json")
        res = query.ilike("numero_documento", f"%{numero_limpo}%").execute()
        candidatos = res.data or []
        if not candidatos and tipo_ref:
            res2 = query.ilike("nome_padronizado", f"%{numero_limpo}%").execute()
            candidatos = res2.data or []
        if not candidatos: return None
        if tipo_ref:
            for c in candidatos:
                if str(c.get('tipo_documento', '')).strip().lower() == str(tipo_ref).strip().lower():
                    return c
        return candidatos[0]
    except Exception:
        return None

def _consultar_estado_e_historico(nome_padrao):
    if not supabase or not nome_padrao: return None, []
    try:
        res_bd = supabase.table("portarias_base").select("id, documento_consolidado_json").eq("nome_padronizado", nome_padrao).execute()
        if not res_bd.data: return None, []
        base_id = res_bd.data[0]['id']
        estado = res_bd.data[0].get("documento_consolidado_json")
        res_alt = supabase.table("portarias_alteradoras").select("nome_padronizado").eq("portaria_base_id", base_id).execute()
        ja_processadas = [r['nome_padronizado'] for r in (res_alt.data or []) if r.get('nome_padronizado')]
        return (json.dumps(estado) if estado else None), ja_processadas
    except Exception:
        return None, []

def _processar_cascata_grupo(prov_id, api_k, model_name, arquivo_base, arquivos_alteradores, textos_extraidos, memoria_aprendida):
    nome_padrao = arquivo_base.get('nome_padronizado_identificado', '')
    reconstruida = bool(arquivo_base.get('_reconstruida_do_banco'))
    estado_json_atual, ja_processadas = _consultar_estado_e_historico(nome_padrao)
    mensagens = []

    if reconstruida:
        detalhe = f" com {len(ja_processadas)} derivação(ões) já aplicada(s)" if ja_processadas else ""
        mensagens.append(("info", f"📎 Reutilizando consolidação de '{nome_padrao}' salva no banco{detalhe}."))
    elif estado_json_atual is not None:
        mensagens.append(("info", f"🧠 '{nome_padrao}' já possui histórico no banco ({len(ja_processadas)} portarias anteriores)."))

    if reconstruida and estado_json_atual is None:
        raise Exception(f"Ato base '{nome_padrao}' sem conteúdo consolidado prévio no banco.")

    ja_processadas_lower = {j.lower() for j in ja_processadas}
    alteradoras_para_aplicar = [alt for alt in arquivos_alteradores if alt.get('nome_padronizado_identificado', '').lower() not in ja_processadas_lower]
    alteradoras_para_aplicar.sort(key=lambda x: x.get('data_oficial_iso') or '')

    modo_gem = (prov_id == "gemini")

    if not alteradoras_para_aplicar:
        if estado_json_atual:
            return json.loads(estado_json_atual), mensagens
        
        texto_base = textos_extraidos[arquivo_base['nome_arquivo_upload']]
        if modo_gem:
            conteudo = ["DOCUMENTO BASE ORIGINAL:"] + (texto_base if isinstance(texto_base, list) else [texto_base])
            conteudo.append(f"Estruture o documento separando a ementa do preâmbulo e aplicando rigorosamente o mapeamento de dispositivos.\n{memoria_aprendida}")
        else:
            conteudo = f"DOCUMENTO BASE ORIGINAL:\n{texto_base}\n\nEstruture o documento separando a ementa do preâmbulo e aplicando rigorosamente o mapeamento de dispositivos.\n{memoria_aprendida}"
            
        dados_resultado = executar_chamada_ia(prov_id, api_k, model_name, conteudo, Consolidacao)
        return dados_resultado, mensagens

    dados_resultado = None
    for i, alt in enumerate(alteradoras_para_aplicar):
        if modo_gem:
            conteudo = []
            if estado_json_atual:
                conteudo.append(f"ESTADO CONSOLIDADO ATUAL (JSON):\n{estado_json_atual}")
            elif i == 0:
                conteudo.append("DOCUMENTO BASE ORIGINAL:")
                conteudo.extend(textos_extraidos[arquivo_base['nome_arquivo_upload']])

            conteudo.append(f"PORTARIA ALTERADORA Nº {i+1} ({alt['nome_arquivo_upload']}):")
            conteudo.extend(textos_extraidos[alt['nome_arquivo_upload']])
            conteudo.append(f"Aplique as alterações cruzando o ato base com a alteradora. Mantenha <b>, <i> e envelopamento <strike><font color=\"red\">...</font></strike> em dispositivos alterados/revogados na versão alterada. Na consolidada, mostre o número e a nova redação vigente (ou '(Revogado)').\n{memoria_aprendida}")
        else:
            conteudo = ""
            if estado_json_atual:
                conteudo += f"ESTADO CONSOLIDADO ATUAL (JSON):\n{estado_json_atual}\n\n"
            elif i == 0:
                conteudo += f"DOCUMENTO BASE ORIGINAL:\n{textos_extraidos[arquivo_base['nome_arquivo_upload']]}\n\n"

            conteudo += f"PORTARIA ALTERADORA Nº {i+1} ({alt['nome_arquivo_upload']}):\n{textos_extraidos[alt['nome_arquivo_upload']]}\n\n"
            conteudo += f"Aplique as alterações cruzando o ato base com a alteradora. Mantenha <b>, <i> e envelopamento <strike><font color=\"red\">...</font></strike> em dispositivos alterados/revogados na versão alterada. Na consolidada, mostre o número e a nova redação vigente (ou '(Revogado)').\n{memoria_aprendida}"

        dados_resultado = executar_chamada_ia(prov_id, api_k, model_name, conteudo, Consolidacao)
        estado_json_atual = json.dumps(dados_resultado)

    return dados_resultado, mensagens

def analisar_lote_arquivos(arquivos, prov_id, api_k, model_name):
    memoria_aprendida = resgatar_memoria()
    modo_gem = (prov_id == "gemini")

    textos_extraidos = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(arquivos)))) as ex:
        futuros = {ex.submit(extrair_conteudo_arquivo, arq.getvalue(), arq.name, modo_gem): arq.name for arq in arquivos}
        for fut in as_completed(futuros):
            textos_extraidos[futuros[fut]] = fut.result()

    if modo_gem:
        prompt_triagem = ["Analise os documentos. Agrupe cada ato original com seus derivativos. Se uma Alteradora citar um ato original ausente, preencha ato_base_referenciado_tipo/numero."]
        for partes in textos_extraidos.values():
            if isinstance(partes, list): prompt_triagem.extend(partes)
            else: prompt_triagem.append(partes)
    else:
        prompt_triagem = "Analise os seguintes documentos normativos. Identifique 'Base' ou 'Alteradora' e relacione os grupos familiares normativos.\nDOCUMENTOS:\n"
        for nome_arq, texto in textos_extraidos.items():
            prompt_triagem += f"\n--- INÍCIO {nome_arq} ---\n{str(texto)[:3500]}\n--- FIM {nome_arq} ---\n"

    triagem_obj = executar_chamada_ia(prov_id, api_k, model_name, prompt_triagem, TriagemDocumentos)
    triagem_dados = triagem_obj.get("arquivos", [])

    grupos = {}
    for a in triagem_dados: grupos.setdefault(a.get('grupo_id', 0), []).append(a)

    grupos_validos = []
    consolidacoes_geradas, arquivos_nao_alterados = [], []
    for grupo_id, itens in grupos.items():
        arquivo_base = next((a for a in itens if a['tipo'] == 'Base'), None)
        arquivos_alteradores = sorted([a for a in itens if a['tipo'] == 'Alteradora'], key=lambda x: x['data_oficial_iso'])

        if not arquivo_base and not arquivos_alteradores: continue
        if not arquivo_base:
            base_reconstruida = None
            for alt in arquivos_alteradores:
                candidato = _localizar_base_no_banco(alt.get('ato_base_referenciado_tipo'), alt.get('ato_base_referenciado_numero'))
                if candidato:
                    base_reconstruida = candidato
                    break
            if base_reconstruida:
                arquivo_base = {
                    "nome_arquivo_upload": None,
                    "tipo": "Base",
                    "nome_padronizado_identificado": base_reconstruida.get("nome_padronizado", ""),
                    "data_oficial_iso": "",
                    "_reconstruida_do_banco": True,
                }
                grupos_validos.append((arquivo_base, arquivos_alteradores))
            else:
                arquivos_nao_alterados.extend([a['nome_arquivo_upload'] for a in arquivos_alteradores])
            continue
        grupos_validos.append((arquivo_base, arquivos_alteradores))

    if grupos_validos:
        with ThreadPoolExecutor(max_workers=min(4, len(grupos_validos))) as ex:
            futuros = {}
            for arquivo_base, arquivos_alteradores in grupos_validos:
                st.toast(f"⚙️ Processando com {model_name}: {arquivo_base.get('nome_padronizado_identificado')}...", icon="⏳")
                fut = ex.submit(_processar_cascata_grupo, prov_id, api_k, model_name, arquivo_base, arquivos_alteradores, textos_extraidos, memoria_aprendida)
                futuros[fut] = (arquivo_base, arquivos_alteradores)
            for fut in as_completed(futuros):
                arquivo_base, arquivos_alteradores = futuros[fut]
                try:
                    resultado, mensagens = fut.result()
                    consolidacoes_geradas.append(resultado)
                    for tipo_msg, texto_msg in mensagens:
                        if tipo_msg == "info": st.info(texto_msg)
                        elif tipo_msg == "warning": st.warning(texto_msg)
                except Exception as e:
                    st.error(f"❌ Falha em '{arquivo_base.get('nome_padronizado_identificado')}': {e}")
                    if arquivo_base.get('nome_arquivo_upload'):
                        arquivos_nao_alterados.append(arquivo_base['nome_arquivo_upload'])
                    arquivos_nao_alterados.extend([a['nome_arquivo_upload'] for a in arquivos_alteradores])

    return {"consolidacoes_geradas": consolidacoes_geradas, "arquivos_nao_alterados": arquivos_nao_alterados}

# =====================================================================
# EXPORTAÇÃO (HTML UNIVERSAL -> WEASYPRINT PDF -> DOCX AST)
# =====================================================================

def gerar_html_dinamico(consolidacao_dict, tipo_versao):
    comp = consolidacao_dict.get("cabecalho_complemento", "")
    titulo_doc = f"VERSÃO {'ALTERADA' if tipo_versao=='alterada' else 'CONSOLIDADA'} - {comp}"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{titulo_doc}</title>
        <style>
            @page {{ size: A4; margin: 2.5cm 2cm; }}
            body {{ font-family: 'Times New Roman', Times, serif; font-size: 11pt; line-height: 1.5; text-align: justify; }}
            .topo {{ text-align: center; color: #444; font-size: 10pt; font-weight: bold; margin-bottom: 20px; text-transform: uppercase; }}
            .brasao {{ text-align: center; margin-bottom: 10px; }}
            .brasao img {{ width: 45px; height: auto; display: block; margin: 0 auto; }}
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
    """
    
    if os.path.exists("brasao.png"):
        import base64
        with open("brasao.png", "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
            html += f"<div class='brasao'><img src='data:image/png;base64,{encoded_string}'/></div>"

    html += f"""
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
            continue
            
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
    if not HAS_WEASYPRINT: return b"Erro: WeasyPrint nao instalado no servidor."
    buffer = io.BytesIO()
    WeasyHTML(string=html_str).write_pdf(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def aplicar_html_no_docx(p, texto_html):
    texto_html = texto_html.replace("&nbsp;", "\xa0")
    tokens = re.split(r'(<[^>]+>)', texto_html)
    is_bold = is_strike = is_red = is_italic = False
    
    for token in tokens:
        if not token: continue
        t = token.lower()
        if t.startswith('<b') and not t.startswith('<br'): is_bold = True
        elif t == '</b>': is_bold = False
        elif t.startswith('<i'): is_italic = True
        elif t == '</i>': is_italic = False
        elif t.startswith('<strike') or t.startswith('<s') and not t.startswith('<span'): is_strike = True
        elif t == '</strike>' or t == '</s>': is_strike = False
        elif t.startswith('<font') and ('red' in t or '#f00' in t or '#e6' in t): is_red = True
        elif t.startswith('<span') and ('red' in t or '#f00' in t or '#e6' in t): is_red = True
        elif t == '</font>' or t == '</span>': is_red = False
        elif token.startswith('<'): pass
        else:
            token = unescape(token)
            run = p.add_run(token)
            run.font.name, run.font.size = 'Times New Roman', Pt(11)
            if is_bold: run.bold = True
            if is_italic: run.italic = True
            if is_strike: run.font.strike = True
            if is_red: run.font.color.rgb = RGBColor(230, 0, 0)

def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
    doc = docx.Document()
    for section in doc.sections: section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Inches(1)

    ph = doc.add_paragraph(); ph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rh = ph.add_run(f"VERSÃO {'ALTERADA' if tipo_versao=='alterada' else 'CONSOLIDADA'} - {consolidacao_dict.get('cabecalho_complemento', '')}")
    rh.font.name, rh.font.size, rh.bold, rh.font.color.rgb = 'Times New Roman', Pt(10), True, RGBColor(68, 68, 68)
    
    po = doc.add_paragraph(); po.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ro = po.add_run(limpar_texto_ia(consolidacao_dict.get("orgaos_emissores") or "").replace("<br/>", "\n"))
    ro.font.name, ro.font.size, ro.bold = 'Times New Roman', Pt(11), True

    ptit = doc.add_paragraph(); ptit.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rt = ptit.add_run(limpar_texto_ia(consolidacao_dict.get("titulo_portaria") or ""))
    rt.font.name, rt.font.size, rt.bold = 'Times New Roman', Pt(11), True

    def _render_docx_p(p_obj, texto_html, bold_all=False):
        if not texto_html: return
        for p_html in texto_html.split("<br/>"):
            if not p_html.strip(): continue
            if bold_all:
                run = p_obj.add_run(re.sub(r'<[^>]+>', '', p_html).replace("&nbsp;", "\xa0"))
                run.font.name, run.font.size, run.bold = 'Times New Roman', Pt(10), True
            else: 
                aplicar_html_no_docx(p_obj, p_html)
            p_obj.add_run("\n")

    p_ementa = doc.add_paragraph()
    p_ementa.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p_ementa.paragraph_format.left_indent = Inches(3)
    _render_docx_p(p_ementa, consolidacao_dict.get("ementa", ""))

    p_preambulo = doc.add_paragraph()
    p_preambulo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p_preambulo.paragraph_format.left_indent = Inches(0)
    _render_docx_p(p_preambulo, consolidacao_dict.get("preambulo", ""))

    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva(item.get(f"texto_principal_{tipo_versao}"), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        
        if "capitulo" in t or "anexo" in t: 
            if "anexo" in t: doc.add_page_break()
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _render_docx_p(p, t_prin, bold_all=True)
            continue
            
        if t_prin:
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; p.paragraph_format.first_line_indent = Inches(0.4)
            _render_docx_p(p, t_prin)
        
        if item.get("is_tabela"):
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas:
                tb = doc.add_table(rows=len(linhas), cols=len(linhas[0])); tb.style = 'Table Grid'
                for r_idx, linha in enumerate(linhas):
                    for c_idx, celula in enumerate(linha):
                        _render_docx_p(tb.cell(r_idx, c_idx).paragraphs[0], celula.replace('\n', '<br/>'))
            t_pos = injetar_nota_remissiva(item.get(f"texto_pos_tabela_{tipo_versao}"), item.get("nota_remissiva"))
            if t_pos:
                p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; p.paragraph_format.first_line_indent = Inches(0.4)
                _render_docx_p(p, t_pos)

    pa = doc.add_paragraph(); pa.alignment = WD_ALIGN_PARAGRAPH.CENTER; pa.paragraph_format.space_before = Pt(36)
    ra = pa.add_run(f"{limpar_texto_ia(consolidacao_dict.get('assinatura_nome') or '')}\n{limpar_texto_ia(consolidacao_dict.get('assinatura_cargo') or '')}")
    ra.font.name, ra.font.size, ra.bold = 'Times New Roman', Pt(11), True
    buffer = io.BytesIO(); doc.save(buffer); buffer.seek(0)
    return buffer.getvalue()

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
        res_busca = supabase.table("portarias_base").select("id").eq("nome_padronizado", base['nome_padronizado']).execute()
        
        if res_busca.data:
            base_id = res_busca.data[0]['id']
            supabase.table("portarias_base").update({"documento_consolidado_json": cons}).eq("id", base_id).execute()
        else:
            res_ins = supabase.table("portarias_base").insert({"tipo_documento": base['tipo_documento'], "numero_documento": base['numero_documento'], "orgao_emissor": base['orgao_emissor'], "data_assinatura": data_base_iso, "nome_padronizado": base['nome_padronizado'], "titulo_original": cons.get("titulo_portaria"), "orgaos_emissores": cons.get("orgaos_emissores"), "assinatura_nome": cons.get("assinatura_nome"), "assinatura_cargo": cons.get("assinatura_cargo"), "documento_consolidado_json": cons}).execute()
            base_id = res_ins.data[0]['id']
            
        for alt in alteradoras:
            res_alt = supabase.table("portarias_alteradoras").select("id").eq("portaria_base_id", base_id).eq("nome_padronizado", alt['nome_padronizado']).execute()
            if not res_alt.data:
                data_alt_iso = converter_para_iso(alt.get('data_assinatura'))
                supabase.table("portarias_alteradoras").insert({"portaria_base_id": base_id, "tipo_documento": alt['tipo_documento'], "numero_documento": alt['numero_documento'], "orgao_emissor": alt['orgao_emissor'], "data_assinatura": data_alt_iso, "nome_padronizado": alt['nome_padronizado'], "arquivo_nome_original": "Múltiplos Documentos"}).execute()
        return True
    except: return False

# ----------------- FRONT-END COM EDITOR VISUAL -----------------
if "dados_processados" not in st.session_state: st.session_state.dados_processados = None
if "dados_originais_ia" not in st.session_state: st.session_state.dados_originais_ia = None
st.markdown("<br>", unsafe_allow_html=True)

if st.button("🚀 Iniciar Análise Autopilot", type="primary", use_container_width=True):
    if not api_key_input:
        st.error(f"⚠️ Insira a chave da API para o provedor selecionado ({conf_atual['secret_key']}).")
    elif not arquivos_enviados:
        st.warning("⚠️ Envie os arquivos normativos primeiro.")
    else:
        with st.spinner(f"⚡ Processando com {conf_atual['model']} ({provedor_selecionado})..."):
            try:
                st.session_state.dados_processados = analisar_lote_arquivos(
                    arquivos=arquivos_enviados,
                    prov_id=conf_atual["id"],
                    api_k=api_key_input.strip(),
                    model_name=conf_atual["model"]
                )
                st.session_state.dados_originais_ia = copy.deepcopy(st.session_state.dados_processados)
                st.success("✨ Processamento concluído com sucesso!")
            except Exception as e:
                st.error(f"❌ Ocorreu um erro: {str(e)}")

if st.session_state.dados_processados:
    st.markdown("---")
    dados = st.session_state.dados_processados
    dados_originais = st.session_state.dados_originais_ia
    
    for i, cons in enumerate(dados.get("consolidacoes_geradas", [])):
        nome_exibicao_base = cons['norma_base']['nome_padronizado']
        nomes_alteradoras = [alt['nome_padronizado'] for alt in cons.get('normas_alteradoras', [])]
        nome_exibicao_alt = " e ".join(nomes_alteradoras) if nomes_alteradoras else "Desconhecido"
        
        with st.expander(f"📁 **{nome_exibicao_base}** alterada por **{nome_exibicao_alt}**", expanded=True):
            st.markdown("### 📝 Editor Visual de Documento")
            
            cons['titulo_portaria'] = st.text_input("Título da Portaria", cons.get('titulo_portaria', ''), key=f"titulo_{i}")
            
            st.markdown("**Ementa**")
            val_ementa = ia_para_editor(cons.get('ementa', ''))
            ementa_editada = st_quill(value=val_ementa, html=True, key=f"q_ementa_{i}")
            if ementa_editada is not None: cons['ementa'] = editor_para_pdf(ementa_editada)
            
            st.markdown("**Preâmbulo e Considerandos**")
            val_preambulo = ia_para_editor(cons.get('preambulo', ''))
            preambulo_editado = st_quill(value=val_preambulo, html=True, key=f"q_preambulo_{i}")
            if preambulo_editado is not None: cons['preambulo'] = editor_para_pdf(preambulo_editado)
            
            st.markdown("#### Dispositivos (Artigos, Parágrafos, Incisos)")
            for j, disp in enumerate(cons.get("dispositivos", [])):
                st.markdown(f"**{disp.get('tipo', 'Dispositivo').upper()} {j+1}**")
                c_alt, c_cons = st.columns(2)
                
                with c_alt:
                    st.markdown("*Versão Alterada*")
                    val_alt = ia_para_editor(disp.get('texto_principal_alterada', ''))
                    alt_editada = st_quill(value=val_alt, html=True, key=f"q_alt_{i}_{j}")
                    if alt_editada is not None: disp['texto_principal_alterada'] = editor_para_pdf(alt_editada)
                    
                with c_cons:
                    st.markdown("*Versão Consolidada*")
                    val_cons = ia_para_editor(disp.get('texto_principal_consolidada', ''))
                    cons_editada = st_quill(value=val_cons, html=True, key=f"q_cons_{i}_{j}")
                    if cons_editada is not None: disp['texto_principal_consolidada'] = editor_para_pdf(cons_editada)
                
                st.markdown("*Nota Remissiva (Injetada automaticamente no final)*")
                nota_editada = st.text_input("Nota", value=disp.get('nota_remissiva', ''), key=f"nota_{i}_{j}", label_visibility="collapsed")
                disp['nota_remissiva'] = nota_editada
                st.markdown("---")

                if disp.get('is_tabela'):
                    st.markdown("*Tabela / Anexo — revise linha a linha*")
                    t_alt, t_cons = st.columns(2)
                    with t_alt:
                        tab_alt_edit = st.data_editor(disp.get('tabela_alterada') or [[""]], key=f"tab_alt_{i}_{j}", num_rows="dynamic", use_container_width=True)
                        disp['tabela_alterada'] = tab_alt_edit if isinstance(tab_alt_edit, list) else disp.get('tabela_alterada')
                        pos_alt = st.text_area("Texto após a tabela (Alterada)", value=disp.get('texto_pos_tabela_alterada') or "", key=f"pos_alt_{i}_{j}")
                        disp['texto_pos_tabela_alterada'] = pos_alt
                    with t_cons:
                        tab_cons_edit = st.data_editor(disp.get('tabela_consolidada') or [[""]], key=f"tab_cons_{i}_{j}", num_rows="dynamic", use_container_width=True)
                        disp['tabela_consolidada'] = tab_cons_edit if isinstance(tab_cons_edit, list) else disp.get('tabela_consolidada')
                        pos_cons = st.text_area("Texto após a tabela (Consolidada)", value=disp.get('texto_pos_tabela_consolidada') or "", key=f"pos_cons_{i}_{j}")
                        disp['texto_pos_tabela_consolidada'] = pos_cons

            st.markdown("### 📥 Opções de Exportação")
            if st.button(f"💾 Salvar Cascata Inteira no Banco de Dados", key=f"btn_sup_{i}"):
                cons_original = dados_originais.get("consolidacoes_geradas", [])[i] if dados_originais else None
                if salvar_no_supabase(cons, cons_original): st.success(f"Banco atualizado!")
            
            c_html, c_pdf, c_docx = st.columns(3)
            html_alt = gerar_html_dinamico(cons, "alterada")
            html_cons = gerar_html_dinamico(cons, "consolidada")
            pdf_alt, docx_alt = gerar_pdf_dinamico(cons, "alterada"), gerar_docx_dinamico(cons, "alterada")
            pdf_cons, docx_cons = gerar_pdf_dinamico(cons, "consolidada"), gerar_docx_dinamico(cons, "consolidada")
            
            nome_arquivo_base = nome_exibicao_base.replace(' ', '_').replace('/', '-')
            
            c_html.download_button("🌐 Baixar HTML (Alterada)", data=html_alt, file_name=f"{nome_arquivo_base}_Alt.html", mime="text/html", key=f"ha_{i}")
            c_html.download_button("🌐 Baixar HTML (Consolidada)", data=html_cons, file_name=f"{nome_arquivo_base}_Cons.html", mime="text/html", key=f"hc_{i}")
            
            c_pdf.download_button("📄 Baixar PDF (Alterada)", data=pdf_alt, file_name=f"{nome_arquivo_base}_Alt.pdf", mime="application/pdf", key=f"pa_{i}")
            c_pdf.download_button("📄 Baixar PDF (Consolidada)", data=pdf_cons, file_name=f"{nome_arquivo_base}_Cons.pdf", mime="application/pdf", key=f"pc_{i}")
            
            c_docx.download_button("📝 Baixar DOCX (Alterada)", data=docx_alt, file_name=f"{nome_arquivo_base}_Alt.docx", mime="application/vnd.openxmlformats", key=f"da_{i}")
            c_docx.download_button("📝 Baixar DOCX (Consolidada)", data=docx_cons, file_name=f"{nome_arquivo_base}_Cons.docx", mime="application/vnd.openxmlformats", key=f"dc_{i}")

    if st.button("🔄 Nova Análise", type="secondary"): 
        st.session_state.dados_processados = None
        st.session_state.dados_originais_ia = None
        st.rerun()
