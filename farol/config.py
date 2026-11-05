"""
Configuração persistente do Farol.

Tudo o que o usuário personaliza (pastas, tema, IA, Modo Dev...) fica em um
único arquivo JSON dentro da "pasta de dados" do Farol. A senha NUNCA é salva
em texto puro: guardamos apenas o hash PBKDF2 (veja security.py).

Pasta de dados padrão por sistema:
  - Windows: %APPDATA%\\Farol
  - macOS:   ~/Library/Application Support/Farol
  - Linux:   ~/.local/share/farol   (ou $XDG_DATA_HOME/farol)
  - Servidor/Docker: defina a variável de ambiente FAROL_HOME (ex.: /var/lib/farol)
"""
from __future__ import annotations

import copy
import json
import os
import platform
import tempfile
import threading
from pathlib import Path

APP_NAME = "Farol"
VERSION = "1.0.0"
LANGUAGES = ("pt-BR", "en", "es")

# Pastas que nunca vale a pena indexar (lixo de build, caches, lixeiras...).
# Comparação é feita pelo NOME da pasta, em qualquer nível.
DEFAULT_EXCLUDES = [
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    ".cache", ".Trash", ".Trashes", "$RECYCLE.BIN", "System Volume Information",
    ".npm", ".gradle", ".idea", ".vscode", ".tox", "dist-packages", "site-packages",
]

# Valores padrão. Ao carregar o config.json, ele é "mesclado" por cima disto,
# então campos novos em versões futuras aparecem automaticamente.
DEFAULTS: dict = {
    "version": 1,
    "mode": "desktop",            # "desktop" (só este PC) ou "server" (rede/Linux server)
    "host": "127.0.0.1",          # desktop escuta só localmente; servidor usa 0.0.0.0
    "port": 8765,
    "language": "pt-BR",
    "auth": {"hash": None, "salt": None, "iterations": 600_000},
    "session_hours": 12,
    "roots": [],                  # pastas indexadas: {id, path, name, color, network, readonly}
    "index": {
        "interval_minutes": 30,   # reindexação automática (0 = desligado)
        "max_content_mb": 25,     # arquivos maiores que isso só têm o NOME indexado
        "include_hidden": False,
        "exclude": DEFAULT_EXCLUDES,
    },
    "ui": {
        "theme": "dark",          # dark | light | auto
        "accent": "#5b8cff",
        "background": {"type": "preset", "value": "aurora"},  # preset | color | image
        "animated": True,
        "blur": 14,
        "font": "system",         # system | rounded | serif | mono
        "density": "comfortable", # comfortable | compact
        "tile_style": "glass",    # glass | solid | outline
        "logo_text": "Farol",
        "greeting": "",
        "show_clock": True,
    },
    "ai": {
        "enabled": False,
        "provider": "ollama",     # ollama | anthropic | openai | openai_compatible
        "model": "llama3.1",
        "base_url": "",
        "api_key": "",
        "context_files": 5,       # quantos arquivos locais enviar como contexto
    },
    # Modo Dev (terminal + SSH). DESLIGADO por padrão; só liga com a senha.
    "dev": {
        "enabled": False,
        "shell": "",              # vazio = shell padrão do sistema
        "ssh_hosts": [],          # {id, name, host, port, user, key_path} — sem senhas!
    },
    # Painel "Rede": dispositivos na LAN + sessões ativas no Farol.
    "network": {"scan_enabled": True},
}


def default_home() -> Path:
    """Descobre a pasta de dados adequada ao sistema operacional."""
    env = os.environ.get("FAROL_HOME")
    if env:
        return Path(env).expanduser()
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "farol"


def deep_merge(base: dict, extra: dict) -> dict:
    """Mescla 'extra' dentro de 'base' (dicionários recursivos; listas são substituídas)."""
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class Config:
    """Acesso thread-safe à configuração, com gravação atômica em disco."""

    def __init__(self, home: str | os.PathLike | None = None):
        self.home = Path(home).expanduser() if home else default_home()
        self.path = self.home / "config.json"
        self.lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                deep_merge(self.data, json.load(fh))

    # ---- atalhos -------------------------------------------------------
    def __getitem__(self, key):
        return self.data[key]

    @property
    def is_configured(self) -> bool:
        """True quando a instalação já definiu uma senha."""
        return bool(self.data["auth"].get("hash"))

    @property
    def db_path(self) -> Path:
        return self.home / "index.db"

    @property
    def wallpapers_dir(self) -> Path:
        return self.home / "wallpapers"

    @property
    def backups_dir(self) -> Path:
        return self.home / "backups"

    # ---- escrita --------------------------------------------------------
    def save(self) -> None:
        """Grava o JSON de forma atômica (arquivo temporário + rename).

        No Linux/macOS o arquivo fica com permissão 600 (só o dono lê),
        porque ele contém o hash da senha e, se configurada, a chave da IA.
        """
        with self.lock:
            self.home.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.home, prefix=".config-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)

    def update(self, patch: dict) -> None:
        """Aplica uma alteração parcial e salva."""
        with self.lock:
            deep_merge(self.data, patch)
            self.save()

    def public_ui(self) -> dict:
        """Subconjunto seguro mostrado na tela de login (sem dados sensíveis)."""
        ui = self.data["ui"]
        bg = ui["background"]
        # Papel de parede pessoal não aparece antes do login (pode ser uma foto privada).
        if bg.get("type") == "image":
            bg = {"type": "preset", "value": "aurora"}
        return {
            "theme": ui["theme"], "accent": ui["accent"], "background": bg,
            "animated": ui["animated"], "logo_text": ui["logo_text"], "font": ui["font"],
        }
