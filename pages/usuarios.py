# pages/usuarios.py - Gerenciamento de usuários (somente administradores)
import os
import re
import sys
import time
from html import escape

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth_utils import gerar_hash_senha
from menu_utils import configurar_pagina, exigir_login, renderizar_cabecalho, renderizar_menu
from db_utils import obter_supabase
import concorrencia as conc
import ui_theme as ui

configurar_pagina("Usuários", "👥")
exigir_login("Você precisa fazer login para acessar o painel de usuários.", somente_admin=True)
renderizar_menu("usuarios")
renderizar_cabecalho("Gerenciamento de usuários", "Crie contas, redefina senhas e acompanhe quem está online. Somente administradores veem esta página.",
                     etiqueta="Administração", icone_nome="users")

supabase = obter_supabase()
if not supabase:
    st.error("Não foi possível conectar ao Supabase.", icon=":material/cloud_off:")
    st.stop()

MIN_SENHA = 8
RE_LOGIN = re.compile(r"^[A-Za-z0-9._-]{3,40}$")


def carregar():
    try:
        res = supabase.table("usuarios").select("id, username, created_at").order("id").execute()
        return res.data or []
    except Exception:
        try:  # esquema sem created_at
            return supabase.table("usuarios").select("id, username").order("id").execute().data or []
        except Exception as e:
            st.error(f"Erro ao carregar usuários: {e}")
            return []


