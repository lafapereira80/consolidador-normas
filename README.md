# Autopilot Normativo — Consolidação de Normas e Atos

Streamlit + Supabase + Hub Multi-IA. Veja `RELATORIO_ANALISE_E_CONCORRENCIA.md` (análise, estudo com múltiplos usuários, implantação).

- `app.py` login + Identificar e Cruzar · `pages/` Extrair BSe, Consolidar, Histórico, Usuários (admin), Diagnóstico
- `ui_theme.py` design system · `menu_utils.py` navegação/presença · `concorrencia.py` estado compartilhado (travas, fila de IA, sessões)
- `repositorio.py` acesso ao banco thread-safe · `exportacao.py` HTML/PDF/DOCX · `supabase_migracao.sql` índices únicos e auditoria
- `tests/` testes, estudo de concorrência, E2E e servidor de demonstração com banco falso
