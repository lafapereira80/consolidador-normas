# pages/3_Consolidar_Norma.py - Consolidação de normas (Autopilot)
import streamlit as st
import json
import os
import re
import time
import copy
import hashlib
import unicodedata
import base64
import traceback
from html import escape, unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import random
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional

import fitz  # PyMuPDF
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

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from menu_utils import configurar_pagina, exigir_login, renderizar_cabecalho, renderizar_menu
from db_utils import obter_supabase, obter_repositorio, kpis_cache
import concorrencia as conc
import ui_theme as ui
import exportacao
from pdf_extrator import criar_pool, extrair_conteudo as _extrair_pdf
from exportacao import editor_para_pdf, gerar_html_dinamico, gerar_pdf_dinamico, gerar_docx_dinamico

configurar_pagina("Consolidar Norma", "⚙️")
exigir_login()

supabase = obter_supabase()
repo = obter_repositorio()
renderizar_menu("consolidar")
if not supabase:
    st.error("Não foi possível conectar ao Supabase. Verifique os Secrets.", icon=":material/cloud_off:")
    st.stop()
renderizar_cabecalho("Consolidação de normas", "Envie um ato base e seus derivativos em PDF. O sistema aplica as alterações em ordem cronológica e gera as versões "
                     "alterada e consolidada, com taxação das alterações e revogações.", etiqueta="Autopilot", icone_nome="merge")


_TIMEOUT_IA_S = 180
_clientes_ia, _clientes_lock = {}, threading.Lock()

def _cliente(chave_cache, fabrica):
    """Reaproveita o cliente HTTP (conexão keep-alive) em vez de criar um novo a cada chamada."""
    with _clientes_lock:
        if chave_cache not in _clientes_ia:
            _clientes_ia[chave_cache] = fabrica()
        return _clientes_ia[chave_cache]

def _espera(tentativa):
    """Backoff exponencial com jitter (evita todas as threads baterem no limite ao mesmo tempo)."""
    return min(2 ** tentativa + random.random() * 1.5, 15)

@st.cache_resource(show_spinner=False)
def _pool_pdf():
    try:
        return criar_pool()
    except Exception:
        return None

@st.cache_data(ttl=300, show_spinner=False)
def _memoria_cache():
    return repo.resgatar_memoria()

def _com_vaga(fn, *a, **kw):
    """Toda chamada de IA passa por um semáforo GLOBAL (todos os usuários e abas compartilham a cota do provedor)."""
    with conc.vaga_ia():
        return fn(*a, **kw)


# Acesso ao banco via repositório thread-safe (mesmos nomes usados pelo restante do código)
def resgatar_memoria():
    return _memoria_cache()


def _localizar_base_no_banco(tipo_ref, numero_ref):
    return repo.localizar_base(tipo_ref, numero_ref)


def _consultar_estado_e_historico(nome_padrao):
    return repo.consultar_estado_e_historico(nome_padrao)


# ----------------- HUB MULTI-IA (mesmo do app.py) -----------------
from ia_config import PROVEDORES_IA

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

# =====================================================================
# MOTOR DE PARSER HTML/XML (ÁRVORE SINTÁTICA AST)
# =====================================================================


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


# =====================================================================
# LÓGICA DE NEGÓCIO E INTELIGÊNCIA ARTIFICIAL
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
   'tabela_consolidada' sempre reflete a versão vigente (mais recente) da tabela.
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
   (conforme definido no sistema original)
7. ANEXOS E CONTEÚDO PÓS-ASSINATURA: OBRIGATÓRIO ler e transcrever TODO o conteúdo após a assinatura.
8. REVOGAÇÃO INTEGRAL: todos os dispositivos do ato revogado devem ser integralmente taxados.
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

TRIAGEM_CHARS_INICIO = 4500
TRIAGEM_CHARS_FIM = 1500

def _resumo_triagem(nome, partes):
    """A triagem só precisa de tipo/número/órgão/data/ato citado: início + fim do ato (assinatura). Antes eram enviados
    TODOS os PDFs inteiros (dezenas de milhares de tokens) só para classificar."""
    texto, imagens = _itens_para_texto_e_imagens(partes)
    saida = []
    if imagens:
        sel = imagens[:2] + ([imagens[-1]] if len(imagens) > 2 else [])
        saida.append(f"ARQUIVO {nome} (escaneado; páginas iniciais e final):")
        saida.extend({"tipo": "imagem", "mime": m, "dados": d} for m, d in sel)
        return saida
    if len(texto) > TRIAGEM_CHARS_INICIO + TRIAGEM_CHARS_FIM:
        texto = texto[:TRIAGEM_CHARS_INICIO] + "\n[... trecho intermediário omitido ...]\n" + texto[-TRIAGEM_CHARS_FIM:]
    return [texto]

def _itens_para_parts_gemini(itens):
    partes = []
    for it in itens:
        if isinstance(it, dict) and it.get("tipo") == "imagem":
            partes.append(types.Part.from_bytes(data=it["dados"], mime_type=it["mime"]))
        elif isinstance(it, str):
            partes.append(it)
    return partes

def _chamar_gemini(chave, itens, response_schema, thinking_level, modelos):
    client = _cliente(("gemini", chave), lambda: genai.Client(api_key=chave, http_options=types.HttpOptions(timeout=_TIMEOUT_IA_S * 1000)))
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
                        tempo_espera = _espera(tentativa)
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

