"""
Linha de comando do Farol.

  python -m farol setup            # primeira configuração (define a SENHA)
  python -m farol setup --server   # modo servidor (Linux server / rede)
  python -m farol run              # inicia (abre o navegador no modo desktop)
  python -m farol passwd           # troca a senha
  python -m farol add-root PASTA   # adiciona uma pasta para indexar
  python -m farol index            # indexa agora (sem abrir a interface)
  python -m farol dev --off        # desliga o Modo Dev pela linha de comando

Para scripts/Docker sem interação:
  echo "minhaSenha" | python -m farol setup --server --password-stdin --root /dados
"""
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
import threading
import webbrowser

from .config import LANGUAGES, VERSION, Config
from .security import hash_password, password_ok

# Mensagens da linha de comando nos 3 idiomas.
MSG = {
    "pt-BR": {
        "welcome": "Bem-vindo ao Farol {v} — seu buscador offline.",
        "lang": "Idioma [1] Português  [2] English  [3] Español: ",
        "mode": "Modo [1] Desktop (só este computador)  [2] Servidor (acesso pela rede): ",
        "pass": "Defina a senha de acesso (mín. 8 caracteres): ",
        "pass2": "Repita a senha: ",
        "mismatch": "As senhas não conferem ou são curtas demais. Tente de novo.",
        "roots": "Pastas para indexar (separe por ';', Enter = sua pasta pessoal): ",
        "port": "Porta [{p}]: ",
        "skip": "  Ignorada (não existe): {p}",
        "done": "Pronto! Inicie com:  python -m farol run",
        "server_warn": "ATENÇÃO: no modo servidor use HTTPS (--cert/--key) ou um proxy reverso.",
        "not_configured": "Farol ainda não configurado. Rode:  python -m farol setup",
        "running": "Farol rodando em {url}  (Ctrl+C para sair)",
        "current": "Senha atual: ", "bad": "Senha incorreta.", "changed": "Senha alterada.",
        "indexing": "Indexando...", "indexed": "Concluído: {n} arquivos verificados, {i} indexados.",
        "dev": "Modo Dev: {s}",
    },
    "en": {
        "welcome": "Welcome to Farol {v} — your offline search engine.",
        "lang": "Language [1] Português  [2] English  [3] Español: ",
        "mode": "Mode [1] Desktop (this computer only)  [2] Server (network access): ",
        "pass": "Set the access password (min. 8 characters): ",
        "pass2": "Repeat the password: ",
        "mismatch": "Passwords don't match or are too short. Try again.",
        "roots": "Folders to index (separate with ';', Enter = your home folder): ",
        "port": "Port [{p}]: ",
        "skip": "  Skipped (does not exist): {p}",
        "done": "Done! Start it with:  python -m farol run",
        "server_warn": "WARNING: in server mode use HTTPS (--cert/--key) or a reverse proxy.",
        "not_configured": "Farol is not configured yet. Run:  python -m farol setup",
        "running": "Farol running at {url}  (Ctrl+C to quit)",
        "current": "Current password: ", "bad": "Wrong password.", "changed": "Password changed.",
        "indexing": "Indexing...", "indexed": "Done: {n} files checked, {i} indexed.",
        "dev": "Dev Mode: {s}",
    },
    "es": {
        "welcome": "Bienvenido a Farol {v} — tu buscador offline.",
        "lang": "Idioma [1] Português  [2] English  [3] Español: ",
        "mode": "Modo [1] Escritorio (solo este equipo)  [2] Servidor (acceso por la red): ",
        "pass": "Define la contraseña de acceso (mín. 8 caracteres): ",
        "pass2": "Repite la contraseña: ",
        "mismatch": "Las contraseñas no coinciden o son muy cortas. Inténtalo de nuevo.",
        "roots": "Carpetas para indexar (separa con ';', Enter = tu carpeta personal): ",
        "port": "Puerto [{p}]: ",
        "skip": "  Omitida (no existe): {p}",
        "done": "¡Listo! Inícialo con:  python -m farol run",
        "server_warn": "ATENCIÓN: en modo servidor usa HTTPS (--cert/--key) o un proxy inverso.",
        "not_configured": "Farol aún no está configurado. Ejecuta:  python -m farol setup",
        "running": "Farol en {url}  (Ctrl+C para salir)",
        "current": "Contraseña actual: ", "bad": "Contraseña incorrecta.", "changed": "Contraseña cambiada.",
        "indexing": "Indexando...", "indexed": "Listo: {n} archivos revisados, {i} indexados.",
        "dev": "Modo Dev: {s}",
    },
}


def t(cfg: Config, key: str, **kw) -> str:
    return MSG.get(cfg["language"], MSG["en"])[key].format(**kw)


def ask_password(cfg: Config, from_stdin: bool) -> str:
    if from_stdin:
        pw = sys.stdin.readline().rstrip("\r\n")
        if not password_ok(pw):
            sys.exit(t(cfg, "mismatch"))
        return pw
    while True:
        a = getpass.getpass(t(cfg, "pass"))
        b = getpass.getpass(t(cfg, "pass2"))
        if a == b and password_ok(a):
            return a
        print(t(cfg, "mismatch"))


def make_root(path: str) -> dict:
    real = os.path.realpath(os.path.expanduser(path))
    net = real.startswith("\\\\") or real.startswith(("/mnt/", "/media/", "/Volumes/", "/net/"))
    return {"id": secrets.token_hex(4), "path": real, "name": os.path.basename(real) or real,
            "color": "#5b8cff", "network": net, "readonly": False}


