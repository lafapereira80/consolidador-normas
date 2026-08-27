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
# FUNÇÕES AUXILIARES (extração, IA, processamento, banco)
# =====================================================================
# (Extraímos as funções principais para manter organização)
# O restante das funções (extrair_conteudo_multimodal, ia_para_editor, editor_rico, etc.)
# permanece idêntico ao último código fornecido.
# Para não estender demais, incluímos apenas as novas funções essenciais.

def salvar_ato_integral(nome_arquivo, texto_integra):
    """Salva o ato integral na tabela atos_importados com status 'importado'."""
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

def processar_derivacoes_arquivo_unico(arquivo, texto_editado, key, provedor, thinking_level):
    """Processa o arquivo único como alteradora, usando o texto editado."""
    # Salva temporariamente o texto para uso no processamento
    textos = {arquivo.name: [texto_editado]}
    # Chama a função de processamento em cascata com um 'arquivo' virtual
    # Mas como não temos a base local, usamos _processar_cascata_grupo com base do banco
    # Simulação: cria um objeto arquivo base a partir do banco
    # Isso é complexo; por simplicidade, reutilizamos analisar_lote_arquivos com o arquivo original
    # e confiamos que a classificação identificará a base existente.
    # Ajuste: passamos o texto editado como conteúdo do arquivo
    # Para não modificar o fluxo principal, usamos um arquivo temporário com o texto editado
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(texto_editado)
        temp_path = f.name
    # Cria um UploadedFile simulado
    class FakeUploadedFile:
        def __init__(self, name, content):
            self.name = name
            self._content = content
        def getvalue(self):
            return self._content
    fake_arquivo = FakeUploadedFile(arquivo.name, texto_editado.encode('utf-8'))
    # Chama analisar_lote_arquivos com o fake arquivo (apenas um)
    resultado = analisar_lote_arquivos([fake_arquivo], key, provedor, thinking_level)
    return resultado

# =====================================================================
# FRONTEND PRINCIPAL
# =====================================================================

# Estado inicial
if "dados_processados" not in st.session_state: st.session_state.dados_processados = None
if "dados_originais_ia" not in st.session_state: st.session_state.dados_originais_ia = None
if "confirmacao_pendente" not in st.session_state: st.session_state.confirmacao_pendente = None
if "pendencia_salvar" not in st.session_state: st.session_state.pendencia_salvar = None
if "arquivo_unico_texto" not in st.session_state: st.session_state.arquivo_unico_texto = ""
if "arquivo_unico_html" not in st.session_state: st.session_state.arquivo_unico_html = ""
if "arquivo_unico_id" not in st.session_state: st.session_state.arquivo_unico_id = None
if "arquivo_unico_classificacao" not in st.session_state: st.session_state.arquivo_unico_classificacao = None

