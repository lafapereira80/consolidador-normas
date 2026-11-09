#!/bin/bash
# Sobe o app com banco falso em memória (usuários: admin / maria.silva / joao.souza, senha Senha@123)
cd "$(dirname "$0")/.." && PYTHONPATH=tests/demo_patch:tests streamlit run app.py --server.port ${1:-8601} --server.headless true
