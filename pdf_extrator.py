# pdf_extrator.py - Leitura de PDF rápida (PyMuPDF), sem dependência do Streamlit.
#
# Ganhos em relação à versão anterior (mesmo formato de saída, o segmentador continua funcionando):
#   1. UMA análise por página (get_text("dict")) em vez de get_text() + get_text("dict") + find_tables() sempre.
#   2. find_tables() só roda em páginas que têm gráficos vetoriais (linhas/retângulos). A estratégia padrão do
#      PyMuPDF depende dessas linhas; sem elas o resultado é sempre vazio, então o custo era desperdício puro.
#   3. PDF escaneado é detectado ANTES do processamento pesado (antes: todo o texto/tabelas era processado e jogado fora).
#   4. Concatenação por lista + join (antes: html_text += ... em loop, quadrático).
#   5. Paralelismo REAL com processos (PyMuPDF é CPU-bound e prende o GIL; ThreadPool não acelerava nada).
#      Vários arquivos -> um processo por arquivo; um arquivo grande -> faixas de páginas em processos distintos.
#   6. OCR visual em tons de cinza e JPEG menor (menos bytes enviados à IA, menos latência e tokens).
import multiprocessing as mp
import os
import re
from concurrent.futures import ProcessPoolExecutor

import fitz  # PyMuPDF

RE_RODAPE_SEI = re.compile(r'\(\d+\)\s*SEI\s+[\d./-]+\s*/\s*pg\.\s*\d+', re.IGNORECASE)
_RE_ANEXO_PAG = re.compile(r'ANEXO\s+[IVXLC]+', re.IGNORECASE)
_MIN_CHARS_POR_PAGINA = 30
_PAGINAS_POR_FAIXA = 12          # tamanho da faixa enviada a cada processo
_MIN_PAGINAS_PARALELO = 24       # abaixo disso o custo de enviar bytes ao processo não compensa
_MIN_PAGINAS_OCR_PARALELO = 6


def criar_pool(max_workers=None):
    n = max_workers or max(1, min(4, (os.cpu_count() or 2)))
    return ProcessPoolExecutor(max_workers=n, mp_context=mp.get_context("spawn"))


def pagina_tem_graficos(page):
    """True se a página tem traços vetoriais (condição necessária para find_tables achar algo)."""
    try:
        return len(page.get_cdrawings()) > 0
    except Exception:
        return True


def _linha_txt(l):
    return "".join(s.get("text", "") for s in l.get("spans", []))


def _pagina_para_texto(page, num):
    """Devolve (texto_da_pagina, caracteres_uteis) no mesmo formato histórico (=== PÁGINA n ===, [TABELA]...)."""
    blocos = [b for b in page.get_text("dict", sort=True).get("blocks", []) if b.get("type") == 0]
    saida = [f"=== PÁGINA {num + 1} ===\n"]
    chars = 0

    # uma única passada para: texto plano (detecção de ANEXO) e y do rodapé SEI
    rodape_y0 = None
    plano = []
    for b in blocos:
        for l in b.get("lines", []):
            t = _linha_txt(l)
            plano.append(t)
            if RE_RODAPE_SEI.search(t):
                y = l.get("bbox", (0, 0, 0, 0))[1]
                rodape_y0 = y if rodape_y0 is None else min(rodape_y0, y)
    if _RE_ANEXO_PAG.search("\n".join(plano)):
        saida.append("[ANEXO]\n")

    tabelas_bbox, tabelas_itens = [], []
    if pagina_tem_graficos(page):
        try:
            try:
                if rodape_y0 is not None:
                    finder = page.find_tables(clip=fitz.Rect(page.rect.x0, page.rect.y0, page.rect.x1, rodape_y0))
                else:
                    finder = page.find_tables()
            except TypeError:
                finder = page.find_tables()
            for tabela in finder.tables:
                linhas = tabela.extract()
                if not linhas:
                    continue
                chars += sum(len(str(c or "")) for linha in linhas for c in linha)
                rect = fitz.Rect(tabela.bbox)
                tabelas_bbox.append(rect)
                partes = ["[TABELA]\n"]
                for linha in linhas:
                    partes.append(" | ".join((str(c).strip() if c is not None else "") for c in linha) + "\n")
                partes.append("[/TABELA]\n<br/>\n")
                tabelas_itens.append((rect.y0, "".join(partes)))
        except Exception:
            pass

    itens_texto = []
    for b in blocos:
        rect_b = fitz.Rect(b.get("bbox", (0, 0, 0, 0)))
        if tabelas_bbox and any(rect_b.intersects(tb) for tb in tabelas_bbox):
            continue
        linhas_bloco = []
        for l in b.get("lines", []):
            if RE_RODAPE_SEI.search(_linha_txt(l)):
                continue
            partes = []
            for s in l.get("spans", []):
                t = s.get("text", "")
                if not t:
                    continue
                chars += len(t.strip())
                fl = s.get("flags", 0)
                if fl & 16:
                    t = f"<b>{t}</b>"
                if fl & 2:
                    t = f"<i>{t}</i>"
                partes.append(t)
            ls = "".join(partes)
            if ls.strip():
                linhas_bloco.append(ls)
        if linhas_bloco:
            itens_texto.append((rect_b.y0, " ".join(linhas_bloco).strip() + "<br/>\n"))

    tabelas_itens.sort(key=lambda x: x[0])
    ti = 0
    for y0, txt in itens_texto:
        while ti < len(tabelas_itens) and tabelas_itens[ti][0] <= y0:
            saida.append(tabelas_itens[ti][1])
            ti += 1
        saida.append(txt)
    while ti < len(tabelas_itens):
        saida.append(tabelas_itens[ti][1])
        ti += 1
    saida.append("<br/>\n")
    return "".join(saida), chars


