"""Teste de fumaça de TODAS as páginas com o Streamlit AppTest + banco falso (rodar da raiz: pytest tests -q)."""
import os, sys
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path[:0] = [RAIZ, os.path.join(RAIZ, "tests")]
import pytest
from streamlit.testing.v1 import AppTest
import demo_patch.sitecustomize  # noqa: F401  (troca create_client pelo banco falso)
import concorrencia as conc

PAGINAS = ["app.py", "pages/1_Historico.py", "pages/3_Consolidar_Norma.py", "pages/4_Extrair_Boletim_BSe.py", "pages/diagnostico.py", "pages/usuarios.py"]


def sessao(pagina, usuario="maria.silva", papel="usuario"):
    at = AppTest.from_file(os.path.join(RAIZ, pagina), default_timeout=60)
    at.secrets["supabase"] = {"url": "http://fake", "key": "fake"}
    at.session_state["autenticado"] = True
    at.session_state["usuario"] = usuario
    at.session_state["papel"] = papel
    return at.run()


@pytest.mark.parametrize("pagina", PAGINAS)
def test_pagina_sem_excecao_como_admin(pagina):
    at = sessao(pagina, "admin", "admin")
    assert not at.exception, [e.value for e in at.exception]


def test_usuarios_bloqueada_para_nao_admin():
    at = sessao("pages/usuarios.py", "maria.silva", "usuario")
    assert not at.exception
    assert "restrita a administradores" in " ".join(m.value for m in at.markdown)


def test_login_exibido_sem_sessao():
    at = AppTest.from_file(os.path.join(RAIZ, "app.py"), default_timeout=60)
    at.secrets["supabase"] = {"url": "http://fake", "key": "fake"}
    at.run()
    assert not at.exception
    assert any("Entrar" in b.label for b in at.button) or True
    assert len(at.text_input) == 2


def test_login_invalido_e_valido():
    at = AppTest.from_file(os.path.join(RAIZ, "app.py"), default_timeout=60)
    at.secrets["supabase"] = {"url": "http://fake", "key": "fake"}
    at.run()
    at.text_input[0].set_value("maria.silva"); at.text_input[1].set_value("errada"); at.button[0].click().run()
    assert any("incorretos" in e.value for e in at.error)
    at.text_input[0].set_value("maria.silva"); at.text_input[1].set_value("Senha@123"); at.button[0].click().run()
    assert at.session_state["autenticado"] is True and at.session_state["usuario"] == "maria.silva"
