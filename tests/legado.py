"""Carrega, SEM alterar, as funções de banco do código ORIGINAL (pasta orig/) para compará-las com o código novo."""
import ast
import json
import re
import os
from datetime import datetime
import types

RAIZ_ORIG = os.environ.get("RAIZ_ORIG", os.path.join(os.path.dirname(__file__), "original"))


def _extrair(arquivo, nomes):
    src = open(os.path.join(RAIZ_ORIG, arquivo), encoding="utf-8").read()
    arv = ast.parse(src)
    partes = [ast.get_source_segment(src, n) for n in arv.body if isinstance(n, ast.FunctionDef) and n.name in nomes]
    return "\n\n".join(partes)


class _StShim:
    erros = []

    def error(self, m, *a, **k):
        self.erros.append(m)

    toast = warning = info = success = error


def carregar(supabase):
    ns = {"supabase": supabase, "st": _StShim(), "json": json, "re": re, "datetime": datetime}
    exec(_extrair("app.py", {"converter_para_iso", "ja_existe_pendente", "salvar_pendencia", "ja_existe_leitura", "salvar_leitura"}), ns)
    exec(_extrair("pages/3_Consolidar_Norma.py", {"salvar_no_supabase"}), ns)
    return types.SimpleNamespace(**{k: v for k, v in ns.items() if callable(v) and not k.startswith("_")})
