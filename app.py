import streamlit as st
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Line
import io
import json
import os
import re
import time
import copy
import hashlib
from html.parser import HTMLParser
from html.entities import name2codepoint
from datetime import datetime
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional

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
        .st-key-login_card { max-width: 420px; margin: 4rem auto; padding: 1.5rem 2rem; background: #ffffff; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.12); }
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
# ÁREA AUTENTICADA
# =====================================================================

if not HAS_WEASYPRINT:
    st.error("🚨 WeasyPrint não encontrado! O gerador de PDF não funcionará. Certifique-se de adicionar 'weasyprint' ao requirements.txt e as dependências ao packages.txt no Streamlit Cloud.")

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

api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    with st.expander("⚙️ Configurações do Sistema (Chave API)", expanded=True):
        api_key = st.text_input("Chave da API", type="password", placeholder="Cole sua chave AI Studio aqui...")

st.markdown("### 📥 Upload de Arquivos Normativos")
arquivos_enviados = st.file_uploader("Arraste todos os documentos (PDF) — um ato original e todos os seus derivativos", type=["pdf"], accept_multiple_files=True, key="uploader_lote")

# =====================================================================
# PARSER AST PARA EXTRAIR FORMATAÇÃO PARA O DOCX
# =====================================================================

class QuillParser(HTMLParser):
    """Analisador Semântico que lê o HTML do Quill e extrai formatações limpas (Negrito, Italico, Taxado, Cor) para o DOCX."""
    def __init__(self):
        super().__init__()
        self.stack = []
        self.runs = []

    def _flags(self):
        b = i = s = r = False
        for tag, attrs in self.stack:
            style = attrs.get('style', '').lower().replace(' ', '')
            cls = attrs.get('class', '').lower()
            cor = attrs.get('color', '').lower()
            
            if tag in ('b', 'strong') or 'font-weight:bold' in style or 'font-weight:700' in style: b = True
            if tag in ('i', 'em') or 'font-style:italic' in style: i = True
            if tag in ('s', 'strike', 'del') or 'text-decoration:line-through' in style or 'ql-strike' in cls: s = True
            if ('color:rgb(230' in style or 'color:red' in style or 'color:#e6' in style or 'color:#f00' in style 
                or (tag == 'font' and ('red' in cor or '#ff' in cor)) or 'color:#ff0000' in style): r = True
        return b, i, s, r

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.runs.append(("\n", False, False, False, False))
            return
        self.stack.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        if tag == 'br':
            self.runs.append(("\n", False, False, False, False))

    def handle_endtag(self, tag):
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx][0] == tag:
                del self.stack[idx]
                break
        if tag in ('p', 'div'):
            self.runs.append(("\n", False, False, False, False))

    def handle_data(self, data):
        if not data: return
        b, i, s, r = self._flags()
        self.runs.append((data, b, i, s, r))

    def handle_entityref(self, name):
        if name in name2codepoint:
            self.handle_data(chr(name2codepoint[name]))
        else:
            self.handle_data(f"&{name};")

    def handle_charref(self, name):
        if name.startswith('x'):
            self.handle_data(chr(int(name[1:], 16)))
        else:
            self.handle_data(chr(int(name)))

def ia_para_editor(texto):
    """Prepara o texto vindo da IA para as tags que o editor visual Quill entende."""
    if not texto: return ""
    texto = texto.replace("<br/>", "</p><p>").replace("<br>", "</p><p>")
    if not texto.startswith("<p>"): texto = f"<p>{texto}</p>"
    texto = re.sub(r'<(strike|del)\b[^>]*>', '<s>', texto, flags=re.IGNORECASE)
    texto = re.sub(r'</(strike|del)>', '</s>', texto, flags=re.IGNORECASE)
    texto = re.sub(r'<font[^>]*color=[\'"]?(red|#f00|#ff0000|rgb\([^)]+\))[\'"]?[^>]*>', '<span style="color: rgb(230, 0, 0);">', texto, flags=re.IGNORECASE)
    texto = re.sub(r'</font>', '</span>', texto, flags=re.IGNORECASE)
    return texto.replace("<p></p>", "")

# =====================================================================
# LÓGICA DE NEGÓCIO E INTELIGÊNCIA ARTIFICIAL
# =====================================================================

