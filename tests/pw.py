import sys
from playwright.sync_api import sync_playwright
CHROME="/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"
def abrir(p, w=1440, h=900):
    b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": w, "height": h})
    return b, ctx
def login(pg, user, pwd="Senha@123", url="http://localhost:8601"):
    pg.goto(url); pg.wait_for_selector("input[aria-label='Usuário']", timeout=20000)
    pg.fill("input[aria-label='Usuário']", user); pg.fill("input[aria-label='Senha']", pwd); pg.keyboard.press("Enter")
    pg.wait_for_selector(".st-key-topbar", timeout=20000); pg.wait_for_timeout(1800)