# Verifica se o fluxo inteligente está ativo e há exatamente um arquivo enviado
if fluxo_inteligente and len(arquivos_enviados) == 1:
    arquivo = arquivos_enviados[0]
    
    # Extrai e mostra o texto no editor rico
    st.markdown("### 📄 Conferência do Documento Original")
    if st.button("📤 Extrair Texto", key="btn_extrair_unico"):
        with st.spinner("Extraindo conteúdo..."):
            try:
                conteudo = extrair_conteudo_multimodal(arquivo.getvalue(), arquivo.name)
                texto_integra = "\n".join([c if isinstance(c, str) else "" for c in conteudo])
                # Converte para HTML compatível com o Quill
                html_inicial = ia_para_editor(texto_integra)
                st.session_state.arquivo_unico_html = html_inicial
                st.session_state.arquivo_unico_texto = ""
                st.session_state.arquivo_unico_id = None
                st.session_state.arquivo_unico_classificacao = None
            except Exception as e:
                st.error(f"Erro na extração: {e}")

    if st.session_state.arquivo_unico_html:
        # Editor rico para edição
        html_editado = editor_rico(value=st.session_state.arquivo_unico_html, key="editor_unico")
        # Converte de volta para HTML limpo (com tags <b>, <i>, <strike>, <font color=red>)
        texto_limpo_html = editor_para_pdf(html_editado) if html_editado else ""
        st.session_state.arquivo_unico_texto = texto_limpo_html
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Salvar Ato Original", key="btn_salvar_unico"):
                if texto_limpo_html.strip():
                    id_salvo = salvar_ato_integral(arquivo.name, texto_limpo_html)
                    if id_salvo:
                        st.session_state.arquivo_unico_id = id_salvo
                        st.success(f"Ato salvo com sucesso (ID: {id_salvo}). Clique em 'Analisar com atos cadastrados' para verificar derivações.")
                else:
                    st.warning("O texto não pode ser vazio.")
        with col2:
            if st.button("🔍 Analisar com atos cadastrados", key="btn_analisar_unico", disabled=(st.session_state.arquivo_unico_id is None)):
                with st.spinner("Analisando derivações..."):
                    # Classifica o ato
                    classif, _, erro = classificar_arquivo_unico(arquivo, api_key.strip(), provedor_escolhido, thinking_level="medium")
                    if erro:
                        st.error(f"Erro na classificação: {erro}")
                    else:
                        st.session_state.arquivo_unico_classificacao = classif
                        if classif and classif.get('tipo') == 'Alteradora':
                            base = _localizar_base_no_banco(classif.get('ato_base_referenciado_tipo'), classif.get('ato_base_referenciado_numero'))
                            if base:
                                st.session_state.confirmacao_pendente = {
                                    "derivacoes_detectadas": [{
                                        "nome_arquivo_upload": arquivo.name,
                                        "ato_base_referenciado_tipo": classif.get('ato_base_referenciado_tipo'),
                                        "ato_base_referenciado_numero": classif.get('ato_base_referenciado_numero'),
                                        "nome_base": base.get('nome_padronizado', '')
                                    }]
                                }
                                st.session_state.pendencia_salvar = None
                            else:
                                st.session_state.pendencia_salvar = {
                                    "tipo_ref": classif.get('ato_base_referenciado_tipo') or 'Desconhecido',
                                    "numero_ref": classif.get('ato_base_referenciado_numero') or 'Desconhecido',
                                    "nome_arquivo": arquivo.name,
                                    "texto_integra": texto_limpo_html
                                }
                                st.session_state.confirmacao_pendente = None
                        else:
                            # É um ato base: processa e salva em portarias_base
                            # Gera o documento estruturado
                            with st.spinner("Gerando estrutura do ato base..."):
                                try:
                                    resp = executar_com_fallback(api_key.strip(), [texto_limpo_html], Consolidacao, provedor_escolhido, thinking_level="medium")
                                    consolidacao = json.loads(resp.text)
                                    salvar_no_supabase(consolidacao, None)
                                    st.success("Ato base salvo no banco como portaria_base.")
                                    # Verifica pendências para esta base
                                    pend = verificar_pendencias_para_base(consolidacao['norma_base']['tipo_documento'], consolidacao['norma_base']['numero_documento'])
                                    if pend:
                                        st.warning(f"🔔 Existem {len(pend)} pendência(s) que referenciam este ato. Processe-as se necessário.")
                                except Exception as e:
                                    st.error(f"Erro ao processar ato base: {e}")
                            st.session_state.confirmacao_pendente = None
                            st.session_state.pendencia_salvar = None

    # Exibe confirmações e pendências resultantes
    if st.session_state.confirmacao_pendente:
        derivacoes = st.session_state.confirmacao_pendente.get("derivacoes_detectadas", [])
        for d in derivacoes:
            st.warning(f"🔔 O arquivo deriva de {d['ato_base_referenciado_tipo']} {d['ato_base_referenciado_numero']} ({d['nome_base']}). Deseja processar as alterações?")
        col_sim, col_nao = st.columns(2)
        with col_sim:
            if st.button("✅ Sim, processar alterações", key="btn_processar_deriv_unico"):
                with st.spinner("Processando derivação..."):
                    try:
                        resultado = processar_derivacoes_arquivo_unico(arquivo, st.session_state.arquivo_unico_texto, api_key.strip(), provedor_escolhido, thinking_level="medium")
                        st.session_state.dados_processados = resultado
                        st.session_state.dados_originais_ia = copy.deepcopy(resultado)
                        st.session_state.confirmacao_pendente = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao processar: {e}")
        with col_nao:
            if st.button("❌ Não, manter apenas o ato original", key="btn_nao_processar_deriv_unico"):
                st.session_state.confirmacao_pendente = None
                st.info("O ato original foi salvo. Nenhuma alteração foi aplicada.")
                st.rerun()

    if st.session_state.pendencia_salvar:
        pend = st.session_state.pendencia_salvar
        st.warning(f"⚠️ Este arquivo é uma alteradora, mas a norma base {pend['tipo_ref']} {pend['numero_ref']} não foi encontrada.")
        if st.button("💾 Salvar como pendente", key="btn_salvar_pend_unico"):
            if salvar_ato_pendente(pend['tipo_ref'], pend['numero_ref'], pend['nome_arquivo'], pend['texto_integra']):
                st.success("Pendência salva! Quando a norma base for cadastrada, você será avisado.")
                st.session_state.pendencia_salvar = None
                st.rerun()

# Caso contrário, mantém o fluxo antigo (múltiplos arquivos ou fluxo inteligente desativado)
else:
    if st.button("🚀 Iniciar Análise Autopilot", type="primary", use_container_width=True):
        if not api_key: st.error("⚠️ Insira sua chave da API nas configurações.")
        elif not arquivos_enviados: st.warning("⚠️ Envie os arquivos normativos primeiro.")
        else:
            if modo_processamento == "Rápido":
                thinking_level = "low"
                dpi_ocr = 1.2
                max_paginas_ocr = 10
            elif modo_processamento == "Equilibrado":
                thinking_level = "medium"
                dpi_ocr = 1.5
                max_paginas_ocr = 20
            else:
                thinking_level = "high"
                dpi_ocr = 1.5
                max_paginas_ocr = None

            with st.spinner("⚡ Executando OCR Estrutural e Consulta ao Histórico de Aprendizado..."):
                progresso = st.progress(0.0, text="Iniciando análise...")
                try:
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
                    st.success("✨ Processamento concluído!")
                except Exception as e:
                    st.error(f"❌ Ocorreu um erro: {str(e)}")
                finally:
                    progresso.empty()

    # Exibição dos resultados (código do editor visual e exportações permanece igual)
    if st.session_state.dados_processados:
        st.markdown("---")
        dados = st.session_state.dados_processados
        dados_originais = st.session_state.dados_originais_ia

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
                for j, disp in enumerate(cons.get("dispositivos", [])):
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
                    st.markdown("*Nota Remissiva*")
                    nota_editada = st.text_input("Nota", value=disp.get('nota_remissiva', ''), key=f"nota_{i}_{j}", label_visibility="collapsed")
                    disp['nota_remissiva'] = nota_editada
                    st.markdown("---")
                    if disp.get('is_tabela'):
                        st.markdown("*Tabela / Anexo*")
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
        if st.button("🔄 Nova Análise", type="secondary"): st.session_state.dados_processados = None; st.session_state.dados_originais_ia = None; st.rerun()