def cmd_setup(args) -> None:
    cfg = Config(args.home)
    interactive = not args.password_stdin and sys.stdin.isatty()
    if args.lang in LANGUAGES:
        cfg.data["language"] = args.lang
    elif interactive:
        choice = input(MSG["pt-BR"]["lang"]).strip()
        cfg.data["language"] = {"2": "en", "3": "es"}.get(choice, "pt-BR")
    print(t(cfg, "welcome", v=VERSION))

    server = args.server
    if not server and interactive and args.mode is None:
        server = input(t(cfg, "mode")).strip() == "2"
    cfg.data["mode"] = "server" if server else "desktop"
    cfg.data["host"] = args.host or ("0.0.0.0" if server else "127.0.0.1")

    if args.port:
        cfg.data["port"] = args.port
    elif interactive:
        p = input(t(cfg, "port", p=cfg["port"])).strip()
        if p.isdigit():
            cfg.data["port"] = int(p)

    cfg.data["auth"] = hash_password(ask_password(cfg, args.password_stdin))

    roots = list(args.root or [])
    if not roots and interactive:
        raw = input(t(cfg, "roots")).strip()
        roots = [r.strip() for r in raw.split(";") if r.strip()] or [os.path.expanduser("~")]
    existing = {r["path"] for r in cfg["roots"]}
    for r in roots:
        if os.path.isdir(os.path.expanduser(r)):
            root = make_root(r)
            if root["path"] not in existing:
                cfg.data["roots"].append(root)
        else:
            print(t(cfg, "skip", p=r))
    cfg.save()
    if server:
        print(t(cfg, "server_warn"))
    print(t(cfg, "done"))


def cmd_run(args) -> None:
    import uvicorn

    from .server import create_app

    cfg = Config(args.home)
    if not cfg.is_configured:
        sys.exit(t(cfg, "not_configured"))
    host = args.host or cfg["host"]
    port = args.port or cfg["port"]
    scheme = "https" if args.cert else "http"
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    url = f"{scheme}://{shown}:{port}"
    print(t(cfg, "running", url=url))
    if cfg["mode"] == "desktop" and not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning",
                ssl_certfile=args.cert, ssl_keyfile=args.key, proxy_headers=bool(args.proxy))


def cmd_passwd(args) -> None:
    from .security import verify_password
    cfg = Config(args.home)
    if cfg.is_configured and not args.password_stdin:
        if not verify_password(getpass.getpass(t(cfg, "current")), cfg["auth"]):
            sys.exit(t(cfg, "bad"))
    cfg.update({"auth": hash_password(ask_password(cfg, args.password_stdin))})
    print(t(cfg, "changed"))


def cmd_add_root(args) -> None:
    cfg = Config(args.home)
    if not os.path.isdir(os.path.expanduser(args.path)):
        sys.exit(t(cfg, "skip", p=args.path))
    root = make_root(args.path)
    if args.readonly:
        root["readonly"] = True
    cfg.update({"roots": cfg["roots"] + [root]})
    print(root["path"])


def cmd_index(args) -> None:
    from .indexer import Indexer
    cfg = Config(args.home)
    print(t(cfg, "indexing"))
    idx = Indexer(cfg)
    idx.run()
    print(t(cfg, "indexed", n=idx.status["scanned"], i=idx.status["indexed"]))


def cmd_dev(args) -> None:
    cfg = Config(args.home)
    dev = dict(cfg["dev"])
    if args.on or args.off:
        dev["enabled"] = bool(args.on)
        cfg.update({"dev": dev})
    print(t(cfg, "dev", s="ON" if cfg["dev"]["enabled"] else "OFF"))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="farol", description="Farol — offline search engine")
    ap.add_argument("--home", help="pasta de dados (padrão: automática ou $FAROL_HOME)")
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="configuração inicial / definir senha")
    s.add_argument("--server", action="store_true", help="modo servidor (escuta na rede)")
    s.add_argument("--mode", choices=["desktop", "server"])
    s.add_argument("--lang", choices=LANGUAGES)
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--root", action="append", help="pasta para indexar (pode repetir)")
    s.add_argument("--password-stdin", action="store_true", help="lê a senha da entrada padrão")
    s.set_defaults(fn=cmd_setup)

    r = sub.add_parser("run", help="inicia o Farol")
    r.add_argument("--host")
    r.add_argument("--port", type=int)
    r.add_argument("--no-browser", action="store_true")
    r.add_argument("--cert", help="certificado TLS (HTTPS)")
    r.add_argument("--key", help="chave privada TLS")
    r.add_argument("--proxy", action="store_true", help="confiar em X-Forwarded-* (atrás de nginx/caddy)")
    r.set_defaults(fn=cmd_run)

    p = sub.add_parser("passwd", help="trocar senha")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(fn=cmd_passwd)

    a = sub.add_parser("add-root", help="adicionar pasta")
    a.add_argument("path")
    a.add_argument("--readonly", action="store_true")
    a.set_defaults(fn=cmd_add_root)

    sub.add_parser("index", help="indexar agora").set_defaults(fn=cmd_index)

    d = sub.add_parser("dev", help="ligar/desligar Modo Dev")
    g = d.add_mutually_exclusive_group()
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")
    d.set_defaults(fn=cmd_dev)

    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        # Sem subcomando: configura se necessário, senão inicia.
        cfg = Config(args.home)
        args = ap.parse_args((["--home", args.home] if args.home else []) + (["run"] if cfg.is_configured else ["setup"]))
    args.fn(args)


if __name__ == "__main__":
    main()
