# Autopilot Normativo — Análise completa, modernização e estudo de concorrência

Ambiente de teste: Streamlit 1.67, Python 3.12, Chromium real (Playwright), Supabase **simulado em memória** com latência de 2–10 ms por chamada.
Não foram usados o Supabase real nem as APIs de IA (sem credenciais): os resultados abaixo comprovam a lógica do app, não a infraestrutura de produção.

## 1. Resposta ao estudo: "funciona com dois usuários logados trabalhando?"

**Código original: parcialmente.** As sessões do Streamlit são isoladas (cada aba tem seu próprio `session_state`), então dois usuários
não veem a tela um do outro. Porém, o banco e os recursos compartilhados tinham condições de corrida reais, medidas abaixo.

| # | Cenário (2+ usuários ao mesmo tempo) | Original | Novo |
|---|---|---|---|
| E1 | Mesmo ato alterador processado por 2 usuários → pendência duplicada | **124 de 150** tentativas duplicaram | 0 |
| E2 | Mesmo ato lido por 2 usuários → leitura duplicada | **126 de 150** duplicaram | 0 |
| E3 | Dois usuários salvam consolidações diferentes da mesma norma | **100/100**: texto consolidado de um usuário perdido em silêncio e tabela de vínculos inconsistente com o texto | 0 perdas; a 2ª gravação é **bloqueada com aviso** listando o ato que faltaria (100/100) |
| E4 | 3 cliques em "Salvar" → memória de correções da IA | 6 linhas duplicadas | 1 |
| E5 | Tentativas de senha em sequência | 1000 aceitas (sem limite) | 5, depois bloqueio de 60 s |
| E6 | 6 usuários chamando a IA ao mesmo tempo (cota compartilhada do provedor) | pico de 6 chamadas simultâneas | pico limitado a 3 (configurável) |
| E7 | 200 threads martelando o registro compartilhado (40 000 operações) | — | 0 exceções, estado consistente |
| P1 | Custo de **uma interação** no Histórico com 8 versões salvas | 6,4 s (gera 4 PDFs por versão a cada clique) | 0,9 s |
| P2 | Idem com 15 versões | 11,1 s | 0,8 s |

Teste de navegador real (`tests/e2e_dois_usuarios.py`, 3 contextos isolados = 3 computadores): login simultâneo de 3 usuários,
páginas independentes, busca de um não afeta o outro, ação de Maria (concluir pendência) aparece para João ao atualizar,
presença mútua ("Equipe online agora"), João não vê "Usuários" e a URL direta é bloqueada, F5 mantém o login, logout de Maria
não derruba João e não volta logada após F5. **14/14 verificações verdadeiras, 0 erros de JavaScript.**
Testes automatizados: 10 de 10 passando (`pytest tests`), incluindo o fluxo Consolidar com dois usuários (aviso de trava, conflito, sobrescrita consciente, exportação sob demanda).

Limites que continuam valendo: (a) as travas e a fila de IA vivem na memória de **um** processo Streamlit; com várias réplicas use também
`supabase_migracao.sql` (índices únicos fazem o próprio banco recusar duplicatas); (b) reinício do servidor/hibernação do Streamlit Cloud
apaga a lista de logins persistentes (usuários só precisam entrar de novo); (c) a "trava" de norma é um aviso, não um bloqueio (decisão de usabilidade).

## 2. Achados da análise do código original e correção

