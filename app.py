# app.py - Página principal: login + "Identificar e Cruzar"
import streamlit as st
import os
import re
import json
import time
import base64
import threading
from html import escape
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
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
from menu_utils import configurar_pagina, renderizar_cabecalho, renderizar_menu, processar_cookies
from db_utils import obter_supabase, obter_repositorio, kpis_cache
import concorrencia as conc
import ui_theme as ui

configurar_pagina("Identificar e Cruzar", "⚖️")

supabase = obter_supabase()
repo = obter_repositorio()


def _com_vaga(fn, *a, **kw):
    """Toda chamada de IA passa por um semáforo GLOBAL: 2+ usuários processando juntos não estouram a cota do provedor."""
    with conc.vaga_ia():
        return fn(*a, **kw)


# =====================================================================
# LOGIN
# =====================================================================
def autenticar(usuario, senha):
    """Retorna (ok, mensagem, papel, nome_canonico)."""
    usuario = (usuario or "").strip()
    if not usuario or not senha:
        return False, "Informe usuário e senha.", None, None
    reg = conc.registro()
    espera = reg.segundos_bloqueado(usuario)
    if espera:
        return False, f"Muitas tentativas incorretas. Aguarde {espera}s para tentar novamente.", None, None
    if not supabase:
        return False, "Erro de conexão com o banco de dados.", None, None
    try:
        res = supabase.table("usuarios").select("*").eq("username", usuario).execute()
    except Exception as e:
        return False, f"Erro ao verificar credenciais: {e}", None, None
    if res.data:
        row = res.data[0]
        ok, precisa_migrar = verificar_senha(senha, row.get("password_hash"))
        if ok:
            if precisa_migrar:
                try:
                    supabase.table("usuarios").update({"password_hash": gerar_hash_senha(senha)}).eq("id", row["id"]).execute()
                except Exception:
                    pass
            nome = row.get("username") or usuario
            papel_db = str(row.get("role") or row.get("papel") or "").lower()
            papel = "admin" if (papel_db == "admin" or nome.lower() == "admin") else "usuario"
            return True, "", papel, nome
    bloqueio = reg.registrar_falha(usuario)
    if bloqueio:
        return False, f"Muitas tentativas incorretas. Acesso bloqueado por {bloqueio}s.", None, None
    return False, "Usuário ou senha incorretos.", None, None


conc.restaurar_sessao_por_cookie()
if not st.session_state.get("autenticado", False):
    processar_cookies()
    with st.container(key="login_shell"):
        col_e, col_d = st.columns([1.12, 0.88], gap="small")
        with col_e:
            with st.container(key="login_left"):
                st.markdown(f"""
{ui.marca("Normas e Atos")}
<div class="cn-lg-titulo">Normas sempre <em>consolidadas</em>,<br>sem retrabalho.</div>
<p class="cn-lg-sub">Leia atos em PDF, descubra o que eles alteram ou revogam e gere as versões alterada e consolidada com taxação automática.</p>
<ul class="cn-lg-lista">
  <li><span class="cn-ico-box">{ui.icone("search", 18)}</span>Identifica atos alteradores e cruza com o banco</li>
  <li><span class="cn-ico-box">{ui.icone("merge", 18)}</span>Aplica alterações em ordem cronológica</li>
  <li><span class="cn-ico-box">{ui.icone("shield", 18)}</span>Vários usuários trabalhando ao mesmo tempo, com segurança</li>
</ul>
<div class="cn-demo" aria-hidden="true">
  <div class="t">Art. 4º · demonstração</div>
  <span class="velho">Art. 4º O prazo de instrução é de trinta dias.</span>
  <span class="novo">Art. 4º O prazo de instrução é de sessenta dias. <span class="nota">(Redação dada pelo Art. 2º da Portaria nº 30/PGJM)</span></span>
</div>
""", unsafe_allow_html=True)
        with col_d:
            with st.container(key="login_right"):
                st.markdown('<div class="cn-lg-saud">Bem-vindo de volta</div><p>Acesse com seu usuário institucional.</p>', unsafe_allow_html=True)
                with st.form("form_login", border=False):
                    usuario = st.text_input("Usuário", placeholder="ex.: maria.silva", autocomplete="username")
                    senha = st.text_input("Senha", type="password", placeholder="Sua senha", autocomplete="current-password")
                    entrar = st.form_submit_button("Entrar no sistema", type="primary", use_container_width=True, icon=":material/login:")
                if entrar:
                    with st.spinner("Verificando credenciais..."):
                        ok, msg, papel, nome = autenticar(usuario, senha)
                    if ok:
                        conc.iniciar_sessao(nome, papel)
                        st.rerun()
                    else:
                        st.error(msg, icon=":material/error:")
                st.markdown(f'<div class="cn-seguro">{ui.icone("lock", 15)} Conexão protegida · senhas com PBKDF2 · sessões independentes por usuário</div>', unsafe_allow_html=True)
    st.stop()