SYSTEM_INSTRUCTION_LEGISTECNICA = """
Você é um Especialista Sênior em Técnica Legislativa do Poder Público brasileiro. Regras obrigatórias:

1. FIDELIDADE ABSOLUTA: transcreva com exatidão o conteúdo de cada dispositivo, preservando formatação (<b>, <i>, quebras <br/>).
2. ALTERAÇÃO DE DISPOSITIVO: quando a norma der "nova redação", na versão ALTERADA mantenha o texto revogado riscado e em vermelho 
   (<span style="color: red;"><s>texto antigo</s></span>) seguido do novo texto normal.
3. REVOGAÇÃO EXPRESSA: dispositivo revogado aparece riscado em vermelho na versão ALTERADA e é OMITIDO na versão CONSOLIDADA.
4. NOTA REMISSIVA: a nota indicando o ato alterador vai EXCLUSIVAMENTE no campo 'nota_remissiva', SEM parênteses. 
   O nome do documento DEVE FICAR EM CAIXA ALTA. Exemplo Correto: "Redação dada pela PORTARIA Nº XX, DE 10 DE MAIO DE 2026."
   NUNCA escreva a nota dentro do 'texto_principal_alterada' ou 'texto_principal_consolidada'. O sistema injeta automaticamente.
"""

def executar_com_fallback(client, contents, response_schema):
    """Nova função de fallback blindada contra erros 503 com Espera Exponencial"""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        system_instruction=SYSTEM_INSTRUCTION_LEGISTECNICA,
        thinking_config=types.ThinkingConfig(thinking_level="high")
    )
    
    # Cascata estrita de modelos conforme solicitado
    modelos_oficiais = ['gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash']
    max_tentativas = 4
    
    ultimo_erro = None
    for modelo in modelos_oficiais:
        for tentativa in range(1, max_tentativas + 1):
            try:
                resp = client.models.generate_content(model=modelo, contents=contents, config=config)
                _validar_resposta(resp)
                return resp
            except Exception as e:
                ultimo_erro = e
                erro_str = str(e).upper()
                
                if "429" in erro_str or "RESOURCE_EXHAUSTED" in erro_str or "503" in erro_str or "UNAVAILABLE" in erro_str:
                    if tentativa < max_tentativas:
                        tempo_espera = tentativa * 4  # Backoff: 4s, 8s, 12s...
                        st.toast(f"⚡ Fila no Google ({modelo}). Tentativa {tentativa}/{max_tentativas}. Aguardando {tempo_espera}s...", icon="⏳")
                        time.sleep(tempo_espera)
                        continue
                    else:
                        st.toast(f"⚡ Tempo esgotado no {modelo}. Mudando para o próximo modelo...", icon="🔄")
                        break # Pula para o próximo modelo no loop 'modelos_oficiais'
                elif "404" in erro_str or "NOT_FOUND" in erro_str or "400" in erro_str:
                    st.toast(f"⚠️ Modelo {modelo} indisponível ou não suportado. Pulando...", icon="⏭️")
                    break # Pula para o próximo modelo
                else:
                    raise e
                    
    raise Exception(f"Erro crítico: Todos os modelos da cascata falharam ({', '.join(modelos_oficiais)}). Último erro: {ultimo_erro}")

def _validar_resposta(resp):
    candidatos = getattr(resp, "candidates", None) or []
    if candidatos:
        finish = getattr(candidatos[0], "finish_reason", None)
        finish_str = str(finish) if finish else ""
        if "MAX_TOKENS" in finish_str: raise Exception("A resposta da IA foi cortada por limite de tokens.")
        if "SAFETY" in finish_str or "PROHIBITED" in finish_str: raise Exception("Bloqueado por política de segurança.")
    if not getattr(resp, "text", None): raise Exception("Resposta vazia da IA.")

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

def extrair_conteudo_multimodal(file_bytes, nome_arquivo):
    if nome_arquivo.lower().endswith(".docx"): return [f"ARQUIVO DOCX: {nome_arquivo}"]
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

        if caracteres_uteis < 30 * max(doc.page_count, 1):
            partes = [f"ARQUIVO {nome_arquivo} É UM DOCUMENTO ESCANEADO. Leia o conteúdo visualmente:"]
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                partes.append(types.Part.from_bytes(data=pix.tobytes("png"), mime_type="image/png"))
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
    cabecalho_complemento: str; orgaos_emissores: str; titulo_portaria: str; ementa_preambulo: str
    assinatura_nome: str; assinatura_cargo: str; dispositivos: List[Dispositivo]