def _worker_texto(file_bytes, ini, fim):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    textos, total = [], 0
    for n in range(ini, min(fim, doc.page_count)):
        t, c = _pagina_para_texto(doc[n], n)
        textos.append(t)
        total += c
    doc.close()
    return textos, total


def _render_paginas(file_bytes, ini, fim, dpi):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    mat = fitz.Matrix(dpi, dpi)
    imgs = []
    for n in range(ini, min(fim, doc.page_count)):
        pix = doc[n].get_pixmap(matrix=mat, colorspace=fitz.csGRAY, alpha=False)
        imgs.append({"tipo": "imagem", "mime": "image/jpeg", "dados": pix.tobytes("jpg", jpg_quality=70)})
    doc.close()
    return imgs


def _parece_escaneado(doc):
    n = doc.page_count
    amostra = min(n, 3)
    for i in range(amostra):
        if len(doc[i].get_text("text").strip()) >= _MIN_CHARS_POR_PAGINA:
            return False
    total = sum(len(doc[i].get_text("text").strip()) for i in range(n))
    return total < _MIN_CHARS_POR_PAGINA * max(n, 1)


def _faixas(n, tam):
    return [(i, min(i + tam, n)) for i in range(0, n, tam)]


def _executar_faixas(pool, fn, file_bytes, faixas, *extra):
    try:
        futs = [pool.submit(fn, file_bytes, a, b, *extra) for a, b in faixas]
        return [f.result() for f in futs]
    except Exception:
        # pool quebrado/indisponível: processa na própria thread (mais lento, mas nunca falha por causa do pool)
        return [fn(file_bytes, a, b, *extra) for a, b in faixas]


def extrair_conteudo(file_bytes, nome_arquivo, dpi_ocr=1.5, max_paginas_ocr=None, pool=None):
    """Retorna a mesma lista de itens de antes: [texto] ou [aviso, {imagem}, ...]."""
    if nome_arquivo.lower().endswith(".docx"):
        return [f"ARQUIVO DOCX: {nome_arquivo}"]
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        n = doc.page_count
        if pool is not None and n < _MIN_PAGINAS_PARALELO:
            # arquivo pequeno: um processo cuida dele inteiro (permite vários arquivos em paralelo de verdade)
            doc.close()
            try:
                return pool.submit(_worker_arquivo, file_bytes, nome_arquivo, dpi_ocr, max_paginas_ocr).result()
            except Exception:
                return _worker_arquivo(file_bytes, nome_arquivo, dpi_ocr, max_paginas_ocr)
        escaneado = _parece_escaneado(doc)
        doc.close()

        if not escaneado:
            if pool is not None and n >= _MIN_PAGINAS_PARALELO:
                res = _executar_faixas(pool, _worker_texto, file_bytes, _faixas(n, _PAGINAS_POR_FAIXA))
                textos = [t for r in res for t in r[0]]
                chars = sum(r[1] for r in res)
            else:
                textos, chars = _worker_texto(file_bytes, 0, n)
            if chars >= _MIN_CHARS_POR_PAGINA * max(n, 1):
                return [f"CONTEÚDO DO ARQUIVO {nome_arquivo}:\n\n" + "".join(textos)]

        limite = n if max_paginas_ocr is None else min(n, max_paginas_ocr)
        partes = [f"ARQUIVO {nome_arquivo} É UM DOCUMENTO ESCANEADO. Leia o conteúdo visualmente, inclusive tabelas:"]
        if pool is not None and limite >= _MIN_PAGINAS_OCR_PARALELO:
            res = _executar_faixas(pool, _render_paginas, file_bytes, _faixas(limite, 4), dpi_ocr)
            partes.extend(img for r in res for img in r)
        else:
            partes.extend(_render_paginas(file_bytes, 0, limite, dpi_ocr))
        if limite < n:
            partes.insert(1, f"[Nota: apenas as primeiras {limite} páginas foram convertidas em imagem por limite do modo de processamento.]")
        return partes
    except Exception as e:
        return [f"Erro ao extrair PDF {nome_arquivo}: {e}"]


def _worker_arquivo(file_bytes, nome, dpi_ocr, max_paginas_ocr):
    return extrair_conteudo(file_bytes, nome, dpi_ocr, max_paginas_ocr, pool=None)


def extrair_varios(arquivos, dpi_ocr=1.5, max_paginas_ocr=None, pool=None, ao_concluir=None):
    """arquivos: lista de (nome, bytes). Retorna {nome: itens}. Vários arquivos => um processo por arquivo."""
    resultado = {}
    if pool is not None and len(arquivos) > 1:
        try:
            futs = {pool.submit(_worker_arquivo, b, nm, dpi_ocr, max_paginas_ocr): nm for nm, b in arquivos}
            from concurrent.futures import as_completed
            for f in as_completed(futs):
                resultado[futs[f]] = f.result()
                if ao_concluir:
                    ao_concluir(futs[f], len(resultado), len(arquivos))
            return resultado
        except Exception:
            resultado.clear()
    for i, (nm, b) in enumerate(arquivos, 1):
        resultado[nm] = extrair_conteudo(b, nm, dpi_ocr, max_paginas_ocr, pool=pool)
        if ao_concluir:
            ao_concluir(nm, i, len(arquivos))
    return resultado
