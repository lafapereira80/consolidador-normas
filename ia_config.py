# ia_config.py - Fonte única dos provedores/modelos de IA (validado em 18/11/2026).
# Para trocar um modelo basta editar aqui; app.py, pages/3_Consolidar_Norma.py e
# pages/diagnostico.py leem deste módulo. A ordem da lista é a ordem de fallback.

PROVEDORES_IA = {
    "Google Gemini": {
        "motor": "gemini",
        # 3.7 e 3.5 foram descontinuados (redirecionam para 3.8 / 3.6).
        "modelos": ["gemini-3.8-flash", "gemini-3.5-flash-lite"],
        "secret": "GEMINI_API_KEY",
        "visao": True,
    },
    "Groq (GPT-OSS)": {
        "motor": "groq",
        # Llama 3.x e Qwen3-32B foram desativados na Groq; GPT-OSS é a linha de produção.
        "modelos": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
        "secret": "GROQ_API_KEY",
        "visao": False,  # GPT-OSS é somente texto
    },
    "OpenRouter (DeepSeek / Qwen)": {
        "motor": "openrouter",
        "modelos": ["deepseek/deepseek-v4.1-flash-1017", "qwen/qwen3.8-flash", "qwen/qwen3.7-plus"],
        "secret": "OPENROUTER_API_KEY",
        "visao": True,
    },
    "Mistral AI (Large / Small)": {
        "motor": "mistral",
        # open-mistral-nemo foi aposentado em 31/07/2026.
        "modelos": ["mistral-large-latest", "mistral-small-latest"],
        "secret": "MISTRAL_API_KEY",
        "visao": True,
    },
}

# Formato usado pela página de diagnóstico: nome -> (motor, secret, modelos)
DIAGNOSTICO = {
    nome.split(" (")[0]: (c["motor"], c["secret"], c["modelos"])
    for nome, c in PROVEDORES_IA.items()
}