@st.dialog("Excluir usuário")
def confirmar_exclusao(uid, nome):
    st.markdown(f"Excluir **{escape(nome)}** permanentemente? Todos os acessos dessa conta serão encerrados.", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("Cancelar", use_container_width=True):
        st.rerun()
    if c2.button("Excluir", type="primary", use_container_width=True, icon=":material/delete:"):
        try:
            supabase.table("usuarios").delete().eq("id", uid).execute()
            conc.registro().revogar_usuario(nome)
            conc.auditar("excluir_usuario", nome)
            st.session_state["_msg_usr"] = f"Usuário '{nome}' excluído."
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao excluir: {e}")


usuarios = carregar()
online = {p["usuario"].lower() for p in conc.registro().online() if p.get("usuario")}
ui.kpis([
    ("Usuários cadastrados", len(usuarios), "users", "info"),
    ("Online agora", len(conc.registro().usuarios_online()), "activity", "ok"),
    ("Sessões ativas", len(conc.registro().online()), "user", ""),
])
if msg := st.session_state.pop("_msg_usr", None):
    st.toast(msg, icon=":material/check_circle:")

tab_lista, tab_novo, tab_ativ = st.tabs([":material/list: Usuários", ":material/person_add: Novo usuário", ":material/history: Atividade e sessões"])

with tab_lista:
    if not usuarios:
        ui.vazio("Nenhum usuário encontrado", "Cadastre o primeiro na aba Novo usuário.", "users")
    for usr in usuarios:
        uid, nome = usr["id"], usr["username"]
        criado = str(usr.get("created_at") or "")[:10] or "—"
        eh_admin_alvo = nome.lower() == "admin"
        eu = nome.lower() == conc.usuario_atual().lower()
        selos = (ui.badge("Online", "ok", pulso=True) if nome.lower() in online else ui.badge("Offline")) \
            + (" " + ui.badge("Administrador", "info") if eh_admin_alvo else "") + (" " + ui.badge("Você", "warn") if eu else "")
        with st.container(border=True):
            c_info, c_senha, c_del = st.columns([3, 2.2, 1.2], vertical_alignment="center")
            c_info.markdown(f'<div class="cn-usr">{ui.avatar(nome)}<div><b style="font-size:1.05rem">{escape(nome)}</b> &nbsp;{selos}<br>'
                            f'<span style="color:#475569;font-size:.82rem">Criado em {escape(criado)}</span></div></div>', unsafe_allow_html=True)
            with c_senha:
                with st.popover("Redefinir senha", icon=":material/key:", use_container_width=True):
                    ns = st.text_input("Nova senha", type="password", key=f"ns_{uid}")
                    ui.barra_forca(ns)
                    if st.button("Atualizar senha", key=f"upd_{uid}", type="primary", use_container_width=True):
                        if len(ns) < MIN_SENHA:
                            st.warning(f"A senha precisa ter ao menos {MIN_SENHA} caracteres.")
                        else:
                            try:
                                supabase.table("usuarios").update({"password_hash": gerar_hash_senha(ns)}).eq("id", uid).execute()
                                conc.registro().revogar_usuario(nome)
                                conc.auditar("redefinir_senha", nome)
                                st.success("Senha atualizada. Logins persistentes dessa conta foram encerrados.")
                            except Exception as e:
                                st.error(f"Erro ao atualizar: {e}")
            with c_del:
                if eh_admin_alvo or eu:
                    st.caption("Protegido" if eh_admin_alvo else "Sua conta")
                elif st.button("Excluir", key=f"del_usr_{uid}", icon=":material/delete:", use_container_width=True):
                    confirmar_exclusao(uid, nome)

with tab_novo:
    with st.container(border=True):
        novo_login = st.text_input("Nome de usuário (login)", placeholder="ex.: joao.silva", key="novo_login", help="3 a 40 caracteres: letras, números, ponto, hífen e sublinhado.")
        nova_senha = st.text_input("Senha de acesso", type="password", placeholder=f"Mínimo de {MIN_SENHA} caracteres", key="nova_senha_in")
        ui.barra_forca(nova_senha)
        if st.button("Cadastrar usuário", type="primary", use_container_width=True, icon=":material/person_add:"):
            login = (novo_login or "").strip()
            if not RE_LOGIN.match(login):
                st.warning("Login inválido: use 3 a 40 caracteres (letras, números, ponto, hífen ou sublinhado).")
            elif len(nova_senha) < MIN_SENHA:
                st.warning(f"A senha precisa ter ao menos {MIN_SENHA} caracteres.")
            elif login.lower() in {u["username"].lower() for u in carregar()}:
                st.error(f"O nome de usuário '{login}' já está em uso.")
            else:
                try:
                    supabase.table("usuarios").insert({"username": login, "password_hash": gerar_hash_senha(nova_senha)}).execute()
                    conc.auditar("criar_usuario", login)
                    st.success(f"Usuário '{login}' criado. Ele já pode acessar o sistema.")
                    time.sleep(1.2)
                    st.rerun()
                except Exception as e:
                    m = str(e).lower()
                    st.error(f"O nome de usuário '{login}' já está em uso." if ("duplicate" in m or "unique" in m) else f"Erro interno: {e}")

with tab_ativ:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Sessões online")
        sess = conc.registro().online()
        if not sess:
            st.caption("Nenhuma sessão ativa.")
        for p in sess:
            from menu_utils import ROTULOS
            st.markdown(f'<div class="cn-chip" style="margin:.2rem 0">{ui.avatar(p.get("usuario") or "?")}<span class="cn-dot"></span>'
                        f'<span><b>{escape(p.get("usuario") or "?")}</b> · {escape(ROTULOS.get(p.get("pagina"), p.get("pagina") or ""))}</span></div>', unsafe_allow_html=True)
    with c2:
        st.markdown("##### Trilha de atividade")
        evs = list(conc.registro().auditoria)[:40]
        if not evs:
            st.caption("Sem eventos desde o último reinício do servidor.")
        for ev in evs:
            q = time.strftime("%d/%m %H:%M:%S", time.localtime(ev["quando"]))
            st.markdown(f'<span style="font-size:.86rem"><b>{escape(ev["usuario"])}</b> · {escape(ev["acao"].replace("_", " "))} '
                        f'<span style="color:#64748B">{escape(ev["detalhe"])} · {q}</span></span>', unsafe_allow_html=True)