def _validar_resposta_gemini(resp):
    candidatos = getattr(resp, "candidates", None) or []
    if candidatos:
        finish = getattr(candidatos[0], "finish_reason", None)
        finish_str = str(finish) if finish else ""
        if "MAX_TOKENS" in finish_str: raise Exception("A resposta da IA foi cortada por limite de tokens.")
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
    if not PROVEDORES_IA["Groq (GPT-OSS)"].get("visao", True) and _itens_para_texto_e_imagens(itens)[1]:
        raise Exception("Groq (GPT-OSS) não processa imagens (modelos somente texto); usando outro provedor.")
    if Groq is None: raise Exception("Biblioteca 'groq' não instalada no servidor.")
    client = _cliente(("groq", chave), lambda: Groq(api_key=chave, timeout=_TIMEOUT_IA_S, max_retries=0))
    mensagens = _montar_mensagens_openai_like(itens, response_schema)
    ultimo_erro = None
    for modelo in modelos:
        for tentativa in range(1, 4):
            try:
                resp = _com_vaga(client.chat.completions.create, 
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
                        tempo_espera = _espera(tentativa)
                        st.toast(f"⚡ Fila na Groq ({modelo}). Tentativa {tentativa}/3...", icon="⏳")
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
    client = _cliente(("openrouter", chave), lambda: OpenAI(api_key=chave, base_url="https://openrouter.ai/api/v1", timeout=_TIMEOUT_IA_S, max_retries=0))
    mensagens = _montar_mensagens_openai_like(itens, response_schema)
    ultimo_erro = None
    for modelo in modelos:
        for tentativa in range(1, 4):
            try:
                resp = _com_vaga(client.chat.completions.create, 
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
                        tempo_espera = _espera(tentativa)
                        st.toast(f"⚡ Fila no OpenRouter ({modelo}). Tentativa {tentativa}/3...", icon="⏳")
                        time.sleep(tempo_espera)
                        continue
                    break
                elif "404" in erro_str or "NOT_FOUND" in erro_str or "NOT A VALID MODEL" in erro_str or "400" in erro_str or "402" in erro_str or "CREDITS" in erro_str or isinstance(e, (ValidationError, json.JSONDecodeError)) or "JSON" in erro_str.upper() or "não retornou" in str(e):
                    st.toast(f"⚠️ {modelo} indisponível/formato inválido. Pulando...", icon="⏭️")
                    break
                else:
                    raise e
    raise Exception(f"OpenRouter: todos os modelos falharam. Último erro: {ultimo_erro}")

def _chamar_mistral(chave, itens, response_schema, modelos):
    if Mistral is None: raise Exception("Biblioteca 'mistralai' não instalada no servidor.")
    client = _cliente(("mistral", chave), lambda: Mistral(api_key=chave, timeout_ms=_TIMEOUT_IA_S * 1000))
    mensagens = _montar_mensagens_openai_like(itens, response_schema)
    ultimo_erro = None
    for modelo in modelos:
        for tentativa in range(1, 4):
            try:
                resp = _com_vaga(client.chat.complete, 
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
                        tempo_espera = _espera(tentativa)
                        st.toast(f"⚡ Fila na Mistral ({modelo}). Tentativa {tentativa}/3...", icon="⏳")
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


@st.cache_data(show_spinner=False, max_entries=30)
def _extrair_cache(hash_arquivo, nome_arquivo, dpi_ocr, max_paginas_ocr, _file_bytes):
    # _file_bytes (com underscore) não entra no hash do cache: a chave é o sha1 calculado uma única vez.
    return _extrair_pdf(_file_bytes, nome_arquivo, dpi_ocr, max_paginas_ocr, pool=_pool_pdf())

def extrair_conteudo_cache(file_bytes, nome_arquivo, dpi_ocr=1.5, max_paginas_ocr=None):
    return _extrair_cache(hashlib.sha1(file_bytes).hexdigest(), nome_arquivo, dpi_ocr, max_paginas_ocr, file_bytes)

_RE_RODAPE_SEI = re.compile(r'\(\d+\)\s*SEI\s+[\d./-]+\s*/\s*pg\.\s*\d+', re.IGNORECASE)

def extrair_conteudo_multimodal(file_bytes, nome_arquivo, dpi_ocr=1.5, max_paginas_ocr=None):
    return extrair_conteudo_cache(file_bytes, nome_arquivo, dpi_ocr, max_paginas_ocr)

# ----------------- ESTRUTURAS PYDANTIC -----------------
class ArquivoClassificado(BaseModel):
    nome_arquivo_upload: str
    tipo: str = Field(description="'Base' ou 'Alteradora'")
    grupo_id: int = Field(description="Identificador da família normativa (comece em 1).")
    nome_padronizado_identificado: str = Field(description="Nome padronizado da norma (tipo, número, órgão e data)")
    data_oficial_iso: str = Field(description="Data formatada estritamente em YYYY-MM-DD.")
    ato_base_referenciado_tipo: Optional[str] = Field(default=None, description="APENAS para 'Alteradora' cujo ato original NÃO está presente neste lote: o tipo do ato que ela declara alterar/revogar. Deixe vazio se o ato base está no próprio lote ou se tipo='Base'.")
    ato_base_referenciado_numero: Optional[str] = Field(default=None, description="APENAS para 'Alteradora' cujo ato original NÃO está presente neste lote: o número/identificador do ato que ela declara alterar/revogar.")

class TriagemDocumentos(BaseModel): arquivos: List[ArquivoClassificado]

class MetadadosNorma(BaseModel):
    tipo_documento: str; numero_documento: str; orgao_emissor: str; data_assinatura: str; nome_padronizado: str

class Dispositivo(BaseModel):
    tipo: str; texto_principal_alterada: str; texto_principal_consolidada: str; is_tabela: bool
    tabela_alterada: Optional[List[List[str]]] = None; tabela_consolidada: Optional[List[List[str]]] = None
    texto_pos_tabela_alterada: Optional[str] = None; texto_pos_tabela_consolidada: Optional[str] = None
    nota_remissiva: Optional[str] = Field(default="", description="Apenas o trecho da citação, sem prefixo e sem parênteses.")

class Consolidacao(BaseModel):
    arquivos_originais_identificados: List[str]; arquivos_alteradores_identificados: List[str]
    norma_base: MetadadosNorma; normas_alteradoras: List[MetadadosNorma]
    cabecalho_complemento: str; orgaos_emissores: str; titulo_portaria: str; ementa: str; preambulo: str
    assinatura_nome: str; assinatura_cargo: str; dispositivos: List[Dispositivo]

class AnaliseGlobal(BaseModel):
    consolidacoes_geradas: List[Consolidacao]; arquivos_nao_alterados: List[str]

# =====================================================================
# FUNÇÕES AUXILIARES PARA PROCESSAMENTO
# =====================================================================



def corrigir_posicionamento_tabela(consolidacao: dict):
    """Garante que, para dispositivos com tabela e que foram alterados, a nova redação
    esteja no campo texto_pos_tabela_alterada e não em texto_principal_alterada."""
    if not isinstance(consolidacao, dict):
        return consolidacao
    dispositivos = consolidacao.get("dispositivos", [])
    for disp in dispositivos:
        if not disp.get("is_tabela"):
            continue
        txt_alt = disp.get("texto_principal_alterada") or ""
        txt_pos_alt = disp.get("texto_pos_tabela_alterada") or ""
        if "redação dada pelo" in txt_pos_alt.lower() or "nova redação" in txt_pos_alt.lower() or "revogado pelo" in txt_pos_alt.lower():
            continue
        nova_redacao = None
        texto_antigo = txt_alt
        partes = re.split(r'<br\s*/?>\s*<br\s*/?>', txt_alt, flags=re.IGNORECASE)
        if len(partes) >= 2:
            primeira = partes[0].strip()
            segunda = partes[-1].strip()
            if '<strike' not in segunda.lower() and '<font color="red"' not in segunda.lower() and '<s>' not in segunda.lower():
                nova_redacao = segunda
                texto_antigo = primeira
            else:
                for idx in range(len(partes)-1, -1, -1):
                    parte_limpa = partes[idx].strip()
                    if '<strike' not in parte_limpa.lower() and '<font color="red"' not in parte_limpa.lower() and '<s>' not in parte_limpa.lower():
                        nova_redacao = parte_limpa
                        texto_antigo = "<br/><br/>".join(partes[:idx]).strip()
                        break
        else:
            match = re.search(r'(\(?\s*Redação dada pelo.*)', txt_alt, flags=re.IGNORECASE)
            if match:
                inicio_nova = match.start()
                texto_antigo = txt_alt[:inicio_nova].strip()
                nova_redacao = txt_alt[inicio_nova:].strip()
            else:
                partes_simples = re.split(r'<br\s*/?>', txt_alt, flags=re.IGNORECASE)
                if len(partes_simples) > 1:
                    ultima = partes_simples[-1].strip()
                    if '<strike' not in ultima.lower() and '<font color="red"' not in ultima.lower() and '<s>' not in ultima.lower():
                        nova_redacao = ultima
                        texto_antigo = "<br/>".join(partes_simples[:-1]).strip()
        if nova_redacao:
            disp["texto_principal_alterada"] = texto_antigo if texto_antigo else ""
            if disp["texto_principal_alterada"] and not disp["texto_principal_alterada"].endswith("<br/><br/>"):
                disp["texto_principal_alterada"] += "<br/><br/>"
            if txt_pos_alt.strip() and txt_pos_alt.strip() != nova_redacao:
                disp["texto_pos_tabela_alterada"] = nova_redacao + "<br/><br/>" + txt_pos_alt.strip()
            else:
                disp["texto_pos_tabela_alterada"] = nova_redacao
    return consolidacao




# =====================================================================
# PROCESSAMENTO EM LOTES (normas extensas) — CORREÇÃO DO TRUNCAMENTO
# =====================================================================
# Causa do erro original: o ato base inteiro + o ato alterador inteiro eram enviados numa ÚNICA chamada e a IA
# precisava devolver, num único JSON, TODOS os dispositivos em duas versões (alterada e consolidada). Em normas
# extensas isso estoura o limite de saída do modelo (ou do provedor de fallback), e a IA resumia/omitia o miolo
# do ato. Agora o texto do ato base é segmentado de forma determinística (sem IA), a IA só decide o EFEITO do
# ato alterador (revogação integral ou alterações pontuais) e o texto original nunca passa pela saída da IA.
LIMITE_LEGADO_CHARS = 0              # tamanho mínimo do ato base para usar o fluxo determinístico (0 = sempre que o texto for segmentável); só cai no fluxo antigo (uma chamada de IA) se a segmentação falhar ou o PDF for escaneado
TAM_LOTE_CHARS = 16000               # tamanho máximo (texto) de cada lote de dispositivos enviado à IA
MAX_DISP_LOTE = 25
LIMITE_CHARS_ALTERADORA_LOTE = 90000
LIMITE_CHARS_PLANO = 25000
LIMITE_EDICAO_DETALHADA = 40

class CabecalhoNorma(BaseModel):
    norma_base: MetadadosNorma
    cabecalho_complemento: str; orgaos_emissores: str; titulo_portaria: str; ementa: str; preambulo: str
    assinatura_nome: str; assinatura_cargo: str

class PlanoAlteracao(BaseModel):
    metadados: MetadadosNorma
    revogacao_integral: bool = Field(description="True somente se o ato alterador revoga o ato base COMO UM TODO (inclusive por cláusula 'revogadas as disposições em contrário, em especial <ato base>').")
    citacao_revogacao: str = Field(default="", description="Se revogacao_integral=True: citação exata no formato 'Art. 3 da PORTARIA Nº 5/PGJM, de 17 de janeiro de 2025' (artigo do ato alterador que revoga o ato base).")

class AlteracaoLote(BaseModel):
    idx: int = Field(description="Número [IDX n] do dispositivo do lote que foi afetado.")
    dispositivo_atualizado: Dispositivo
    dispositivos_novos_apos: List[Dispositivo] = Field(default_factory=list, description="Dispositivos ACRESCENTADOS pelo ato alterador imediatamente após este.")

class ResultadoLote(BaseModel):
    alteracoes: List[AlteracaoLote]

_RE_ART = re.compile(r'^Art\.\s*\d+', re.IGNORECASE)
_RE_PAR = re.compile(r'^(Par[áa]grafo\s+[ÚUúu]nico|§\s*\d+)')
_RE_INC = re.compile(r'^[IVXLC]+\s*[–—-]\s*\S')
_RE_ALI = re.compile(r'^[a-z](\.\d+)?\)\s')
_RE_CAP = re.compile(r'^(T[ÍI]TULO|CAP[ÍI]TULO|LIVRO|PARTE|SUBSE[ÇC][ÃA]O|SE[ÇC][ÃA]O)\s+([IVXLC]+|\d+|[ÚU]NIC[AO])\b', re.IGNORECASE)
_RE_ANEXO = re.compile(r'^ANEXO\s+([IVXLC]+|\d+|[ÚU]NICO)\s*$', re.IGNORECASE)
_RE_SUMARIO = re.compile(r'^SUM[ÁA]RIO$', re.IGNORECASE)

def _plano(h):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', '', h or ''))).strip()

def _norm_txt(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c)).lower().strip()

def _texto_unico(partes):
    if isinstance(partes, list) and len(partes) == 1 and isinstance(partes[0], str) and partes[0].startswith("CONTEÚDO DO ARQUIVO"):
        return partes[0]
    return None

def _limpar_html_linha(l):
    l = re.sub(r'<b>\s*-\s*</b>', '-', l)
    l = re.sub(r'</b>(\s*)<b>', r'\1', l)
    l = re.sub(r'<i>\s*</i>|<b>\s*</b>', '', l)
    return l.strip()

def _parsear_tabela(linhas_tab):
    rows = []
    for ln in linhas_tab:
        if " | " in ln or ln.strip() == "|" or ln.startswith(" |") or ln.endswith(" |"):
            rows.append([c.strip() for c in ln.split(" | ")])
        elif rows and ln.strip():
            rows[-1][-1] = (rows[-1][-1] + "<br/>" + ln.strip()) if rows[-1][-1] else ln.strip()
        elif ln.strip():
            rows.append([ln.strip()])
    if not rows: return []
    n = max(len(r) for r in rows)
    return [r + [""] * (n - len(r)) for r in rows]

def segmentar_dispositivos(texto, assinatura_nome=None, assinatura_cargo=None):
    """Segmenta deterministicamente o texto extraído do ato em dispositivos (um por Artigo, mais títulos,
    capítulos, seções, anexos, tabelas). Retorna None se não reconhecer a estrutura (aí vale o fluxo antigo)."""
    if not texto: return None
    bruto = texto.split("\n")
    itens = []   # ('t', linha) ou ('tab', [linhas])
    i = 0
    while i < len(bruto):
        l = bruto[i].rstrip()
        if l.strip() == "[TABELA]":
            blk = []; i += 1
            while i < len(bruto) and bruto[i].strip() != "[/TABELA]":
                blk.append(bruto[i]); i += 1
            itens.append(('tab', blk)); i += 1; continue
        i += 1
        s = l.strip()
        if not s or re.match(r'^=== P[ÁA]GINA \d+ ===$', s) or s in ("[ANEXO]", "<br/>") or s.startswith("CONTEÚDO DO ARQUIVO"):
            continue
        if s.endswith("<br/>"): s = s[:-5].strip()
        if not s or _RE_RODAPE_SEI.search(s): continue
        itens.append(('t', _limpar_html_linha(s)))
    # corte da assinatura eletrônica final
    for k, (tp, v) in enumerate(itens):
        if tp == 't' and _plano(v).lower().startswith("documento assinado eletronicamente"):
            itens = itens[:k]; break
    ini = next((k for k, (tp, v) in enumerate(itens) if tp == 't' and re.match(r'^Art\.\s*1\s*[º°o]?(\s|\.|$)', _plano(v))), None)
    if ini is None: return None
    itens = itens[ini:]
    # remove a assinatura (nome + cargo) do corpo
    if assinatura_nome:
        nn = _norm_txt(assinatura_nome); cn = _norm_txt(assinatura_cargo or "")
        rem = set()
        for k, (tp, v) in enumerate(itens):
            if tp != 't': continue
            p = _plano(v)
            if nn in _norm_txt(p) and len(p) <= len(assinatura_nome) + len(assinatura_cargo or "") + 25:
                rem.add(k)
                if cn and cn not in _norm_txt(p) and k + 1 < len(itens) and itens[k+1][0] == 't' and _norm_txt(_plano(itens[k+1][1])) == cn:
                    rem.add(k + 1)
        itens = [x for n_, x in enumerate(itens) if n_ not in rem]
    itens = [x for x in itens if not (x[0] == 't' and re.match(r'^(Este texto n[ãa]o substitui|Nota: Este documento possui)', _plano(x[1]), re.IGNORECASE))]
    disps = []
    cur = None; fechado = False
    def novo(tipo, linha=None):
        d = {"tipo": tipo, "linhas": [linha] if linha is not None else [], "tabela": None}
        disps.append(d); return d
    k = 0
    while k < len(itens):
        tp, v = itens[k]
        if tp == 'tab':
            rows = _parsear_tabela(v)
            if rows:
                if cur and cur["tipo"] == "anexo" and cur["tabela"] is None and not fechado:
                    cur["tabela"] = rows
                else:
                    cur = novo("tabela"); cur["tabela"] = rows
                fechado = True
            k += 1; continue
        p = _plano(v)
        if _RE_SUMARIO.match(p):
            j = next((x for x in range(k + 1, len(itens)) if itens[x][0] == 't' and _RE_ANEXO.match(_plano(itens[x][1]))), None)
            if j is not None:
                cur = novo("sumario", v)
                for x in range(k + 1, j):
                    if itens[x][0] == 't': cur["linhas"].append(itens[x][1])
                fechado = True; k = j; continue
        estrutural = bool(_RE_ART.match(p) or _RE_PAR.match(p) or _RE_INC.match(p) or _RE_ALI.match(p) or (_RE_CAP.match(p) and len(p) <= 150) or _RE_ANEXO.match(p))
        if _RE_ART.match(p):
            cur = novo("artigo", v); fechado = False
        elif _RE_CAP.match(p) and len(p) <= 150:
            cur = novo("capitulo", v); fechado = False
        elif _RE_ANEXO.match(p):
            cur = novo("anexo", v); fechado = False
        elif _RE_PAR.match(p) or _RE_INC.match(p) or _RE_ALI.match(p):
            if cur and cur["tipo"] in ("artigo", "paragrafo", "inciso", "alinea") and not fechado:
                cur["linhas"].append(v)
            else:
                cur = novo("paragrafo" if _RE_PAR.match(p) else ("inciso" if _RE_INC.match(p) else "alinea"), v); fechado = False
        else:
            if cur and not fechado and cur["tipo"] in ("capitulo", "anexo") and len(cur["linhas"]) < 4:
                cur["linhas"].append(v)
            elif cur and not fechado and cur["tipo"] in ("artigo", "paragrafo", "inciso", "alinea", "texto"):
                ult = _plano(cur["linhas"][-1])
                if ult.endswith(('.', ';', ':')) and not _plano(v)[:1].islower():
                    cur["linhas"].append(v)
                else:
                    cur["linhas"][-1] = cur["linhas"][-1] + " " + v
            else:
                cur = novo("texto", v); fechado = False
        k += 1
    for d in disps:
        d["texto"] = "<br/>".join(d["linhas"])
    return disps

def _riscar_html(texto):
    partes = [p.strip() for p in re.split(r'<br\s*/?>', texto or '') if p.strip()]
    return "<br/>".join(f'<strike><font color="red">{p}</font></strike>' for p in partes)

def _riscar_tabela(rows):
    return [[_riscar_html(c) if (c or '').strip() else "" for c in r] for r in (rows or [])]

def _normalizar_citacao(c):
    c = (c or "").strip().strip('()').strip()
    c = re.sub(r'^(Revogad[oa]s?|Alterad[oa]s?)\s+pel[oa]s?\s+', '', c, flags=re.IGNORECASE)
    c = re.sub(r'^(Art\.\s*\d+(?:-[A-Za-z]+)?)\s*[º°]', r'\1', c)
    return c.rstrip('.;, ')

def _identificador(d_tipo, primeira_linha_html):
    p = _plano(primeira_linha_html)
    if d_tipo == "artigo":
        m = re.match(r'^(Art\.\s*\d+(?:-[A-Za-z]+)?\s*[º°]?\.?)', p)
        return m.group(1).strip() if m else p[:12]
    if d_tipo in ("capitulo", "anexo", "sumario"):
        return p
    m = _RE_PAR.match(p) or re.match(r'^([IVXLC]+\s*[–—-])', p) or re.match(r'^([a-z](?:\.\d+)?\))', p)
    return m.group(1) if m else ""

def _seg_para_dispositivo(d):
    tab = d.get("tabela")
    return {
        "tipo": d["tipo"], "texto_principal_alterada": d["texto"], "texto_principal_consolidada": d["texto"],
        "is_tabela": bool(tab), "tabela_alterada": tab if tab else None, "tabela_consolidada": tab if tab else None,
        "texto_pos_tabela_alterada": None, "texto_pos_tabela_consolidada": None, "nota_remissiva": "",
    }

def _aplicar_revogacao_integral(estado, citacao):
    """Revogação integral aplicada de forma DETERMINÍSTICA (sem IA): nenhum texto do ato base é reescrito."""
    cit = _normalizar_citacao(citacao)
    nota = f"Revogado pelo {cit}"
    for d in estado:
        cons_txt = d.get("texto_principal_consolidada") or ""
        if "revogado pelo" in _plano(cons_txt).lower() and not (d.get("tabela_consolidada")):
            continue
        tab_cons = d.get("tabela_consolidada") or []
        tab_alt = d.get("tabela_alterada") or []
        virgem = (d.get("texto_principal_alterada") or "") == cons_txt and tab_alt == tab_cons
        eh_tab = bool(d.get("is_tabela") or tab_cons or tab_alt)
        primeira = re.split(r'<br\s*/?>', cons_txt)[0] if cons_txt else ""
        ident = _identificador(d.get("tipo", ""), primeira) if cons_txt else ""
        # --- versão ALTERADA ---
        if virgem:
            alt_txt = _riscar_html(cons_txt)
        else:
            alt_old = d.get("texto_principal_alterada") or ""
            partes = re.split(r'(<br\s*/?>\s*<br\s*/?>)', alt_old)
            if len(partes) >= 3 and '<strike' not in partes[-1].lower() and partes[-1].strip():
                partes[-1] = _riscar_html(partes[-1]); alt_txt = "".join(partes)
            else:
                alt_txt = (alt_old + "<br/><br/>" if alt_old.strip() else "") + _riscar_html(cons_txt)
        if eh_tab:
            d["texto_principal_alterada"] = alt_txt
            d["tabela_alterada"] = _riscar_tabela(tab_cons or tab_alt)
            d["texto_pos_tabela_alterada"] = f"({nota});"
            d["texto_principal_consolidada"] = f"{ident} ({nota})." if ident else ""
            d["tabela_consolidada"] = []
            d["texto_pos_tabela_consolidada"] = ""
            d["is_tabela"] = True
            d["nota_remissiva"] = ""
        else:
            if virgem and d.get("tipo") in ("artigo", "paragrafo", "inciso", "alinea") and alt_txt:
                # cada parágrafo/inciso/alínea é um dispositivo próprio: a nota de revogação acompanha cada linha taxada
                alt_txt = "<br/>".join(f"{ln} ({nota});" for ln in alt_txt.split("<br/>"))
                d["texto_principal_alterada"] = alt_txt
            else:
                d["texto_principal_alterada"] = f"{alt_txt} ({nota});" if alt_txt else f"({nota});"
            d["texto_principal_consolidada"] = f"{ident} ({nota})." if ident else f"({nota})."
            d["nota_remissiva"] = nota
    return estado

def _chars_estado(estado):
    tot = 0
    for d in (estado or {}).get("dispositivos", []) or []:
        tot += len(_plano(d.get("texto_principal_alterada") or ""))
        for tb in (d.get("tabela_alterada") or d.get("tabela_consolidada") or []):
            tot += sum(len(_plano(c)) for c in tb)
    return tot

def _chars_seg(seg):
    tot = 0
    for d in seg:
        tot += len(_plano(d["texto"]))
        for r in (d.get("tabela") or []): tot += sum(len(_plano(c)) for c in r)
    return tot

def _estado_incompleto(estado, seg):
    """Detecta estado salvo no banco que NÃO contém o ato base completo (resultado de execuções truncadas)."""
    if not isinstance(estado, dict) or not (estado.get("dispositivos")): return True
    return _chars_estado(estado) < 0.7 * _chars_seg(seg)

def _montar_lotes(estado):
    lotes, atual, tam = [], [], 0
    for i, d in enumerate(estado):
        t = len(d.get("texto_principal_consolidada") or "") + (len(d.get("texto_principal_alterada") or "") if (d.get("texto_principal_alterada") or "") != (d.get("texto_principal_consolidada") or "") else 0) + sum(len(str(c)) for r in (d.get("tabela_consolidada") or []) for c in r)
        if atual and (tam + t > TAM_LOTE_CHARS or len(atual) >= MAX_DISP_LOTE):
            lotes.append(atual); atual, tam = [], 0
        atual.append(i); tam += t
    if atual: lotes.append(atual)
    return lotes

def _dump_lote(estado, indices):
    out = []
    for i in indices:
        d = estado[i]
        s = f"[IDX {i}] tipo={d.get('tipo')}\nCONSOLIDADA_ATUAL: {d.get('texto_principal_consolidada') or ''}"
        if (d.get('texto_principal_alterada') or '') != (d.get('texto_principal_consolidada') or ''):
            s += f"\nALTERADA_ATUAL: {d.get('texto_principal_alterada') or ''}"
        if d.get('tabela_consolidada'):
            s += f"\nTABELA_CONSOLIDADA_ATUAL: {json.dumps(d['tabela_consolidada'], ensure_ascii=False)}"
        if d.get('tabela_alterada') and d.get('tabela_alterada') != d.get('tabela_consolidada'):
            s += f"\nTABELA_ALTERADA_ATUAL: {json.dumps(d['tabela_alterada'], ensure_ascii=False)}"
        out.append(s)
    return "\n\n".join(out)

def _conteudo_alteradora(itens, limite=LIMITE_CHARS_ALTERADORA_LOTE):
    saida, usado = [], 0
    for it in itens:
        if isinstance(it, str):
            if usado >= limite: continue
            restante = limite - usado
            saida.append(it if len(it) <= restante else it[:restante] + "\n[... texto do ato alterador truncado por tamanho ...]")
            usado += len(it)
        else:
            saida.append(it)
    return saida

class IdxAfetados(BaseModel):
    idx_afetados: List[int] = Field(default_factory=list, description="IDX dos dispositivos do ato base que o ato alterador altera, revoga ou após os quais acrescenta texto.")

_TIPOS_FILHOS = ("paragrafo", "inciso", "alinea")

def _indice_estado(estado):
    return "\n".join(f"[IDX {i}] {d.get('tipo')}: {_plano(d.get('texto_principal_consolidada'))[:110]}" for i, d in enumerate(estado))

def _expandir_para_artigo(estado, afetados):
    """Cada IDX afetado puxa o artigo inteiro (caput, parágrafos, incisos e alíneas): a IA vê o contexto completo."""
    n, res = len(estado), set()
    for i in afetados:
        if not isinstance(i, int) or not (0 <= i < n): continue
        a = i
        while a > 0 and estado[a].get("tipo") in _TIPOS_FILHOS: a -= 1
        b = a + 1
        while b < n and estado[b].get("tipo") in _TIPOS_FILHOS: b += 1
        res.update(range(a, b))
    return sorted(res)

def _localizar_afetados(key, provedor, nome_alt, itens_alt, estado):
    """UMA chamada barata (thinking baixo) devolve quais dispositivos o ato alterador toca. Só esses vão para os lotes,
    em vez de reenviar o ato alterador inteiro a cada lote do ato base inteiro. Retorna None => varrer tudo (fallback)."""
    conteudo = [f"ATO ALTERADOR/REVOGADOR ({nome_alt}):"] + _conteudo_alteradora(itens_alt)
    conteudo.append("ÍNDICE DO ATO BASE (IDX, tipo e início do texto vigente):\n" + _indice_estado(estado))
    conteudo.append("Liste em 'idx_afetados' TODOS os IDX do ato base que o ato alterador altera, revoga (total ou parcialmente), renumera, "
                    "ou após os quais acrescenta dispositivos (neste caso inclua o IDX do dispositivo imediatamente anterior ao acréscimo). "
                    "Considere também anexos e tabelas. Na dúvida, INCLUA. Não explique.")
    try:
        resp = executar_com_fallback(key, conteudo, IdxAfetados, provedor, "low")
        ids = json.loads(resp.text).get("idx_afetados") or []
        expandidos = _expandir_para_artigo(estado, ids)
        return expandidos or None
    except Exception:
        return None

def _lotes_de_indices(estado, indices):
    sub_lotes = _montar_lotes([estado[i] for i in indices])
    return [[indices[k] for k in lote] for lote in sub_lotes]

def _chamar_lote(key, provedor, thinking_level, nome_alt, itens_alt, estado, indices, n_lote, total_lotes, memoria):
    prompt = f"""
LOTE {n_lote} DE {total_lotes}. Os dispositivos abaixo estão numerados com [IDX n] e representam o ESTADO ATUAL do ato base
(texto vigente 'CONSOLIDADA_ATUAL' e, se houver, o histórico 'ALTERADA_ATUAL').
Aplique o ato alterador/revogador ({nome_alt}) SOMENTE aos dispositivos deste lote.
Devolva em 'alteracoes' APENAS os dispositivos efetivamente alterados, revogados parcialmente ou que recebam dispositivos
ACRESCENTADOS (estes em 'dispositivos_novos_apos', logo após o IDX correspondente). Dispositivos não afetados NÃO devem ser devolvidos.
Em 'dispositivo_atualizado' devolva o dispositivo COMPLETO (todos os campos), com TEXTO INTEGRAL, nunca resumido ou truncado,
seguindo EXATAMENTE as regras 4, 6 e 8 do sistema (taxação em vermelho, notas citando o ARTIGO ESPECÍFICO do ato alterador).
Se um dispositivo já possuía ALTERADA_ATUAL, preserve esse histórico e acrescente a nova marcação.
{memoria}
"""
    conteudo = [f"ATO ALTERADOR/REVOGADOR ({nome_alt}):"] + _conteudo_alteradora(itens_alt)
    conteudo.append("DISPOSITIVOS DO LOTE:\n" + _dump_lote(estado, indices))
    conteudo.append(prompt)
    nivel = "medium" if thinking_level == "high" else thinking_level
    resp = executar_com_fallback(key, conteudo, ResultadoLote, provedor, nivel)
    return json.loads(resp.text).get("alteracoes", [])

def _aplicar_alteracoes_pontuais(key, provedor, thinking_level, nome_alt, itens_alt, estado, memoria, mensagens):
    lotes = _montar_lotes(estado)
    total_original = len(lotes)
    if thinking_level != "high" and len(lotes) > 1:
        afetados_pre = _localizar_afetados(key, provedor, nome_alt, itens_alt, estado)
        if afetados_pre and len(afetados_pre) < 0.7 * len(estado):
            lotes = _lotes_de_indices(estado, afetados_pre)
            mensagens.append(("info", f"⚡ '{nome_alt}': pré-seleção localizou {len(afetados_pre)} de {len(estado)} dispositivos relevantes ({len(lotes)} lote(s) em vez de {total_original})."))
    resultados = {}
    workers = 2 if thinking_level == "low" else 3
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(lotes)))) as ex:
        futs = {}
        for n, indices in enumerate(lotes, 1):
            f = submit_com_contexto(ex, _chamar_lote, key, provedor, thinking_level, nome_alt, itens_alt, estado, indices, n, len(lotes), memoria)
            futs[f] = (n, indices)
        for f in as_completed(futs):
            n, indices = futs[f]
            try:
                alts = f.result()
            except Exception as e:
                raise Exception(f"Falha no lote {n}/{len(lotes)} ao aplicar '{nome_alt}': {e}")
            for a in alts:
                idx = a.get("idx")
                if isinstance(idx, int) and idx in indices:
                    resultados[idx] = a
    novo_estado, afetados = [], 0
    for i, d in enumerate(estado):
        a = resultados.get(i)
        if not a:
            novo_estado.append(d); continue
        upd = a.get("dispositivo_atualizado") or {}
        vazio = not _plano(upd.get("texto_principal_alterada")) and not _plano(upd.get("texto_principal_consolidada")) and not upd.get("tabela_alterada")
        if vazio and (_plano(d.get("texto_principal_alterada")) or d.get("tabela_alterada")):
            mensagens.append(("warning", f"⚠️ A IA devolveu o dispositivo {i+1} vazio ao aplicar '{nome_alt}'; o texto anterior foi preservado."))
            novo_estado.append(d)
        else:
            if not upd.get("tipo"): upd["tipo"] = d.get("tipo")
            novo_estado.append(upd); afetados += 1
        for nd in (a.get("dispositivos_novos_apos") or []):
            novo_estado.append(nd); afetados += 1
    mensagens.append(("info", f"📚 '{nome_alt}': {afetados} dispositivo(s) alterado(s)/acrescentado(s) em {len(lotes)} lote(s); os demais foram preservados integralmente."))
    return novo_estado

