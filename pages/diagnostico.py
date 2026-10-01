# pages/diagnostico.py - Testa chaves de IA, modelos e Supabase usando os Secrets do Streamlit Cloud
import sys
import os
import time
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from menu_utils import configurar_pagina, exigir_login, renderizar_cabecalho, renderizar_menu

configurar_pagina("Diagnóstico do Sistema", "🩺")
exigir_login()
renderizar_cabecalho("🩺 Diagnóstico do Sistema")
renderizar_menu("diagnostico")

PROVEDORES = {
    "Google Gemini": ("gemini", "GEMINI_API_KEY", ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]),
    "Groq": ("groq", "GROQ_API_KEY", ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]),
    "OpenRouter": ("openrouter", "OPENROUTER_API_KEY", ["deepseek/deepseek-v4-flash", "qwen/qwen3.5-plus-20260420", "meta-llama/llama-4-maverick"]),
    "Mistral AI": ("mistral", "MISTRAL_API_KEY", ["mistral-small-latest", "open-mistral-nemo"]),
}
PROMPT = 'Responda somente com o JSON {"ok": true}'


def obter_chave(nome):
    try:
        return st.secrets[nome]
    except Exception:
        try:
            return st.secrets["api_keys"][nome]
        except Exception:
            return os.environ.get(nome, "")


def testar_modelo(motor, chave, modelo):
    if motor == "gemini":
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=chave)  # mantém a referência viva durante a chamada
        r = client.models.generate_content(
            model=modelo, contents=PROMPT,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        texto = r.text
        client.close() if hasattr(client, "close") else None
        return texto
    if motor == "groq":
        from groq import Groq
        r = Groq(api_key=chave).chat.completions.create(
            model=modelo, messages=[{"role": "user", "content": PROMPT}],
            response_format={"type": "json_object"})
        return r.choices[0].message.content
    if motor == "openrouter":
        from openai import OpenAI
        r = OpenAI(api_key=chave, base_url="https://openrouter.ai/api/v1").chat.completions.create(
            model=modelo, messages=[{"role": "user", "content": PROMPT}],
            response_format={"type": "json_object"})
        return r.choices[0].message.content
    if motor == "mistral":
        try:
            from mistralai import Mistral
        except ImportError:
            from mistralai.client import Mistral
        r = Mistral(api_key=chave).chat.complete(
            model=modelo, messages=[{"role": "user", "content": PROMPT}],
            response_format={"type": "json_object"})
        return r.choices[0].message.content


def limpar(msg):
    return str(msg).replace("\n", " ")[:300]


st.markdown("Testa cada chave e modelo configurados nos **Secrets** e o acesso às tabelas do Supabase. As chaves não são exibidas.")

if st.button("▶️ Executar diagnóstico", type="primary", use_container_width=True):
    st.markdown("### 🧠 Provedores de IA")
    for nome, (motor, nome_chave, modelos) in PROVEDORES.items():
        chave = obter_chave(nome_chave)
        st.markdown(f"**{nome}**")
        if not chave:
            st.error(f"{nome_chave} não encontrada nos Secrets.")
            continue
        for modelo in modelos:
            inicio = time.time()
            try:
                resp = testar_modelo(motor, chave, modelo)
                st.success(f"{modelo} — respondeu em {time.time() - inicio:.1f}s")
            except Exception as e:
                st.error(f"{modelo} — {limpar(e)}")

    st.markdown("### 🗄️ Supabase")
    try:
        from supabase import create_client
        sb = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
        for tabela in ["usuarios", "portarias_base", "portarias_alteradoras", "atos_importados", "memoria_de_correcoes"]:
            try:
                sb.table(tabela).select("*").limit(1).execute()
                st.success(f"Tabela '{tabela}' acessível")
            except Exception as e:
                st.error(f"Tabela '{tabela}' — {limpar(e)}")

        nome_teste = "__DIAGNOSTICO__ PORTARIA Nº 0/TESTE"
        reg = {"tipo_documento": "PORTARIA", "numero_documento": "0/TESTE", "orgao_emissor": "TESTE",
               "data_assinatura": "2000-01-01", "nome_padronizado": nome_teste, "documento_consolidado_json": {}}
        try:
            sb.table("portarias_base").upsert(reg, on_conflict="nome_padronizado").execute()
            sb.table("portarias_base").upsert(reg, on_conflict="nome_padronizado").execute()
            st.success("Salvar no banco (upsert em portarias_base) funcionando")
        except Exception as e:
            st.error(f"Salvar no banco (upsert em portarias_base) — {limpar(e)}")
        finally:
            try:
                sb.table("portarias_base").delete().eq("nome_padronizado", nome_teste).execute()
            except Exception:
                pass
    except Exception as e:
        st.error(f"Conexão com o Supabase — {limpar(e)}")
