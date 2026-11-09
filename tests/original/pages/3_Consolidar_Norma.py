# pages/3_Consolidar_Norma.py (com correção do erro supabase não definido)
import streamlit as st
import tempfile
import io
import json
import os
import re
import time
import copy
import hashlib
import unicodedata
import base64
import traceback
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

try:
    from weasyprint import HTML as WeasyHTML, CSS as WeasyCSS
    HAS_WEASYPRINT = True
except ImportError:
    HAS_WEASYPRINT = False

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from menu_utils import configurar_pagina, exigir_login, renderizar_cabecalho, renderizar_menu

configurar_pagina("Consolidar Norma", "⚙️")
exigir_login()

# =====================================================================
# INICIALIZAÇÃO DO SUPABASE (CORREÇÃO)
# =====================================================================
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

# =====================================================================

renderizar_cabecalho("⚙️ Consolidação de Normas (Autopilot)")
renderizar_menu("consolidar")

# ----------------- HUB MULTI-IA (mesmo do app.py) -----------------
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

_RE_RODAPE_SEI = re.compile(r'\(\d+\)\s*SEI\s+[\d./-]+\s*/\s*pg\.\s*\d+', re.IGNORECASE)

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
            blocks = page.get_text("dict", sort=True).get("blocks", [])
            # Rodapé de sistema (ex.: "- Portaria PGJM 7 (1022365) SEI ... / pg. 2"): era misturado ao texto e
            # às células das tabelas. Agora é descartado e usado como limite inferior da busca de tabelas.
            rodape_y0 = None
            for b in blocks:
                if b.get('type') != 0: continue
                for l in b.get("lines", []):
                    txt_l = "".join(s.get("text", "") for s in l.get("spans", []))
                    if _RE_RODAPE_SEI.search(txt_l):
                        y = l.get("bbox", (0, 0, 0, 0))[1]
                        rodape_y0 = y if rodape_y0 is None else min(rodape_y0, y)
            tabelas_bbox = []
            tabelas_itens = []  # (y0, texto) — inseridas na posição real da página
            try:
                try:
                    if rodape_y0 is not None:
                        tab_finder = page.find_tables(clip=fitz.Rect(page.rect.x0, page.rect.y0, page.rect.x1, rodape_y0))
                    else:
                        tab_finder = page.find_tables()
                except TypeError:
                    tab_finder = page.find_tables()
                for tabela in tab_finder.tables:
                    linhas = tabela.extract()
                    if not linhas: continue
                    caracteres_uteis += sum(len(str(c or "")) for linha in linhas for c in linha)
                    rect_tab = fitz.Rect(tabela.bbox)
                    tabelas_bbox.append(rect_tab)
                    txt_tab = "[TABELA]\n"
                    for linha in linhas:
                        txt_tab += " | ".join((str(c).strip() if c is not None else "") for c in linha) + "\n"
                    txt_tab += "[/TABELA]\n<br/>\n"
                    tabelas_itens.append((rect_tab.y0, txt_tab))
            except Exception:
                pass
            itens_texto = []
            for b in blocks:
                if b.get('type') != 0: continue
                bloco_rect = fitz.Rect(b.get("bbox", (0, 0, 0, 0)))
                if any(bloco_rect.intersects(tb) for tb in tabelas_bbox):
                    continue
                bloco_linhas = ""
                for l in b.get("lines", []):
                    txt_l = "".join(s.get("text", "") for s in l.get("spans", []))
                    if _RE_RODAPE_SEI.search(txt_l):
                        continue
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
                if bloco_linhas.strip():
                    itens_texto.append((bloco_rect.y0, bloco_linhas.strip() + "<br/>\n"))
            tabelas_itens.sort(key=lambda x: x[0])
            ti = 0
            for y0, txt in itens_texto:
                while ti < len(tabelas_itens) and tabelas_itens[ti][0] <= y0:
                    html_text += tabelas_itens[ti][1]; ti += 1
                html_text += txt
            while ti < len(tabelas_itens):
                html_text += tabelas_itens[ti][1]; ti += 1
            html_text += "<br/>\n"
        if caracteres_uteis < 30 * max(doc.page_count, 1):
            partes = [f"ARQUIVO {nome_arquivo} É UM DOCUMENTO ESCANEADO. Leia o conteúdo visualmente, inclusive tabelas:"]
            for page_num, page in enumerate(doc):
                if max_paginas_ocr is not None and page_num >= max_paginas_ocr:
                    partes.append(f"[Nota: apenas as primeiras {max_paginas_ocr} páginas foram convertidas em imagem por limite do modo de processamento.]")
                    break
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi_ocr, dpi_ocr))
                partes.append({"tipo": "imagem", "mime": "image/jpeg", "dados": pix.tobytes("jpg", jpg_quality=78)})
            return partes
        return [html_text]
    except Exception as e: return [f"Erro ao extrair PDF {nome_arquivo}: {str(e)}"]

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