def _processar_cascata_lotes(key, provedor, arquivo_base, alteradoras, textos_extraidos, memoria_aprendida, thinking_level, estado_json_atual, mensagens, texto_base):
    low = "low"
    if estado_json_atual:
        cons = json.loads(estado_json_atual) if isinstance(estado_json_atual, str) else estado_json_atual
        cons.setdefault("normas_alteradoras", []); cons.setdefault("arquivos_alteradores_identificados", [])
        estado = cons.get("dispositivos") or []
    else:
        resp_cab = executar_com_fallback(key, [
            "Extraia SOMENTE o cabeçalho da norma abaixo (metadados da norma base, cabeçalho complementar, órgãos emissores, título, ementa, "
            "preâmbulo e assinatura). NÃO transcreva os dispositivos (artigos). Texto do início do ato:\n" + texto_base[:9000]
        ], CabecalhoNorma, provedor, low)
        cab = json.loads(resp_cab.text)
        seg = segmentar_dispositivos(texto_base, cab.get("assinatura_nome"), cab.get("assinatura_cargo"))
        if not seg:
            raise Exception("Não foi possível segmentar os dispositivos do ato base.")
        estado = [_seg_para_dispositivo(d) for d in seg]
        cons = {
            "arquivos_originais_identificados": [arquivo_base.get("nome_arquivo_upload")] if arquivo_base.get("nome_arquivo_upload") else [],
            "arquivos_alteradores_identificados": [], "norma_base": cab["norma_base"], "normas_alteradoras": [],
            "cabecalho_complemento": cab.get("cabecalho_complemento", ""), "orgaos_emissores": cab.get("orgaos_emissores", ""),
            "titulo_portaria": cab.get("titulo_portaria", ""), "ementa": cab.get("ementa", ""), "preambulo": cab.get("preambulo", ""),
            "assinatura_nome": cab.get("assinatura_nome", ""), "assinatura_cargo": cab.get("assinatura_cargo", ""),
        }
        mensagens.append(("info", f"📚 Ato base segmentado de forma determinística em {len(estado)} dispositivos (texto original preservado integralmente)."))
    nome_base = (cons.get("norma_base") or {}).get("nome_padronizado") or arquivo_base.get("nome_padronizado_identificado", "")

    def _planejar(alt):
        # O plano (metadados + revogação integral) de cada alteradora é independente do estado: roda todos em paralelo.
        itens_alt = textos_extraidos[alt['nome_arquivo_upload']]
        txt_alt = _texto_unico(itens_alt)
        head = (txt_alt or "")[:LIMITE_CHARS_PLANO] if txt_alt else None
        conteudo_plano = [f"ATO BASE ALVO: {nome_base}. Analise o ato alterador abaixo e identifique seus metadados e se ele REVOGA INTEGRALMENTE o ato base."]
        conteudo_plano += [head] if head else _conteudo_alteradora(itens_alt, LIMITE_CHARS_PLANO)
        resp_plano = executar_com_fallback(key, conteudo_plano, PlanoAlteracao, provedor, low)
        return json.loads(resp_plano.text), head

    planos = {}
    if alteradoras:
        with ThreadPoolExecutor(max_workers=min(3, len(alteradoras))) as ex_p:
            futs_p = {submit_com_contexto(ex_p, _planejar, a): a['nome_arquivo_upload'] for a in alteradoras}
            for fp, nome_up in futs_p.items():
                planos[nome_up] = fp.result()

    for alt in alteradoras:
        itens_alt = textos_extraidos[alt['nome_arquivo_upload']]
        plano, head = planos[alt['nome_arquivo_upload']]
        meta = plano["metadados"]
        if meta.get("nome_padronizado") and not any(n.get("nome_padronizado") == meta["nome_padronizado"] for n in cons["normas_alteradoras"]):
            cons["normas_alteradoras"].append(meta)
        nome_alt = meta.get("nome_padronizado") or alt.get("nome_padronizado_identificado", "")
        if plano.get("revogacao_integral"):
            cit = _normalizar_citacao(plano.get("citacao_revogacao"))
            if not cit.lower().startswith("art"):
                m = next((re.match(r'^Art\.\s*(\d+)', _plano(l)) for l in (head or "").split("\n") if re.match(r'^Art\.\s*\d+', _plano(l)) and 'revog' in _plano(l).lower()), None)
                cit = f"Art. {m.group(1) if m else '?'} da {nome_alt}"
            estado = _aplicar_revogacao_integral(estado, cit)
            mensagens.append(("info", f"📚 '{nome_alt}' revoga integralmente '{nome_base}': todos os {len(estado)} dispositivos foram taxados (Revogado pelo {cit})."))
        else:
            estado = _aplicar_alteracoes_pontuais(key, provedor, thinking_level, nome_alt, itens_alt, estado, memoria_aprendida, mensagens)
        if alt.get("nome_arquivo_upload") and alt["nome_arquivo_upload"] not in cons["arquivos_alteradores_identificados"]:
            cons["arquivos_alteradores_identificados"].append(alt["nome_arquivo_upload"])
    cons["dispositivos"] = estado
    return cons


