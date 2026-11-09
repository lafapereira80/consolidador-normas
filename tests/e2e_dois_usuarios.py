"""E2E com navegador real: usuários em contextos isolados (como computadores diferentes) usando o sistema ao mesmo tempo.
Pré-requisito: tests/servidor_demo.sh rodando na porta 8601."""
import json
from pw import *

URL = "http://localhost:8601"
res = {}


def ir(pg, rotulo):
    pg.locator(f".st-key-topbar a:has-text('{rotulo}')").first.click()
    pg.wait_for_selector(".cn-hero", timeout=20000)
    pg.wait_for_timeout(1500)


with sync_playwright() as p:
    b, ctx_m = abrir(p)
    ctx_j = b.new_context(viewport={"width": 1440, "height": 900})
    ctx_a = b.new_context(viewport={"width": 1440, "height": 900})
    m, j, a = ctx_m.new_page(), ctx_j.new_page(), ctx_a.new_page()
    erros = []
    for pg, nome in ((m, "maria"), (j, "joao"), (a, "admin")):
        pg.on("pageerror", lambda e, n=nome: erros.append((n, str(e)[:200])))
    login(m, "maria.silva")
    login(j, "joao.souza")
    login(a, "admin")
    res["login_3_usuarios_simultaneos"] = all(pg.locator(".st-key-topbar").count() == 1 for pg in (m, j, a))
    res["usuario_exibido_maria"] = "maria.silva" in m.locator(".st-key-topbar").inner_text()
    res["usuario_exibido_joao"] = "joao.souza" in j.locator(".st-key-topbar").inner_text()

    ir(m, "Histórico")
    ir(j, "Consolidar")
    ir(a, "Diagnóstico")
    m.screenshot(path="/tmp/s_hist.png")
    j.screenshot(path="/tmp/s_cons.png")
    a.screenshot(path="/tmp/s_diag.png")
    res["paginas_independentes"] = ("Histórico e banco" in m.inner_text("body")) and ("Consolidação de normas" in j.inner_text("body")) and ("Diagnóstico do sistema" in a.inner_text("body"))

    m.wait_for_timeout(2500)
    ir(m, "Consolidar")
    ir(m, "Histórico")
    texto_m = m.locator(".cn-presenca").first.inner_text()
    res["presenca_maria_ve"] = {"texto": texto_m, "ve_joao": "joao.souza" in texto_m, "ve_admin": "admin" in texto_m}

    m.fill("input[placeholder^='Buscar']", "Portaria")
    m.keyboard.press("Enter")
    m.wait_for_timeout(1200)
    ir(j, "Histórico")
    res["estado_isolado_busca"] = j.input_value("input[placeholder^='Buscar']") == ""

    m.locator("[data-testid=stTab]:has-text('Pendências')").click()
    m.wait_for_timeout(600)
    antes = j.locator("[data-testid=stTab]:has-text('Pendências')").inner_text()
    m.fill("input[placeholder^='Buscar']", "")
    m.keyboard.press("Enter")
    m.wait_for_timeout(1000)
    m.locator("[data-testid=stExpander] summary:visible").first.click()
    m.wait_for_timeout(600)
    m.locator("label:visible:has-text('Concluído')").first.click()
    m.wait_for_timeout(1800)
    j.locator("button:has-text('Atualizar')").click()
    j.wait_for_timeout(2000)
    depois = j.locator("[data-testid=stTab]:has-text('Pendências')").inner_text()
    res["joao_ve_acao_da_maria"] = {"antes": antes, "depois": depois}

    res["joao_nao_ve_item_usuarios"] = j.locator(".st-key-topbar a:has-text('Usuários')").count() == 0
    j.goto(URL + "/usuarios")
    j.wait_for_timeout(4000)
    res["joao_url_direta_usuarios_bloqueada"] = "restrita a administradores" in j.inner_text("body").lower()
    ir(a, "Usuários")
    a.screenshot(path="/tmp/s_usr.png")
    res["admin_acessa_usuarios"] = "Gerenciamento de usuários" in a.inner_text("body")

    m.reload()
    m.wait_for_timeout(5000)
    res["f5_mantem_login_maria"] = m.locator(".st-key-topbar").count() == 1

    m.locator(".st-key-topbar button:has-text('maria.silva')").click()
    m.wait_for_timeout(500)
    m.locator("button:has-text('Sair do sistema')").click()
    m.wait_for_selector(".st-key-login_shell", timeout=15000)
    j.reload()
    j.wait_for_timeout(5000)
    res["joao_continua_logado_apos_logout_da_maria"] = j.locator(".st-key-login_shell").count() == 0 and ("restrita" in j.inner_text("body").lower() or j.locator(".st-key-topbar").count() == 1)
    m.reload()
    m.wait_for_timeout(5000)
    res["maria_nao_volta_logada_apos_logout_e_F5"] = m.locator(".st-key-login_shell").count() == 1
    res["erros_javascript"] = erros
    b.close()

print(json.dumps(res, ensure_ascii=False, indent=2))
json.dump(res, open("resultado_e2e.json", "w"), ensure_ascii=False, indent=2)
