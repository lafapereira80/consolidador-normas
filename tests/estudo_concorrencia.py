"""Estudo empírico de concorrência: código ORIGINAL x código NOVO, com 2+ usuários simultâneos.
Uso:  python tests/estudo_concorrencia.py   (gera tests/resultado_estudo.json)
"""
import json
import os
import sys
import threading
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, ".."))
sys.path.insert(0, AQUI)

from fake_supabase import FakeClient
import legado
from repositorio import Repositorio
from concorrencia import Registro

LAT = (0.002, 0.010)   # latência simulada por chamada de rede (2-10 ms)


def correr(fns, barreira=True):
    """Executa fns em threads iniciadas juntas (usuários clicando no mesmo instante)."""
    b = threading.Barrier(len(fns)) if barreira else None
    saidas = [None] * len(fns)

    def _w(i, f):
        if b:
            b.wait()
        try:
            saidas[i] = f()
        except Exception as e:   # noqa
            saidas[i] = e

    ts = [threading.Thread(target=_w, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return saidas


IDENT = {"tipo_documento": "PORTARIA", "numero_documento": "30/PGJM", "orgao_emissor": "PGJM",
         "data_assinatura": "2026-05-20", "nome_padronizado": "PORTARIA Nº 30/PGJM, de 20 de maio de 2026"}
REF = {"tipo_ato_afetado": "PORTARIA", "numero_ato_afetado": "10/PGJ"}


def e1_pendencia_duplicada(tentativas=150):
    res = {}
    for modo in ("original", "novo"):
        dup = 0
        for _ in range(tentativas):
            cli = FakeClient(LAT)
            if modo == "original":
                L = legado.carregar(cli)
                fns = [lambda: L.salvar_pendencia("a.pdf", "x", IDENT, REF)] * 2
            else:
                R = Repositorio(cli, Registro())
                fns = [lambda: R.salvar_pendencia("a.pdf", "x", IDENT, REF)] * 2
            correr(fns)
            if len(cli.linhas("atos_importados")) > 1:
                dup += 1
        res[modo] = {"tentativas": tentativas, "com_duplicata": dup}
    return res


def e2_leitura_duplicada(tentativas=150):
    res = {}
    for modo in ("original", "novo"):
        dup = 0
        for _ in range(tentativas):
            cli = FakeClient(LAT)
            if modo == "original":
                L = legado.carregar(cli)
                fns = [lambda: L.salvar_leitura("a.pdf", "x", IDENT)] * 2
            else:
                R = Repositorio(cli, Registro())
                fns = [lambda: R.salvar_leitura("a.pdf", "x", IDENT)] * 2
            correr(fns)
            if len(cli.linhas("atos_importados")) > 1:
                dup += 1
        res[modo] = {"tentativas": tentativas, "com_duplicata": dup}
    return res


def _cons(alteradoras, marca):
    base = {"tipo_documento": "PORTARIA", "numero_documento": "5/PGJM", "orgao_emissor": "PGJM",
            "data_assinatura": "2025-01-17", "nome_padronizado": "PORTARIA Nº 5/PGJM, de 17 de janeiro de 2025"}
    alts = [{"tipo_documento": "PORTARIA", "numero_documento": n, "orgao_emissor": "PGJM", "data_assinatura": "2026-01-01",
             "nome_padronizado": f"PORTARIA Nº {n}, de 1 de janeiro de 2026"} for n in alteradoras]
    return {"norma_base": base, "normas_alteradoras": alts, "titulo_portaria": "t", "orgaos_emissores": "o",
            "assinatura_nome": "n", "assinatura_cargo": "c", "ementa": "e", "preambulo": "p",
            "dispositivos": [{"tipo": "artigo", "texto_principal_consolidada": marca, "texto_principal_alterada": marca}]}


def e3_atualizacao_perdida(tentativas=100):
    """A grava a consolidação com a alteradora 11/PGJM; B (que abriu a mesma base antes) grava com 12/PGJM."""
    res = {}
    for modo in ("original", "novo"):
        inconsist = perdidas = bloqueios = 0
        for _ in range(tentativas):
            cli = FakeClient(LAT)
            A, B = _cons(["11/PGJM"], "estado A"), _cons(["12/PGJM"], "estado B")
            if modo == "original":
                L = legado.carregar(cli)
                correr([lambda: L.salvar_no_supabase(A, None), lambda: L.salvar_no_supabase(B, None)])
            else:
                R = Repositorio(cli, Registro())
                r = correr([lambda: R.salvar_consolidacao(A, None), lambda: R.salvar_consolidacao(B, None)])
                bloqueios += sum(1 for x in r if getattr(x, "conflito", None))
            base = cli.linhas("portarias_base")[0]
            nomes_json = {a["nome_padronizado"] for a in base["documento_consolidado_json"]["normas_alteradoras"]}
            nomes_tab = {a["nome_padronizado"] for a in cli.linhas("portarias_alteradoras")}
            if nomes_json != nomes_tab:
                inconsist += 1          # tabela de vínculos lista alteradoras que o texto consolidado NÃO contém
            if len(nomes_json) < 2 and modo == "original":
                perdidas += 1
        res[modo] = {"tentativas": tentativas, "banco_inconsistente": inconsist, "alteracao_perdida_silenciosamente": perdidas,
                     "gravacoes_bloqueadas_por_conflito": bloqueios}
    return res


def e4_memoria_duplicada():
    res = {}
    for modo in ("original", "novo"):
        cli = FakeClient()
        orig, edit = _cons(["11/PGJM"], "texto da IA"), _cons(["11/PGJM"], "texto corrigido")
        if modo == "original":
            L = legado.carregar(cli)
            for _ in range(3):
                L.salvar_no_supabase(edit, orig)
        else:
            R = Repositorio(cli, Registro())
            for _ in range(3):
                R.salvar_consolidacao(edit, orig)
        res[modo] = {"cliques_em_salvar": 3, "linhas_em_memoria_de_correcoes": len(cli.linhas("memoria_de_correcoes"))}
    return res


def e5_forca_bruta():
    reg = Registro()
    ate_bloquear = 0
    for i in range(1000):
        if reg.segundos_bloqueado("admin"):
            break
        reg.registrar_falha("admin")
        ate_bloquear += 1
    return {"original": {"tentativas_aceitas_de_1000": 1000, "observacao": "nenhum limite: senha pode ser testada indefinidamente"},
            "novo": {"tentativas_aceitas_de_1000": ate_bloquear, "bloqueio_s": reg.segundos_bloqueado("admin")}}


def e6_ia_simultanea(usuarios=6, chamadas_por_usuario=5):
    def medir(usar_sem):
        reg = Registro(ia_simultaneas=3)
        atual = [0]
        pico = [0]
        lk = threading.Lock()

        def chamada():
            with lk:
                atual[0] += 1
                pico[0] = max(pico[0], atual[0])
            time.sleep(0.03)
            with lk:
                atual[0] -= 1

        def usuario():
            for _ in range(chamadas_por_usuario):
                if usar_sem:
                    with reg.vaga_ia():
                        chamada()
                else:
                    chamada()

        t0 = time.time()
        correr([usuario] * usuarios)
        return {"pico_de_chamadas_simultaneas": pico[0], "tempo_s": round(time.time() - t0, 2)}
    return {"original": medir(False), "novo": medir(True)}


def e7_registro_sob_carga():
    """200 threads batendo no registro compartilhado (presença, trava, token): nenhuma exceção / estado corrompido."""
    reg = Registro()
    erros = []

    def w(i):
        try:
            for k in range(50):
                reg.batimento(f"s{i}", f"u{i%5}", "p")
                reg.adquirir_trava("base:X", f"s{i}", f"u{i%5}")
                t = reg.criar_token(f"u{i%5}", "usuario")
                assert reg.validar_token(t)
                reg.evento(f"u{i%5}", "x")
        except Exception as e:   # noqa
            erros.append(repr(e))

    correr([lambda i=i: w(i) for i in range(200)])
    return {"threads": 200, "operacoes": 200 * 50 * 4, "excecoes": len(erros), "sessoes_online": len(reg.online()), "travas_ativas": len(reg.travas)}


if __name__ == "__main__":
    inicio = time.time()
    saida = {
        "E1_pendencia_duplicada": e1_pendencia_duplicada(),
        "E2_leitura_duplicada": e2_leitura_duplicada(),
        "E3_atualizacao_perdida": e3_atualizacao_perdida(),
        "E4_memoria_de_correcoes_duplicada": e4_memoria_duplicada(),
        "E5_forca_bruta_login": e5_forca_bruta(),
        "E6_chamadas_de_ia_simultaneas": e6_ia_simultanea(),
        "E7_registro_compartilhado_sob_carga": e7_registro_sob_carga(),
    }
    saida["duracao_s"] = round(time.time() - inicio, 1)
    json.dump(saida, open(os.path.join(AQUI, "resultado_estudo.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(saida, ensure_ascii=False, indent=2))