def _processar_cascata_grupo(key, provedor, arquivo_base, arquivos_alteradores, textos_extraidos, memoria_aprendida, thinking_level="medium"):
    nome_padrao = arquivo_base.get('nome_padronizado_identificado', '')
    reconstruida = bool(arquivo_base.get('_reconstruida_do_banco'))
    estado_json_atual, ja_processadas = _consultar_estado_e_historico(nome_padrao)
    mensagens = []

    # --- Normas extensas: segmentação determinística + processamento em lotes (evita truncamento da IA) ---
    texto_base_lotes, seg_prelim = None, None
    nome_base_up = arquivo_base.get('nome_arquivo_upload')
    if nome_base_up and not reconstruida:
        texto_base_lotes = _texto_unico(textos_extraidos.get(nome_base_up))
        if texto_base_lotes and len(texto_base_lotes) > LIMITE_LEGADO_CHARS:
            seg_prelim = segmentar_dispositivos(texto_base_lotes)
            if seg_prelim and estado_json_atual:
                try:
                    estado_obj = json.loads(estado_json_atual)
                except Exception:
                    estado_obj = None
                if _estado_incompleto(estado_obj, seg_prelim):
                    mensagens.append(("warning", f"⚠️ O estado de '{nome_padrao}' salvo no banco está INCOMPLETO (não contém todo o texto do ato original). Ele foi ignorado e o ato foi reconstruído integralmente a partir do arquivo original enviado."))
                    estado_json_atual = None
                    ja_processadas = []

    if reconstruida:
        detalhe = f" com {len(ja_processadas)} derivação(ões) já aplicada(s) ({', '.join(ja_processadas)})" if ja_processadas else ""
        mensagens.append(("info", f"📎 Os arquivos enviados alteram/revogam o ato '{nome_padrao}', já cadastrado no banco{detalhe}. Recomendamos anexar também o arquivo ORIGINAL de '{nome_padrao}' em um novo envio para garantir a máxima fidelidade; por ora, o processamento usará o estado já consolidado salvo no banco de dados."))
    elif estado_json_atual is not None:
        detalhe = f" ({', '.join(ja_processadas)})" if ja_processadas else ""
        mensagens.append(("info", f"🧠 '{nome_padrao}' já possui histórico no banco: {len(ja_processadas)} alteração(ões)/revogação(ões) processada(s) anteriormente{detalhe}."))

    if reconstruida and estado_json_atual is None:
        mensagens.append(("warning", f"⚠️ '{nome_padrao}' foi localizado no banco, mas sem conteúdo consolidado salvo. Envie também o arquivo ORIGINAL de '{nome_padrao}' junto com as alteradoras para que o processamento seja possível."))
        raise Exception(f"Ato base '{nome_padrao}' localizado no banco sem conteúdo salvo — reenvie junto com o arquivo original.")

    ja_processadas_lower = {j.lower() for j in ja_processadas}
    alteradoras_para_aplicar = []
    for alt in arquivos_alteradores:
        nome_alt = alt.get('nome_padronizado_identificado', '')
        if nome_alt and nome_alt.lower() in ja_processadas_lower:
            mensagens.append(("warning", f"⚠️ '{nome_alt}' já havia sido processada e aplicada anteriormente a '{nome_padrao}' — não será reaplicada agora para evitar duplicar a alteração/revogação."))
        else:
            alteradoras_para_aplicar.append(alt)
    alteradoras_para_aplicar.sort(key=lambda x: x.get('data_oficial_iso') or '')

    usar_lotes = seg_prelim is not None
    if reconstruida and estado_json_atual:
        try:
            usar_lotes = _chars_estado(json.loads(estado_json_atual)) > LIMITE_LEGADO_CHARS
        except Exception:
            usar_lotes = False
    if usar_lotes:
        if not alteradoras_para_aplicar and estado_json_atual:
            return json.loads(estado_json_atual), mensagens
        resultado_lotes = _processar_cascata_lotes(key, provedor, arquivo_base, alteradoras_para_aplicar, textos_extraidos, memoria_aprendida, thinking_level, estado_json_atual, mensagens, texto_base_lotes)
        return resultado_lotes, mensagens

    if not alteradoras_para_aplicar:
        if estado_json_atual:
            return json.loads(estado_json_atual), mensagens
        conteudo_loop = ["Texto Base:"] + textos_extraidos[arquivo_base['nome_arquivo_upload']]
        resp_loop = executar_com_fallback(key, conteudo_loop + ["Estruture o documento separando a ementa do preâmbulo e aplicando rigorosamente o mapeamento de dispositivos, incluindo tabelas quando houver." + memoria_aprendida], Consolidacao, provedor, thinking_level)
        return json.loads(resp_loop.text), mensagens

    resp_loop = None
    for i, alt in enumerate(alteradoras_para_aplicar):
        conteudo_loop = []
        if estado_json_atual:
            conteudo_loop.append(f"ESTADO ATUAL (JSON):\n{estado_json_atual}")
        elif i == 0:
            conteudo_loop.append("DOCUMENTO BASE ORIGINAL:")
            conteudo_loop.extend(textos_extraidos[arquivo_base['nome_arquivo_upload']])

        conteudo_loop.append(f"ATO ALTERADOR/REVOGADOR Nº {i+1} DE {len(alteradoras_para_aplicar)} A SER APLICADO, EM ORDEM CRONOLÓGICA DO MAIS ANTIGO PARA O MAIS NOVO ({alt['nome_arquivo_upload']}):")
        conteudo_loop.extend(textos_extraidos[alt['nome_arquivo_upload']])
        prompt_loop = f"""
        Aplique o ato alterador/revogador cruzando detalhadamente com o ato base (seja Lei, Decreto,
        Resolução, Enunciado, Portaria ou qualquer outra espécie normativa).
        Obrigatório: siga EXATAMENTE o formato de citação e a estrutura de parágrafos definidos nas regras
        do sistema (item 4 e item 6 para tabelas) — "(Alterada pelo Art. N da TIPO Nº NÚMERO/ANO - SIGLA)" na
        linha riscada, "(Redação dada pelo Art. N da TIPO Nº NÚMERO/ANO - SIGLA)" na linha nova, ou
        "(Revogado pelo Art. N da TIPO Nº NÚMERO/ANO - SIGLA)" para revogação (sem repetir linha). Preserve
        <b>/<i> e tabelas ([TABELA]...[/TABELA]) com fidelidade absoluta, redesenhando a tabela inteira
        quando alterada.
        Se o ato for de revogação integral, aplique a taxação completa em todos os dispositivos, anexos e tabelas,
        conforme item 8.
        {memoria_aprendida}
        """
        conteudo_loop.append(prompt_loop)
        resp_loop = executar_com_fallback(key, conteudo_loop, Consolidacao, provedor, thinking_level)
        estado_json_atual = resp_loop.text
    return json.loads(resp_loop.text), mensagens

