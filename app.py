import streamlit as st
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Line
import io
import json
import os
import re
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional

# Importação para Supabase e Word
from supabase import create_client, Client
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(page_title="Autopilot Normativo", page_icon="⚖️", layout="wide")

# ----------------- LAYOUT E CSS -----------------
st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none; }
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
<div class="main-header">
    <h1>⚖️ Autopilot Normativo</h1>
    <p>Consolidação Inteligente e Gestão de Portarias com IA (Memória Cumulativa Ativa)</p>
</div>
""", unsafe_allow_html=True)

# ----------------- CONEXÃO COM SUPABASE -----------------
@st.cache_resource
def init_supabase() -> Optional[Client]:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        return None

supabase = init_supabase()

def render_botao_historico():
    caminho_real = None
    if os.path.exists("pages"):
        for arquivo in os.listdir("pages"):
            if "historico" in arquivo.lower() and arquivo.endswith(".py"):
                caminho_real = f"pages/{arquivo}"
                break
    if caminho_real:
        try:
            st.page_link(caminho_real, label="🗄️ Acessar Banco de Dados", icon="➡️")
        except Exception:
            nome_pagina = caminho_real.replace("pages/", "").replace(".py", "")
            st.markdown(f'<a href="{nome_pagina}" target="_top" style="display: block; text-align: center; background-color: #ff4b4b; color: white !important; padding: 0.6rem 1rem; border-radius: 0.5rem; text-decoration: none; font-weight: bold;">➡️ 🗄️ Acessar Banco de Dados</a>', unsafe_allow_html=True)

col_info, col_nav = st.columns([2, 1])
with col_info:
    st.info("💡 **Inteligência Ativada:** Envie os novos arquivos. O sistema caçará datas ocultas no SEI e cruzará com o banco de dados.")
with col_nav:
    render_botao_historico()

st.markdown("---")

api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except:
    with st.expander("⚙️ Configurações do Sistema (Chave API)", expanded=True):
        api_key = st.text_input("Chave da API", type="password", placeholder="Cole sua chave AI Studio aqui...")

st.markdown("### 📥 Upload de Arquivos Normativos")
arquivos_enviados = st.file_uploader("Arraste todos os documentos (PDF ou DOCX)", type=["pdf", "docx"], accept_multiple_files=True, key="uploader_lote")

# ----------------- ESTRUTURAS PYDANTIC (NOVA INTELIGÊNCIA) -----------------
class MetadadosNorma(BaseModel):
    tipo_documento: str = Field(description="Ex: 'Portaria', 'Lei', 'Decreto'")
    numero_documento: str = Field(description="O número. Ex: '158', '137', ou 'S/N'")
    orgao_emissor: str = Field(description="Sigla do órgão. Ex: 'PGJM'")
    data_assinatura: str = Field(description="Data exata no formato YYYY-MM-DD. IMPORTANTE: Se o cabeçalho disser '(data de assinatura)', procure no bloco final de assinatura eletrônica do SEI.")
    nome_padronizado: str = Field(description="Nome por extenso. Ex: 'PORTARIA Nº 158/PGJM, DE 29 DE JULHO DE 2026'. Deve ser a data real.")

class Dispositivo(BaseModel):
    tipo: str = Field(description="Ex: 'capitulo', 'artigo', 'paragrafo', etc.")
    texto_principal_alterada: str = Field(description="Texto da versão alterada. Tache em vermelho.")
    texto_principal_consolidada: str = Field(description="Texto limpo da versão consolidada.")
    is_tabela: bool = Field(description="True se houver tabela.")
    tabela_alterada: Optional[List[List[str]]] = Field(default=None)
    tabela_consolidada: Optional[List[List[str]]] = Field(default=None)
    texto_pos_tabela_alterada: Optional[str] = Field(default=None)
    texto_pos_tabela_consolidada: Optional[str] = Field(default=None)
    nota_remissiva: Optional[str] = Field(default="")

class Consolidacao(BaseModel):
    arquivo_original_identificado: str
    arquivo_alterador_identificado: str
    norma_base: MetadadosNorma
    norma_alteradora: MetadadosNorma
    cabecalho_complemento: str
    orgaos_emissores: str
    titulo_portaria: str
    ementa_preambulo: str
    assinatura_nome: str
    assinatura_cargo: str
    dispositivos: List[Dispositivo]

class ArquivoAvulso(BaseModel):
    nome_arquivo: str
    nome_portaria_identificada: str
    motivo: str

class AnaliseGlobal(BaseModel):
    consolidacoes_geradas: List[Consolidacao]
    arquivos_nao_alterados: List[ArquivoAvulso]

class IdentificadorDeAlvos(BaseModel):
    nomes_padronizados_alvo: List[str] = Field(description="Lista de 'nome_padronizado' do banco que estão sendo alterados.")

def analisar_lote_arquivos(arquivos, key):
    client = genai.Client(api_key=key)
    caminhos_temporarios = []
    gemini_files_objs = []
    
    try:
        for arq in arquivos:
            ext = f".{arq.name.split('.')[-1]}"
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(arq.getvalue())
                caminhos_temporarios.append((tmp.name, arq.name))
                
        conteudos_iniciais = []
        for caminho_tmp, nome_original in caminhos_temporarios:
            g_file = client.files.upload(file=caminho_tmp)
            gemini_files_objs.append(g_file)
            conteudos_iniciais.append(f"ARQUIVO: {nome_original}")
            conteudos_iniciais.append(g_file)

        # ETAPA 1: Pré-Análise com a nova padronização
        nomes_bd = []
        if supabase:
            try:
                res_bd = supabase.table("portarias_base").select("nome_padronizado").execute()
                nomes_bd = [r["nome_padronizado"] for r in res_bd.data]
            except: pass

        prompt_pre = f"""
        Normas já cadastradas no nosso banco de dados: {nomes_bd}
        Descubra se os arquivos fornecidos alteram alguma norma listada acima. Para datas ocultas tipo 'SEI', leia a assinatura no final do documento para formar o nome padronizado corretamente e buscar a correspondência.
        """
        st.toast("🔍 Cruzando dados e buscando datas em assinaturas...", icon="⏳")
        resp_pre = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=conteudos_iniciais + [prompt_pre],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=IdentificadorDeAlvos, temperature=0.0)
        )
        
        alvos = json.loads(resp_pre.text).get("nomes_padronizados_alvo", [])
        textos_historico = []
        
        if supabase and alvos:
            for alvo_nome in alvos:
                try:
                    res_json = supabase.table("portarias_base").select("nome_padronizado, documento_consolidado_json").eq("nome_padronizado", alvo_nome).execute()
                    if res_json.data and res_json.data[0].get("documento_consolidado_json"):
                        json_str = json.dumps(res_json.data[0]['documento_consolidado_json'])
                        textos_historico.append(f"JSON DA NORMA BASE '{alvo_nome}':\n{json_str}")
                        st.toast(f"✅ Histórico carregado para: {alvo_nome}!", icon="🧠")
                except: pass

        # ETAPA 2: Consolidação Final
        conteudos_prompt = ["Analise as relações normativas e gere a consolidação:"]
        conteudos_prompt.extend(conteudos_iniciais)
        if textos_historico:
            conteudos_prompt.append("\n\nATENÇÃO - HISTÓRICO NO BANCO:")
            conteudos_prompt.extend(textos_historico)

        prompt_comandos = """
        Atue como Especialista Legislativo.
        1. Identifique pares e extraia todos os metadados (tipo, número, orgao, data formato ISO, nome padronizado real).
        2. ATENÇÃO PARA O SEI: Se a data no cabeçalho for genérica '(data da assinatura)', busque ativamente no rodapé do documento pela assinatura eletrônica.
        3. Se houver 'JSON DA NORMA BASE' no prompt, APLIQUE AS ALTERAÇÕES EM CIMA DELE (Memória Cumulativa).
        4. Tache revogações em vermelho. Preserve formatação <b> e <i>.
        """
        conteudos_prompt.append(prompt_comandos)

        st.toast("⚙️ Gerando Textos Consolidados...", icon="⏳")
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=conteudos_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=AnaliseGlobal, temperature=0.0)
        )
        return json.loads(response.text)
    finally:
        for g_file in gemini_files_objs:
            try: client.files.delete(name=g_file.name)
            except: pass
        for caminho_tmp, _ in caminhos_temporarios:
            if os.path.exists(caminho_tmp): os.remove(caminho_tmp)

# --- FUNÇÕES DE PDF/DOCX (MANTIDAS EXATAMENTE IGUAIS) ---
def extrair_paragrafos_seguros(texto_html):
    texto_html = (texto_html or "").replace("</font></strike>", "</strike></font>").replace("</b></i>", "</i></b>").replace('<em>', '<i>').replace('</em>', '</i>').replace('<strong>', '<b>').replace('</strong>', '</b>').replace('<s>', '<strike>').replace('</s>', '</strike>')
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
                    pilha.pop(i)
                    rm = True
                    break
            if rm: texto_atual += token
        elif t.startswith("<font") or t.startswith("<strike") or t in ["<b>", "<i>"]:
            pilha.append(token)
            texto_atual += token
        else: texto_atual += token
    texto_atual += fechar_todas(pilha)
    if re.sub(r'<[^>]+>', '', texto_atual).strip(): paragrafos.append(texto_atual.strip())
    return paragrafos

def injetar_nota_remissiva(texto, nota):
    if nota and nota.strip():
        n = f"({nota.strip()})" if not nota.strip().startswith("(") else nota.strip()
        return f"{texto.rstrip('<br/>').rstrip('<br>').rstrip()} &nbsp;<font color='red'>{n}</font>" if texto else f"<font color='red'>{n}</font>"
    return texto

def renderizar_paragrafos_pdf(story, texto_html, estilo):
    for p in extrair_paragrafos_seguros(texto_html): story.append(Paragraph(p, estilo))

def aplicar_html_no_docx(p, texto_html):
    texto_html = (texto_html or "").replace("&nbsp;", "\xa0")
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
        p.alignment = alignment
        p.paragraph_format.first_line_indent = first_line_indent
        p.paragraph_format.space_after = space_after
        p.paragraph_format.line_spacing = 1.15
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
        'ass': ParagraphStyle('Ass', parent=styles['Normal'], fontName='Times-Bold', fontSize=11, alignment=1, spaceBefore=50, spaceAfter=20)
    }

    comp = consolidacao_dict.get("cabecalho_complemento", "")
    story.append(Paragraph(f"VERSÃO {'ALTERADA' if tipo_versao=='alterada' else 'CONSOLIDADA'} - {comp}", estilos['topo']))
    if os.path.exists("brasao.png"):
        img = Image("brasao.png", width=60, height=60); img.hAlign = 'CENTER'; story.append(img); story.append(Spacer(1, 10))

    story.append(Paragraph((consolidacao_dict.get("orgaos_emissores") or "").replace('\n', '<br/>'), estilos['orgaos']))
    story.append(Paragraph((consolidacao_dict.get("titulo_portaria") or "").replace('\n', '<br/>'), estilos['tit']))
    renderizar_paragrafos_pdf(story, (consolidacao_dict.get("ementa_preambulo") or "").replace('\n', '<br/>'), estilos['disp'])

    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva((item.get(f"texto_principal_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        if "capitulo" in t: story.append(Paragraph(t_prin, estilos['cap'])); continue
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

    story.append(Paragraph(f"{(consolidacao_dict.get('assinatura_nome') or '')}<br/>{(consolidacao_dict.get('assinatura_cargo') or '')}", estilos['ass']))
    doc.build(story); buffer.seek(0)
    return buffer.getvalue()

def gerar_docx_dinamico(consolidacao_dict, tipo_versao):
    doc = docx.Document()
    for section in doc.sections: section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Inches(1)

    ph = doc.add_paragraph(); ph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rh = ph.add_run(f"VERSÃO {'ALTERADA' if tipo_versao=='alterada' else 'CONSOLIDADA'} - {consolidacao_dict.get('cabecalho_complemento', '')}")
    rh.font.name, rh.font.size, rh.bold, rh.font.color.rgb = 'Times New Roman', Pt(10), True, RGBColor(68, 68, 68)
    
    po = doc.add_paragraph(); po.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ro = po.add_run((consolidacao_dict.get("orgaos_emissores") or "").replace("<br/>", "\n"))
    ro.font.name, ro.font.size, ro.bold = 'Times New Roman', Pt(11), True

    ptit = doc.add_paragraph(); ptit.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rt = ptit.add_run(consolidacao_dict.get("titulo_portaria") or "")
    rt.font.name, rt.font.size, rt.bold = 'Times New Roman', Pt(11), True

    renderizar_paragrafos_docx(doc, (consolidacao_dict.get("ementa_preambulo") or "").replace('\n', '<br/>'), WD_ALIGN_PARAGRAPH.JUSTIFY, Inches(0.4))

    for item in consolidacao_dict.get("dispositivos", []):
        t = (item.get("tipo") or "").lower()
        t_prin = injetar_nota_remissiva((item.get(f"texto_principal_{tipo_versao}") or "").replace('\n', '<br/>'), item.get("nota_remissiva") if not item.get("is_tabela") else "")
        if "capitulo" in t: renderizar_paragrafos_docx(doc, t_prin, WD_ALIGN_PARAGRAPH.CENTER, Inches(0), Pt(10), bold_all=True); continue
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
    ra = pa.add_run(f"{(consolidacao_dict.get('assinatura_nome') or '')}\n{(consolidacao_dict.get('assinatura_cargo') or '')}")
    ra.font.name, ra.font.size, ra.bold = 'Times New Roman', Pt(11), True
    buffer = io.BytesIO(); doc.save(buffer); buffer.seek(0)
    return buffer.getvalue()

# ----------------- NOVO SALVAMENTO NO SUPABASE (METADADOS EXATOS) -----------------
def salvar_no_supabase(cons):
    if not supabase: st.error("⚠️ Supabase não configurado."); return False
    try:
        base = cons['norma_base']
        alt = cons['norma_alteradora']
        
        # 1. Busca se a norma base já existe
        res_busca = supabase.table("portarias_base").select("id").eq("nome_padronizado", base['nome_padronizado']).execute()
        
        if res_busca.data:
            base_id = res_busca.data[0]['id']
            # Atualiza o JSON da Memória
            supabase.table("portarias_base").update({"documento_consolidado_json": cons}).eq("id", base_id).execute()
        else:
            data_ass = base.get('data_assinatura')
            if not data_ass or data_ass.strip() == "": data_ass = None
            
            res_ins = supabase.table("portarias_base").insert({
                "tipo_documento": base['tipo_documento'],
                "numero_documento": base['numero_documento'],
                "orgao_emissor": base['orgao_emissor'],
                "data_assinatura": data_ass,
                "nome_padronizado": base['nome_padronizado'],
                "titulo_original": cons.get("titulo_portaria"),
                "orgaos_emissores": cons.get("orgaos_emissores"),
                "assinatura_nome": cons.get("assinatura_nome"),
                "assinatura_cargo": cons.get("assinatura_cargo"),
                "documento_consolidado_json": cons
            }).execute()
            base_id = res_ins.data[0]['id']
            
        # 2. Registra a Norma Alteradora
        res_alt = supabase.table("portarias_alteradoras").select("id").eq("portaria_base_id", base_id).eq("nome_padronizado", alt['nome_padronizado']).execute()
        
        if not res_alt.data:
            data_alt = alt.get('data_assinatura')
            if not data_alt or data_alt.strip() == "": data_alt = None
            
            supabase.table("portarias_alteradoras").insert({
                "portaria_base_id": base_id,
                "tipo_documento": alt['tipo_documento'],
                "numero_documento": alt['numero_documento'],
                "orgao_emissor": alt['orgao_emissor'],
                "data_assinatura": data_alt,
                "nome_padronizado": alt['nome_padronizado'],
                "arquivo_nome_original": cons.get("arquivo_alterador_identificado")
            }).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

# ----------------- FRONT-END -----------------
if "dados_processados" not in st.session_state: st.session_state.dados_processados = None
st.markdown("<br>", unsafe_allow_html=True)

if st.button("🚀 Iniciar Análise Autopilot", type="primary", use_container_width=True):
    if not api_key: st.error("⚠️ Insira sua chave.")
    elif not arquivos_enviados: st.warning("⚠️ Envie arquivos.")
    else:
        with st.spinner("🧠 Processando e lendo assinaturas SEI..."):
            try:
                st.session_state.dados_processados = analisar_lote_arquivos(arquivos_enviados, api_key.strip())
                st.success("✨ Processamento Concluído!")
            except Exception as e: st.error(f"❌ Erro: {e}")

if st.session_state.dados_processados:
    st.markdown("---")
    dados = st.session_state.dados_processados
    for i, cons in enumerate(dados.get("consolidacoes_geradas", [])):
        nome_exibicao_base = cons['norma_base']['nome_padronizado']
        nome_exibicao_alt = cons['norma_alteradora']['nome_padronizado']
        
        with st.expander(f"📁 **{nome_exibicao_base}** alterada por **{nome_exibicao_alt}**", expanded=True):
            if st.button(f"💾 Salvar/Atualizar no Supabase", key=f"btn_sup_{i}"):
                if salvar_no_supabase(cons): st.success(f"Banco atualizado com {nome_exibicao_alt}!")
            
            c1, c2 = st.columns(2)
            pdf_alt, docx_alt = gerar_pdf_dinamico(cons, "alterada"), gerar_docx_dinamico(cons, "alterada")
            pdf_cons, docx_cons = gerar_pdf_dinamico(cons, "consolidada"), gerar_docx_dinamico(cons, "consolidada")
            
            nome_arquivo_base = nome_exibicao_base.replace(' ', '_').replace('/', '-')
            c1.download_button("Baixar PDF (Alterada)", data=pdf_alt, file_name=f"{nome_arquivo_base}_Alt.pdf", mime="application/pdf", key=f"pa_{i}")
            c1.download_button("Baixar DOCX (Alterada)", data=docx_alt, file_name=f"{nome_arquivo_base}_Alt.docx", mime="application/vnd.openxmlformats", key=f"da_{i}")
            c2.download_button("Baixar PDF (Consolidada)", data=pdf_cons, file_name=f"{nome_arquivo_base}_Cons.pdf", mime="application/pdf", key=f"pc_{i}")
            c2.download_button("Baixar DOCX (Consolidada)", data=docx_cons, file_name=f"{nome_arquivo_base}_Cons.docx", mime="application/vnd.openxmlformats", key=f"dc_{i}")

    if st.button("🔄 Nova Análise", type="secondary"): st.session_state.dados_processados = None; st.rerun()
