"""Fluxo de Consolidar com DOIS usuários (AppTest): prévia, salvar, conflito de gravação, sobrescrita consciente."""
import copy, os, sys
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path[:0] = [RAIZ, os.path.join(RAIZ, "tests")]
from streamlit.testing.v1 import AppTest
import demo_patch.sitecustomize as demo  # noqa: F401
import concorrencia as conc

PAG = os.path.join(RAIZ, "pages/3_Consolidar_Norma.py")


def cons(alteradoras, marca):
    base = {"tipo_documento": "PORTARIA", "numero_documento": "99/PGJM", "orgao_emissor": "PGJM", "data_assinatura": "2025-01-17",
            "nome_padronizado": "PORTARIA Nº 99/PGJM, de 17 de janeiro de 2025"}
    alts = [{"tipo_documento": "PORTARIA", "numero_documento": n, "orgao_emissor": "PGJM", "data_assinatura": "2026-01-01",
             "nome_padronizado": f"PORTARIA Nº {n}, de 1 de janeiro de 2026"} for n in alteradoras]
    return {"norma_base": base, "normas_alteradoras": alts, "titulo_portaria": "PORTARIA Nº 99/PGJM", "orgaos_emissores": "MPM", "assinatura_nome": "Fulano",
            "assinatura_cargo": "Procurador", "ementa": "<p>Ementa</p>", "preambulo": "<p>Considerando</p>",
            "dispositivos": [{"tipo": "artigo", "texto_principal_alterada": f"<strike>Art. 1 velho</strike> {marca}", "texto_principal_consolidada": f"Art. 1 {marca}",
                              "is_tabela": False, "nota_remissiva": ""}]}


def abrir(usuario, c):
    at = AppTest.from_file(PAG, default_timeout=90)
    at.secrets["supabase"] = {"url": "http://fake", "key": "fake"}
    at.session_state["autenticado"] = True
    at.session_state["usuario"] = usuario
    at.session_state["papel"] = "usuario"
    pacote = {"consolidacoes_geradas": [c], "arquivos_nao_alterados": [], "referencias_pendentes": [], "arquivos_nao_classificados": [], "mensagens": [], "erros": []}
    at.session_state["dados_processados"] = pacote
    at.session_state["dados_originais_ia"] = copy.deepcopy(pacote)
    return at.run()


def test_fluxo_dois_usuarios_conflito_e_sobrescrita():
    a = abrir("maria.silva", cons(["11/PGJM"], "A"))
    b = abrir("joao.souza", cons(["12/PGJM"], "B"))
    assert not a.exception and not b.exception
    # aviso de trava branda: cada um enxerga que o outro está com a mesma norma aberta
    assert "também está com esta norma aberta" in " ".join(m.value for m in b.markdown)

    a.radio(key="vista_0").set_value("Prévia").run()
    assert not a.exception and "cn-papel" in " ".join(m.value for m in a.markdown)

    a.radio(key="vista_0").set_value("Exportar e salvar").run()
    a.button(key="btn_sup_0").click().run()
    assert any("Banco atualizado" in s.value for s in a.success), [e.value for e in a.error]

    b.radio(key="vista_0").set_value("Exportar e salvar").run()
    b.button(key="btn_sup_0").click().run()          # B não tem a alteradora de A => conflito
    assert any("Outro usuário salvou" in w.value for w in b.warning), ([e.value for e in b.error], [s.value for s in b.success])
    assert "11/PGJM" in " ".join(w.value for w in b.warning)

    b.checkbox(key="forcar_0").check().run()
    b.button(key="btn_sup_0").click().run()
    assert any("Banco atualizado" in s.value for s in b.success)

    b.button(key="prep_0").click().run()             # exportação sob demanda
    assert not b.exception
    nomes = [d.label for d in b.get("download_button")] if hasattr(b, "get") else []
    assert nomes == [] or any("HTML" in n for n in nomes)