| Sev. | Achado | Correção |
|---|---|---|
| Alta | `verificar e depois gravar` sem trava (duplicatas) | `repositorio.py`: seção crítica por chave + tratamento de violação de unicidade |
| Alta | Salvar = *upsert* "última gravação vence" (perda silenciosa) | `detectar_conflito()` compara alteradoras do banco com as da tela; bloqueia e oferece sobrescrever |
| Alta | Sessão sem identidade (`autenticado` apenas), qualquer usuário criava/apagava usuários e redefinia senhas | `usuario` e `papel` na sessão; página Usuários só para admin (usuário `admin` ou coluna `role`) |
| Alta | Logout não limpava `session_state` (resultados e chaves digitadas ficavam para o próximo usuário do mesmo navegador) | `encerrar_sessao()` limpa tudo, revoga token e apaga cookie |
| Alta | Sem proteção contra força bruta | 5 falhas / 5 min → bloqueio de 60 s |
| Alta | Texto vindo de PDF/IA injetado como HTML sem escape (`unsafe_allow_html`) | `escape()` em todos os campos; `sanitizar()` remove script/iframe/`on*=` na prévia |
| Média | **Bug**: Histórico nunca achava a norma base de uma pendência (consulta não trazia `tipo_documento`) | colunas corrigidas |
| Média | Histórico: `SELECT *` (texto integral até 100 mil caracteres) + 1 consulta por item + 4 PDFs WeasyPrint por versão **a cada clique** | 1 consulta leve por tabela, cache de 10 s, PDF só ao clicar |
| Média | BSe: um editor Quill e um PDF por ato, todos a cada interação, mesmo recolhidos | lista mestre-detalhe: 1 editor, PDF sob demanda |
| Média | Consolidar: 6 exportações (HTML/PDF/DOCX × 2) regeneradas a cada digitação | vistas Editar / Prévia / Exportar; geração só ao clicar, com aviso de arquivo desatualizado |
| Média | Cota de IA compartilhada sem controle | semáforo global (`[limites] ia_simultaneas`, padrão 3) |
| Média | Memória de correções duplicada a cada salvamento | deduplicada por hash |
| Baixa | `except Exception` antes de `except TypeError` (ramo inalcançável) no BSe | ordem corrigida |
| Baixa | 5 cópias de `init_supabase`; exportação duplicada e divergente (Histórico sem nota remissiva) | `db_utils.py`, `exportacao.py` únicos |
| Baixa | F5 desloga | cookie de sessão validado no servidor (8 h) |
| Info | Tabela `versoes_documentos` é lida, mas **nenhum código grava nela** (aba "Versões" sempre vazia) | mantida (consulta leve); decidir se será usada |
| Info | Hub de IA duplicado em `app.py` e `3_Consolidar_Norma.py`; lista de modelos do Diagnóstico difere da usada | não unificado para não arriscar regressão sem acesso às APIs; recomendável como próximo passo |
| Info | Chave Supabase no servidor sem RLS comprovada | `supabase_migracao.sql` (seção 6) |

## 3. Modernização visual

- **Design system** (`ui_theme.py`), gerado com a skill ui-ux-pro-max: EB Garamond (títulos jurídicos) + Atkinson Hyperlegible (interface), azul-marinho institucional, verde-esmeralda de acento, vermelho reservado à taxação.
- **Login**: painel dividido com aurora animada e demonstração viva (texto antigo é taxado em vermelho e a nova redação surge).
- **Barra superior** de vidro fosco com navegação, sua página ativa sublinhada, avatar/menu do usuário e **presença da equipe em tempo real**.
- **Hero** com aurora e grade, **linha de etapas** animada, **cartões de indicadores com contador animado**, cartões de resultado com borda semântica e selos pulsantes.
- Botões com brilho deslizante, abas em pílula, upload com realce, entrada escalonada dos blocos, progresso e *status* de processamento.
- **Prévia do documento em "papel"** (alterada/consolidada) antes de exportar; confirmações em diálogo; estados vazios ilustrados.
- Acessibilidade: foco visível, contraste ≥ 4,5:1, alvos ≥ 44 px, `prefers-reduced-motion` respeitado, ícones SVG (sem emoji).

## 4. Implantação

1. Copie os arquivos sobre o repositório (mantenha `brasao.png`). `requirements.txt` agora pede `streamlit>=1.48`.
2. Rode `supabase_migracao.sql` no SQL Editor (faça backup; a seção 0 apaga duplicatas existentes).
3. Opcional em *Secrets*: `[limites]` → `ia_simultaneas = 3`.
4. As fontes vêm do Google Fonts; sem internet, o sistema usa fontes do sistema (o layout continua íntegro).
5. Para rever tudo sem banco real: `bash tests/servidor_demo.sh` (usuários `admin`, `maria.silva`, `joao.souza`; senha `Senha@123`).
6. Testes: `pip install -r requirements-dev.txt && pytest tests && python tests/estudo_concorrencia.py`.

## 5. O que não foi verificado

Supabase real (RLS, latência, `count="exact"`), chamadas reais às IAs e PDFs reais de boletim/portarias; o cookie de sessão não é `HttpOnly`
(limitação do Streamlit) e vale só como chave opaca validada no servidor; a animação de contagem usa `@property` (navegadores antigos mostram o número final direto).
