import hashlib
import os

PBKDF2_ITERACOES = 200_000

def gerar_hash_senha(senha: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt, PBKDF2_ITERACOES)
    return f"{salt.hex()}${dk.hex()}"

def verificar_senha(senha: str, hash_armazenado: str):
    """Retorna (ok, precisa_migrar). precisa_migrar=True quando o hash
    ainda está no formato antigo (SHA-256 sem salt) e deve ser regravado."""
    if not hash_armazenado:
        return False, False
    if '$' in hash_armazenado:
        try:
            salt_hex, hash_hex = hash_armazenado.split('$', 1)
            salt = bytes.fromhex(salt_hex)
            dk = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt, PBKDF2_ITERACOES)
            return dk.hex() == hash_hex, False
        except Exception:
            return False, False
    # Formato legado (SHA-256 puro, sem salt) - ainda validado, mas marcado para migração.
    return hashlib.sha256(senha.encode('utf-8')).hexdigest() == hash_armazenado, True
