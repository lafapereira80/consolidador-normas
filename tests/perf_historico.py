"""Custo de UMA interação na página Histórico com N versões salvas: original x novo.
Uso: python tests/perf_historico.py <raiz_do_codigo> [N]"""
import os, sys, time, json
raiz = os.path.abspath(sys.argv[1]); N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [raiz, AQUI]
import supabase as _sb
from fake_supabase import FakeClient
from streamlit.testing.v1 import AppTest
cli = FakeClient(latencia=(0.002, 0.008))
disp = [{"tipo": "artigo", "texto_principal_alterada": f"<strike>Art. {i} velho</strike><br/><br/>Art. {i} novo " + "texto " * 60,
         "texto_principal_consolidada": f"Art. {i} novo " + "texto " * 60, "is_tabela": False, "nota_remissiva": ""} for i in range(60)]
estado = {"orgaos_emissores": "MPM", "titulo_portaria": "PORTARIA Nº 1", "ementa": "e", "preambulo": "p", "assinatura_nome": "N", "assinatura_cargo": "C", "dispositivos": disp}
cli.semear("portarias_base", [{"tipo_documento": "PORTARIA", "numero_documento": "1/X", "orgao_emissor": "X", "data_assinatura": "2025-01-01", "nome_padronizado": "PORTARIA Nº 1/X", "documento_consolidado_json": estado}])
cli.semear("versoes_documentos", [{"portaria_base_id": 1, "tipo_versao": "consolidada", "descricao": f"v{i}", "alteradoras_aplicadas": [], "estado_json": estado} for i in range(N)])
cli.semear("atos_importados", [{"nome_arquivo_original": f"a{i}.pdf", "status": "identificado", "numero_documento": str(i), "estrutura_json": {}, "texto_integra": "x" * 100000} for i in range(30)])
_sb.create_client = lambda *a, **k: cli
at = AppTest.from_file(os.path.join(raiz, "pages/1_Historico.py"), default_timeout=300)
at.secrets["supabase"] = {"url": "x", "key": "y"}
at.session_state["autenticado"] = True; at.session_state["usuario"] = "maria"; at.session_state["papel"] = "usuario"
t0 = time.time(); at.run(); dt = time.time() - t0
print(json.dumps({"versoes": N, "segundos_por_interacao": round(dt, 2), "excecoes": len(at.exception), "consultas_ao_banco": cli.chamadas}))