def analisar_lote_arquivos(arquivos, key, provedor, thinking_level="medium", dpi_ocr=1.5, max_paginas_ocr=None, progresso=None):
    memoria_aprendida = resgatar_memoria()
    textos_extraidos = {}
    max_workers_extração = 6
    with ThreadPoolExecutor(max_workers=min(max_workers_extração, max(1, len(arquivos)))) as ex:
        futuros = {submit_com_contexto(ex, extrair_conteudo_cache, arq.getvalue(), arq.name, dpi_ocr, max_paginas_ocr): arq.name for arq in arquivos}
        total_arquivos = len(arquivos)
        for idx, fut in enumerate(as_completed(futuros)):
            textos_extraidos[futuros[fut]] = fut.result()
            if progresso:
                progresso.progress((idx + 1) / (total_arquivos * 2), text=f"Extraindo conteúdo de {futuros[fut]}...")

    contents_triagem = [f"Analise os documentos. Agrupe cada ato original com seus derivativos presentes neste lote. Se uma Alteradora citar um ato original que NÃO está entre os arquivos deste lote, preencha ato_base_referenciado_tipo/numero com o que ela declara alterar/revogar, para localização posterior no banco de dados. ARQUIVOS: {', '.join(textos_extraidos.keys())}"]
    for nome_t, partes in textos_extraidos.items(): contents_triagem.extend(_resumo_triagem(nome_t, partes))
    if progresso:
        progresso.progress(0.5, text="Classificando documentos...")
    resp_triagem = executar_com_fallback(key, contents_triagem, TriagemDocumentos, provedor, thinking_level="low")
    triagem_dados = json.loads(resp_triagem.text).get("arquivos", [])

    # Normaliza o tipo devolvido pela IA (ex.: "base", "Base Original", "alteradora", "Revogadora")
    # para evitar que arquivos sejam descartados silenciosamente por diferença de grafia.
    for a in triagem_dados:
        tipo_norm = str(a.get('tipo') or '').strip().lower()
        a['tipo'] = 'Base' if (tipo_norm.startswith('base') or tipo_norm.startswith('orig')) else 'Alteradora'
        a['data_oficial_iso'] = a.get('data_oficial_iso') or ''

    nomes_classificados = {a.get('nome_arquivo_upload') for a in triagem_dados}
    arquivos_nao_classificados = [n for n in textos_extraidos.keys() if n not in nomes_classificados]

    mensagens_processamento, erros_processamento = [], []

    grupos = {}
    for a in triagem_dados: grupos.setdefault(a.get('grupo_id', 0), []).append(a)

    grupos_validos = []
    consolidacoes_geradas, arquivos_nao_alterados = [], []
    referencias_pendentes = []

    for grupo_id, itens in grupos.items():
        arquivo_base = next((a for a in itens if a['tipo'] == 'Base'), None)
        arquivos_alteradores = sorted([a for a in itens if a['tipo'] == 'Alteradora'], key=lambda x: x.get('data_oficial_iso') or '')

        if not arquivo_base and not arquivos_alteradores: continue
        if not arquivo_base:
            base_reconstruida = None
            ato_ref_tipo = None
            ato_ref_numero = None
            for alt in arquivos_alteradores:
                if alt.get('ato_base_referenciado_tipo') and alt.get('ato_base_referenciado_numero'):
                    ato_ref_tipo = alt['ato_base_referenciado_tipo']
                    ato_ref_numero = alt['ato_base_referenciado_numero']
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
                if not ato_ref_tipo or not ato_ref_numero:
                    ato_ref_tipo = "Desconhecido"
                    ato_ref_numero = "Desconhecido"
                referencias_pendentes.append({
                    "ato_referenciado_tipo": ato_ref_tipo,
                    "ato_referenciado_numero": ato_ref_numero,
                    "arquivos_alteradores": [a['nome_arquivo_upload'] for a in arquivos_alteradores],
                })
                arquivos_nao_alterados.extend([a['nome_arquivo_upload'] for a in arquivos_alteradores])
            continue
        grupos_validos.append((arquivo_base, arquivos_alteradores))

    if grupos_validos:
        max_workers_processamento = 1 if thinking_level == "low" else 2
        with ThreadPoolExecutor(max_workers=min(max_workers_processamento, len(grupos_validos))) as ex:
            futuros = {}
            for arquivo_base, arquivos_alteradores in grupos_validos:
                st.toast(f"⚙️ Processando: {arquivo_base.get('nome_padronizado_identificado')}...", icon="⏳")
                fut = submit_com_contexto(ex, _processar_cascata_grupo, key, provedor, arquivo_base, arquivos_alteradores, textos_extraidos, memoria_aprendida, thinking_level)
                futuros[fut] = (arquivo_base, arquivos_alteradores)
            total_grupos = len(grupos_validos)
            for idx, fut in enumerate(as_completed(futuros)):
                arquivo_base, arquivos_alteradores = futuros[fut]
                try:
                    resultado, mensagens = fut.result()
                    resultado = corrigir_posicionamento_tabela(resultado)
                    consolidacoes_geradas.append(resultado)
                    mensagens_processamento.extend(mensagens)
                except Exception as e:
                    erros_processamento.append(f"Falha em '{arquivo_base.get('nome_padronizado_identificado')}': {e}")
                    if arquivo_base.get('nome_arquivo_upload'):
                        arquivos_nao_alterados.append(arquivo_base['nome_arquivo_upload'])
                    arquivos_nao_alterados.extend([a['nome_arquivo_upload'] for a in arquivos_alteradores])
                if progresso:
                    progresso.progress(0.5 + 0.5 * (idx + 1) / total_grupos, text=f"Processando grupo {idx+1}/{total_grupos}...")

    return {
        "consolidacoes_geradas": consolidacoes_geradas,
        "arquivos_nao_alterados": arquivos_nao_alterados,
        "referencias_pendentes": referencias_pendentes,
        "arquivos_nao_classificados": arquivos_nao_classificados,
        "mensagens": mensagens_processamento,
        "erros": erros_processamento,
    }








