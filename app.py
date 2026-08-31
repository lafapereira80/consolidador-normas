# app.py (nova página principal - Identificar e Cruzar)
import streamlit as st
import os
import re
import json
import time
import base64
import threading
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
from supabase import create_client, Client
import fitz  # PyMuPDF
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

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

from auth_utils import gerar_hash_senha, verificar_senha

st.set_page_config(page_title="Autopilot Normativo", page_icon="⚖️", layout="wide", initial_sidebar_state="collapsed")

# PROTEÇÃO DE ACESSO (LOGIN)
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

@st.cache_resource
def init_supabase() -> Optional[Client]:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception:
        return None

supabase = init_supabase()

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

# APÓS LOGIN: CONTEÚDO DA PÁGINA IDENTIFICAR E CRUZAR

st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 20px 20px;
        border-radius: 12px;
        color: white;
        text-align: center;
        margin-bottom: 25px;
    }
    .main-header h1 { color: #00FF87; font-weight: 800; font-size: 2.2rem; margin-bottom: 0px; }
    .card-achado {
        border: 1px solid #d0d4dc; border-radius: 10px; padding: 14px 18px;
        margin-bottom: 10px; background: #f8faff;
    }
    .card-achado.correlacionado { border-left: 5px solid #1e9c4f; }
    .card-achado.pendente { border-left: 5px solid #d98c00; }
</style>
<div class="main-header">
    <h1>🔎 Identificação e Cruzamento de Atos</h1>
</div>
""", unsafe_allow_html=True)

# --- MENU DE NAVEGAÇÃO SUPERIOR FIXO ---
col_home, col_cons, col_hist, col_usr, col_logout = st.columns([1.5, 1.5, 1.5, 1.5, 1])

with col_home:
    st.markdown("🏠 **Início**")

with col_cons:
    # Link para a página de consolidação (nova)
    cons_path = "pages/3_Consolidar_Norma.py"
    if os.path.exists("pages"):
        for f in os.listdir("pages"):
            if "consolidar" in f.lower() and f.endswith(".py"):
                cons_path = f"pages/{f}"
                break
    try:
        st.page_link(cons_path, label="⚙️ Consolidar Norma", icon="➡️")
    except Exception:
        st.markdown(f'<a href="{cons_path.replace("pages/", "").replace(".py", "")}" target="_top" style="display:block;text-align:center;background:#f0f2f6;border:1px solid #d0d4dc;color:#31333F !important;padding:0.5rem;border-radius:0.5rem;text-decoration:none;font-weight:500;">➡️ ⚙️ Consolidar</a>', unsafe_allow_html=True)

with col_hist:
    hist_path = "pages/1_Historico.py"
    if os.path.exists("pages"):
        for f in os.listdir("pages"):
            if "historico" in f.lower() and f.endswith(".py"):
                hist_path = f"pages/{f}"
                break
    try:
        st.page_link(hist_path, label="🗄️ Histórico", icon="➡️")
    except Exception:
        st.markdown(f'<a href="{hist_path.replace("pages/", "").replace(".py", "")}" target="_top" style="display:block;text-align:center;background:#f0f2f6;border:1px solid #d0d4dc;color:#31333F !important;padding:0.5rem;border-radius:0.5rem;text-decoration:none;font-weight:500;">➡️ 🗄️ Histórico</a>', unsafe_allow_html=True)

with col_usr:
    usr_path = "pages/usuarios.py"
    if os.path.exists("pages"):
        for f in os.listdir("pages"):
            if "usuario" in f.lower() and f.endswith(".py"):
                usr_path = f"pages/{f}"
                break
    try:
        st.page_link(usr_path, label="👥 Usuários", icon="➡️")
    except Exception:
        st.markdown(f'<a href="{usr_path.replace("pages/", "").replace(".py", "")}" target="_top" style="display:block;text-align:center;background:#f0f2f6;border:1px solid #d0d4dc;color:#31333F !important;padding:0.5rem;border-radius:0.5rem;text-decoration:none;font-weight:500;">➡️ 👥 Usuários</a>', unsafe_allow_html=True)

with col_logout:
    if st.button("Sair", key="btn_sair_ident", type="secondary", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

st.markdown("---")

# ----------------- CONEXÃO COM BANCO -----------------
@st.cache_resource
def init_supabase() -> Optional[Client]:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception:
        return None

supabase = init_supabase()
if not supabase:
    st.error("⚠️ Não foi possível conectar ao Supabase.")
    st.stop()

# ----------------- HUB MULTI-IA (mesmos provedores do Autopilot) -----------------
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

# ----------------- INSTRUÇÃO DE SISTEMA (IDENTIFICAÇÃO) -----------------
SYSTEM_INSTRUCTION_IDENTIFICACAO = """
Você é um Especialista Sênior em Técnica Legislativa do Poder Público brasileiro, com domínio do
Manual de Redação da Presidência da República. Sua única tarefa aqui é IDENTIFICAR metadados do
documento e detectar se ele ALTERA, ACRESCENTA ou REVOGA (parcial ou integralmente) algum outro Ato
normativo (Lei, Decreto, Resolução, Portaria, Enunciado, Instrução Normativa etc.). NÃO transcreva o
conteúdo integral do documento. Regras obrigatórias:

1. IDENTIFICAÇÃO DO PRÓPRIO DOCUMENTO:
   - 'tipo_documento': espécie normativa em maiúsculas (ex.: "PORTARIA", "RESOLUÇÃO", "DECRETO").
   - 'numero_documento': número/identificador tal como grafado (ex.: "30/PGJM").
   - 'orgao_emissor': sigla/nome do órgão emissor.
   - 'data_assinatura': data de assinatura no formato ESTRITO YYYY-MM-DD.
   - 'nome_padronizado': nome padronizado único no formato
     "<TIPO> Nº <NÚMERO>, de <DATA POR EXTENSO>" (ex.: "PORTARIA Nº 30/PGJM, de 20 de maio de 2026"),
     seguindo o Manual de Redação da Presidência da República.
   - 'ementa': resumo descritivo do objeto da norma, se houver (senão string vazia).

2. DETECÇÃO DE ALTERAÇÃO/REVOGAÇÃO (leia TODO o documento: preâmbulo, considerandos, artigos e
   disposições finais — a menção pode estar em qualquer parte, ex.: "Fica alterado o art. 5º da
   Portaria nº 10/PGJ...", "Revoga-se a Portaria nº 8/PGJM...", "Ficam revogados os incisos II e III
   do art. 4º..."):
   - 'e_documento_alterador': true se o documento altera, acrescenta ou revoga (total ou parcialmente)
     qualquer outro ato; caso contrário false.
   - 'atos_referenciados': uma entrada para CADA ato distinto afetado, contendo:
       - 'tipo_operacao': exatamente um destre: "altera", "acrescenta", "revoga_parcial",
         "revoga_integral".
       - 'tipo_ato_afetado': espécie do ato afetado (ex.: "PORTARIA").
       - 'numero_ato_afetado': número do ato afetado tal como citado no texto (ex.: "10/PGJ").
       - 'dispositivo_afetado': o dispositivo específico afetado, se citado (ex.: "Art. 5º, inciso III");
         null se a revogação for integral ou o dispositivo não for especificado.
       - 'resumo_alteracao': resumo curto (uma frase) do que muda.
   - Se o documento não alterar/revogar nada, 'atos_referenciados' deve ser uma lista vazia.

3. NUNCA invente números ou tipos de atos que não estejam explicitamente citados no texto.
"""

def _prompt_schema_json(response_schema):
    esquema = response_schema.model_json_schema()
    return (
        "\n\nRESPONDA EXCLUSIVAMENTE COM UM OBJETO JSON VÁLIDO (sem markdown, sem ```json, sem comentários, "
        "sem texto antes ou depois) que obedeça RIGOROSAMENTE a este JSON Schema:\n"
        + json.dumps(esquema, ensure_ascii=False)
    )

def _extrair_json_bruto(texto):
    if not texto:
        raise Exception("Resposta vazia da IA.")
    t = texto.strip()
    t = re.sub(r'^```(json)?', '', t.strip(), flags=re.IGNORECASE).strip()
    t = re.sub(r'```$', '', t.strip()).strip()
    inicio = t.find('{')
    fim = t.rfind('}')
    if inicio == -1 or fim == -1:
        raise Exception("A IA não retornou um JSON reconhecível.")
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

def _validar_resposta_gemini(resp):
    candidatos = getattr(resp, "candidates", None) or []
    if candidatos:
        finish = getattr(candidatos[0], "finish_reason", None)
        finish_str = str(finish) if finish else ""
        if "MAX_TOKENS" in finish_str:
            raise Exception("A resposta da IA foi cortada por limite de tokens.")
        if "SAFETY" in finish_str or "PROHIBITED" in finish_str:
            raise Exception("Bloqueado por política de segurança.")
    if not getattr(resp, "text", None):
        raise Exception("Resposta vazia da IA.")

def _chamar_gemini(chave, itens, response_schema, modelos):
    client = genai.Client(api_key=chave)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        system_instruction=SYSTEM_INSTRUCTION_IDENTIFICACAO,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
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
                if "PERDAY" in erro_str.replace(" ", "") or "FREE_TIER" in erro_str:
                    st.toast(f"⚠️ Cota diária do {modelo} esgotada. Pulando para o próximo modelo...", icon="📅")
                    cota_diaria_esgotada = True
                    break
                elif "429" in erro_str or "RESOURCE_EXHAUSTED" in erro_str or "503" in erro_str or "UNAVAILABLE" in erro_str:
                    if tentativa < 3:
                        tempo_espera = min(tentativa * 3, 10)
                        st.toast(f"⚡ Fila no Google ({modelo}). Tentativa {tentativa}/3...", icon="⏳")
                        time.sleep(tempo_espera)
                        continue
                    break
                elif "404" in erro_str or "NOT_FOUND" in erro_str or "400" in erro_str:
                    st.toast(f"⚠️ Modelo {modelo} indisponível. Pulando...", icon="⏭️")
                    break
                else:
                    raise e
        if cota_diaria_esgotada:
            continue
    raise Exception(f"Google Gemini: todos os modelos falharam. Último erro: {ultimo_erro}")

def _montar_mensagens_openai_like(itens, response_schema):
    texto, imagens = _itens_para_texto_e_imagens(itens)
    texto += _prompt_schema_json(response_schema)
    conteudo_usuario = [{"type": "text", "text": texto}]
    for mime, dados in imagens:
        b64 = base64.b64encode(dados).decode()
        conteudo_usuario.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION_IDENTIFICACAO},
        {"role": "user", "content": conteudo_usuario if imagens else texto},
    ]

def _chamar_groq(chave, itens, response_schema, modelos):
    if Groq is None:
        raise Exception("Biblioteca 'groq' não instalada no servidor.")
    client = Groq(api_key=chave)
    mensagens = _montar_mensagens_openai_like(itens, response_schema)
    ultimo_erro = None
    for modelo in modelos:
        for tentativa in range(1, 4):
            try:
                resp = client.chat.completions.create(model=modelo, messages=mensagens, response_format={"type": "json_object"}, temperature=0.1)
                bruto = _extrair_json_bruto(resp.choices[0].message.content)
                return response_schema.model_validate(json.loads(bruto))
            except Exception as e:
                ultimo_erro = e
                erro_str = str(e).upper()
                if "429" in erro_str or "RATE_LIMIT" in erro_str or "503" in erro_str:
                    if tentativa < 3:
                        time.sleep(min(tentativa * 3, 10))
                        continue
                    break
                elif "404" in erro_str or "NOT_FOUND" in erro_str or isinstance(e, (ValidationError, json.JSONDecodeError)):
                    break
                else:
                    raise e
    raise Exception(f"Groq: todos os modelos falharam. Último erro: {ultimo_erro}")

def _chamar_openrouter(chave, itens, response_schema, modelos):
    if OpenAI is None:
        raise Exception("Biblioteca 'openai' não instalada no servidor.")
    client = OpenAI(api_key=chave, base_url="https://openrouter.ai/api/v1")
    mensagens = _montar_mensagens_openai_like(itens, response_schema)
    ultimo_erro = None
    for modelo in modelos:
        for tentativa in range(1, 4):
            try:
                resp = client.chat.completions.create(model=modelo, messages=mensagens, response_format={"type": "json_object"}, temperature=0.1)
                bruto = _extrair_json_bruto(resp.choices[0].message.content)
                return response_schema.model_validate(json.loads(bruto))
            except Exception as e:
                ultimo_erro = e
                erro_str = str(e).upper()
                if "429" in erro_str or "RATE_LIMIT" in erro_str or "503" in erro_str:
                    if tentativa < 3:
                        time.sleep(min(tentativa * 3, 10))
                        continue
                    break
                elif "404" in erro_str or "NOT_FOUND" in erro_str or isinstance(e, (ValidationError, json.JSONDecodeError)):
                    break
                else:
                    raise e
    raise Exception(f"OpenRouter: todos os modelos falharam. Último erro: {ultimo_erro}")

def _chamar_mistral(chave, itens, response_schema, modelos):
    if Mistral is None:
        raise Exception("Biblioteca 'mistralai' não instalada no servidor.")
    client = Mistral(api_key=chave)
    mensagens = _montar_mensagens_openai_like(itens, response_schema)
    ultimo_erro = None
    for modelo in modelos:
        for tentativa in range(1, 4):
            try:
                resp = client.chat.complete(model=modelo, messages=mensagens, response_format={"type": "json_object"}, temperature=0.1)
                bruto = _extrair_json_bruto(resp.choices[0].message.content)
                return response_schema.model_validate(json.loads(bruto))
            except Exception as e:
                ultimo_erro = e
                erro_str = str(e).upper()
                if "429" in erro_str or "CAPACITY" in erro_str or "503" in erro_str:
                    if tentativa < 3:
                        time.sleep(min(tentativa * 3, 10))
                        continue
                    break
                elif "404" in erro_str or "NOT_FOUND" in erro_str or isinstance(e, (ValidationError, json.JSONDecodeError)):
                    break
                else:
                    raise e
    raise Exception(f"Mistral AI: todos os modelos falharam. Último erro: {ultimo_erro}")

def _chamar_por_motor(motor, chave, itens, response_schema, modelos):
    if motor == "gemini":
        return _chamar_gemini(chave, itens, response_schema, modelos)
    elif motor == "groq":
        return _chamar_groq(chave, itens, response_schema, modelos)
    elif motor == "openrouter":
        return _chamar_openrouter(chave, itens, response_schema, modelos)
    elif motor == "mistral":
        return _chamar_mistral(chave, itens, response_schema, modelos)
    raise Exception(f"Provedor desconhecido: {motor}")

def executar_com_fallback(chave, itens, response_schema, provedor):
    cfg = PROVEDORES_IA[provedor]
    try:
        return _chamar_por_motor(cfg["motor"], chave, itens, response_schema, cfg["modelos"])
    except Exception as erro_provedor_escolhido:
        outros = [p for p in PROVEDORES_IA if p != provedor]
        ultimo_erro = erro_provedor_escolhido
        for nome_alt in outros:
            chave_alt = obter_chave_provedor(nome_alt)
            if not chave_alt:
                continue
            try:
                st.toast(f"🔀 {provedor} indisponível. Tentando com {nome_alt}...", icon="🔁")
                cfg_alt = PROVEDORES_IA[nome_alt]
                return _chamar_por_motor(cfg_alt["motor"], chave_alt, itens, response_schema, cfg_alt["modelos"])
            except Exception as e2:
                ultimo_erro = e2
                continue
        raise Exception(f"{provedor} falhou e nenhum provedor alternativo configurado deu certo. Último erro: {ultimo_erro}")

def converter_para_iso(data_str):
    if not data_str:
        return None
    data_str = str(data_str).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', data_str):
        return data_str
    match_br = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', data_str)
    if match_br:
        d, m, a = match_br.groups()
        return f"{a}-{m}-{d}"
    try:
        return datetime.strptime(data_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        return None

# ----------------- EXTRAÇÃO DE CONTEÚDO DO PDF (mesma técnica do Autopilot) -----------------
@st.cache_data(show_spinner=False, max_entries=20)
def extrair_conteudo_cache(file_bytes, nome_arquivo):
    return extrair_conteudo_multimodal(file_bytes, nome_arquivo)

def extrair_conteudo_multimodal(file_bytes, nome_arquivo):
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        html_text = f"CONTEÚDO DO ARQUIVO {nome_arquivo}:\n\n"
        caracteres_uteis = 0
        for page_num, page in enumerate(doc):
            html_text += f"=== PÁGINA {page_num + 1} ===\n"
            page_text = page.get_text()
            html_text += page_text + "\n"
            caracteres_uteis += len(page_text.strip())
        if caracteres_uteis < 30 * max(doc.page_count, 1):
            partes = [f"ARQUIVO {nome_arquivo} É UM DOCUMENTO ESCANEADO. Leia visualmente:"]
            for page_num, page in enumerate(doc):
                if page_num >= 15:
                    partes.append("[Nota: apenas as primeiras 15 páginas foram convertidas em imagem.]")
                    break
                pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4))
                partes.append({"tipo": "imagem", "mime": "image/jpeg", "dados": pix.tobytes("jpg", jpg_quality=75)})
            return partes
        return [html_text]
    except Exception as e:
        return [f"Erro ao extrair PDF {nome_arquivo}: {str(e)}"]

# ----------------- ESTRUTURAS PYDANTIC -----------------
class AtoReferenciado(BaseModel):
    tipo_operacao: str = Field(description="'altera', 'acrescenta', 'revoga_parcial' ou 'revoga_integral'")
    tipo_ato_afetado: str
    numero_ato_afetado: str
    dispositivo_afetado: Optional[str] = None
    resumo_alteracao: Optional[str] = ""

class IdentificacaoAto(BaseModel):
    tipo_documento: str
    numero_documento: str
    orgao_emissor: str
    data_assinatura: str
    nome_padronizado: str
    ementa: Optional[str] = ""
    e_documento_alterador: bool
    atos_referenciados: List[AtoReferenciado] = Field(default_factory=list)

# ----------------- CRUZAMENTO COM O BANCO -----------------
def localizar_no_banco(numero_ref, tipo_ref=None):
    numero_limpo = str(numero_ref or "").strip()
    if not numero_limpo:
        return None, None
    try:
        res = supabase.table("portarias_base").select(
            "id, nome_padronizado, tipo_documento, numero_documento, data_assinatura"
        ).ilike("numero_documento", f"%{numero_limpo}%").execute()
        if res.data:
            return "portarias_base", res.data[0]
    except Exception:
        pass
    try:
        res2 = supabase.table("atos_importados").select(
            "id, nome_arquivo_original, tipo_documento, numero_documento, status"
        ).ilike("numero_documento", f"%{numero_limpo}%").execute()
        if res2.data:
            return "atos_importados", res2.data[0]
    except Exception:
        pass
    return None, None

def buscar_dependentes_pendentes(numero_documento):
    numero_limpo = str(numero_documento or "").strip()
    if not numero_limpo:
        return []
    try:
        res = supabase.table("atos_importados").select("*").eq("status", "pendente").ilike(
            "ato_base_referenciado_numero", f"%{numero_limpo}%"
        ).execute()
        return res.data or []
    except Exception:
        return []

def ja_existe_pendente(numero_documento, numero_ato_afetado):
    try:
        res = supabase.table("atos_importados").select("id").eq("status", "pendente").eq(
            "numero_documento", numero_documento
        ).eq("ato_base_referenciado_numero", numero_ato_afetado).execute()
        return bool(res.data)
    except Exception:
        return False

def ja_existe_leitura(numero_documento):
    try:
        res = supabase.table("atos_importados").select("id").eq(
            "numero_documento", numero_documento
        ).is_("ato_base_referenciado_numero", "null").execute()
        return bool(res.data)
    except Exception:
        return False

def salvar_pendencia(nome_arquivo, texto_integra, identificacao: dict, ref: dict):
    if ja_existe_pendente(identificacao["numero_documento"], ref["numero_ato_afetado"]):
        return False
    try:
        supabase.table("atos_importados").insert({
            "nome_arquivo_original": nome_arquivo,
            "texto_integra": texto_integra[:100000],
            "tipo_documento": identificacao.get("tipo_documento"),
            "numero_documento": identificacao.get("numero_documento"),
            "data_assinatura": converter_para_iso(identificacao.get("data_assinatura")),
            "orgao_emissor": identificacao.get("orgao_emissor"),
            "ato_base_referenciado_tipo": ref.get("tipo_ato_afetado"),
            "ato_base_referenciado_numero": ref.get("numero_ato_afetado"),
            "status": "pendente",
            "estrutura_json": identificacao,
        }).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar pendência no banco: {e}")
        return False

def salvar_leitura(nome_arquivo, texto_integra, identificacao: dict):
    """Sempre registra o documento lido no banco (sem vínculo de pendência), mesmo quando ele
    não altera/revoga nada ou quando todas as referências já foram resolvidas. Isso garante que,
    caso algum outro Ato apareça futuramente alterando ou revogando este documento, o cruzamento
    o encontre."""
    if ja_existe_leitura(identificacao.get("numero_documento")):
        return False
    try:
        supabase.table("atos_importados").insert({
            "nome_arquivo_original": nome_arquivo,
            "texto_integra": texto_integra[:100000],
            "tipo_documento": identificacao.get("tipo_documento"),
            "numero_documento": identificacao.get("numero_documento"),
            "data_assinatura": converter_para_iso(identificacao.get("data_assinatura")),
            "orgao_emissor": identificacao.get("orgao_emissor"),
            "ato_base_referenciado_tipo": None,
            "ato_base_referenciado_numero": None,
            "status": "identificado",
            "estrutura_json": identificacao,
        }).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar leitura no banco: {e}")
        return False

def atualizar_status_pendencia(id_pendencia, novo_status):
    try:
        supabase.table("atos_importados").update({"status": novo_status}).eq("id", id_pendencia).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao atualizar status: {e}")
        return False

# ----------------- PROCESSAMENTO DE UM ARQUIVO -----------------
def processar_arquivo(arquivo, api_key, provedor):
    file_bytes = arquivo.getvalue()
    itens = extrair_conteudo_cache(file_bytes, arquivo.name)
    prompt = [f"Identifique os metadados deste documento e detecte se ele altera/acrescenta/revoga outro ato. ARQUIVO: {arquivo.name}"]
    prompt.extend(itens)
    resultado = executar_com_fallback(api_key.strip(), prompt, IdentificacaoAto, provedor)
    identificacao = resultado.model_dump()

    texto_integra, _ = _itens_para_texto_e_imagens(itens)
    if not texto_integra:
        texto_integra = f"[Documento {arquivo.name} extraído via OCR de imagem]"

    achados = []
    algum_pendente = False
    if identificacao.get("e_documento_alterador"):
        for ref in identificacao.get("atos_referenciados", []):
            origem, registro = localizar_no_banco(ref.get("numero_ato_afetado"), ref.get("tipo_ato_afetado"))
            salvo_pendente = False
            if origem is None:
                salvo_pendente = salvar_pendencia(arquivo.name, texto_integra, identificacao, ref)
                algum_pendente = True
            achados.append({"ref": ref, "origem": origem, "registro": registro, "salvo_pendente": salvo_pendente})

    # Todo documento lido é sempre persistido no banco (mesmo sem pendência aberta), pois
    # futuramente outro Ato pode vir a alterá-lo ou revogá-lo e precisa encontrá-lo no cruzamento.
    salvo_leitura = False
    if not algum_pendente:
        salvo_leitura = salvar_leitura(arquivo.name, texto_integra, identificacao)

    dependentes = buscar_dependentes_pendentes(identificacao.get("numero_documento"))

    return {
        "arquivo": arquivo.name,
        "identificacao": identificacao,
        "achados": achados,
        "dependentes": dependentes,
        "salvo_leitura": salvo_leitura,
    }

# ----------------- FRONT-END -----------------
st.markdown("""
Envie um ou mais Atos normativos em PDF. O sistema identifica **tipo, número, órgão e data**,
detecta se o documento **altera, acrescenta ou revoga** algum outro Ato e **cruza automaticamente**
essa informação com o que já existe no banco de dados (Atos consolidados e pendências anteriores),
avisando quando encontrar correlações para que você possa trabalhar nelas no Autopilot.
""")

provedor_escolhido = st.selectbox("🧠 Motor de IA", list(PROVEDORES_IA.keys()), key="provedor_ia_identificar")
cfg_provedor = PROVEDORES_IA[provedor_escolhido]
api_key = obter_chave_provedor(provedor_escolhido)
if not api_key:
    api_key = st.text_input(f"Chave da API ({cfg_provedor['secret']} não encontrada nos secrets)", type="password", key="api_key_identificar")

arquivos_enviados = st.file_uploader("Arraste os Atos normativos (PDF) para identificar e cruzar", type=["pdf"], accept_multiple_files=True, key="uploader_identificar")

if st.button("🔎 Identificar e Cruzar", type="primary", use_container_width=True):
    if not api_key:
        st.error("⚠️ Insira sua chave da API.")
    elif not arquivos_enviados:
        st.warning("⚠️ Envie ao menos um arquivo PDF.")
    else:
        resultados = []
        with st.spinner("⚡ Lendo documentos e cruzando com o banco de dados..."):
            with ThreadPoolExecutor(max_workers=min(4, len(arquivos_enviados))) as ex:
                futuros = {submit_com_contexto(ex, processar_arquivo, arq, api_key, provedor_escolhido): arq.name for arq in arquivos_enviados}
                for fut in as_completed(futuros):
                    nome = futuros[fut]
                    try:
                        resultados.append(fut.result())
                    except Exception as e:
                        resultados.append({"arquivo": nome, "erro": str(e)})
        st.session_state.resultados_identificacao = resultados

if st.session_state.get("resultados_identificacao"):
    st.markdown("---")
    st.markdown("## 📋 Resultado da Identificação e Cruzamento")
    # Verifica se há correlações encontradas para emitir alerta
    tem_correlacao = False
    for res in st.session_state.resultados_identificacao:
        if "erro" not in res:
            for achado in res.get("achados", []):
                if achado.get("origem") is not None:
                    tem_correlacao = True
                    break
        if tem_correlacao:
            break
    if tem_correlacao:
        st.success("🔔 **Alerta!** Foram encontradas correlações com Atos já existentes no banco. Consolide-os na página 'Consolidar Norma'.")

    for res in st.session_state.resultados_identificacao:
        if "erro" in res:
            st.error(f"❌ **{res['arquivo']}**: {res['erro']}")
            continue

        ident = res["identificacao"]
        with st.expander(f"📄 {ident.get('nome_padronizado', res['arquivo'])}", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f"**Tipo:**\n{ident.get('tipo_documento', '—')}")
            c2.markdown(f"**Número:**\n{ident.get('numero_documento', '—')}")
            c3.markdown(f"**Órgão:**\n{ident.get('orgao_emissor', '—')}")
            c4.markdown(f"**Data:**\n{ident.get('data_assinatura', '—')}")
            if ident.get("ementa"):
                st.caption(f"Ementa: {ident['ementa']}")

            if res.get("salvo_leitura"):
                st.caption("💾 Documento salvo no banco para consulta em cruzamentos futuros.")
            elif not any(a.get("salvo_pendente") for a in res.get("achados", [])):
                st.caption("💾 Documento já constava no banco (leitura anterior).")

            if not ident.get("e_documento_alterador"):
                st.info("ℹ️ Este documento **não** altera nem revoga outro Ato — é um Ato base/original.")
            else:
                st.markdown("#### 🔗 Atos referenciados (alterados/revogados por este documento)")
                if not res["achados"]:
                    st.warning("A IA identificou o documento como alterador, mas não conseguiu extrair o(s) ato(s) referenciado(s).")
                for achado in res["achados"]:
                    ref = achado["ref"]
                    op = ref.get("tipo_operacao", "altera")
                    descricao_ref = f"{ref.get('tipo_ato_afetado', '')} Nº {ref.get('numero_ato_afetado', '')}".strip()
                    if achado["origem"] == "portarias_base":
                        reg = achado["registro"]
                        st.markdown(f"""
<div class="card-achado correlacionado">
✅ <b>Correlacionado</b> — {op.replace('_', ' ')} <b>{descricao_ref}</b><br/>
Ato base já consolidado no banco: <b>{reg.get('nome_padronizado')}</b><br/>
{ref.get('resumo_alteracao', '')}<br/>
<i>Envie este arquivo junto ao Ato base no Autopilot para gerar a nova versão consolidada.</i>
</div>""", unsafe_allow_html=True)
                    elif achado["origem"] == "atos_importados":
                        reg = achado["registro"]
                        st.markdown(f"""
<div class="card-achado correlacionado">
✅ <b>Correlacionado</b> — {op.replace('_', ' ')} <b>{descricao_ref}</b><br/>
Já existe outro arquivo pendente no banco referenciando o mesmo Ato base: <b>{reg.get('nome_arquivo_original')}</b><br/>
{ref.get('resumo_alteracao', '')}<br/>
<i>Reúna os arquivos correlacionados e processe-os juntos no Autopilot.</i>
</div>""", unsafe_allow_html=True)
                    else:
                        status_txt = "salvo como pendência no banco" if achado["salvo_pendente"] else "já registrado como pendência"
                        st.markdown(f"""
<div class="card-achado pendente">
⏳ <b>Pendente</b> — {op.replace('_', ' ')} <b>{descricao_ref}</b><br/>
O Ato base ainda não foi encontrado no banco de dados ({status_txt}).<br/>
{ref.get('resumo_alteracao', '')}<br/>
<i>Assim que você enviar o Ato base correspondente, esta correlação será identificada automaticamente.</i>
</div>""", unsafe_allow_html=True)

            if res["dependentes"]:
                st.markdown("#### 📌 Arquivos pendentes que estavam esperando por este Ato")
                for dep in res["dependentes"]:
                    st.markdown(f"""
<div class="card-achado correlacionado">
✅ <b>{dep.get('nome_arquivo_original')}</b> ({dep.get('tipo_documento')} Nº {dep.get('numero_documento')})
já estava aguardando este Ato como base.<br/>
<i>Estes arquivos agora podem ser processados juntos no Autopilot.</i>
</div>""", unsafe_allow_html=True)

    if st.button("🔄 Nova Identificação", type="secondary"):
        st.session_state.resultados_identificacao = None
        st.rerun()