def _consultar_estado_e_historico(nome_padrao):
    if not supabase or not nome_padrao:
        return None, []
    try:
        res_bd = supabase.table("portarias_base").select("id, documento_consolidado_json").eq("nome_padronizado", nome_padrao).execute()
        if not res_bd.data:
            return None, []
        base_id = res_bd.data[0]['id']
        estado = res_bd.data[0].get("documento_consolidado_json")
        res_alt = supabase.table("portarias_alteradoras").select("nome_padronizado").eq("portaria_base_id", base_id).execute()
        ja_processadas = [r['nome_padronizado'] for r in (res_alt.data or []) if r.get('nome_padronizado')]
        return (json.dumps(estado) if estado else None), ja_processadas
    except Exception:
        return None, []

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
    resp = executar_com_fallback(key, conteudo, ResultadoLote, provedor, thinking_level)
    return json.loads(resp.text).get("alteracoes", [])

def _aplicar_alteracoes_pontuais(key, provedor, thinking_level, nome_alt, itens_alt, estado, memoria, mensagens):
    lotes = _montar_lotes(estado)
    resultados = {}
    workers = 1 if thinking_level == "low" else 2
    with ThreadPoolExecutor(max_workers=min(workers, len(lotes))) as ex:
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
    for alt in alteradoras:
        itens_alt = textos_extraidos[alt['nome_arquivo_upload']]
        txt_alt = _texto_unico(itens_alt)
        head = (txt_alt or "")[:LIMITE_CHARS_PLANO] if txt_alt else None
        conteudo_plano = [f"ATO BASE ALVO: {nome_base}. Analise o ato alterador abaixo e identifique seus metadados e se ele REVOGA INTEGRALMENTE o ato base."]
        conteudo_plano += [head] if head else _conteudo_alteradora(itens_alt, LIMITE_CHARS_PLANO)
        resp_plano = executar_com_fallback(key, conteudo_plano, PlanoAlteracao, provedor, low)
        plano = json.loads(resp_plano.text)
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
    max_workers_extração = 2 if thinking_level == "low" else 4
    with ThreadPoolExecutor(max_workers=min(max_workers_extração, max(1, len(arquivos)))) as ex:
        futuros = {submit_com_contexto(ex, extrair_conteudo_cache, arq.getvalue(), arq.name, dpi_ocr, max_paginas_ocr): arq.name for arq in arquivos}
        total_arquivos = len(arquivos)
        for idx, fut in enumerate(as_completed(futuros)):
            textos_extraidos[futuros[fut]] = fut.result()
            if progresso:
                progresso.progress((idx + 1) / (total_arquivos * 2), text=f"Extraindo conteúdo de {futuros[fut]}...")

    contents_triagem = [f"Analise os documentos. Agrupe cada ato original com seus derivativos presentes neste lote. Se uma Alteradora citar um ato original que NÃO está entre os arquivos deste lote, preencha ato_base_referenciado_tipo/numero com o que ela declara alterar/revogar, para localização posterior no banco de dados. ARQUIVOS: {', '.join(textos_extraidos.keys())}"]
    for partes in textos_extraidos.values(): contents_triagem.extend(partes)
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
# EXPORTAÇÃO (HTML UNIVERSAL -> WEASYPRINT PDF -> DOCX AST)
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
            @page {{
                size: A4;
                margin: 2.5cm 2cm;
                @bottom-center {{
                    content: "Nota: Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial.";
                    font-size: 9pt;
                    font-style: italic;
                    color: #333;
                }}
            }}
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
        eh_capitulo_ou_anexo = "capitulo" in t or "anexo" in t
        texto_puro = re.sub(r'<[^>]+>', '', t_prin or '')
        if eh_capitulo_ou_anexo and len(texto_puro) <= 150:
            # Título curto (ex.: "CAPÍTULO I", "ANEXO I"): mantém o destaque
            # centralizado/negrito/maiúsculo de sempre.
            html += f"<div class='capitulo'>{t_prin}</div>"
            if not item.get("is_tabela"):
                continue
        elif eh_capitulo_ou_anexo:
            # Bloco longo (ex.: corpo inteiro de um Anexo, não só o título):
            # força tudo em negrito/maiúsculo/centralizado deixava o texto
            # ilegível. Só a 1ª linha é o título; o resto vira parágrafo
            # normal, preservando negrito/itálico/riscado originais.
            partes_bloco = (t_prin or "").split("<br/>")
            if partes_bloco:
                html += f"<div class='capitulo'>{partes_bloco[0].strip()}</div>"
                for p in partes_bloco[1:]:
                    if p.strip():
                        html += f"<div class='dispositivo' style='text-indent:0;'>{p.strip()}</div>"
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
        raise Exception("WeasyPrint não está disponível neste servidor.")
    buffer = io.BytesIO()
    WeasyHTML(string=html_str).write_pdf(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def aplicar_html_no_docx(p, texto_html, negrito_forcado=False, tamanho=11):
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
            run.font.name, run.font.size = 'Times New Roman', Pt(tamanho)
            if is_bold or negrito_forcado: run.bold = True
            if is_italic: run.italic = True
            if is_strike: run.font.strike = True
            if is_red: run.font.color.rgb = RGBColor(230, 0, 0)

def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
    doc = docx.Document()
    for section in doc.sections: section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Inches(1)
    ph = doc.add_paragraph(); ph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rh = ph.add_run(f"Versão {'Alterada' if tipo_versao=='alterada' else 'Consolidada'}")
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
                aplicar_html_no_docx(p_obj, p_html, negrito_forcado=True, tamanho=10)
            else: 
                aplicar_html_no_docx(p_obj, p_html)
            p_obj.add_run("\n")

    p_ementa = doc.add_paragraph(); p_ementa.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; p_ementa.paragraph_format.left_indent = Inches(3)
    _render_docx_p(p_ementa, consolidacao_dict.get("ementa", ""))
    p_preambulo = doc.add_paragraph(); p_preambulo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; p_preambulo.paragraph_format.left_indent = Inches(0)
    _render_docx_p(p_preambulo, consolidacao_dict.get("preambulo", ""))

    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva(item.get(f"texto_principal_{tipo_versao}"), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        eh_capitulo_ou_anexo = "capitulo" in t or "anexo" in t
        texto_puro = re.sub(r'<[^>]+>', '', t_prin or '')
        if eh_capitulo_ou_anexo and len(texto_puro) <= 150:
            # Título curto: mantém o destaque centralizado/negrito de sempre.
            if "anexo" in t: doc.add_page_break()
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _render_docx_p(p, t_prin, bold_all=True)
            if not item.get("is_tabela"):
                continue
        elif eh_capitulo_ou_anexo:
            # Bloco longo: só a 1ª linha é o título (centralizado/negrito); o
            # resto vira parágrafo normal, preservando negrito/itálico/riscado
            # originais (bold_all=True apagava essas tags e forçava tudo em
            # negrito, deixando o corpo do Anexo desformatado).
            if "anexo" in t: doc.add_page_break()
            partes_bloco = (t_prin or "").split("<br/>")
            if partes_bloco:
                p_tit = doc.add_paragraph(); p_tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
                aplicar_html_no_docx(p_tit, partes_bloco[0], negrito_forcado=True, tamanho=10)
                corpo_restante = "<br/>".join(partes_bloco[1:]).strip()
                if corpo_restante:
                    p_corpo = doc.add_paragraph(); p_corpo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                    _render_docx_p(p_corpo, corpo_restante)
            if not item.get("is_tabela"):
                continue
        else:
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

    p_nota = doc.add_paragraph(); p_nota.alignment = WD_ALIGN_PARAGRAPH.CENTER; p_nota.paragraph_format.space_before = Pt(30)
    r_nota = p_nota.add_run("Nota: Este documento possui caráter estritamente consultivo e informativo, não substituindo o texto original publicado no Boletim de Serviço Eletrônico (BSe) ou no Diário Oficial.")
    r_nota.font.name = 'Times New Roman'; r_nota.font.size = Pt(9); r_nota.italic = True

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
        res_upsert = supabase.table("portarias_base").upsert({
            "tipo_documento": base['tipo_documento'], "numero_documento": base['numero_documento'],
            "orgao_emissor": base['orgao_emissor'], "data_assinatura": data_base_iso,
            "nome_padronizado": base['nome_padronizado'], "titulo_original": cons.get("titulo_portaria"),
            "orgaos_emissores": cons.get("orgaos_emissores"), "assinatura_nome": cons.get("assinatura_nome"),
            "assinatura_cargo": cons.get("assinatura_cargo"), "documento_consolidado_json": cons,
        }, on_conflict="nome_padronizado").execute()
        if res_upsert.data:
            base_id = res_upsert.data[0]['id']
        else:
            base_id = supabase.table("portarias_base").select("id").eq("nome_padronizado", base['nome_padronizado']).execute().data[0]['id']

        for alt in alteradoras:
            res_alt = supabase.table("portarias_alteradoras").select("id").eq("portaria_base_id", base_id).eq("nome_padronizado", alt['nome_padronizado']).execute()
            if not res_alt.data:
                data_alt_iso = converter_para_iso(alt.get('data_assinatura'))
                supabase.table("portarias_alteradoras").insert({"portaria_base_id": base_id, "tipo_documento": alt['tipo_documento'], "numero_documento": alt['numero_documento'], "orgao_emissor": alt['orgao_emissor'], "data_assinatura": data_alt_iso, "nome_padronizado": alt['nome_padronizado'], "arquivo_nome_original": "Múltiplos Documentos"}).execute()
        return True
    except Exception as e:
        st.error(f"❌ Não foi possível salvar no banco de dados: {e}")
        return False

# =====================================================================
# FRONT-END
# =====================================================================
st.markdown("""
Envie um ato base e seus derivativos (alteradores/revogadores) em PDF. O sistema aplica as alterações
em ordem cronológica e gera as versões alterada e consolidada, com taxação das alterações e revogações.
""")

provedor_escolhido = st.selectbox("🧠 Motor de IA (Hub Multi-IA)", list(PROVEDORES_IA.keys()), key="provedor_ia_cons")
modo_processamento = st.radio(
    "⚡ Modo de Processamento",
    ["Equilibrado", "Rápido", "Máxima Qualidade"],
    index=0,
    horizontal=True,
)
cfg_provedor = PROVEDORES_IA[provedor_escolhido]
api_key = obter_chave_provedor(provedor_escolhido)
if not api_key:
    api_key = st.text_input(f"Chave da API ({cfg_provedor['secret']} não encontrada nos secrets)", type="password", placeholder=f"Cole sua chave de {provedor_escolhido} aqui...")
st.caption(f"Modelos utilizados (do mais capaz ao mais estável): {' → '.join(cfg_provedor['modelos'])}")

st.markdown("### 📥 Upload de Arquivos Normativos")
st.caption("Aceita Leis, Decretos, Resoluções, Enunciados, Portarias e demais atos normativos, em PDF.")
arquivos_enviados = st.file_uploader("Arraste todos os documentos (PDF) — um ato original e todos os seus derivativos", type=["pdf"], accept_multiple_files=True, key="uploader_cons")

if "dados_processados" not in st.session_state: st.session_state.dados_processados = None
if "dados_originais_ia" not in st.session_state: st.session_state.dados_originais_ia = None

if st.button("🚀 Iniciar Análise Autopilot", type="primary", use_container_width=True):
    if not api_key: st.error("⚠️ Insira sua chave da API nas configurações.")
    elif not arquivos_enviados: st.warning("⚠️ Envie os arquivos normativos primeiro.")
    else:
        if modo_processamento == "Rápido":
            thinking_level = "low"; dpi_ocr = 1.2; max_paginas_ocr = 10
        elif modo_processamento == "Equilibrado":
            thinking_level = "medium"; dpi_ocr = 1.5; max_paginas_ocr = 20
        else:
            thinking_level = "high"; dpi_ocr = 1.5; max_paginas_ocr = None

        with st.spinner("⚡ Executando OCR Estrutural e Consulta ao Histórico de Aprendizado..."):
            progresso = st.progress(0.0, text="Iniciando análise...")
            try:
                st.session_state.dados_processados = None
                st.session_state.dados_originais_ia = None
                st.session_state.dados_processados = analisar_lote_arquivos(
                    arquivos_enviados,
                    api_key.strip(),
                    provedor_escolhido,
                    thinking_level=thinking_level,
                    dpi_ocr=dpi_ocr,
                    max_paginas_ocr=max_paginas_ocr,
                    progresso=progresso
                )
                st.session_state.dados_originais_ia = copy.deepcopy(st.session_state.dados_processados)
                progresso.progress(1.0, text="Análise concluída!")
                if st.session_state.dados_processados.get("consolidacoes_geradas"):
                    st.success("✨ Processamento concluído!")
                else:
                    st.warning("⚠️ O processamento terminou, mas nenhuma consolidação foi gerada. Veja os detalhes abaixo.")
            except Exception as e:
                st.error(f"❌ Ocorreu um erro: {str(e)}")
                with st.expander("🔍 Detalhes técnicos do erro"):
                    st.code(traceback.format_exc())
            finally:
                progresso.empty()

if st.session_state.dados_processados:
    st.markdown("---")
    dados = st.session_state.dados_processados
    dados_originais = st.session_state.dados_originais_ia

    for tipo_msg, texto_msg in dados.get("mensagens", []):
        if tipo_msg == "warning": st.warning(texto_msg)
        else: st.info(texto_msg)
    for texto_erro in dados.get("erros", []):
        st.error(f"❌ {texto_erro}")
    if dados.get("arquivos_nao_classificados"):
        st.warning("⚠️ A IA não classificou estes arquivos e eles não foram processados: " + ", ".join(dados["arquivos_nao_classificados"]))
    if dados.get("arquivos_nao_alterados") and not dados.get("consolidacoes_geradas"):
        st.info("Arquivos que não geraram consolidação: " + ", ".join(dict.fromkeys(dados["arquivos_nao_alterados"])))

    referencias_pendentes = dados.get("referencias_pendentes", [])
    if referencias_pendentes:
        st.warning("⚠️ Alguns arquivos fazem referência a normas que não foram encontradas no lote nem no banco de dados. Para processar essas alterações, envie também o(s) ato(s) original(is) correspondente(s).")
        for ref in referencias_pendentes:
            ato_ref = f"{ref.get('ato_referenciado_tipo', 'Desconhecido')} {ref.get('ato_referenciado_numero', 'Desconhecido')}"
            arquivos = ", ".join(ref.get("arquivos_alteradores", []))
            st.markdown(f"- **Referência:** {ato_ref}  \n  **Alteradora(s):** {arquivos}")

    for i, cons in enumerate(dados.get("consolidacoes_geradas", [])):
        nome_exibicao_base = cons['norma_base']['nome_padronizado']
        nomes_alteradoras = [alt['nome_padronizado'] for alt in cons.get('normas_alteradoras', [])]
        nome_exibicao_alt = " e ".join(nomes_alteradoras) if nomes_alteradoras else "Desconhecido"
        
        with st.expander(f"📁 **{nome_exibicao_base}** alterada por **{nome_exibicao_alt}**", expanded=True):
            st.markdown("### 📝 Editor Visual de Documento")

            cons['titulo_portaria'] = st.text_input("Título do Ato Normativo", cons.get('titulo_portaria', ''), key=f"titulo_{i}")
            st.markdown("**Ementa**")
            val_ementa = ia_para_editor(cons.get('ementa', ''))
            ementa_editada = editor_rico(value=val_ementa, key=f"q_ementa_{i}")
            if ementa_editada is not None: cons['ementa'] = editor_para_pdf(ementa_editada)

            st.markdown("**Preâmbulo e Considerandos**")
            val_preambulo = ia_para_editor(cons.get('preambulo', ''))
            preambulo_editado = editor_rico(value=val_preambulo, key=f"q_preambulo_{i}")
            if preambulo_editado is not None: cons['preambulo'] = editor_para_pdf(preambulo_editado)

            st.markdown("#### Dispositivos (Artigos, Parágrafos, Incisos, Anexos)")
            _n_disp = len(cons.get("dispositivos", []))
            _editar_detalhado = True
            if _n_disp > LIMITE_EDICAO_DETALHADA:
                _editar_detalhado = st.checkbox(f"✏️ Habilitar edição detalhada dos {_n_disp} dispositivos (pode deixar a página lenta). As exportações já contêm o texto completo.", value=False, key=f"edit_det_{i}")
            for j, disp in enumerate(cons.get("dispositivos", []) if _editar_detalhado else []):
                st.markdown(f"**{disp.get('tipo', 'Dispositivo').upper()} {j+1}**")
                c_alt, c_cons = st.columns(2)
                with c_alt:
                    st.markdown("*Versão Alterada*")
                    val_alt = ia_para_editor(disp.get('texto_principal_alterada', ''))
                    alt_editada = editor_rico(value=val_alt, key=f"q_alt_{i}_{j}")
                    if alt_editada is not None: disp['texto_principal_alterada'] = editor_para_pdf(alt_editada)
                with c_cons:
                    st.markdown("*Versão Consolidada*")
                    val_cons = ia_para_editor(disp.get('texto_principal_consolidada', ''))
                    cons_editada = editor_rico(value=val_cons, key=f"q_cons_{i}_{j}")
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
            nome_arquivo_base = nome_exibicao_base.replace(' ', '_').replace('/', '-')

            try:
                html_alt = gerar_html_dinamico(cons, "alterada")
                html_cons = gerar_html_dinamico(cons, "consolidada")
                c_html.download_button("🌐 Baixar HTML (Alterada)", data=html_alt, file_name=f"{nome_arquivo_base}_Alt.html", mime="text/html", key=f"ha_{i}")
                c_html.download_button("🌐 Baixar HTML (Consolidada)", data=html_cons, file_name=f"{nome_arquivo_base}_Cons.html", mime="text/html", key=f"hc_{i}")
            except Exception as e:
                c_html.error(f"Falha ao gerar HTML: {e}")

            try:
                pdf_alt = gerar_pdf_dinamico(cons, "alterada")
                pdf_cons = gerar_pdf_dinamico(cons, "consolidada")
                c_pdf.download_button("📄 Baixar PDF (Alterada)", data=pdf_alt, file_name=f"{nome_arquivo_base}_Alt.pdf", mime="application/pdf", key=f"pa_{i}")
                c_pdf.download_button("📄 Baixar PDF (Consolidada)", data=pdf_cons, file_name=f"{nome_arquivo_base}_Cons.pdf", mime="application/pdf", key=f"pc_{i}")
            except Exception as e:
                c_pdf.error(f"Falha ao gerar PDF: {e}")

            try:
                docx_alt = gerar_docx_dinamico(cons, "alterada")
                docx_cons = gerar_docx_dinamico(cons, "consolidada")
                c_docx.download_button("📝 Baixar DOCX (Alterada)", data=docx_alt, file_name=f"{nome_arquivo_base}_Alt.docx", mime="application/vnd.openxmlformats", key=f"da_{i}")
                c_docx.download_button("📝 Baixar DOCX (Consolidada)", data=docx_cons, file_name=f"{nome_arquivo_base}_Cons.docx", mime="application/vnd.openxmlformats", key=f"dc_{i}")
            except Exception as e:
                c_docx.error(f"Falha ao gerar DOCX: {e}")

    if st.button("🔄 Nova Análise", type="secondary"):
        st.session_state.dados_processados = None
        st.session_state.dados_originais_ia = None
        st.rerun()