# =====================================================================
# FRONT-END
# =====================================================================
ss = st.session_state
ss.setdefault("dados_processados", None)
ss.setdefault("dados_originais_ia", None)
ss.setdefault("exports_cons", {})
ss.setdefault("uploader_cons_ver", 0)
reg = conc.registro()
sid = conc.id_sessao()


def _hash_cons(c):
    return hashlib.md5(json.dumps(c, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def _liberar_travas():
    for chave in list(ss.get("_travas_minhas", [])):
        reg.liberar_trava(chave, sid)
    ss["_travas_minhas"] = []


dados = ss.dados_processados
etapa = 3 if (dados and dados.get("consolidacoes_geradas")) else 0

with st.container(border=True):
    c_ia, c_modo = st.columns([1, 1.2])
    with c_ia:
        provedor_escolhido = st.selectbox("Motor de IA (Hub Multi-IA)", list(PROVEDORES_IA.keys()), key="provedor_ia_cons")
    with c_modo:
        modo_processamento = st.radio("Modo de processamento", ["Equilibrado", "Rápido", "Máxima Qualidade"], index=0, horizontal=True,
                                      help="Rápido: menos raciocínio e OCR limitado. Máxima Qualidade: mais lento e mais caro.")
    cfg_provedor = PROVEDORES_IA[provedor_escolhido]
    api_key = obter_chave_provedor(provedor_escolhido)
    if api_key:
        st.markdown(ui.badge("Chave de API configurada nos Secrets", "ok", pulso=True) + f' <span style="color:#64748B;font-size:.82rem">Modelos: {escape(" → ".join(cfg_provedor["modelos"]))}</span>', unsafe_allow_html=True)
    else:
        api_key = st.text_input(f"Chave da API ({cfg_provedor['secret']} não encontrada nos secrets)", type="password", placeholder=f"Cole sua chave de {provedor_escolhido} aqui...")
    arquivos_enviados = st.file_uploader("Arraste todos os documentos (PDF): um ato original e todos os seus derivativos", type=["pdf"],
                                         accept_multiple_files=True, key=f"uploader_cons_{ss.uploader_cons_ver}",
                                         help="Aceita Leis, Decretos, Resoluções, Enunciados, Portarias e demais atos normativos.")
    iniciar = st.button("Iniciar análise Autopilot", type="primary", use_container_width=True, icon=":material/auto_awesome:", disabled=not arquivos_enviados)

ui.fluxo(["Enviar arquivos", "Triagem por IA", "Cascata de alterações", "Revisar e exportar"], etapa if etapa else (1 if arquivos_enviados else 0))

if iniciar:
    if not api_key:
        st.error("Insira sua chave da API.", icon=":material/key:")
    else:
        if modo_processamento == "Rápido":
            thinking_level, dpi_ocr, max_paginas_ocr = "low", 1.2, 10
        elif modo_processamento == "Equilibrado":
            thinking_level, dpi_ocr, max_paginas_ocr = "medium", 1.5, 20
        else:
            thinking_level, dpi_ocr, max_paginas_ocr = "high", 1.5, None

        _liberar_travas()
        with st.status("Executando OCR estrutural e consultando o aprendizado da equipe...", expanded=True) as status:
            progresso = st.progress(0.0, text="Iniciando análise...")
            try:
                ss.dados_processados = None
                ss.dados_originais_ia = None
                ss.exports_cons = {}
                ss.dados_processados = analisar_lote_arquivos(arquivos_enviados, api_key.strip(), provedor_escolhido, thinking_level=thinking_level,
                                                              dpi_ocr=dpi_ocr, max_paginas_ocr=max_paginas_ocr, progresso=progresso)
                ss.dados_originais_ia = copy.deepcopy(ss.dados_processados)
                n = len(ss.dados_processados.get("consolidacoes_geradas", []))
                conc.auditar("analisar_consolidacao", f"{len(arquivos_enviados)} arquivo(s) → {n} consolidação(ões)")
                status.update(label="Análise concluída" if n else "Concluído sem consolidações", state="complete", expanded=False)
            except Exception as e:
                status.update(label="Falha na análise", state="error")
                st.error(f"Ocorreu um erro: {e}", icon=":material/error:")
                with st.expander("Detalhes técnicos do erro"):
                    st.code(traceback.format_exc())
            finally:
                progresso.empty()
        st.rerun()

if dados:
    dados_originais = ss.dados_originais_ia
    consolidacoes = dados.get("consolidacoes_geradas", [])
    ui.kpis([
        ("Consolidações geradas", len(consolidacoes), "layers", "ok"),
        ("Alterações aplicadas", sum(len(c.get("normas_alteradoras", [])) for c in consolidacoes), "merge", "info"),
        ("Referências sem base", len(dados.get("referencias_pendentes", [])), "clock", "warn"),
        ("Arquivos sem efeito", len(set(dados.get("arquivos_nao_alterados", []))), "file", ""),
    ])
    if consolidacoes:
        st.success("Processamento concluído. Revise, exporte e salve cada consolidação abaixo.", icon=":material/check_circle:")
    else:
        st.warning("O processamento terminou, mas nenhuma consolidação foi gerada. Veja os detalhes abaixo.", icon=":material/warning:")

    for tipo_msg, texto_msg in dados.get("mensagens", []):
        (st.warning if tipo_msg == "warning" else st.info)(texto_msg)
    for texto_erro in dados.get("erros", []):
        st.error(texto_erro, icon=":material/error:")
    if dados.get("arquivos_nao_classificados"):
        st.warning("A IA não classificou estes arquivos e eles não foram processados: " + ", ".join(dados["arquivos_nao_classificados"]))
    if dados.get("arquivos_nao_alterados") and not consolidacoes:
        st.info("Arquivos que não geraram consolidação: " + ", ".join(dict.fromkeys(dados["arquivos_nao_alterados"])))
    referencias_pendentes = dados.get("referencias_pendentes", [])
    if referencias_pendentes:
        st.warning("Alguns arquivos fazem referência a normas que não foram encontradas no lote nem no banco. Envie também o(s) ato(s) original(is) correspondente(s).")
        for ref in referencias_pendentes:
            ato_ref = f"{ref.get('ato_referenciado_tipo', 'Desconhecido')} {ref.get('ato_referenciado_numero', 'Desconhecido')}"
            ui.cartao(f'{ui.icone("clock", 17)} Referência: {escape(ato_ref)}', f"<p>Alteradora(s): {escape(', '.join(ref.get('arquivos_alteradores', [])))}</p>", "warn")

    minhas = []
    for i, cons in enumerate(consolidacoes):
        nome_base = cons['norma_base']['nome_padronizado']
        nomes_alt = [alt['nome_padronizado'] for alt in cons.get('normas_alteradoras', [])]
        nome_alt = " e ".join(nomes_alt) if nomes_alt else "Desconhecido"

        # ---- trava branda: avisa quando outra pessoa está com a mesma norma aberta (nunca bloqueia)
        chave_trava = f"base:{nome_base}"
        reg.adquirir_trava(chave_trava, sid, conc.usuario_atual())
        minhas.append(chave_trava)
        outro = reg.dono_da_trava(chave_trava, sid)
        conc.batimento("consolidar", "consolidando", nome_base)

        with st.expander(f"{nome_base}  ·  alterada por {nome_alt}", expanded=True, icon=":material/folder_open:"):
            if outro:
                st.markdown(f'<div class="cn-aviso-trava">{ui.icone("users", 18)} {escape(outro["usuario"])} também está com esta norma aberta. '
                            f'Ao salvar, o sistema confere se há alterações dele que você ainda não tem.</div>', unsafe_allow_html=True)
            vista = st.radio("Vista", ["Editar", "Prévia", "Exportar e salvar"], horizontal=True, key=f"vista_{i}", label_visibility="collapsed")

            # ======================================================== EDITAR
            if vista == "Editar":
                cons['titulo_portaria'] = st.text_input("Título do ato normativo", cons.get('titulo_portaria', ''), key=f"titulo_{i}")
                st.markdown("**Ementa**")
                ementa_editada = editor_rico(value=ia_para_editor(cons.get('ementa', '')), key=f"q_ementa_{i}")
                if ementa_editada is not None:
                    cons['ementa'] = editor_para_pdf(ementa_editada)
                st.markdown("**Preâmbulo e considerandos**")
                preambulo_editado = editor_rico(value=ia_para_editor(cons.get('preambulo', '')), key=f"q_preambulo_{i}")
                if preambulo_editado is not None:
                    cons['preambulo'] = editor_para_pdf(preambulo_editado)

                st.markdown("#### Dispositivos (artigos, parágrafos, incisos, anexos)")
                _disps = cons.get("dispositivos", [])
                _sel = []
                if _disps:
                    # Um dispositivo por vez: antes cada um criava 2 editores Quill (iframes) + data_editors na MESMA página,
                    # o que travava o navegador e re-renderizava tudo a cada clique. As exportações sempre usam o texto completo.
                    _rot = lambda k, _d=_disps: f"{k + 1} · {str(_d[k].get('tipo', '')).upper()} · {_plano(_d[k].get('texto_principal_consolidada'))[:70]}"
                    _jsel = st.selectbox(f"Dispositivo a editar ({len(_disps)} no total; um por vez para a página ficar leve)", list(range(len(_disps))),
                                         format_func=_rot, key=f"sel_disp_{i}")
                    _sel = [(_jsel, _disps[_jsel])]
                for j, disp in _sel:
                    st.markdown(f"**{disp.get('tipo', 'Dispositivo').upper()} {j + 1}**")
                    c_alt, c_cons = st.columns(2)
                    with c_alt:
                        st.caption("Versão alterada")
                        alt_editada = editor_rico(value=ia_para_editor(disp.get('texto_principal_alterada', '')), key=f"q_alt_{i}_{j}")
                        if alt_editada is not None:
                            disp['texto_principal_alterada'] = editor_para_pdf(alt_editada)
                    with c_cons:
                        st.caption("Versão consolidada")
                        cons_editada = editor_rico(value=ia_para_editor(disp.get('texto_principal_consolidada', '')), key=f"q_cons_{i}_{j}")
                        if cons_editada is not None:
                            disp['texto_principal_consolidada'] = editor_para_pdf(cons_editada)
                    disp['nota_remissiva'] = st.text_input("Nota remissiva (injetada automaticamente no final)", value=disp.get('nota_remissiva', ''), key=f"nota_{i}_{j}")
                    if disp.get('is_tabela'):
                        st.caption("Tabela / anexo: revise linha a linha")
                        t_alt, t_cons = st.columns(2)
                        with t_alt:
                            tab_alt_edit = st.data_editor(disp.get('tabela_alterada') or [[""]], key=f"tab_alt_{i}_{j}", num_rows="dynamic", use_container_width=True)
                            disp['tabela_alterada'] = tab_alt_edit if isinstance(tab_alt_edit, list) else disp.get('tabela_alterada')
                            disp['texto_pos_tabela_alterada'] = st.text_area("Texto após a tabela (alterada)", value=disp.get('texto_pos_tabela_alterada') or "", key=f"pos_alt_{i}_{j}")
                        with t_cons:
                            tab_cons_edit = st.data_editor(disp.get('tabela_consolidada') or [[""]], key=f"tab_cons_{i}_{j}", num_rows="dynamic", use_container_width=True)
                            disp['tabela_consolidada'] = tab_cons_edit if isinstance(tab_cons_edit, list) else disp.get('tabela_consolidada')
                            disp['texto_pos_tabela_consolidada'] = st.text_area("Texto após a tabela (consolidada)", value=disp.get('texto_pos_tabela_consolidada') or "", key=f"pos_cons_{i}_{j}")
                    st.divider()

            # ======================================================== PRÉVIA
            elif vista == "Prévia":
                qual = st.radio("Versão", ["Consolidada", "Alterada"], horizontal=True, key=f"prev_{i}")
                try:
                    _hprev = _hash_cons(cons)
                    _cache_prev = ss.setdefault("previas_cons", {})
                    _ent = _cache_prev.get((i, qual))
                    if _ent and _ent[0] == _hprev:
                        corpo = _ent[1]
                    else:
                        corpo = exportacao.corpo_para_previa(cons, "consolidada" if qual == "Consolidada" else "alterada")
                        _cache_prev[(i, qual)] = (_hprev, corpo)
                    st.markdown(f'<div class="cn-papel-barra"><i></i><i></i><i></i>&nbsp;{escape(nome_base)} · versão {qual.lower()}</div><div class="cn-papel">{corpo}</div>', unsafe_allow_html=True)
                    st.caption("Em vermelho/taxado: trechos alterados ou revogados. A prévia é fiel ao conteúdo exportado, mas a paginação final é a do PDF.")
                except Exception as e:
                    st.error(f"Não foi possível montar a prévia: {e}")

            # ======================================================== EXPORTAR E SALVAR
            else:
                st.markdown("##### Salvar no banco de dados")
                conflito = ss.get(f"conflito_{i}")
                if conflito:
                    st.warning("Outro usuário salvou alterações nesta norma depois que você iniciou a análise. Se você salvar agora, estas alterações "
                               "deixarão de constar no texto consolidado: **" + "; ".join(conflito["faltando"]) + "**. "
                               "O ideal é refazer a análise incluindo também esses atos.", icon=":material/merge_type:")
                    forcar = st.checkbox("Entendo o risco: sobrescrever mesmo assim", key=f"forcar_{i}")
                else:
                    forcar = False
                if st.button("Salvar cascata inteira no banco de dados", key=f"btn_sup_{i}", type="primary", icon=":material/cloud_upload:", use_container_width=True):
                    cons_original = dados_originais.get("consolidacoes_geradas", [])[i] if dados_originais else None
                    r = repo.salvar_consolidacao(cons, cons_original, sobrescrever=forcar, usuario=conc.usuario_atual())
                    if r.ok:
                        ss.pop(f"conflito_{i}", None)
                        kpis_cache.clear()
                        st.success("Banco atualizado!", icon=":material/check_circle:")
                    elif r.conflito:
                        ss[f"conflito_{i}"] = r.conflito
                        st.rerun()
                    else:
                        st.error(f"Não foi possível salvar no banco de dados: {r.mensagem}", icon=":material/error:")

                st.markdown("##### Arquivos para download")
                h_atual = _hash_cons(cons)
                chave_exp = f"exp_{i}"
                pronto = ss.exports_cons.get(chave_exp)
                fmts_sel = st.multiselect("Formatos", ["HTML", "DOCX", "PDF"], default=["HTML", "DOCX", "PDF"], key=f"fmts_{i}",
                                          help="Gere só o que precisar: o PDF é o formato mais demorado. Formatos já gerados (sem edições novas) são reaproveitados.")
                if st.button("Preparar arquivos (alterada e consolidada)", key=f"prep_{i}", icon=":material/build:", use_container_width=True, disabled=not fmts_sel):
                    _fn_fmt = {"HTML": ("html", gerar_html_dinamico), "PDF": ("pdf", gerar_pdf_dinamico), "DOCX": ("docx", gerar_docx_dinamico)}
                    arqs = dict(pronto["arqs"]) if (pronto and pronto["hash"] == h_atual) else {}
                    falhas = []
                    with st.status("Gerando arquivos...", expanded=False) as stt:
                        for nome_fmt in fmts_sel:
                            fmt, fn = _fn_fmt[nome_fmt]
                            for tv in ("alterada", "consolidada"):
                                if (fmt, tv) in arqs: continue
                                try:
                                    arqs[(fmt, tv)] = fn(cons, tv)
                                except Exception as e:
                                    falhas.append(f"{fmt.upper()} {tv}: {e}")
                        stt.update(label="Arquivos prontos" if not falhas else "Arquivos gerados com falhas", state="complete" if not falhas else "error")
                    ss.exports_cons[chave_exp] = {"hash": h_atual, "arqs": arqs, "falhas": falhas}
                    pronto = ss.exports_cons[chave_exp]
                if pronto:
                    if pronto["hash"] != h_atual:
                        st.info("O documento foi editado depois da última geração. Gere os arquivos novamente para refletir as edições.", icon=":material/info:")
                    for f in pronto["falhas"]:
                        st.error(f"Falha ao gerar {f}")
                    nome_arq = nome_base.replace(' ', '_').replace('/', '-')
                    mimes = {"html": "text/html", "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
                    cols = st.columns(3)
                    for col, fmt in zip(cols, ("html", "pdf", "docx")):
                        for tv, suf in (("alterada", "Alt"), ("consolidada", "Cons")):
                            dado = pronto["arqs"].get((fmt, tv))
                            if dado is not None:
                                col.download_button(f"{fmt.upper()} · {tv.capitalize()}", data=dado, file_name=f"{nome_arq}_{suf}.{fmt}", mime=mimes[fmt],
                                                    key=f"dl_{fmt}_{tv}_{i}", use_container_width=True, icon=":material/download:")

    ss["_travas_minhas"] = minhas

    if st.button("Nova análise", type="secondary", icon=":material/restart_alt:"):
        _liberar_travas()
        ss.dados_processados = None
        ss.dados_originais_ia = None
        ss.exports_cons = {}
        ss.uploader_cons_ver += 1
        st.rerun()
