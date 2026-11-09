"""Modo demonstração/testes: troca o Supabase por um banco em memória semeado. Uso:
   PYTHONPATH=tests/demo_patch:tests streamlit run app.py   (com secrets.toml contendo [supabase] url/key fictícios)
Nunca é carregado em produção (só entra se PYTHONPATH apontar para esta pasta)."""
import os, sys
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path[:0] = [RAIZ, os.path.join(RAIZ, "tests")]
try:
    import supabase as _sb
    from fake_supabase import FakeClient
    from auth_utils import gerar_hash_senha
    _cli = FakeClient(latencia=(0.0, 0.01))
    h = gerar_hash_senha("Senha@123")
    _cli.semear("usuarios", [{"username": "admin", "password_hash": h}, {"username": "maria.silva", "password_hash": h}, {"username": "joao.souza", "password_hash": h}])
    base = {"tipo_documento": "PORTARIA", "numero_documento": "5/PGJM", "orgao_emissor": "PGJM", "data_assinatura": "2025-01-17",
            "nome_padronizado": "PORTARIA Nº 5/PGJM, de 17 de janeiro de 2025"}
    _cli.semear("portarias_base", [base, {"tipo_documento": "RESOLUÇÃO", "numero_documento": "12/CSMPM", "orgao_emissor": "CSMPM", "data_assinatura": "2024-08-02",
                                          "nome_padronizado": "RESOLUÇÃO Nº 12/CSMPM, de 2 de agosto de 2024"}])
    _cli.semear("portarias_alteradoras", [{"portaria_base_id": 1, "tipo_documento": "PORTARIA", "numero_documento": "30/PGJM", "orgao_emissor": "PGJM",
                                           "data_assinatura": "2026-05-20", "nome_padronizado": "PORTARIA Nº 30/PGJM, de 20 de maio de 2026"}])
    _cli.semear("atos_importados", [
        {"nome_arquivo_original": "portaria_77.pdf", "tipo_documento": "PORTARIA", "numero_documento": "77/PGJM", "status": "pendente",
         "ato_base_referenciado_tipo": "PORTARIA", "ato_base_referenciado_numero": "5/PGJM", "estrutura_json": {"nome_padronizado": "PORTARIA Nº 77/PGJM, de 3 de março de 2026"}, "texto_integra": "x"},
        {"nome_arquivo_original": "decreto_9.pdf", "tipo_documento": "DECRETO", "numero_documento": "9/2025", "status": "identificado",
         "estrutura_json": {"nome_padronizado": "DECRETO Nº 9/2025, de 10 de junho de 2025", "tipo_documento": "DECRETO", "numero_documento": "9/2025", "data_assinatura": "2025-06-10"}, "texto_integra": "x"}])
    _cli.semear("memoria_de_correcoes", [{"texto_ia": "(Alterada pelo Art 3)", "texto_corrigido": "(Alterada pelo Art. 3º da PORTARIA Nº 30/PGJM)"}])
    _sb.create_client = lambda *a, **k: _cli
except Exception as e:  # pragma: no cover
    print("demo_patch falhou:", e)
