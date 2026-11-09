"""Supabase falso, em memória, com latência de rede simulada, para testes de concorrência e demonstração.

Cada chamada .execute() é atômica (como uma requisição HTTP isolada ao PostgREST); sequências de chamadas NÃO são
atômicas - exatamente como no banco real - e a latência artificial alarga a janela das condições de corrida.
"""
import copy
import itertools
import random
import re
import threading
import time
from datetime import datetime, timezone


class _Res:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class FakeClient:
    def __init__(self, latencia=(0.0, 0.0), unicos=None):
        self.tabelas = {}
        self.ids = {}
        self.lock = threading.RLock()
        self.latencia = latencia
        self.unicos = unicos or {}      # {"tabela": [("col1", "col2"), ...]}
        self.chamadas = 0

    def table(self, nome):
        return _Query(self, nome)

    # utilidades de teste
    def linhas(self, nome):
        with self.lock:
            return copy.deepcopy(self.tabelas.get(nome, []))

    def semear(self, nome, linhas):
        with self.lock:
            for l in linhas:
                self._inserir(nome, dict(l))

    def _inserir(self, nome, linha):
        self.tabelas.setdefault(nome, [])
        self.ids.setdefault(nome, itertools.count(1))
        linha.setdefault("id", next(self.ids[nome]))
        agora = datetime.now(timezone.utc).isoformat()
        linha.setdefault("created_at", agora)
        linha.setdefault("criado_em", agora)
        for cols in self.unicos.get(nome, []):
            chave = tuple(linha.get(c) for c in cols)
            for r in self.tabelas[nome]:
                if tuple(r.get(c) for c in cols) == chave and all(v is not None for v in chave):
                    raise Exception(f"duplicate key value violates unique constraint ({', '.join(cols)}) 23505")
        self.tabelas[nome].append(linha)
        return linha


class _Query:
    def __init__(self, cli, nome):
        self.cli, self.nome = cli, nome
        self.op, self.payload, self.filtros = "select", None, []
        self.cols, self.contar, self.ordem, self.lim, self.on_conflict = "*", None, None, None, None

    def select(self, cols="*", count=None):
        self.op, self.cols, self.contar = "select", cols, count
        return self

    def insert(self, d):
        self.op, self.payload = "insert", d
        return self

    def upsert(self, d, on_conflict=None):
        self.op, self.payload, self.on_conflict = "upsert", d, on_conflict
        return self

    def update(self, d):
        self.op, self.payload = "update", d
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, c, v):
        self.filtros.append(("eq", c, v)); return self

    def ilike(self, c, v):
        self.filtros.append(("ilike", c, v)); return self

    def is_(self, c, v):
        self.filtros.append(("is", c, v)); return self

    def order(self, c, desc=False):
        self.ordem = (c, desc); return self

    def limit(self, n):
        self.lim = n; return self

    def _ok(self, r):
        for op, c, v in self.filtros:
            x = r.get(c)
            if op == "eq" and x != v:
                return False
            if op == "ilike":
                pad = "^" + re.escape(str(v)).replace("%", ".*") + "$"
                if x is None or not re.match(pad, str(x), re.IGNORECASE | re.DOTALL):
                    return False
            if op == "is" and not (x is None if v == "null" else x == v):
                return False
        return True

    def execute(self):
        lo, hi = self.cli.latencia
        if hi:
            time.sleep(random.uniform(lo, hi))
        cli = self.cli
        with cli.lock:
            cli.chamadas += 1
            tab = cli.tabelas.setdefault(self.nome, [])
            if self.op == "select":
                rows = [r for r in tab if self._ok(r)]
                total = len(rows)
                if self.ordem:
                    c, desc = self.ordem
                    rows.sort(key=lambda r: (r.get(c) is None, r.get(c)), reverse=desc)
                if self.lim is not None:
                    rows = rows[: self.lim]
                rows = copy.deepcopy(rows)
                m = re.search(r"(\w+)\((.*?)\)", self.cols or "")
                if m and m.group(1) == "portarias_base":
                    for r in rows:
                        pb = next((p for p in cli.tabelas.get("portarias_base", []) if p["id"] == r.get("portaria_base_id")), None)
                        r["portarias_base"] = {"nome_padronizado": pb["nome_padronizado"]} if pb else None
                elif self.cols not in (None, "*") and "(" not in self.cols:
                    cols = [c.strip() for c in self.cols.split(",")]
                    rows = [{c: r.get(c) for c in cols} for r in rows]
                return _Res(rows, total if self.contar else None)
            if self.op == "insert":
                return _Res([copy.deepcopy(cli._inserir(self.nome, copy.deepcopy(self.payload)))])
            if self.op == "upsert":
                chave = self.on_conflict
                for r in tab:
                    if chave and r.get(chave) == self.payload.get(chave):
                        r.update(copy.deepcopy(self.payload))
                        return _Res([copy.deepcopy(r)])
                return _Res([copy.deepcopy(cli._inserir(self.nome, copy.deepcopy(self.payload)))])
            if self.op == "update":
                alvo = [r for r in tab if self._ok(r)]
                for r in alvo:
                    r.update(copy.deepcopy(self.payload))
                return _Res(copy.deepcopy(alvo))
            if self.op == "delete":
                alvo = [r for r in tab if self._ok(r)]
                cli.tabelas[self.nome] = [r for r in tab if r not in alvo]
                return _Res(copy.deepcopy(alvo))
        raise RuntimeError("operação não suportada")
