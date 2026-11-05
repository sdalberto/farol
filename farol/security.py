"""
Segurança do Farol.

- Senha: PBKDF2-HMAC-SHA256 com 600 mil iterações e salt aleatório (só stdlib).
- Sessões: token aleatório de 256 bits em cookie HttpOnly + SameSite=Strict.
- Força bruta: bloqueio progressivo por IP após tentativas erradas.
- Caminhos: todo arquivo pedido pela interface precisa estar DENTRO de uma pasta
  indexada (sem "../", sem links simbólicos apontando para fora).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

ITERATIONS = 600_000
MIN_PASSWORD = 8


# --------------------------------------------------------------------------
# Senhas
# --------------------------------------------------------------------------
def hash_password(password: str, salt: str | None = None, iterations: int = ITERATIONS) -> dict:
    """Gera o dicionário salvo em config['auth']."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return {"hash": digest.hex(), "salt": salt, "iterations": iterations}


def verify_password(password: str, auth: dict) -> bool:
    """Compara em tempo constante (evita ataques de tempo)."""
    if not auth or not auth.get("hash"):
        return False
    test = hash_password(password, auth["salt"], int(auth.get("iterations", ITERATIONS)))
    return hmac.compare_digest(test["hash"], auth["hash"])


def password_ok(password: str) -> bool:
    """Regra mínima: 8+ caracteres. Ajuste aqui se quiser regras mais rígidas."""
    return isinstance(password, str) and len(password) >= MIN_PASSWORD


# --------------------------------------------------------------------------
# Sessões (em memória: reiniciar o Farol desloga todo mundo — é proposital)
# --------------------------------------------------------------------------
class Sessions:
    def __init__(self, hours: float = 12):
        self.hours = hours
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, ip: str, agent: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._data[token] = {
                "id": secrets.token_hex(4),     # id curto exibido no painel Rede
                "ip": ip, "agent": agent[:200],
                "created": now, "last_seen": now,
                "expires": now + self.hours * 3600,
            }
        return token

    def valid(self, token: str | None, touch: bool = True) -> bool:
        if not token:
            return False
        with self._lock:
            s = self._data.get(token)
            if not s:
                return False
            if s["expires"] < time.time():
                self._data.pop(token, None)
                return False
            if touch:
                s["last_seen"] = time.time()
            return True

    def get(self, token: str | None) -> dict | None:
        with self._lock:
            return self._data.get(token or "")

    def revoke(self, token: str | None) -> None:
        with self._lock:
            self._data.pop(token or "", None)

    def revoke_id(self, sid: str) -> bool:
        """Derruba uma sessão pelo id curto (botão "desconectar" no painel Rede)."""
        with self._lock:
            for tok, s in list(self._data.items()):
                if s["id"] == sid:
                    self._data.pop(tok)
                    return True
        return False

    def revoke_all(self, keep: str | None = None) -> None:
        with self._lock:
            for tok in list(self._data):
                if tok != keep:
                    self._data.pop(tok)

    def list(self) -> list[dict]:
        """Lista pública das sessões (sem o token!)."""
        now = time.time()
        with self._lock:
            return [
                {k: v for k, v in s.items() if k != "expires"}
                for s in self._data.values() if s["expires"] > now
            ]


# --------------------------------------------------------------------------
# Limite de tentativas de login
# --------------------------------------------------------------------------
class RateLimiter:
    """5 erros seguidos => bloqueio de 30s, que dobra a cada novo erro (máx. 15 min)."""

    def __init__(self, max_fails: int = 5):
        self.max_fails = max_fails
        self._fails: dict[str, list] = {}   # ip -> [contagem, bloqueado_até]
        self._lock = threading.Lock()

    def locked_for(self, ip: str) -> int:
        with self._lock:
            entry = self._fails.get(ip)
            if not entry:
                return 0
            return max(0, int(entry[1] - time.time()))

    def fail(self, ip: str) -> None:
        with self._lock:
            entry = self._fails.setdefault(ip, [0, 0.0])
            entry[0] += 1
            if entry[0] >= self.max_fails:
                extra = entry[0] - self.max_fails
                entry[1] = time.time() + min(30 * (2 ** extra), 900)

    def success(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


# --------------------------------------------------------------------------
# Validação de caminhos
# --------------------------------------------------------------------------
def _norm(p: str) -> str:
    # normcase deixa minúsculo no Windows (sistema de arquivos não diferencia).
    return os.path.normcase(os.path.realpath(p))


def resolve_in_roots(path: str, roots: list[dict]) -> tuple[Path, dict] | None:
    """Retorna (caminho_real, pasta_raiz) se 'path' estiver dentro de alguma raiz.

    realpath() segue links simbólicos; por isso um link dentro da pasta que
    aponte para fora dela é REJEITADO aqui. Retorna None se não for permitido.
    """
    if not path or "\x00" in path:
        return None
    real = _norm(path)
    for root in roots:
        rroot = _norm(root["path"])
        try:
            if os.path.commonpath([real, rroot]) == rroot:
                return Path(os.path.realpath(path)), root
        except ValueError:      # discos diferentes no Windows (C: vs D:)
            continue
    return None
