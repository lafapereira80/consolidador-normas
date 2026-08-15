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
from datetime import datetime
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional

# Importação para Supabase, Word, Leitura de PDF Determinística e Editor Web
from supabase import create_client, Client
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import fitz  # PyMuPDF
from streamlit_quill import st_quill
from auth_utils import gerar_hash_senha, verificar_senha

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
# Adicionado initial_sidebar_state="collapsed" para forçar ocultação do menu lateral
st.set_page_config(page_title="Autopilot Normativo", page_icon="⚖️", layout="wide", initial_sidebar_state="collapsed")

# ----------------- BLOQUEIO TOTAL DO MENU LATERAL E CSS GLOBAL -----------------
st.markdown("""
<style>
    /* Oculta completamente a Sidebar padrão do Streamlit (Menu Lateral) e o botão de expandir */
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
                # Login legado validado: regrava com hash salgado (PBKDF2) sem exigir ação do usuário.
                try:
                    supabase.table("usuarios").update({"password_hash": gerar_hash_senha(password)}).eq("id", res.data[0]['id']).execute()
                except Exception:
                    pass
            return ok
    except Exception as e:
        st.error(f"Erro ao verificar credenciais: {e}")
    return False

if not st.session_state.autenticado:
    # --- TELA DE LOGIN ---
    # CORREÇÃO DE LAYOUT: antes o card era feito com <div> aberta num st.markdown
    # e fechada em outro, com o st.form no meio — Streamlit renderiza cada
    # chamada como um elemento HTML independente (não aninhado), então a <div>
    # ficava vazia (a "caixa vazia" reportada) e o formulário aparecia solto,
    # fora do card. Agora o card é um st.container(border=True) de verdade,
    # com tudo (título, subtítulo e formulário) dentro dele.
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
    st.stop() # Bloqueia a renderização do resto do código se não estiver logado!

# =====================================================================
# A PARTIR DAQUI, O CÓDIGO SÓ RODA SE O USUÁRIO ESTIVER AUTENTICADO
# =====================================================================

st.markdown("""
<div class="main-header">
    <h1>⚖️ Autopilot Normativo</h1>
    <p>Motor Híbrido OCR com Editor Visual e Aprendizado Contínuo (Feedback Loop)</p>
</div>
""", unsafe_allow_html=True)

# --- MENU DE NAVEGAÇÃO SUPERIOR FIXO ---
col_info, col_hist, col_usr, col_logout = st.columns([3, 1.5, 1.5, 1])

with col_info:
    st.info("💡 **Sistema Autenticado:** Proteção de dados ativa.")

# Busca dinâmica dos arquivos para garantir que o link funcione
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
arquivos_enviados = st.file_uploader("Arraste todos os documentos (PDF) — um ato original e todos os seus derivativos, ou vários grupos normativos de uma vez", type=["pdf"], accept_multiple_files=True, key="uploader_lote")

# ----------------- TRADUTORES PARA O EDITOR VISUAL -----------------
def ia_para_editor(texto):
    if not texto: return ""
    texto = texto.replace("<br/>", "</p><p>").replace("<br>", "</p><p>")
    texto = f"<p>{texto}</p>"
    texto = texto.replace("<p></p>", "")
    texto = texto.replace("<font color='red'><strike>", '<span style="color: rgb(230, 0, 0);"><s>')
    texto = texto.replace("</strike></font>", "</s></span>")
    texto = texto.replace("<font color='red'>", '<span style="color: rgb(230, 0, 0);">')
    texto = texto.replace("</font>", "</span>")
    texto = texto.replace("<strike>", "<s>").replace("</strike>", "</s>")
    texto = texto.replace("<b>", "<strong>").replace("</b>", "</strong>")
    texto = texto.replace("<i>", "<em>").replace("</i>", "</em>")
    return texto

def editor_para_pdf(texto):
    """Converte o HTML devolvido pelo Quill de volta para o markup canônico
    (<b>, <i>, <strike>, <font color='red'>, <br/>) usado no PDF/DOCX.
    Usa um parser HTML de verdade (em vez de replace/regex encadeados) porque
    o Quill pode serializar negrito/itálico/riscado/cor em ordens e formas
    diferentes (tag dedicada, classe CSS, ou style inline combinado na mesma
    tag) — um replace literal quebra nesses casos e é a causa da perda de
    negrito/riscado e de tags malformadas na exportação."""
    if not texto: return ""
    parser = _QuillParser()
    try:
        parser.feed(texto)
    except Exception:
        return limpar_texto_ia(texto)

    segs = []
    for text, b, i, s, r in parser.runs:
        if text == "\n":
            segs.append("<br/>")
            continue
        if not text: continue
        seg = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\xa0', '&nbsp;')
        if b: seg = f"<b>{seg}</b>"
        if i: seg = f"<i>{seg}</i>"
        if s: seg = f"<strike>{seg}</strike>"
        if r: seg = f"<font color='red'>{seg}</font>"
        segs.append(seg)

    resultado = "".join(segs)
    resultado = re.sub(r'(<br/>\s*){3,}', '<br/><br/>', resultado)
    resultado = re.sub(r'^(<br/>)+|(<br/>)+$', '', resultado).strip()
    return resultado

class _QuillParser(HTMLParser):
    """Lê o HTML do Quill e produz uma lista plana de (texto, negrito, italico,
    riscado, vermelho) — independente de como as tags/estilos foram aninhados
    ou combinados pelo editor."""
    def __init__(self):
        super().__init__()
        self.stack = []
        self.runs = []

    @staticmethod
    def _flags(tag, attrs):
        style = (attrs.get('style') or '').lower().replace(' ', '')
        cls = (attrs.get('class') or '').lower()
        cor = (attrs.get('color') or '').lower()
        bold = tag in ('b', 'strong') or 'font-weight:bold' in style or 'font-weight:700' in style or 'font-weight:600' in style
        italic = tag in ('i', 'em') or 'font-style:italic' in style
        strike = tag in ('s', 'strike', 'del') or 'text-decoration:line-through' in style or 'ql-strike' in cls
        red = ('color:rgb(230' in style or 'color:#e6' in style or 'color:red' in style
               or (tag == 'font' and 'red' in cor))
        return {'bold': bold, 'italic': italic, 'strike': strike, 'red': red}

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.runs.append(("\n", False, False, False, False)); return
        self.stack.append((tag, self._flags(tag, dict(attrs))))

    def handle_startendtag(self, tag, attrs):
        if tag == 'br':
            self.runs.append(("\n", False, False, False, False))

    def handle_endtag(self, tag):
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx][0] == tag:
                del self.stack[idx]; break
        if tag == 'p':
            self.runs.append(("\n", False, False, False, False))

    def handle_data(self, data):
        if not data: return
        b = i = s = r = False
        for _, f in self.stack:
            b |= f['bold']; i |= f['italic']; s |= f['strike']; r |= f['red']
        self.runs.append((data, b, i, s, r))

SYSTEM_INSTRUCTION_LEGISTECNICA = """
Você é um Especialista Sênior em Técnica Legislativa do Poder Público brasileiro,
seguindo rigorosamente a Lei Complementar nº 95/1998 e o Manual de Redação da
Presidência da República para consolidação normativa. Regras obrigatórias:

1. FIDELIDADE ABSOLUTA: nunca resuma, corrija estilo ou "melhore" o texto original.
   Transcreva com exatidão o conteúdo de cada dispositivo (artigo, parágrafo, inciso,
   alínea, item), preservando numeração, ordem e formatação (<b>, <i>, quebras <br/>).
2. ALTERAÇÃO DE DISPOSITIVO: quando uma norma alteradora dá "nova redação" a um
   dispositivo, na versão ALTERADA mantenha o texto revogado riscado
   (<font color='red'><strike>texto antigo</strike></font>) seguido do novo texto,
   e na versão CONSOLIDADA mostre apenas o texto vigente (o novo).
3. REVOGAÇÃO EXPRESSA: dispositivo revogado aparece riscado na versão ALTERADA e
   é OMITIDO (ou marcado "(Revogado)") na versão CONSOLIDADA — nunca invente texto
   substituto que não conste da norma alteradora.
4. INCLUSÃO DE DISPOSITIVO NOVO: inserido na posição indicada pela alteradora,
   mantendo a numeração de alíneas/incisos existente (não renumere dispositivos
   não afetados).
5. NOTA REMISSIVA: toda alteração/revogação recebe nota indicando o ato que a
   promoveu (ex.: "Redação dada pela Portaria nº X/Y, de DATA." ou "Revogado
   pela Portaria nº X/Y, de DATA."). Essa nota vai EXCLUSIVAMENTE no campo
   'nota_remissiva' do dispositivo, SEM parênteses. NUNCA escreva essa mesma
   nota também dentro de texto_principal_alterada/texto_principal_consolidada
   — o aplicativo insere a nota automaticamente a partir do campo dedicado, e
   repeti-la no texto principal causa duplicação visível no documento final.
6. NUNCA altere dispositivos não mencionados pela norma alteradora em processamento
   nesta etapa — preserve-os byte a byte em relação ao estado anterior.
7. Se um mesmo dispositivo já foi corrigido manualmente pelo usuário no passado
   (ver regras aprendidas abaixo, se houver), replique o mesmo padrão de correção.
8. ANEXOS E TABELAS: classifique cabeçalhos de anexo com tipo="anexo" (ex.: "ANEXO I").
   Reproduza tabelas linha a linha em 'tabela_alterada'/'tabela_consolidada' e qualquer
   texto que venha depois da tabela em 'texto_pos_tabela_alterada'/'_consolidada' — nunca
   misture o texto pós-tabela dentro das células. Preserve a ordem e o número exato de
   colunas/linhas do documento original.
"""

MODELOS_FALLBACK = ['gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash']

def executar_com_fallback(client, contents, response_schema):
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        system_instruction=SYSTEM_INSTRUCTION_LEGISTECNICA,
        thinking_config=types.ThinkingConfig(thinking_level="high"),
    )
    max_tentativas_por_modelo = 5
    erros = {}
    for idx, modelo in enumerate(MODELOS_FALLBACK):
        for tentativa in range(1, max_tentativas_por_modelo + 1):
            try:
                resp = client.models.generate_content(model=modelo, contents=contents, config=config)
                _validar_resposta(resp)
                return resp
            except Exception as e:
                erros[modelo] = e
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    if tentativa < max_tentativas_por_modelo:
                        st.toast(f"⚡ Tentativa {tentativa}/{max_tentativas_por_modelo} no {modelo} esgotada. Tentando novamente...", icon="⏳")
                        time.sleep(3)
                        continue
                    elif idx < len(MODELOS_FALLBACK) - 1:
                        st.toast(f"⚡ Cota esgotada no {modelo}. Alternando para {MODELOS_FALLBACK[idx + 1]}...", icon="🔄")
                        break
                    else:
                        raise Exception(f"Erro crítico: todos os modelos falharam. Detalhes: {erros}")
                elif "404" in str(e) or "NOT_FOUND" in str(e):
                    # Modelo indisponível/descontinuado: pula direto para o próximo, sem gastar as 5 tentativas.
                    st.toast(f"⚠️ {modelo} indisponível. Alternando para o próximo da cadeia...", icon="🔄")
                    break
                else:
                    raise e
    raise Exception(f"Erro crítico: todos os modelos da cadeia de fallback falharam. Detalhes: {erros}")

def _validar_resposta(resp):
    """Detecta truncamento (MAX_TOKENS) ou bloqueio de segurança antes de tentar
    fazer json.loads em cima de um texto incompleto/ausente."""
    candidatos = getattr(resp, "candidates", None) or []
    if candidatos:
        finish = getattr(candidatos[0], "finish_reason", None)
        finish_str = str(finish) if finish else ""
        if "MAX_TOKENS" in finish_str:
            raise Exception("A resposta da IA foi cortada por exceder o limite de tokens (documento muito extenso para uma única etapa).")
        if "SAFETY" in finish_str or "PROHIBITED" in finish_str:
            raise Exception("A resposta da IA foi bloqueada por política de segurança do modelo.")
    if not getattr(resp, "text", None):
        raise Exception("A IA retornou uma resposta vazia.")

def converter_para_iso(data_str):
    if not data_str: return None
    data_str = data_str.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', data_str): return data_str
    match_br = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', data_str)
    if match_br:
        d, m, a = match_br.groups()
        return f"{a}-{m}-{d}"
    try:
        dt = datetime.strptime(data_str, "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except:
        return None

def extrair_conteudo_multimodal(file_bytes, nome_arquivo):
    """Retorna uma lista de 'parts' para enviar ao Gemini: texto estruturado
    (com <b>/<i> preservados via camada de texto do PDF) quando disponível,
    ou as páginas rasterizadas em imagem quando o PDF não tem camada de texto
    (documento escaneado) — nesse caso o próprio gemini-3.6-flash faz a leitura
    (OCR) das imagens, o que é mais confiável do que tentar extrair texto vazio."""
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
                        if linha_span.strip():
                            bloco_linhas += linha_span + " "
                    if bloco_linhas.strip():
                        html_text += bloco_linhas.strip() + "<br/>\n"
            html_text += "<br/>\n"

        # Heurística: menos de ~30 caracteres úteis por página indica PDF
        # escaneado (sem camada de texto) — extração por dict() falharia.
        if caracteres_uteis < 30 * max(doc.page_count, 1):
            partes = [f"ARQUIVO {nome_arquivo} É UM DOCUMENTO ESCANEADO (sem texto extraível). "
                      f"Leia o conteúdo diretamente das {doc.page_count} imagens de página abaixo, "
                      f"preservando negrito/itálico perceptíveis visualmente e a ordem exata do texto:"]
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                partes.append(types.Part.from_bytes(data=pix.tobytes("png"), mime_type="image/png"))
            return partes

        return [html_text]
    except Exception as e:
        return [f"Erro ao extrair PDF {nome_arquivo}: {str(e)}"]

# ----------------- ESTRUTURAS PYDANTIC -----------------
class ArquivoClassificado(BaseModel):
    nome_arquivo_upload: str
    tipo: str = Field(description="'Base' ou 'Alteradora'")
    grupo_id: int = Field(description="Identificador da família normativa (comece em 1). Um ATO ORIGINAL e TODOS os seus atos derivativos (que o alteram ou revogam) devem compartilhar o MESMO grupo_id. Se houver mais de um ato original independente no lote, use grupo_id diferente para cada família.")
    nome_padronizado_identificado: str = Field(description="Nome padronizado da norma (tipo, número, órgão e data), ex.: 'PORTARIA Nº 158/PGJM, DE 29 DE JULHO DE 2026'. Usado para localizar memória já salva no banco.")
    data_oficial_iso: str = Field(description="Data formatada estritamente em YYYY-MM-DD.")

class TriagemDocumentos(BaseModel):
    arquivos: List[ArquivoClassificado]

class MetadadosNorma(BaseModel):
    tipo_documento: str
    numero_documento: str
    orgao_emissor: str
    data_assinatura: str
    nome_padronizado: str

class Dispositivo(BaseModel):
    tipo: str
    texto_principal_alterada: str
    texto_principal_consolidada: str
    is_tabela: bool
    tabela_alterada: Optional[List[List[str]]] = None
    tabela_consolidada: Optional[List[List[str]]] = None
    texto_pos_tabela_alterada: Optional[str] = None
    texto_pos_tabela_consolidada: Optional[str] = None
    nota_remissiva: Optional[str] = Field(default="", description="APENAS o texto da nota, SEM parênteses, ex.: 'Redação dada pela Portaria nº X/Y, de DATA.' NUNCA repita/inclua essa nota dentro de texto_principal_alterada ou texto_principal_consolidada — o aplicativo insere a nota automaticamente a partir deste campo.")

class Consolidacao(BaseModel):
    arquivos_originais_identificados: List[str]
    arquivos_alteradores_identificados: List[str]
    norma_base: MetadadosNorma
    normas_alteradoras: List[MetadadosNorma]
    cabecalho_complemento: str
    orgaos_emissores: str
    titulo_portaria: str
    ementa_preambulo: str
    assinatura_nome: str
    assinatura_cargo: str
    dispositivos: List[Dispositivo]

class AnaliseGlobal(BaseModel):
    consolidacoes_geradas: List[Consolidacao]
    arquivos_nao_alterados: List[str]

def limpar_texto_ia(texto):
    if not texto: return ""
    texto = texto.replace('\\n', ' ').replace('\n', ' ').replace('<br>', '<br/>').replace('<br >', '<br/>')
    return re.sub(r' {2,}', ' ', texto).strip()

def injetar_nota_remissiva(texto, nota):
    if nota and nota.strip():
        n = nota.strip()
        n_sem_parenteses = n.strip("()").strip()
        n_fmt = f"({n_sem_parenteses})"
        # Proteção contra duplicação: se a IA (ou uma edição manual) já deixou
        # essa mesma nota escrita dentro do texto principal, não injeta de novo.
        if texto and n_sem_parenteses and n_sem_parenteses.lower() in re.sub(r'<[^>]+>', '', texto).lower():
            return texto
        if texto:
            texto_limpo = re.sub(r'(<br/?>|\s)+$', '', texto).strip()
            return f"{texto_limpo} &nbsp;<font color='red'>{n_fmt}</font>"
        return f"<font color='red'>{n_fmt}</font>"
    return texto

# ----------------- RESGATE DE MEMÓRIA (FEEDBACK LOOP) -----------------
def resgatar_memoria():
    memoria = ""
    if supabase:
        try:
            res = supabase.table("memoria_de_correcoes").select("*").order("id", desc=True).limit(5).execute()
            if res.data:
                memoria = "\n\n⚠️ REGRAS APRENDIDAS (HISTÓRICO DE CORREÇÕES DO USUÁRIO):\nPreste muita atenção aos erros que você cometeu no passado e que o usuário corrigiu. Não repita os 'Erros da IA' abaixo, utilize o padrão da 'Correção do Usuário':\n"
                for m in res.data:
                    memoria += f"- Erro da IA: {m['texto_ia']}\n- Correção do Usuário: {m['texto_corrigido']}\n\n"
        except: pass
    return memoria

def analisar_lote_arquivos(arquivos, key):
    client = genai.Client(api_key=key)
    memoria_aprendida = resgatar_memoria()

    textos_extraidos = {}
    for arq in arquivos: textos_extraidos[arq.name] = extrair_conteudo_multimodal(arq.getvalue(), arq.name)

    contents_triagem = [f"Analise os documentos abaixo. Um ATO ORIGINAL pode ter vários atos derivativos — agrupe cada ato original com todos os seus derivativos no mesmo grupo_id. Pode haver mais de uma família normativa independente no lote: use grupo_id diferente para cada uma. ARQUIVOS: {', '.join(textos_extraidos.keys())}"]
    for partes in textos_extraidos.values(): contents_triagem.extend(partes)
    resp_triagem = executar_com_fallback(client, contents_triagem, TriagemDocumentos)
    triagem_dados = json.loads(resp_triagem.text).get("arquivos", [])

    if not triagem_dados: raise ValueError("Não foi possível identificar a relação normativa.")

    grupos = {}
    for a in triagem_dados: grupos.setdefault(a.get('grupo_id', 0), []).append(a)

    consolidacoes_geradas, arquivos_nao_alterados = [], []
    for grupo_id, itens in grupos.items():
        arquivo_base = next((a for a in itens if a['tipo'] == 'Base'), None)
        arquivos_alteradores = sorted([a for a in itens if a['tipo'] == 'Alteradora'], key=lambda x: x['data_oficial_iso'])

        if not arquivo_base and not arquivos_alteradores:
            continue
        if not arquivo_base:
            # Alteradoras sem ato original identificado no lote: não há como aplicar
            # a alteração com segurança. Reportado ao usuário, não processado.
            arquivos_nao_alterados.extend([a['nome_arquivo_upload'] for a in arquivos_alteradores])
            continue

        st.toast(f"⚙️ Processando família normativa: {arquivo_base.get('nome_padronizado_identificado', grupo_id)}...", icon="⏳")
        try:
            consolidacoes_geradas.append(
                _processar_cascata_grupo(client, arquivo_base, arquivos_alteradores, textos_extraidos, memoria_aprendida)
            )
        except Exception as e:
            st.error(f"❌ Falha ao processar a família de '{arquivo_base.get('nome_padronizado_identificado')}': {e}")
            arquivos_nao_alterados.append(arquivo_base['nome_arquivo_upload'])
            arquivos_nao_alterados.extend([a['nome_arquivo_upload'] for a in arquivos_alteradores])

    return {"consolidacoes_geradas": consolidacoes_geradas, "arquivos_nao_alterados": arquivos_nao_alterados}

def _processar_cascata_grupo(client, arquivo_base, arquivos_alteradores, textos_extraidos, memoria_aprendida):
    """Roda a cascata cronológica (do ato mais antigo para o mais novo) para UMA
    única família normativa (um ato original + seus derivativos), recuperando
    memória prévia do Supabase quando existir. Retorna um dict compatível com Consolidacao."""
    estado_json_atual = None
    if supabase:
        try:
            nome_padrao = arquivo_base.get('nome_padronizado_identificado', '')
            res_bd = supabase.table("portarias_base").select("documento_consolidado_json").eq("nome_padronizado", nome_padrao).execute()
            if res_bd.data and res_bd.data[0].get("documento_consolidado_json"):
                estado_json_atual = json.dumps(res_bd.data[0]['documento_consolidado_json'])
                st.toast("🧠 Memória da base recuperada do banco de dados.", icon="✅")
        except Exception:
            pass

    if not arquivos_alteradores:
        conteudo_loop = ["Texto Base:"] + textos_extraidos[arquivo_base['nome_arquivo_upload']]
        resp_loop = executar_com_fallback(client, conteudo_loop + [
            "Estruture este documento normativo (ainda sem alterações a aplicar) de acordo com o esquema solicitado, "
            "preservando RIGOROSAMENTE a estrutura original: parágrafos, negrito <b>, itálico <i>, tabelas e "
            "estrutura de anexos, exatamente como no arquivo-fonte." + memoria_aprendida
        ], Consolidacao)
        return json.loads(resp_loop.text)

    resp_loop = None
    for i, alt in enumerate(arquivos_alteradores):
        conteudo_loop = []
        if estado_json_atual:
            conteudo_loop.append(f"ESTADO ATUAL DO DOCUMENTO (JSON):\n{estado_json_atual}")
        elif i == 0:
            conteudo_loop.append("DOCUMENTO BASE ORIGINAL:")
            conteudo_loop.extend(textos_extraidos[arquivo_base['nome_arquivo_upload']])

        conteudo_loop.append(f"PORTARIA ALTERADORA Nº {i+1} DE {len(arquivos_alteradores)} A SER APLICADA, EM ORDEM CRONOLÓGICA ({alt['nome_arquivo_upload']}):")
        conteudo_loop.extend(textos_extraidos[alt['nome_arquivo_upload']])
        prompt_loop = f"""
        Execute o passo {i+1} de {len(arquivos_alteradores)} aplicando as modificações desta portaria alteradora
        sobre o texto atual, na ordem cronológica correta (do ato mais antigo para o mais novo).
        REGRAS CRÍTICAS DE FORMATAÇÃO E FIDELIDADE ESTRUTURAL:
        1. PREÂMBULO E EMENTA: mantenha exatamente o fluxo original, com <br/> preservando a estrutura de parágrafos.
        2. Preserve negrito <b>, itálico <i>, tabelas e a estrutura de anexos IDÊNTICOS ao ato original, exceto
           nos trechos efetivamente alterados/revogados por esta portaria.
        3. Use <font color='red'><strike>texto revogado</strike></font> para trechos revogados/substituídos.
        4. NUNCA modifique dispositivos, tabelas ou anexos que esta portaria alteradora não menciona.
        {memoria_aprendida}
        """
        conteudo_loop.append(prompt_loop)
        resp_loop = executar_com_fallback(client, conteudo_loop, Consolidacao)
        estado_json_atual = resp_loop.text
    return json.loads(resp_loop.text)

# --- FUNÇÕES DE RENDERIZAÇÃO PDF E DOCX ---
def extrair_paragrafos_seguros(texto_html):
    texto_html = limpar_texto_ia(texto_html)
    texto_html = re.sub(r'</?(span|div|p|ul|li|ol)[^>]*>', '', texto_html, flags=re.IGNORECASE).replace("</font></strike>", "</strike></font>").replace("</b></i>", "</i></b>")
    tokens = re.split(r'(<[^>]+>)', texto_html)
    paragrafos, pilha, texto_atual = [], [], ""
    def fechar_todas(p_tags):
        r = ""
        for tag in reversed(p_tags):
            t = tag.lower()
            if t.startswith("<font"): r += "</font>"
            elif t.startswith("<strike"): r += "</strike>"
            elif t == "<b>": r += "</b>"
            elif t == "<i>": r += "</i>"
        return r
    def abrir_todas(p_tags): return "".join(p_tags)
    for token in tokens:
        if not token: continue
        t = token.lower()
        if t in ["<br>", "<br/>", "<br />"]:
            texto_atual += fechar_todas(pilha)
            if re.sub(r'<[^>]+>', '', texto_atual).strip(): paragrafos.append(texto_atual.strip())
            texto_atual = abrir_todas(pilha)
        elif t.startswith("</"):
            rm = False
            for i in range(len(pilha)-1, -1, -1):
                pl = pilha[i].lower()
                if (t == "</font>" and pl.startswith("<font")) or (t == "</strike>" and pl.startswith("<strike")) or (t == "</b>" and pl == "<b>") or (t == "</i>" and pl == "<i>"):
                    pilha.pop(i); rm = True; break
            if rm: texto_atual += token
        elif t.startswith("<font") or t.startswith("<strike") or t in ["<b>", "<i>"]:
            pilha.append(token); texto_atual += token
        else: texto_atual += token
    texto_atual += fechar_todas(pilha)
    if re.sub(r'<[^>]+>', '', texto_atual).strip(): paragrafos.append(texto_atual.strip())
    return paragrafos

def renderizar_paragrafos_pdf(story, texto_html, estilo):
    for p in extrair_paragrafos_seguros(texto_html): story.append(Paragraph(p, estilo))

def aplicar_html_no_docx(p, texto_html):
    texto_html = limpar_texto_ia(texto_html).replace("&nbsp;", "\xa0")
    texto_html = re.sub(r'</?(span|div|p|ul|li|ol)[^>]*>', '', texto_html, flags=re.IGNORECASE)
    tokens = re.split(r'(<[^>]+>)', texto_html)
    is_bold = is_strike = is_red = is_italic = False
    for token in tokens:
        if not token: continue
        t = token.lower()
        if t == '<b>': is_bold = True
        elif t == '</b>': is_bold = False
        elif t == '<i>': is_italic = True
        elif t == '</i>': is_italic = False
        elif t == '<strike>': is_strike = True
        elif t == '</strike>': is_strike = False
        elif "font color" in t and ("red" in t or "'red'" in t or '"red"' in t): is_red = True
        elif t == '</font>': is_red = False
        elif token.startswith('<'): pass
        else:
            run = p.add_run(token)
            run.font.name, run.font.size = 'Times New Roman', Pt(11)
            if is_bold: run.bold = True
            if is_italic: run.italic = True
            if is_strike: run.font.strike = True
            if is_red: run.font.color.rgb = RGBColor(255, 0, 0)

def renderizar_paragrafos_docx(doc, texto_html, alignment, first_line_indent, space_after=Pt(6), bold_all=False):
    for p_html in extrair_paragrafos_seguros(texto_html):
        p = doc.add_paragraph()
        p.alignment = alignment; p.paragraph_format.first_line_indent = first_line_indent; p.paragraph_format.space_after = space_after; p.paragraph_format.line_spacing = 1.15
        if bold_all:
            run = p.add_run(re.sub(r'<[^>]+>', '', p_html).replace("&nbsp;", "\xa0"))
            run.font.name, run.font.size, run.bold = 'Times New Roman', Pt(10), True
        else: aplicar_html_no_docx(p, p_html)

def gerar_pdf_dinamico(consolidacao_dict, tipo_versao):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    story, styles = [], getSampleStyleSheet()
    estilos = {
        'topo': ParagraphStyle('Topo', parent=styles['Normal'], fontName='Times-Bold', fontSize=10, alignment=1, textColor=colors.HexColor('#444444'), spaceAfter=20),
        'orgaos': ParagraphStyle('Orgaos', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, alignment=1, spaceAfter=25),
        'tit': ParagraphStyle('Tit', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, alignment=1, spaceAfter=20),
        'disp': ParagraphStyle('Disp', parent=styles['Normal'], fontName='Times-Roman', fontSize=11, alignment=4, firstLineIndent=30, spaceAfter=12),
        'cel': ParagraphStyle('Cel', parent=styles['Normal'], fontName='Times-Roman', fontSize=10, alignment=0),
        'cap': ParagraphStyle('Cap', parent=styles['Normal'], fontName='Times-Bold', fontSize=10, alignment=1, spaceBefore=20, spaceAfter=12, textTransform='uppercase'),
        'anexo': ParagraphStyle('Anexo', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, alignment=1, spaceBefore=10, spaceAfter=14, textTransform='uppercase'),
        'ass': ParagraphStyle('Ass', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, alignment=1, spaceBefore=50, spaceAfter=20)
    }

    comp = consolidacao_dict.get("cabecalho_complemento", "")
    story.append(Paragraph(f"VERSÃO {'ALTERADA' if tipo_versao=='alterada' else 'CONSOLIDADA'} - {comp}", estilos['topo']))
    if os.path.exists("brasao.png"): img = Image("brasao.png", width=60, height=60); img.hAlign = 'CENTER'; story.append(img); story.append(Spacer(1, 10))

    story.append(Paragraph(limpar_texto_ia(consolidacao_dict.get("orgaos_emissores") or "").replace('\n', '<br/>'), estilos['orgaos']))
    story.append(Paragraph(limpar_texto_ia(consolidacao_dict.get("titulo_portaria") or "").replace('\n', '<br/>'), estilos['tit']))
    renderizar_paragrafos_pdf(story, (consolidacao_dict.get("ementa_preambulo") or "").replace('\n', '<br/>'), estilos['disp'])

    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva((item.get(f"texto_principal_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        if "capitulo" in t: story.append(Paragraph(t_prin, estilos['cap'])); continue
        if "anexo" in t: story.append(PageBreak()); story.append(Paragraph(t_prin, estilos['anexo'])); continue
        if t_prin: renderizar_paragrafos_pdf(story, t_prin, estilos['disp'])
        
        if item.get("is_tabela"):
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas:
                tabela = [[Paragraph(c.replace('\n', '<br/>'), estilos['cel']) for c in l] for l in linhas]
                tb = Table(tabela, colWidths='*')
                tb.setStyle(TableStyle([('TEXTCOLOR',(0,0),(-1,-1),colors.black), ('ALIGN',(0,0),(-1,-1),'LEFT'), ('VALIGN',(0,0),(-1,-1),'MIDDLE'), ('GRID',(0,0),(-1,-1),0.5,colors.black), ('BOTTOMPADDING',(0,0),(-1,-1),6), ('TOPPADDING',(0,0),(-1,-1),6)]))
                story.append(tb); story.append(Spacer(1, 15))
            t_pos = injetar_nota_remissiva((item.get(f"texto_pos_tabela_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva"))
            if t_pos: renderizar_paragrafos_pdf(story, t_pos, estilos['disp'])

    story.append(Paragraph(f"{limpar_texto_ia(consolidacao_dict.get('assinatura_nome') or '')}<br/>{limpar_texto_ia(consolidacao_dict.get('assinatura_cargo') or '')}", estilos['ass']))
    doc.build(story); buffer.seek(0)
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

    renderizar_paragrafos_docx(doc, (consolidacao_dict.get("ementa_preambulo") or "").replace('\n', '<br/>'), WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))

    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva((item.get(f"texto_principal_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        if "capitulo" in t: renderizar_paragrafos_docx(doc, t_prin, WD_ALIGN_PARAGRAPH.CENTER, Inches(0), Pt(10), bold_all=True); continue
        if "anexo" in t: doc.add_page_break(); renderizar_paragrafos_docx(doc, t_prin, WD_ALIGN_PARAGRAPH.CENTER, Inches(0), Pt(14), bold_all=True); continue
        if t_prin: renderizar_paragrafos_docx(doc, t_prin, WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))
        
        if item.get("is_tabela"):
            linhas = item.get(f"tabela_{tipo_versao}") or []
            if linhas:
                tb = doc.add_table(rows=len(linhas), cols=len(linhas[0])); tb.style = 'Table Grid'
                for r_idx, linha in enumerate(linhas):
                    for c_idx, celula in enumerate(linha):
                        aplicar_html_no_docx(tb.cell(r_idx, c_idx).paragraphs[0], celula.replace('\n', '<br/>'))
            t_pos = injetar_nota_remissiva((item.get(f"texto_pos_tabela_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva"))
            if t_pos: renderizar_paragrafos_docx(doc, t_pos, WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))

    pa = doc.add_paragraph(); pa.alignment = WD_ALIGN_PARAGRAPH.CENTER; pa.paragraph_format.space_before = Pt(36)
    ra = pa.add_run(f"{limpar_texto_ia(consolidacao_dict.get('assinatura_nome') or '')}\n{limpar_texto_ia(consolidacao_dict.get('assinatura_cargo') or '')}")
    ra.font.name, ra.font.size, ra.bold = 'Times New Roman', Pt(11), True
    buffer = io.BytesIO(); doc.save(buffer); buffer.seek(0)
    return buffer.getvalue()

# ----------------- REGISTRO DE MEMÓRIA E SALVAMENTO -----------------
def salvar_no_supabase(cons, cons_original):
    if not supabase: st.error("⚠️ Supabase não configurado."); return False
    try:
        # FEEDBACK LOOP: compara TUDO que é editável (ementa, alterada, consolidada,
        # tabelas e texto pós-tabela) e grava cada correção real feita pelo usuário —
        # antes só a versão Consolidada do texto principal era capturada.
        if cons_original:
            def _registrar(campo, original, editado):
                if original != editado and (original or editado):
                    try:
                        supabase.table("memoria_de_correcoes").insert({
                            "texto_ia": json.dumps(original) if not isinstance(original, str) else original,
                            "texto_corrigido": json.dumps(editado) if not isinstance(editado, str) else editado,
                        }).execute()
                    except Exception:
                        pass

            _registrar("ementa", cons_original.get('ementa_preambulo'), cons.get('ementa_preambulo'))
            for j, disp_editado in enumerate(cons.get("dispositivos", [])):
                if j >= len(cons_original.get("dispositivos", [])): break
                disp_original = cons_original["dispositivos"][j]
                for campo in ["texto_principal_alterada", "texto_principal_consolidada",
                              "tabela_alterada", "tabela_consolidada",
                              "texto_pos_tabela_alterada", "texto_pos_tabela_consolidada"]:
                    _registrar(campo, disp_original.get(campo), disp_editado.get(campo))
        
        base = cons['norma_base']
        alteradoras = cons.get('normas_alteradoras', [])
        data_base_iso = converter_para_iso(base.get('data_assinatura'))
        
        res_busca = supabase.table("portarias_base").select("id").eq("nome_padronizado", base['nome_padronizado']).execute()
        if res_busca.data:
            base_id = res_busca.data[0]['id']
            supabase.table("portarias_base").update({"documento_consolidado_json": cons}).eq("id", base_id).execute()
        else:
            res_ins = supabase.table("portarias_base").insert({
                "tipo_documento": base['tipo_documento'], "numero_documento": base['numero_documento'],
                "orgao_emissor": base['orgao_emissor'], "data_assinatura": data_base_iso,
                "nome_padronizado": base['nome_padronizado'], "titulo_original": cons.get("titulo_portaria"),
                "orgaos_emissores": cons.get("orgaos_emissores"), "assinatura_nome": cons.get("assinatura_nome"),
                "assinatura_cargo": cons.get("assinatura_cargo"), "documento_consolidado_json": cons
            }).execute()
            base_id = res_ins.data[0]['id']
            
        for alt in alteradoras:
            res_alt = supabase.table("portarias_alteradoras").select("id").eq("portaria_base_id", base_id).eq("nome_padronizado", alt['nome_padronizado']).execute()
            if not res_alt.data:
                data_alt_iso = converter_para_iso(alt.get('data_assinatura'))
                supabase.table("portarias_alteradoras").insert({
                    "portaria_base_id": base_id, "tipo_documento": alt['tipo_documento'],
                    "numero_documento": alt['numero_documento'], "orgao_emissor": alt['orgao_emissor'],
                    "data_assinatura": data_alt_iso, "nome_padronizado": alt['nome_padronizado'],
                    "arquivo_nome_original": "Múltiplos Documentos"
                }).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

# ----------------- FRONT-END COM EDITOR VISUAL -----------------
if "dados_processados" not in st.session_state: st.session_state.dados_processados = None
if "dados_originais_ia" not in st.session_state: st.session_state.dados_originais_ia = None
st.markdown("<br>", unsafe_allow_html=True)

if st.button("🚀 Iniciar Análise Autopilot", type="primary", use_container_width=True):
    if not api_key: 
        st.error("⚠️ Insira sua chave da API nas configurações.")
    elif not arquivos_enviados: 
        st.warning("⚠️ Envie os arquivos normativos primeiro.")
    else:
        with st.spinner("⚡ Executando OCR Estrutural e Consulta ao Histórico de Aprendizado..."):
            try:
                st.session_state.dados_processados = analisar_lote_arquivos(arquivos_enviados, api_key.strip())
                st.session_state.dados_originais_ia = copy.deepcopy(st.session_state.dados_processados)
                n_grupos = len(st.session_state.dados_processados.get("consolidacoes_geradas", []))
                st.success(f"✨ Processamento concluído: {n_grupos} família(s) normativa(s) identificada(s) e consolidada(s)!")
                nao_alterados = st.session_state.dados_processados.get("arquivos_nao_alterados", [])
                if nao_alterados:
                    st.warning("⚠️ Estes arquivos NÃO foram consolidados (nenhum ato original correspondente foi identificado no lote): " + ", ".join(nao_alterados))
            except Exception as e:
                mensagem_erro = str(e)
                if "429" in mensagem_erro or "RESOURCE_EXHAUSTED" in mensagem_erro:
                    st.error("❌ Limite de cota esgotado em ambos os modelos (Gemini 3.6 e Gemini 3.5).")
                else:
                    st.error(f"❌ Ocorreu um erro: {mensagem_erro}")

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
            st.info("Formate o texto livremente. Alterações manuais ensinam a IA a não errar novamente na próxima vez que você gerar.")
            
            cons['titulo_portaria'] = st.text_input("Título da Portaria", cons.get('titulo_portaria', ''), key=f"titulo_{i}")
            st.markdown("**Ementa e Preâmbulo**")
            val_ementa = ia_para_editor(cons.get('ementa_preambulo', ''))
            ementa_editada = st_quill(value=val_ementa, html=True, key=f"q_ementa_{i}")
            if ementa_editada: cons['ementa_preambulo'] = editor_para_pdf(ementa_editada)
            
            st.markdown("#### Dispositivos (Artigos, Parágrafos, Incisos, Anexos)")
            for j, disp in enumerate(cons.get("dispositivos", [])):
                with st.expander(f"**{disp.get('tipo', 'Dispositivo').upper()} {j+1}** — clique para revisar/editar", expanded=False):
                    c_alt, c_cons = st.columns(2)

                    with c_alt:
                        st.markdown("*Versão Alterada*")
                        val_alt = ia_para_editor(disp.get('texto_principal_alterada', ''))
                        alt_editada = st_quill(value=val_alt, html=True, key=f"q_alt_{i}_{j}")
                        if alt_editada: disp['texto_principal_alterada'] = editor_para_pdf(alt_editada)

                    with c_cons:
                        st.markdown("*Versão Consolidada*")
                        val_cons = ia_para_editor(disp.get('texto_principal_consolidada', ''))
                        cons_editada = st_quill(value=val_cons, html=True, key=f"q_cons_{i}_{j}")
                        if cons_editada: disp['texto_principal_consolidada'] = editor_para_pdf(cons_editada)

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
                if salvar_no_supabase(cons, cons_original): 
                    st.success(f"Banco atualizado e Inteligência Artificial re-treinada com seus ajustes!")
            
            c1, c2 = st.columns(2)
            pdf_alt, docx_alt = gerar_pdf_dinamico(cons, "alterada"), gerar_docx_dinamico(cons, "alterada")
            pdf_cons, docx_cons = gerar_pdf_dinamico(cons, "consolidada"), gerar_docx_dinamico(cons, "consolidada")
            
            nome_arquivo_base = nome_exibicao_base.replace(' ', '_').replace('/', '-')
            c1.download_button("Baixar PDF (Alterada)", data=pdf_alt, file_name=f"{nome_arquivo_base}_Alt.pdf", mime="application/pdf", key=f"pa_{i}")
            c1.download_button("Baixar DOCX (Alterada)", data=docx_alt, file_name=f"{nome_arquivo_base}_Alt.docx", mime="application/vnd.openxmlformats", key=f"da_{i}")
            c2.download_button("Baixar PDF (Consolidada)", data=pdf_cons, file_name=f"{nome_arquivo_base}_Cons.pdf", mime="application/pdf", key=f"pc_{i}")
            c2.download_button("Baixar DOCX (Consolidada)", data=docx_cons, file_name=f"{nome_arquivo_base}_Cons.docx", mime="application/vnd.openxmlformats", key=f"dc_{i}")

    if st.button("🔄 Nova Análise", type="secondary"): st.session_state.dados_processados = None; st.session_state.dados_originais_ia = None; st.rerun()