class AnaliseGlobal(BaseModel):
    consolidacoes_geradas: List[Consolidacao]; arquivos_nao_alterados: List[str]

def limpar_texto_ia(texto):
    if not texto: return ""
    return re.sub(r' {2,}', ' ', str(texto)).strip()

def injetar_nota_remissiva(texto, nota):
    if nota and nota.strip():
        n_sem_parenteses = nota.strip("()").strip()
        n_fmt = f"({n_sem_parenteses})"
        
        texto_puro = re.sub(r'<[^>]+>', '', texto if texto else '')
        if n_sem_parenteses.lower() in texto_puro.lower(): return texto # Anti-duplicação
        
        if texto:
            texto_limpo = re.sub(r'(<br/?>|\s)+$', '', texto).strip()
            # Injeta a nota usando SPAN (Padrão WeasyPrint e Quill)
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
                for m in res.data: memoria += f"- Erro da IA: {m['texto_ia']}\n- Correção do Usuário: {m['texto_corrigido']}\n\n"
        except: pass
    return memoria

def analisar_lote_arquivos(arquivos, key):
    client = genai.Client(api_key=key)
    memoria_aprendida = resgatar_memoria()

    textos_extraidos = {}
    for arq in arquivos: textos_extraidos[arq.name] = extrair_conteudo_multimodal(arq.getvalue(), arq.name)

    contents_triagem = [f"Analise os documentos. Agrupe cada ato original com seus derivativos no mesmo grupo_id. ARQUIVOS: {', '.join(textos_extraidos.keys())}"]
    for partes in textos_extraidos.values(): contents_triagem.extend(partes)
    resp_triagem = executar_com_fallback(client, contents_triagem, TriagemDocumentos)
    triagem_dados = json.loads(resp_triagem.text).get("arquivos", [])

    grupos = {}
    for a in triagem_dados: grupos.setdefault(a.get('grupo_id', 0), []).append(a)

    consolidacoes_geradas, arquivos_nao_alterados = [], []
    for grupo_id, itens in grupos.items():
        arquivo_base = next((a for a in itens if a['tipo'] == 'Base'), None)
        arquivos_alteradores = sorted([a for a in itens if a['tipo'] == 'Alteradora'], key=lambda x: x['data_oficial_iso'])

        if not arquivo_base and not arquivos_alteradores: continue
        if not arquivo_base:
            arquivos_nao_alterados.extend([a['nome_arquivo_upload'] for a in arquivos_alteradores])
            continue

        st.toast(f"⚙️ Processando: {arquivo_base.get('nome_padronizado_identificado', grupo_id)}...", icon="⏳")
        try:
            consolidacoes_geradas.append(_processar_cascata_grupo(client, arquivo_base, arquivos_alteradores, textos_extraidos, memoria_aprendida))
        except Exception as e:
            st.error(f"❌ Falha em '{arquivo_base.get('nome_padronizado_identificado')}': {e}")
            arquivos_nao_alterados.append(arquivo_base['nome_arquivo_upload'])
            arquivos_nao_alterados.extend([a['nome_arquivo_upload'] for a in arquivos_alteradores])

    return {"consolidacoes_geradas": consolidacoes_geradas, "arquivos_nao_alterados": arquivos_nao_alterados}

