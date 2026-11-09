# pages/diagnostico.py - Testa chaves de IA, modelos, Supabase e o estado de concorrência do servidor
import sys
import os
import time
from html import escape
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from menu_utils import configurar_pagina, exigir_login, renderizar_cabecalho, renderizar_menu
import concorrencia as conc
import ui_theme as ui

configurar_pagina("Diagnóstico", "🩺")
exigir_login()
renderizar_menu("diagnostico")
renderizar_cabecalho("Diagnóstico do sistema", "Testa cada chave e modelo configurados nos Secrets, o acesso às tabelas do Supabase e mostra o estado do servidor com vários usuários. As chaves não são exibidas.",
                     etiqueta="Saúde do ambiente", icone_nome="activity")

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
        if hasattr(client, "close"):
            client.close()
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
            response_format={"type": "json_object"}, max_tokens=200)
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



def linha(ok, titulo, detalhe=""):
    tom = "ok" if ok else "danger"
    st.markdown(f'<div class="cn-card {"ok" if ok else "warn"}" style="padding:.6rem 1rem;margin-bottom:.4rem">'
                f'{ui.badge("OK" if ok else "FALHA", tom)} &nbsp;<b>{escape(titulo)}</b> <span style="color:#475569">{escape(detalhe)}</span></div>', unsafe_allow_html=True)


tab_srv, tab_teste = st.tabs([":material/dns: Servidor e concorrência", ":material/science: Testar IA e banco"])

with tab_srv:
    reg = conc.registro()
    online = reg.online()
    ui.kpis([
        ("Sessões online", len(online), "users", "info"),
        ("Chamadas de IA em andamento", reg.ia_em_uso, "cpu", "ok"),
        ("Aguardando vaga de IA", reg.ia_aguardando, "clock", "warn"),
        ("Normas em edição (travas)", len(reg.travas), "lock", "rosa"),
    ])
    st.caption(f"Limite global de chamadas de IA simultâneas: **{reg.ia_max}** (ajustável em Secrets: `[limites] ia_simultaneas = N`). "
               "Isso evita que dois ou mais usuários estourem juntos a cota do provedor.")
    st.markdown("##### Sessões ativas")
    if not online:
        st.caption("Nenhuma.")
    for p in online:
        desde = int((time.time() - p["desde"]) // 60)
        st.markdown(f'{ui.avatar(p.get("usuario") or "?")} &nbsp;**{escape(p.get("usuario") or "?")}** · página `{escape(str(p.get("pagina")))}` · há {desde} min', unsafe_allow_html=True)
    if reg.travas:
        st.markdown("##### Travas de norma")
        for chave, t in list(reg.travas.items()):
            st.markdown(f"`{escape(chave)}` → **{escape(t['usuario'])}**", unsafe_allow_html=True)

with tab_teste:
    if st.button("Executar diagnóstico", type="primary", use_container_width=True, icon=":material/play_arrow:"):
        st.markdown("### Provedores de IA")
        for nome, (motor, nome_chave, modelos) in PROVEDORES.items():
            chave = obter_chave(nome_chave)
            st.markdown(f"**{nome}**")
            if not chave:
                linha(False, nome_chave, "não encontrada nos Secrets")
                continue
            for modelo in modelos:
                inicio = time.time()
                try:
                    testar_modelo(motor, chave, modelo)
                    linha(True, modelo, f"respondeu em {time.time() - inicio:.1f}s")
                except Exception as e:
                    linha(False, modelo, limpar(e))

        st.markdown("### Supabase")
        try:
            from db_utils import obter_supabase
            sb = obter_supabase()
            if sb is None:
                raise RuntimeError("Secrets do Supabase ausentes")
            for tabela in ["usuarios", "portarias_base", "portarias_alteradoras", "atos_importados", "memoria_de_correcoes"]:
                try:
                    sb.table(tabela).select("*").limit(1).execute()
                    linha(True, f"Tabela '{tabela}'", "acessível")
                except Exception as e:
                    linha(False, f"Tabela '{tabela}'", limpar(e))

            nome_teste = "__DIAGNOSTICO__ PORTARIA Nº 0/TESTE"
            reg_t = {"tipo_documento": "PORTARIA", "numero_documento": "0/TESTE", "orgao_emissor": "TESTE",
                     "data_assinatura": "2000-01-01", "nome_padronizado": nome_teste, "documento_consolidado_json": {}}
            try:
                sb.table("portarias_base").upsert(reg_t, on_conflict="nome_padronizado").execute()
                sb.table("portarias_base").upsert(reg_t, on_conflict="nome_padronizado").execute()
                linha(True, "Salvar no banco (upsert em portarias_base)", "funcionando")
            except Exception as e:
                linha(False, "Salvar no banco (upsert em portarias_base)", limpar(e))
            finally:
                try:
                    sb.table("portarias_base").delete().eq("nome_padronizado", nome_teste).execute()
                except Exception:
                    pass
        except Exception as e:
            linha(False, "Conexão com o Supabase", limpar(e))
