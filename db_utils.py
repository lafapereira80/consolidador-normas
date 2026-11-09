# db_utils.py - UMA conexão Supabase e UM repositório para o app inteiro (antes: 5 cópias de init_supabase).
from typing import Optional

import streamlit as st
from supabase import create_client, Client

from repositorio import Repositorio


@st.cache_resource
def obter_supabase() -> Optional[Client]:
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except Exception:
        return None


@st.cache_resource
def obter_repositorio() -> Optional[Repositorio]:
    sb = obter_supabase()
    return Repositorio(sb) if sb else None


@st.cache_data(ttl=20, show_spinner=False)
def kpis_cache():
    """Contagens do painel, com cache de 20 s compartilhado por todos os usuários (1 consulta, não N)."""
    repo = obter_repositorio()
    return repo.contagens() if repo else {}