def _processar_cascata_grupo(client, arquivo_base, arquivos_alteradores, textos_extraidos, memoria_aprendida):
    estado_json_atual = None
    if supabase:
        try:
            nome_padrao = arquivo_base.get('nome_padronizado_identificado', '')
            res_bd = supabase.table("portarias_base").select("documento_consolidado_json").eq("nome_padronizado", nome_padrao).execute()
            if res_bd.data and res_bd.data[0].get("documento_consolidado_json"):
                estado_json_atual = json.dumps(res_bd.data[0]['documento_consolidado_json'])
        except: pass

    if not arquivos_alteradores:
        conteudo_loop = ["Texto Base:"] + textos_extraidos[arquivo_base['nome_arquivo_upload']]
        resp_loop = executar_com_fallback(client, conteudo_loop + ["Estruture o documento. " + memoria_aprendida], Consolidacao)
        return json.loads(resp_loop.text)

    resp_loop = None
    for i, alt in enumerate(arquivos_alteradores):
        conteudo_loop = []
        if estado_json_atual:
            conteudo_loop.append(f"ESTADO ATUAL (JSON):\n{estado_json_atual}")
        elif i == 0:
            conteudo_loop.append("DOCUMENTO BASE ORIGINAL:")
            conteudo_loop.extend(textos_extraidos[arquivo_base['nome_arquivo_upload']])

        conteudo_loop.append(f"PORTARIA ALTERADORA Nº {i+1} A SER APLICADA ({alt['nome_arquivo_upload']}):")
        conteudo_loop.extend(textos_extraidos[alt['nome_arquivo_upload']])
        prompt_loop = f"""
        Aplique a portaria alteradora. Mantenha negrito <b>, itálico <i> e use <span style="color: red;"><s>texto revogado</s></span> para revogações.
        Atenção para não duplicar a nota remissiva.
        {memoria_aprendida}
        """
        conteudo_loop.append(prompt_loop)
        resp_loop = executar_com_fallback(client, conteudo_loop, Consolidacao)
        estado_json_atual = resp_loop.text
    return json.loads(resp_loop.text)

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
            body {{ font-family: 'Times New Roman', Times, serif; font-size: 11pt; line-height: 1.5; margin: 40px auto; max-width: 800px; padding: 0 20px; text-align: justify; }}
            .topo {{ text-align: center; color: #444; font-size: 10pt; font-weight: bold; margin-bottom: 20px; text-transform: uppercase; }}
            .orgaos {{ text-align: center; font-weight: bold; margin-bottom: 25px; }}
            .titulo {{ text-align: center; font-weight: bold; margin-bottom: 20px; }}
            .dispositivo {{ text-indent: 40px; margin-bottom: 12px; }}
            .ementa {{ margin-left: 50%; margin-bottom: 20px; font-style: italic; }}
            .capitulo {{ text-align: center; font-weight: bold; margin-top: 20px; margin-bottom: 12px; text-transform: uppercase; }}
            .assinatura {{ text-align: center; font-weight: bold; margin-top: 50px; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 15px; }}
            td, th {{ border: 1px solid black; padding: 6px; text-align: left; vertical-align: middle; }}
            
            /* CSS CRUCIAL PARA PRESERVAR FORMATAÇÃO WEASYPRINT/HTML */
            strike, s, del {{ text-decoration: line-through; }}
            b, strong {{ font-weight: bold; }}
            i, em {{ font-style: italic; }}
        </style>
    </head>
    <body>
        <div class="topo">{titulo_doc}</div>
        <div class="orgaos">{limpar_texto_ia(consolidacao_dict.get("orgaos_emissores") or "").replace('<br/>', '<br>')}</div>
        <div class="titulo">{limpar_texto_ia(consolidacao_dict.get("titulo_portaria") or "").replace('<br/>', '<br>')}</div>
        
        <div class="ementa">{limpar_texto_ia(consolidacao_dict.get("ementa_preambulo") or "").replace('<br/>', '<br>')}</div>
    """
    
    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva(item.get(f"texto_principal_{tipo_versao}"), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        
        if "capitulo" in t or "anexo" in t:
            html += f"<div class='capitulo'>{t_prin}</div>"
            continue
            
        if t_prin:
            html += f"<div class='dispositivo'>{t_prin}</div>"
            
        if item.get("is_tabela"):
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas:
                html += "<table>"
                for linha in linhas:
                    html += "<tr>"
                    for celula in linha: html += f"<td>{celula}</td>"
                    html += "</tr>"
                html += "</table>"
                
            t_pos = injetar_nota_remissiva(item.get(f"texto_pos_tabela_{tipo_versao}"), item.get("nota_remissiva"))
            if t_pos: html += f"<div class='dispositivo'>{t_pos}</div>"
                
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
        parser = QuillParser()
        try: parser.feed(texto_html)
        except: return
        
        linhas = []
        linha_atual = []
        for text, b, i, s, r in parser.runs:
            if text == "\n":
                if linha_atual: linhas.append(linha_atual)
                linha_atual = []
            else:
                linha_atual.append((text, b, i, s, r))
        if linha_atual: linhas.append(linha_atual)

        for line in linhas:
            for text, b, i, s, r in line:
                run = p_obj.add_run(text.replace('&nbsp;', '\xa0'))
                run.font.name, run.font.size = 'Times New Roman', Pt(10) if bold_all else Pt(11)
                if bold_all or b: run.bold = True
                if i: run.italic = True
                if s: run.font.strike = True
                if r: run.font.color.rgb = RGBColor(230, 0, 0)
            p_obj.add_run("\n")

    p_ementa = doc.add_paragraph(); p_ementa.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY; p_ementa.paragraph_format.left_indent = Inches(3)
    _render_docx_p(p_ementa, consolidacao_dict.get("ementa_preambulo", ""))

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

            _registrar("ementa", cons_original.get('ementa_preambulo'), cons.get('ementa_preambulo'))
            for j, disp_editado in enumerate(cons.get("dispositivos", [])):
                if j >= len(cons_original.get("dispositivos", [])): break
                disp_original = cons_original["dispositivos"][j]
                for campo in ["texto_principal_alterada", "texto_principal_consolidada", "tabela_alterada", "tabela_consolidada", "texto_pos_tabela_alterada", "texto_pos_tabela_consolidada"]:
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
    if not api_key: st.error("⚠️ Insira sua chave da API nas configurações.")
    elif not arquivos_enviados: st.warning("⚠️ Envie os arquivos normativos primeiro.")
    else:
        with st.spinner("⚡ Executando OCR Estrutural e Consulta ao Histórico de Aprendizado..."):
            try:
                st.session_state.dados_processados = analisar_lote_arquivos(arquivos_enviados, api_key.strip())
                st.session_state.dados_originais_ia = copy.deepcopy(st.session_state.dados_processados)
                st.success("✨ Processamento concluído!")
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
            st.markdown("**Ementa e Preâmbulo**")
            val_ementa = ia_para_editor(cons.get('ementa_preambulo', ''))
            ementa_editada = st_quill(value=val_ementa, key=f"q_ementa_{i}")
            if ementa_editada: cons['ementa_preambulo'] = ementa_editada
            
            st.markdown("#### Dispositivos (Artigos, Parágrafos, Incisos)")
            for j, disp in enumerate(cons.get("dispositivos", [])):
                st.markdown(f"**{disp.get('tipo', 'Dispositivo').upper()} {j+1}**")
                c_alt, c_cons = st.columns(2)
                
                with c_alt:
                    st.markdown("*Versão Alterada*")
                    val_alt = ia_para_editor(disp.get('texto_principal_alterada', ''))
                    alt_editada = st_quill(value=val_alt, key=f"q_alt_{i}_{j}")
                    if alt_editada: disp['texto_principal_alterada'] = alt_editada
                    
                with c_cons:
                    st.markdown("*Versão Consolidada*")
                    val_cons = ia_para_editor(disp.get('texto_principal_consolidada', ''))
                    cons_editada = st_quill(value=val_cons, key=f"q_cons_{i}_{j}")
                    if cons_editada: disp['texto_principal_consolidada'] = cons_editada

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
            
            c_html.download_button("🌐 Baixar HTML (Alterada)", data=html_alt.encode('utf-8'), file_name=f"{nome_arquivo_base}_Alt.html", mime="text/html", key=f"ha_{i}")
            c_html.download_button("🌐 Baixar HTML (Consolidada)", data=html_cons.encode('utf-8'), file_name=f"{nome_arquivo_base}_Cons.html", mime="text/html", key=f"hc_{i}")
            
            c_pdf.download_button("📄 Baixar PDF (Alterada)", data=pdf_alt, file_name=f"{nome_arquivo_base}_Alt.pdf", mime="application/pdf", key=f"pa_{i}")
            c_pdf.download_button("📄 Baixar PDF (Consolidada)", data=pdf_cons, file_name=f"{nome_arquivo_base}_Cons.pdf", mime="application/pdf", key=f"pc_{i}")
            
            c_docx.download_button("📝 Baixar DOCX (Alterada)", data=docx_alt, file_name=f"{nome_arquivo_base}_Alt.docx", mime="application/vnd.openxmlformats", key=f"da_{i}")
            c_docx.download_button("📝 Baixar DOCX (Consolidada)", data=docx_cons, file_name=f"{nome_arquivo_base}_Cons.docx", mime="application/vnd.openxmlformats", key=f"dc_{i}")

    if st.button("🔄 Nova Análise", type="secondary"): st.session_state.dados_processados = None; st.session_state.dados_originais_ia = None; st.rerun()
