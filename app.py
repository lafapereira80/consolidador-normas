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
from typing import List, Optional, Any, Dict

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
        "modelos": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-70b-versatile"],
        "secret": "GROQ_API_KEY",
    },
    "OpenRouter (Qwen / DeepSeek / Llama)": {
        "motor": "openrouter",
        "modelos": ["qwen/qwen-2.5-72b-instruct", "meta-llama/llama-3.3-70b-instruct:free"],
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
    if not supabase: return False
    try:
        res = supabase.table("usuarios").select("id, password_hash").eq("username", username).execute()
        if res.data and len(res.data) > 0:
            ok, precisa_migrar = verificar_senha(password, res.data[0]['password_hash'])
            if ok and precisa_migrar:
                try: supabase.table("usuarios").update({"password_hash": gerar_hash_senha(password)}).eq("id", res.data[0]['id']).execute()
                except: pass
            return ok
    except Exception as e: pass
    return False

if not st.session_state.autenticado:
    st.markdown("""
    <style>
        div[data-testid="stAppViewContainer"] { display: flex; align-items: center; }
        .st-key-login_card { max-width: 420px; margin: 4rem auto; padding: 1.5rem 2rem; background: #ffffff; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.12); }
        .login-title { text-align: center; color: #1e3c72; font-weight: 800; font-size: 1.8rem; margin-bottom: 0.3rem; }
    </style>
    """, unsafe_allow_html=True)
    _, col_login, _ = st.columns([1, 1.3, 1])
    with col_login:
        with st.container(border=True, key="login_card"):
            st.markdown('<div class="login-title">⚖️ Autopilot Normativo</div>', unsafe_allow_html=True)
            with st.form("form_login"):
                usuario = st.text_input("Usuário")
                senha = st.text_input("Senha", type="password")
                if st.form_submit_button("Entrar", use_container_width=True):
                    if verificar_login(usuario, senha):
                        st.session_state.autenticado = True
                        st.rerun()
                    else: st.error("❌ Usuário ou senha incorretos.")
    st.stop()

st.markdown("""<div class="main-header"><h1>⚖️ Autopilot Normativo</h1><p>Motor Híbrido OCR e Aprendizado Contínuo com Efeito Cascata</p></div>""", unsafe_allow_html=True)

col_info, col_hist, col_usr, col_logout = st.columns([3, 1.5, 1.5, 1])
with col_info: st.info("💡 **Sistema Autenticado:** Proteção de dados ativa.")
hist_path = "pages/1_Historico.py" if os.path.exists("pages/1_Historico.py") else "pages/historico.py"
usr_path = "pages/usuarios.py"
with col_hist:
    try: st.page_link(hist_path, label="🗄️ Histórico", icon="➡️")
    except: st.markdown(f'<a href="{hist_path.replace("pages/","").replace(".py","")}" target="_top" style="display:block;text-align:center;background:#f0f2f6;border:1px solid #d0d4dc;color:#31333F;padding:0.5rem;border-radius:0.5rem;text-decoration:none;font-weight:500;">➡️ 🗄️ Histórico</a>', unsafe_allow_html=True)
with col_usr:
    try: st.page_link(usr_path, label="👥 Usuários", icon="➡️")
    except: st.markdown(f'<a href="{usr_path.replace("pages/","").replace(".py","")}" target="_top" style="display:block;text-align:center;background:#f0f2f6;border:1px solid #d0d4dc;color:#31333F;padding:0.5rem;border-radius:0.5rem;text-decoration:none;font-weight:500;">➡️ 👥 Usuários</a>', unsafe_allow_html=True)
with col_logout:
    if st.button("Sair", type="secondary", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()
st.markdown("---")

provedor_escolhido = st.selectbox("🧠 Motor de IA (Hub Multi-IA)", list(PROVEDORES_IA.keys()), key="provedor_ia_select")
modo_processamento = st.radio("⚡ Modo de Processamento", ["Equilibrado", "Rápido", "Máxima Qualidade"], index=0, horizontal=True)

cfg_provedor = PROVEDORES_IA[provedor_escolhido]
api_key = obter_chave_provedor(provedor_escolhido)
if not api_key: api_key = st.text_input(f"Chave da API", type="password")

st.markdown("### 📥 Upload e Tratamento de Atos Normativos")
arquivos_enviados = st.file_uploader("Arraste o documento original ou derivativo (PDF)", type=["pdf"], accept_multiple_files=True, key="uploader_lote")

# =====================================================================
# MOTOR HTML / QUILL
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
            for t in tags: res += f"<{t}>"
        return res
    def _break_paragraph(self):
        if self.current_html:
            p_text = "".join(self.current_html) + self._close_all_tags()
            if re.sub(r'<[^>]+>', '', p_text).strip(): self.paragraphs.append(p_text.strip())
        self.current_html = []
        if self.stack: self.current_html.append(self._open_all_tags())
    def handle_starttag(self, tag, attrs):
        if tag in ('p', 'br', 'div'): return self._break_paragraph()
        attrs_dict = dict(attrs)
        style = attrs_dict.get('style', '').lower().replace(' ', '')
        cls = attrs_dict.get('class', '').lower()
        added_tags = []
        if tag in ('b', 'strong') or 'font-weight:bold' in style or 'font-weight:700' in style: added_tags.append("b")
        if tag in ('i', 'em') or 'font-style:italic' in style: added_tags.append("i")
        if tag in ('s', 'strike', 'del') or 'text-decoration:line-through' in style or 'ql-strike' in cls: added_tags.append("strike")
        if ('color:rgb(230' in style or 'color:red' in style or 'color:#f00' in style) or (tag == 'font' and attrs_dict.get('color') in ('red', '#f00', '#ff0000')): added_tags.append('font color="red"')
        if added_tags:
            for t in added_tags: self.current_html.append(f"<{t}>")
            self.stack.append(added_tags)
        else: self.stack.append([])
    def handle_endtag(self, tag):
        if tag in ('p', 'br', 'div'): return 
        if self.stack:
            tags_to_close = self.stack.pop()
            for t in reversed(tags_to_close): self.current_html.append(f"</{t.split()[0]}>")
    def handle_startendtag(self, tag, attrs):
        if tag in ('br',): self._break_paragraph()
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

_QUILL_TOOLBAR = [["bold", "italic", "underline", "strike"], [{"color": []}, {"background": []}], [{"list": "ordered"}, {"list": "bullet"}], ["clean"]]

def editor_rico(value, key):
    try: return st_quill(value=value, html=True, toolbar=_QUILL_TOOLBAR, key=key)
    except Exception: return st.text_area("HTML", value=value, key=f"{key}_fallback", label_visibility="collapsed", height=150)

def editor_para_pdf(texto):
    if not texto: return ""
    parser = QuillParser()
    try:
        parser.feed(texto)
        return "<br/>".join(parser.get_paragraphs())
    except Exception: return re.sub(r'</?(span|div|p|ul|li|ol)[^>]*>', '', texto, flags=re.IGNORECASE)

# =====================================================================
# SCHEMAS
# =====================================================================
class ArquivoClassificado(BaseModel):
    nome_arquivo_upload: str
    tipo: str = Field(description="'Base' ou 'Alteradora'")
    grupo_id: int
    nome_padronizado_identificado: str
    data_oficial_iso: str
    ato_base_referenciado_tipo: Optional[str] = None
    ato_base_referenciado_numero: Optional[str] = None

class TriagemDocumentos(BaseModel): arquivos: List[ArquivoClassificado]

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
Você é um Especialista Sênior em Técnica Legislativa do Poder Público.
1. FIDELIDADE ABSOLUTA: transcreva o conteúdo de cada dispositivo, preservando formatação (<b>, <i>, <br/>).
2. SEPARAÇÃO OBRIGATÓRIA: 'ementa' (resumo) e 'preambulo' (autoridade/considerandos).
3. CRITÉRIO RIGOROSO DE ALTERAÇÃO:
   Na versão ALTERADA (`texto_principal_alterada`), todo dispositivo alterado/revogado DEVE aparecer com a tag exata: `<strike><font color="red">texto antigo alterado/revogado</font></strike>` seguido imediatamente pelo texto novo vigente. Em caso de revogação, apenas risque e indique a revogação.
   Na versão CONSOLIDADA (`texto_principal_consolidada`), exiba apenas a NOVA redação vigente sem riscos, ou o identificador + "(Revogado)".
4. ACÚMULO DE NOTAS REMISSIVAS (EFEITO CASCATA): Se o texto de origem (fornecido no prompt como estado atual) JÁ POSSUIR uma nota remissiva de alteração passada (ex: '(Redação dada pela PORTARIA X)'), VOCÊ NUNCA DEVE APAGÁ-LA. Mantenha a nota antiga e adicione a NOVA nota da nova alteradora logo em seguida. Exemplo: '(Redação dada pela PORTARIA X) (Redação dada pela PORTARIA Y)'. Mantenha a ordem cronológica da mais antiga para a mais nova. O mesmo vale para tabelas.
"""

def _prompt_schema_json(response_schema):
    return "\n\nRESPONDA EXCLUSIVAMENTE COM JSON VÁLIDO QUE OBEDEÇA AO SCHEMA:\n" + json.dumps(response_schema.model_json_schema(), ensure_ascii=False)

def _extrair_json_bruto(texto):
    t = re.sub(r'^```(json)?', '', texto.strip(), flags=re.IGNORECASE).strip()
    t = re.sub(r'```$', '', t.strip()).strip()
    inicio, fim = t.find('{'), t.rfind('}')
    return t[inicio:fim + 1]

def extrair_conteudo_multimodal(file_bytes, nome_arquivo, dpi_ocr=1.5, max_paginas_ocr=None):
    if nome_arquivo.lower().endswith(".docx"): return [f"ARQUIVO DOCX: {nome_arquivo}"]
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        html_text = f"CONTEÚDO DO ARQUIVO {nome_arquivo}:\n\n"
        caracteres_uteis = 0
        for page_num, page in enumerate(doc):
            html_text += f"=== PÁGINA {page_num + 1} ===\n"
            tabelas_bbox = []
            try:
                for tabela in page.find_tables().tables:
                    linhas = tabela.extract()
                    if not linhas: continue
                    caracteres_uteis += sum(len(str(c or "")) for linha in linhas for c in linha)
                    tabelas_bbox.append(fitz.Rect(tabela.bbox))
                    html_text += "[TABELA]\n"
                    for linha in linhas: html_text += " | ".join((str(c).strip() if c is not None else "") for c in linha) + "\n"
                    html_text += "[/TABELA]\n<br/>\n"
            except: pass
            for b in page.get_text("dict", sort=True).get("blocks", []):
                if b.get('type') != 0: continue
                if any(fitz.Rect(b.get("bbox", (0,0,0,0))).intersects(tb) for tb in tabelas_bbox): continue
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
            partes = [f"ARQUIVO {nome_arquivo} É UM DOCUMENTO ESCANEADO. Leia o conteúdo visualmente:"]
            for page_num, page in enumerate(doc):
                if max_paginas_ocr and page_num >= max_paginas_ocr: break
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi_ocr, dpi_ocr))
                partes.append({"tipo": "imagem", "mime": "image/jpeg", "dados": pix.tobytes("jpg", jpg_quality=78)})
            return partes
        return [html_text]
    except Exception as e: return [f"Erro: {str(e)}"]

@st.cache_data(show_spinner=False, max_entries=20)
def extrair_conteudo_cache(file_bytes, nome_arquivo, dpi_ocr=1.5, max_paginas_ocr=None):
    return extrair_conteudo_multimodal(file_bytes, nome_arquivo, dpi_ocr, max_paginas_ocr)

def _chamar_motor(motor, chave, itens, schema, thinking_level, modelos):
    if motor == "gemini":
        client = genai.Client(api_key=chave)
        config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, system_instruction=SYSTEM_INSTRUCTION_LEGISTECNICA, thinking_config=types.ThinkingConfig(thinking_level=thinking_level))
        partes = [types.Part.from_bytes(data=it["dados"], mime_type=it["mime"]) if isinstance(it, dict) else it for it in itens]
        for mod in modelos:
            for _ in range(3):
                try:
                    resp = client.models.generate_content(model=mod, contents=partes, config=config)
                    return schema.model_validate(json.loads(resp.text))
                except Exception as e: 
                    if "429" in str(e) or "503" in str(e): time.sleep(5); continue
                    break
        raise Exception("Gemini falhou.")
    else:
        textos, imagens = [], []
        for it in itens:
            if isinstance(it, dict): imagens.append(it)
            else: textos.append(it)
        texto_final = "\n\n".join(textos) + _prompt_schema_json(schema)
        conteudo = [{"type": "text", "text": texto_final}]
        for img in imagens: conteudo.append({"type": "image_url", "image_url": {"url": f"data:{img['mime']};base64,{base64.b64encode(img['dados']).decode()}"}})
        mensagens = [{"role": "system", "content": SYSTEM_INSTRUCTION_LEGISTECNICA}, {"role": "user", "content": conteudo}]
        
        client = None
        if motor == "groq" and Groq: client = Groq(api_key=chave)
        elif motor == "openrouter" and OpenAI: client = OpenAI(api_key=chave, base_url="https://openrouter.ai/api/v1")
        elif motor == "mistral" and Mistral: client = Mistral(api_key=chave)
        if not client: raise Exception(f"Cliente {motor} não disponível.")

        for mod in modelos:
            for _ in range(3):
                try:
                    fn = client.chat.complete if motor == "mistral" else client.chat.completions.create
                    resp = fn(model=mod, messages=mensagens, response_format={"type": "json_object"}, temperature=0.2)
                    return schema.model_validate(json.loads(_extrair_json_bruto(resp.choices[0].message.content)))
                except Exception as e:
                    if "429" in str(e) or "503" in str(e): time.sleep(5); continue
                    break
        raise Exception(f"{motor} falhou.")

def executar_com_fallback(chave, itens, schema, provedor, thinking_level="high"):
    cfg = PROVEDORES_IA[provedor]
    try: res = _chamar_motor(cfg["motor"], chave, itens, schema, thinking_level, cfg["modelos"])
    except Exception as e:
        for p_alt, cfg_alt in PROVEDORES_IA.items():
            if p_alt == provedor: continue
            k_alt = obter_chave_provedor(p_alt)
            if not k_alt: continue
            try: res = _chamar_motor(cfg_alt["motor"], k_alt, itens, schema, thinking_level, cfg_alt["modelos"]); break
            except: pass
        else: raise e
    class _Resp: text = res.model_dump_json()
    return _Resp()

def converter_para_iso(data_str):
    if not data_str: return None
    data_str = data_str.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', data_str): return data_str
    try: return datetime.strptime(data_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    except: return None

# =====================================================================
# UI DE FLUXO ETAPA POR ETAPA
# =====================================================================
if "atos_estruturados" not in st.session_state: st.session_state.atos_estruturados = []
if "lote_processado_id" not in st.session_state: st.session_state.lote_processado_id = None

current_lote_id = hashlib.md5(str([f.name for f in arquivos_enviados] if arquivos_enviados else "").encode()).hexdigest()

if arquivos_enviados and current_lote_id != st.session_state.lote_processado_id:
    st.session_state.atos_estruturados = []
    st.session_state.lote_processado_id = current_lote_id

if arquivos_enviados and not st.session_state.atos_estruturados:
    if st.button("1. Ler e Estruturar Documento(s)", type="primary"):
        with st.spinner("Lendo PDFs e Estruturando..."):
            dpi = 1.2 if modo_processamento == "Rápido" else 1.5
            max_p = 10 if modo_processamento == "Rápido" else (20 if modo_processamento == "Equilibrado" else None)
            tl = "low" if modo_processamento == "Rápido" else ("medium" if modo_processamento == "Equilibrado" else "high")
            
            for f in arquivos_enviados:
                txt_partes = extrair_conteudo_cache(f.getvalue(), f.name, dpi, max_p)
                prompt = ["Estruture este documento individualmente em formato JSON (Ementa, Preambulo, Dispositivos). Não faça cruzamento de dados agora, apenas formate O QUE ESTÁ NESTE DOCUMENTO."] + txt_partes
                try:
                    resp = executar_com_fallback(api_key, prompt, Consolidacao, provedor_escolhido, tl)
                    ato_json = json.loads(resp.text)
                    ato_json["_upload_name"] = f.name
                    st.session_state.atos_estruturados.append(ato_json)
                except Exception as e:
                    st.error(f"Erro ao processar {f.name}: {e}")
        st.rerun()

if st.session_state.atos_estruturados:
    st.markdown("---")
    st.markdown("### 📝 Editor e Gestão de Atos Normativos")
    
    for i, ato in enumerate(st.session_state.atos_estruturados):
        nome_base = ato['norma_base']['nome_padronizado'] if 'norma_base' in ato else "Documento Não Identificado"
        
        with st.expander(f"📄 {ato.get('_upload_name', 'Arquivo')} → **{nome_base}**", expanded=True):
            c_top1, c_top2 = st.columns(2)
            with c_top1:
                if st.button("💾 Salvar Ato Inicial no Banco", key=f"btn_salvar_init_{i}"):
                    if supabase:
                        dados_db = {
                            "tipo_documento": ato['norma_base']['tipo_documento'],
                            "numero_documento": ato['norma_base']['numero_documento'],
                            "orgao_emissor": ato['norma_base']['orgao_emissor'],
                            "data_assinatura": converter_para_iso(ato['norma_base']['data_assinatura']),
                            "nome_padronizado": nome_base,
                            "titulo_original": ato.get("titulo_portaria"),
                            "documento_consolidado_json": ato
                        }
                        try:
                            supabase.table("portarias_base").upsert(dados_db, on_conflict="nome_padronizado").execute()
                            st.success(f"{nome_base} salvo no banco como ato de referência!")
                        except Exception as e:
                            st.error(f"Erro ao salvar: {e}")
                    else: st.error("Sem conexão com DB.")
            with c_top2:
                if st.button("🔍 Analisar e Consolidar com Banco", key=f"btn_analisar_{i}", type="primary"):
                    with st.spinner("Buscando histórico e consolidando..."):
                        # Busca o ato base principal (ou o próprio ato se ele já existe)
                        tl = "low" if modo_processamento == "Rápido" else ("medium" if modo_processamento == "Equilibrado" else "high")
                        try:
                            res_db = supabase.table("portarias_base").select("*").eq("nome_padronizado", nome_base).execute()
                            if not res_db.data and ato.get('normas_alteradoras'):
                                # Tenta achar pela referência
                                ref_nome = ato['normas_alteradoras'][0]['nome_padronizado']
                                res_db = supabase.table("portarias_base").select("*").ilike("nome_padronizado", f"%{ref_nome}%").execute()
                                
                            if res_db.data:
                                json_db = res_db.data[0].get("documento_consolidado_json")
                                id_base_db = res_db.data[0].get("id")
                                
                                prompt = [
                                    f"ESTADO ATUAL CONSOLIDADO DO BANCO (Base):\n{json.dumps(json_db)}\n\n",
                                    f"NOVO ATO APLICADO AGORA ({ato.get('_upload_name')}):\n{json.dumps(ato)}\n\n",
                                    "Cruze os dados. MANTENHA AS NOTAS REMISSIVAS ANTIGAS e adicione a NOVA nota nas partes alteradas. Gere a versão Consolidada final."
                                ]
                                resp = executar_com_fallback(api_key, prompt, Consolidacao, provedor_escolhido, tl)
                                st.session_state.atos_estruturados[i] = json.loads(resp.text)
                                st.session_state.atos_estruturados[i]['_id_base_vinculada'] = id_base_db
                                st.session_state.atos_estruturados[i]['_upload_name'] = ato.get('_upload_name')
                                st.success("Cascata aplicada com sucesso! Editor atualizado.")
                                st.rerun()
                            else:
                                st.warning("Ato base não encontrado no banco para consolidar.")
                        except Exception as e:
                            st.error(f"Erro na análise: {e}")

            st.markdown("---")
            # --- EDITOR ---
            ato['titulo_portaria'] = st.text_input("Título do Ato", ato.get('titulo_portaria', ''), key=f"t_{i}")
            ato['ementa'] = editor_para_pdf(editor_rico(ia_para_editor(ato.get('ementa', '')), f"em_{i}"))
            ato['preambulo'] = editor_para_pdf(editor_rico(ia_para_editor(ato.get('preambulo', '')), f"pr_{i}"))
            
            for j, disp in enumerate(ato.get("dispositivos", [])):
                st.markdown(f"**{disp.get('tipo', 'Dispositivo').upper()} {j+1}**")
                ca, cc = st.columns(2)
                with ca: disp['texto_principal_alterada'] = editor_para_pdf(editor_rico(ia_para_editor(disp.get('texto_principal_alterada', '')), f"ta_{i}_{j}"))
                with cc: disp['texto_principal_consolidada'] = editor_para_pdf(editor_rico(ia_para_editor(disp.get('texto_principal_consolidada', '')), f"tc_{i}_{j}"))
                
                disp['nota_remissiva'] = st.text_input("Nota Remissiva (Indexação)", value=disp.get('nota_remissiva', ''), key=f"nr_{i}_{j}")
                
                if disp.get('is_tabela'):
                    ta, tc = st.columns(2)
                    with ta:
                        disp['tabela_alterada'] = st.data_editor(disp.get('tabela_alterada') or [[""]], key=f"tba_{i}_{j}")
                        disp['texto_pos_tabela_alterada'] = st.text_area("Pós-tabela (Alt)", value=disp.get('texto_pos_tabela_alterada', ''), key=f"tpa_{i}_{j}")
                    with tc:
                        disp['tabela_consolidada'] = st.data_editor(disp.get('tabela_consolidada') or [[""]], key=f"tbc_{i}_{j}")
                        disp['texto_pos_tabela_consolidada'] = st.text_area("Pós-tabela (Cons)", value=disp.get('texto_pos_tabela_consolidada', ''), key=f"tpc_{i}_{j}")
                st.markdown("---")
            
            if '_id_base_vinculada' in ato:
                if st.button("💾 Salvar Versões (Alterada/Consolidada) no Banco de Dados", key=f"btn_salvar_versoes_{i}", type="primary"):
                    if supabase:
                        try:
                            # Atualiza consolidado principal
                            supabase.table("portarias_base").update({"documento_consolidado_json": ato}).eq("id", ato['_id_base_vinculada']).execute()
                            
                            # Registra na tabela versoes_documentos para histórico e rastreabilidade
                            desc = f"Análise do arquivo {ato.get('_upload_name')}"
                            alt_aplicadas = [a['nome_padronizado'] for a in ato.get('normas_alteradoras', [])]
                            
                            supabase.table("versoes_documentos").insert({
                                "portaria_base_id": ato['_id_base_vinculada'],
                                "tipo_versao": "alterada",
                                "estado_json": ato,
                                "alteradoras_aplicadas": alt_aplicadas,
                                "descricao": desc
                            }).execute()
                            
                            supabase.table("versoes_documentos").insert({
                                "portaria_base_id": ato['_id_base_vinculada'],
                                "tipo_versao": "consolidada",
                                "estado_json": ato,
                                "alteradoras_aplicadas": alt_aplicadas,
                                "descricao": desc
                            }).execute()
                            
                            st.success("Versões salvas no histórico do banco!")
                        except Exception as e:
                            st.error(f"Erro ao salvar versões: {e}")

            # Exportadores (HTML/PDF/DOCX)
            def gerar_html_dinamico(consolidacao_dict, tipo_versao):
                html = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Versão {tipo_versao}</title><style>@page {{ size: A4; margin: 2.5cm 2cm; }} body {{ font-family: 'Times New Roman', serif; font-size: 11pt; line-height: 1.5; text-align: justify; }} .topo, .titulo, .orgaos, .capitulo, .assinatura {{ text-align: center; font-weight: bold; }} .ementa {{ margin-left: 45%; }} .dispositivo {{ text-indent: 40px; }} table {{ width: 100%; border-collapse: collapse; }} td, th {{ border: 1px solid black; padding: 6px; }} strike, font[color='red'] {{ color: red !important; text-decoration: line-through; }} </style></head><body>"
                html += f"<div class='orgaos'>{consolidacao_dict.get('orgaos_emissores','')}</div><div class='titulo'>{consolidacao_dict.get('titulo_portaria','')}</div><div class='ementa'>{consolidacao_dict.get('ementa','')}</div><div class='preambulo'>{consolidacao_dict.get('preambulo','')}</div>"
                for disp in consolidacao_dict.get('dispositivos', []):
                    t_prin = disp.get(f'texto_principal_{tipo_versao}', '')
                    if t_prin: html += f"<div class='dispositivo'>{t_prin}</div>"
                    if disp.get('is_tabela') and disp.get(f'tabela_{tipo_versao}'):
                        html += "<table>"
                        for linha in disp.get(f'tabela_{tipo_versao}'):
                            html += "<tr>" + "".join([f"<td>{cel}</td>" for cel in linha]) + "</tr>"
                        html += "</table>"
                        t_pos = disp.get(f'texto_pos_tabela_{tipo_versao}', '')
                        if t_pos: html += f"<div class='dispositivo'>{t_pos}</div>"
                html += f"<div class='assinatura'>{consolidacao_dict.get('assinatura_nome','')}<br>{consolidacao_dict.get('assinatura_cargo','')}</div></body></html>"
                return html

            def gerar_pdf_dinamico(consolidacao_dict, tipo_versao):
                if not HAS_WEASYPRINT: raise Exception("WeasyPrint indisponível")
                html_str = gerar_html_dinamico(consolidacao_dict, tipo_versao)
                buffer = io.BytesIO()
                WeasyHTML(string=html_str).write_pdf(buffer)
                buffer.seek(0)
                return buffer.getvalue()

            def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
                doc = docx.Document()
                doc.add_paragraph(consolidacao_dict.get('titulo_portaria', '')).alignment = WD_ALIGN_PARAGRAPH.CENTER
                for disp in consolidacao_dict.get('dispositivos', []):
                    doc.add_paragraph(re.sub(r'<[^>]+>', '', disp.get(f'texto_principal_{tipo_versao}', ''))).alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                b = io.BytesIO(); doc.save(b); b.seek(0)
                return b.getvalue()

            c_html, c_pdf, c_docx = st.columns(3)
            arq_base = nome_base.replace(' ', '_').replace('/', '-')
            
            try:
                c_html.download_button("🌐 Baixar HTML (Alt)", gerar_html_dinamico(ato, "alterada"), f"{arq_base}_Alt.html", "text/html", key=f"ha_{i}")
                c_html.download_button("🌐 Baixar HTML (Cons)", gerar_html_dinamico(ato, "consolidada"), f"{arq_base}_Cons.html", "text/html", key=f"hc_{i}")
            except: pass
            try:
                c_pdf.download_button("📄 Baixar PDF (Alt)", gerar_pdf_dinamico(ato, "alterada"), f"{arq_base}_Alt.pdf", "application/pdf", key=f"pa_{i}")
                c_pdf.download_button("📄 Baixar PDF (Cons)", gerar_pdf_dinamico(ato, "consolidada"), f"{arq_base}_Cons.pdf", "application/pdf", key=f"pc_{i}")
            except: pass
            try:
                c_docx.download_button("📝 Baixar DOCX (Alt)", gerar_docx_dinamico(ato, "alterada"), f"{arq_base}_Alt.docx", "application/vnd.openxmlformats", key=f"da_{i}")
                c_docx.download_button("📝 Baixar DOCX (Cons)", gerar_docx_dinamico(ato, "consolidada"), f"{arq_base}_Cons.docx", "application/vnd.openxmlformats", key=f"dc_{i}")
            except: pass