processar_cookies()

# =====================================================================
# APÓS LOGIN: IDENTIFICAR E CRUZAR
# =====================================================================
renderizar_menu("inicio")
if not supabase:
    st.error("Não foi possível conectar ao Supabase. Verifique os Secrets (supabase.url / supabase.key).", icon=":material/cloud_off:")
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
        "modelos": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
        "secret": "GROQ_API_KEY",
    },
    "OpenRouter (Qwen / DeepSeek / Llama)": {
        "motor": "openrouter",
        "modelos": ["deepseek/deepseek-v4-flash", "qwen/qwen3.5-plus-20260420", "meta-llama/llama-4-maverick"],
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
       - 'tipo_operacao': exatamente um destes: "altera", "acrescenta", "revoga_parcial",
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
                resp = _com_vaga(client.models.generate_content, model=modelo, contents=contents, config=config)
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
                resp = _com_vaga(client.chat.completions.create, model=modelo, messages=mensagens, response_format={"type": "json_object"}, temperature=0.1)
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
                resp = _com_vaga(client.chat.completions.create, model=modelo, messages=mensagens, response_format={"type": "json_object"}, temperature=0.1)
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
                elif "404" in erro_str or "NOT_FOUND" in erro_str or "NOT A VALID MODEL" in erro_str or "400" in erro_str or "402" in erro_str or "CREDITS" in erro_str or isinstance(e, (ValidationError, json.JSONDecodeError)):
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
                resp = _com_vaga(client.chat.complete, model=modelo, messages=mensagens, response_format={"type": "json_object"}, temperature=0.1)
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


# ----------------- PROCESSAMENTO DE UM ARQUIVO (banco via repositório thread-safe) -----------------
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
            origem, registro = repo.localizar_no_banco(ref.get("numero_ato_afetado"), ref.get("tipo_ato_afetado"))
            salvo_pendente = False
            if origem is None:
                salvo_pendente = repo.salvar_pendencia(arquivo.name, texto_integra, identificacao, ref)
                algum_pendente = True
            achados.append({"ref": ref, "origem": origem, "registro": registro, "salvo_pendente": salvo_pendente})

    salvo_leitura = False
    if not algum_pendente:
        salvo_leitura = repo.salvar_leitura(arquivo.name, texto_integra, identificacao)

    dependentes = repo.buscar_dependentes_pendentes(identificacao.get("numero_documento"))
    return {"arquivo": arquivo.name, "identificacao": identificacao, "achados": achados, "dependentes": dependentes, "salvo_leitura": salvo_leitura}


# ----------------- FRONT-END -----------------
ss = st.session_state
ss.setdefault("resultados_identificacao", None)
ss.setdefault("uploader_ver", 0)

renderizar_cabecalho(
    "Identificação e cruzamento de atos",
    "Envie um ou mais atos em PDF. O sistema identifica tipo, número, órgão e data, detecta o que cada ato altera ou revoga "
    "e cruza com o banco para avisar quando houver correlações a consolidar.",
    etiqueta="Passo 1 · Leitura inteligente", icone_nome="search")

k = kpis_cache()
ui.kpis([
    ("Normas consolidadas", k.get("normas"), "layers", "ok"),
    ("Atos identificados", k.get("identificados"), "file", "info"),
    ("Pendências abertas", k.get("pendentes"), "clock", "warn"),
    ("Alterações vinculadas", k.get("alteradoras"), "link", "rosa"),
])

resultados = ss.resultados_identificacao

with st.container(border=True):
    c_ia, c_chave = st.columns([1, 1.2], vertical_alignment="bottom")
    with c_ia:
        provedor_escolhido = st.selectbox("Motor de IA", list(PROVEDORES_IA.keys()), key="provedor_ia_identificar")
    cfg_provedor = PROVEDORES_IA[provedor_escolhido]
    api_key = obter_chave_provedor(provedor_escolhido)
    with c_chave:
        if api_key:
            st.markdown(ui.badge("Chave de API configurada nos Secrets", "ok", pulso=True), unsafe_allow_html=True)
        else:
            api_key = st.text_input(f"Chave da API ({cfg_provedor['secret']} não encontrada nos secrets)", type="password", key="api_key_identificar")
    arquivos_enviados = st.file_uploader("Arraste os atos normativos (PDF) para identificar e cruzar", type=["pdf"], accept_multiple_files=True,
                                         key=f"uploader_identificar_{ss.uploader_ver}")
    iniciar = st.button("Identificar e cruzar", type="primary", use_container_width=True, icon=":material/travel_explore:", disabled=not arquivos_enviados)

ui.fluxo(["Enviar PDFs", "Leitura por IA", "Cruzamento com o banco", "Resultado"], 4 if resultados else (1 if arquivos_enviados else 0))

if iniciar:
    if not api_key:
        st.error("Insira sua chave da API.", icon=":material/key:")
    else:
        resultados = []
        with st.status(f"Processando {len(arquivos_enviados)} arquivo(s)...", expanded=True) as status:
            status.write("Lendo PDFs, extraindo texto e consultando a IA em paralelo.")
            with ThreadPoolExecutor(max_workers=min(4, len(arquivos_enviados))) as ex:
                futuros = {submit_com_contexto(ex, processar_arquivo, arq, api_key, provedor_escolhido): arq.name for arq in arquivos_enviados}
                for fut in as_completed(futuros):
                    nome = futuros[fut]
                    try:
                        resultados.append(fut.result())
                        status.write(f"✓ {nome} lido e cruzado")
                    except Exception as e:
                        resultados.append({"arquivo": nome, "erro": str(e)})
                        status.write(f"✗ {nome} falhou")
            status.update(label="Identificação concluída", state="complete", expanded=False)
        ss.resultados_identificacao = resultados
        conc.auditar("identificar", f"{len(resultados)} arquivo(s)")
        st.rerun()

if resultados:
    ok_res = [r for r in resultados if "erro" not in r]
    n_alt = sum(1 for r in ok_res if r["identificacao"].get("e_documento_alterador"))
    n_corr = sum(1 for r in ok_res for a in r.get("achados", []) if a.get("origem") is not None)
    n_pend = sum(1 for r in ok_res for a in r.get("achados", []) if a.get("origem") is None)
    st.markdown("### Resultado da identificação")
    ui.kpis([
        ("Arquivos lidos", len(ok_res), "file", "info"),
        ("Atos alteradores", n_alt, "merge", ""),
        ("Correlações encontradas", n_corr, "link", "ok"),
        ("Novas pendências", n_pend, "clock", "warn"),
    ])
    if n_corr:
        st.success("Foram encontradas correlações com atos já existentes no banco. Consolide-os na página **Consolidar**.", icon=":material/notifications_active:")

    for res in resultados:
        if "erro" in res:
            st.error(f"**{res['arquivo']}**: {res['erro']}", icon=":material/error:")
            continue
        ident = res["identificacao"]
        with st.expander(ident.get("nome_padronizado") or res["arquivo"], expanded=True, icon=":material/description:"):
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f"**Tipo**<br>{escape(str(ident.get('tipo_documento') or '—'))}", unsafe_allow_html=True)
            c2.markdown(f"**Número**<br>{escape(str(ident.get('numero_documento') or '—'))}", unsafe_allow_html=True)
            c3.markdown(f"**Órgão**<br>{escape(str(ident.get('orgao_emissor') or '—'))}", unsafe_allow_html=True)
            c4.markdown(f"**Data**<br>{escape(str(ident.get('data_assinatura') or '—'))}", unsafe_allow_html=True)
            if ident.get("ementa"):
                st.caption(f"Ementa: {ident['ementa']}")
            if res.get("salvo_leitura"):
                st.markdown(ui.badge("Salvo no banco para cruzamentos futuros", "ok"), unsafe_allow_html=True)
            elif not any(a.get("salvo_pendente") for a in res.get("achados", [])):
                st.markdown(ui.badge("Já constava no banco", "info"), unsafe_allow_html=True)

            if not ident.get("e_documento_alterador"):
                ui.cartao(f'{ui.icone("info", 17)} Ato base / original', "<p>Este documento <b>não</b> altera nem revoga outro ato.</p>", "info")
            else:
                st.markdown("##### Atos referenciados (alterados ou revogados por este documento)")
                if not res["achados"]:
                    st.warning("A IA identificou o documento como alterador, mas não conseguiu extrair o(s) ato(s) referenciado(s).")
                for achado in res["achados"]:
                    ref = achado["ref"]
                    op = escape(str(ref.get("tipo_operacao", "altera")).replace("_", " "))
                    descricao_ref = escape(f"{ref.get('tipo_ato_afetado', '')} Nº {ref.get('numero_ato_afetado', '')}".strip())
                    resumo = escape(str(ref.get("resumo_alteracao") or ""))
                    if achado["origem"] == "portarias_base":
                        reg = achado["registro"]
                        ui.cartao(f'{ui.icone("check", 17)} Correlacionado · {op} {descricao_ref}',
                                  f"<p>Ato base já consolidado no banco: <b>{escape(str(reg.get('nome_padronizado')))}</b></p><p>{resumo}</p>",
                                  "ok", "Envie este arquivo junto ao ato base em <b>Consolidar</b> para gerar a nova versão consolidada.")
                    elif achado["origem"] == "atos_importados":
                        reg = achado["registro"]
                        ui.cartao(f'{ui.icone("check", 17)} Correlacionado · {op} {descricao_ref}',
                                  f"<p>Já existe outro arquivo no banco referenciando o mesmo ato base: <b>{escape(str(reg.get('nome_arquivo_original')))}</b></p><p>{resumo}</p>",
                                  "ok", "Reúna os arquivos correlacionados e processe-os juntos em <b>Consolidar</b>.")
                    else:
                        status_txt = "salvo como pendência no banco" if achado["salvo_pendente"] else "já registrado como pendência"
                        ui.cartao(f'{ui.icone("clock", 17)} Pendente · {op} {descricao_ref}',
                                  f"<p>O ato base ainda não foi encontrado no banco ({status_txt}).</p><p>{resumo}</p>",
                                  "warn", "Assim que você enviar o ato base correspondente, esta correlação será identificada automaticamente.")

            if res["dependentes"]:
                st.markdown("##### Arquivos pendentes que esperavam por este ato")
                for dep in res["dependentes"]:
                    ui.cartao(f'{ui.icone("link", 17)} {escape(str(dep.get("nome_arquivo_original")))}',
                              f"<p>{escape(str(dep.get('tipo_documento')))} Nº {escape(str(dep.get('numero_documento')))} já aguardava este ato como base.</p>",
                              "ok", "Estes arquivos agora podem ser processados juntos em <b>Consolidar</b>.")

    if st.button("Nova identificação", type="secondary", icon=":material/restart_alt:"):
        ss.resultados_identificacao = None
        ss.uploader_ver += 1
        st.rerun()

with st.expander("Atividade recente da equipe", icon=":material/history:"):
    eventos = list(conc.registro().auditoria)[:8]
    if not eventos:
        st.caption("Nenhuma atividade registrada desde o último reinício do servidor.")
    for ev in eventos:
        quando = time.strftime("%H:%M:%S", time.localtime(ev["quando"]))
        st.markdown(f'{ui.avatar(ev["usuario"])} &nbsp; **{escape(ev["usuario"])}** · {escape(ev["acao"].replace("_", " "))} '
                    f'<span style="color:#64748B">— {escape(ev["detalhe"])} · {quando}</span>', unsafe_allow_html=True)

st.markdown('<div class="cn-rodape">Autopilot Normativo · Consolidação de Normas e Atos</div>', unsafe_allow_html=True)
