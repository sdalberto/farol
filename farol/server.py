"""
Servidor web do Farol (FastAPI).

A interface é um site estático (pasta static/) que conversa com esta API.
Tudo roda localmente: nenhuma requisição sai da máquina, exceto quando o
usuário liga um provedor de IA na nuvem.

Camadas de segurança aplicadas aqui:
  - Toda rota /api exige sessão válida (exceto login e status).
  - Rotas que alteram algo exigem o cabeçalho X-Farol: 1 (proteção CSRF:
    outro site não consegue mandar esse cabeçalho sem permissão CORS).
  - Cabeçalhos CSP / nosniff / frame-options em todas as respostas.
  - Arquivos do usuário são servidos com CSP "sandbox" e HTML/SVG viram
    texto puro — um .html malicioso na sua pasta não executa script no Farol.
  - O WebSocket do terminal confere a sessão E a origem (Origin).
"""
from __future__ import annotations

import asyncio
import codecs
import json
import mimetypes
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import ai as ai_mod
from . import devterm, netscan
from .config import LANGUAGES, VERSION, Config
from .extractors import EDITABLE, can_extract, decode_bytes, ext_of, extract_text, kind_of
from .indexer import Indexer
from .security import (RateLimiter, Sessions, hash_password, password_ok, resolve_in_roots,
                       verify_password)

STATIC_DIR = Path(__file__).parent / "static"
COOKIE = "farol_session"

CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'self'; "
       "connect-src 'self' ws: wss:; object-src 'none'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'self'")

# Tipos que poderiam executar script no navegador: sempre servidos como texto.
DANGEROUS_EXT = {"html", "htm", "xhtml", "svg", "xml", "js", "mjs", "shtml", "xht"}
EXTRA_MIME = {"mkv": "video/x-matroska", "webm": "video/webm", "flac": "audio/flac",
              "opus": "audio/ogg", "m4a": "audio/mp4", "ogv": "video/ogg", "oga": "audio/ogg",
              "mov": "video/quicktime", "avif": "image/avif", "webp": "image/webp", "md": "text/plain"}

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_EDIT_BYTES = 3 * 1024 * 1024


def err(code: str, status: int = 400):
    """Erros sempre no formato {"error": "codigo"}; a interface traduz o código."""
    raise HTTPException(status_code=status, detail=code)


def create_app(cfg: Config, start_indexer: bool = True) -> FastAPI:
    app = FastAPI(title="Farol", docs_url=None, redoc_url=None, openapi_url=None)
    idx = Indexer(cfg)
    sessions = Sessions(cfg["session_hours"])
    limiter = RateLimiter()
    app.state.cfg, app.state.idx, app.state.sessions = cfg, idx, sessions
    net_cache: dict = {}

    # ------------------------------------------------------------------
    # Middleware: CSRF + cabeçalhos de segurança
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            if request.headers.get("x-farol") != "1":
                return JSONResponse({"error": "csrf"}, status_code=403)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------
    def client_ip(request) -> str:
        return request.client.host if request.client else "?"

    def require(request: Request) -> str:
        tok = request.cookies.get(COOKIE)
        if not sessions.valid(tok):
            err("auth", 401)
        return tok

    def resolve(path: str):
        r = resolve_in_roots(path, cfg["roots"])
        if not r:
            err("forbidden_path", 403)
        if not r[0].exists():
            err("not_found", 404)
        return r

    def settings_view() -> dict:
        """Configurações enviadas à interface — a chave da IA nunca sai do servidor."""
        ai = dict(cfg["ai"])
        ai["has_key"] = bool(ai.pop("api_key", ""))
        return {"language": cfg["language"], "mode": cfg["mode"], "ui": cfg["ui"], "ai": ai,
                "index": {k: cfg["index"][k] for k in ("interval_minutes", "max_content_mb", "include_hidden")},
                "session_hours": cfg["session_hours"], "roots": cfg["roots"],
                "dev": {"enabled": cfg["dev"]["enabled"] and not devterm.DISABLED_BY_ENV,
                        "ssh_hosts": cfg["dev"]["ssh_hosts"], "shell": cfg["dev"]["shell"]},
                "network": cfg["network"], "version": VERSION}

    def file_item(p: Path) -> dict:
        st = p.stat()
        ext = ext_of(p.name)
        return {"path": str(p), "name": p.name, "ext": ext, "kind": kind_of(ext),
                "size": st.st_size, "mtime": st.st_mtime, "is_dir": p.is_dir()}

    # ------------------------------------------------------------------
    # Sessão / login
    # ------------------------------------------------------------------
    @app.get("/api/session")
    def session_info(request: Request):
        return {"authenticated": sessions.valid(request.cookies.get(COOKIE), touch=False),
                "configured": cfg.is_configured, "language": cfg["language"],
                "ui": cfg.public_ui(), "version": VERSION}

    @app.post("/api/login")
    async def login(request: Request):
        ip = client_ip(request)
        wait = limiter.locked_for(ip)
        if wait:
            return JSONResponse({"error": "locked", "retry": wait}, status_code=429)
        body = await request.json()
        await asyncio.sleep(0.3)   # atraso fixo: atrapalha força bruta
        if not verify_password(str(body.get("password", "")), cfg["auth"]):
            limiter.fail(ip)
            err("bad_password", 401)
        limiter.success(ip)
        tok = sessions.create(ip, request.headers.get("user-agent", ""))
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, tok, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", max_age=int(cfg["session_hours"] * 3600))
        return resp

    @app.post("/api/logout")
    def logout(request: Request):
        sessions.revoke(request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    @app.post("/api/password")
    async def change_password(request: Request):
        tok = require(request)
        body = await request.json()
        if not verify_password(str(body.get("current", "")), cfg["auth"]):
            err("bad_password", 401)
        new = str(body.get("new", ""))
        if not password_ok(new):
            err("weak_password")
        cfg.update({"auth": hash_password(new)})
        sessions.revoke_all(keep=tok)   # derruba as outras sessões
        return {"ok": True}

    # ------------------------------------------------------------------
    # Dados iniciais da interface
    # ------------------------------------------------------------------
    @app.get("/api/bootstrap")
    def bootstrap(request: Request):
        require(request)
        return {"settings": settings_view(), "favorites": idx.favorites(), "recent": idx.recent(),
                "stats": idx.stats(), "index": idx.status, "dev": devterm.platform_info()}

    # ------------------------------------------------------------------
    # Busca e arquivos
    # ------------------------------------------------------------------
    @app.get("/api/search")
    def search(request: Request, q: str = "", kind: str = "all", limit: int = 30, offset: int = 0):
        require(request)
        return idx.search(q, kind, max(1, min(limit, 200)), max(0, offset))

    @app.get("/api/file")
    def get_file(request: Request, path: str, dl: int = 0):
        require(request)
        p, _root = resolve(path)
        if p.is_dir():
            err("is_dir")
        ext = ext_of(p.name)
        mime = EXTRA_MIME.get(ext) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        headers = {"Content-Disposition":
                   f"{'attachment' if dl else 'inline'}; filename*=UTF-8''{quote(p.name)}"}
        if ext in DANGEROUS_EXT and not dl:
            mime = "text/plain; charset=utf-8"
        if ext != "pdf":
            # Sandbox: mesmo que o navegador tente interpretar, nada executa.
            headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'"
        else:
            headers["Content-Security-Policy"] = "default-src 'none'; object-src 'self'; plugin-types application/pdf"
        idx.touch_recent(str(p))
        return range_response(p, request, mime, headers)

    @app.get("/api/preview")
    def preview(request: Request, path: str):
        """Texto do arquivo: bruto (editável) para código/texto, extraído para documentos."""
        require(request)
        p, root = resolve(path)
        ext = ext_of(p.name)
        size = p.stat().st_size
        editable = ext in EDITABLE and size <= MAX_EDIT_BYTES
        if editable:
            text, enc = decode_bytes(p.read_bytes())
        elif can_extract(ext):
            text, enc = extract_text(str(p), ext), "utf-8"
        else:
            err("no_preview")
        idx.touch_recent(str(p))
        return {"text": text, "encoding": enc, "ext": ext, "kind": kind_of(ext),
                "editable": editable and not root.get("readonly"), "readonly_root": bool(root.get("readonly"))}

    @app.post("/api/save")
    async def save(request: Request):
        """Salva um arquivo de texto/código. Faz backup da versão anterior na pasta de dados."""
        require(request)
        body = await request.json()
        p, root = resolve(str(body.get("path", "")))
        if root.get("readonly"):
            err("readonly")
        if ext_of(p.name) not in EDITABLE:
            err("not_editable")
        content = str(body.get("content", ""))
        enc = body.get("encoding") if body.get("encoding") in ("utf-8", "cp1252", "latin-1") else "utf-8"
        data = content.encode(enc, errors="replace")
        if len(data) > MAX_EDIT_BYTES:
            err("too_large")
        cfg.backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(p, cfg.backups_dir / f"{stamp}-{secrets.token_hex(3)}-{p.name}")
        tmp = p.with_name(f".{p.name}.farol-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)          # escrita atômica
        idx.reindex_file(str(p), root["path"])
        return {"ok": True}

    @app.get("/api/browse")
    def browse(request: Request, path: str = ""):
        """Lista uma pasta (navegação estilo explorador de arquivos)."""
        require(request)
        if not path:
            return {"path": "", "parent": None, "items": [
                {**r, "is_dir": True, "online": os.path.isdir(r["path"])} for r in cfg["roots"]]}
        p, root = resolve(path)
        if not p.is_dir():
            err("not_dir")
        items = []
        hidden = cfg["index"].get("include_hidden")
        try:
            entries = sorted(os.scandir(p), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            err("permission", 403)
        for e in entries[:2000]:
            if (not hidden and e.name.startswith(".")) or e.is_symlink():
                continue
            try:
                items.append(file_item(Path(e.path)))
            except OSError:
                continue
        is_root = os.path.normcase(str(p)) == os.path.normcase(os.path.realpath(root["path"]))
        return {"path": str(p), "root": root, "parent": "" if is_root else str(p.parent), "items": items}

    # ------------------------------------------------------------------
    # Favoritos
    # ------------------------------------------------------------------
    @app.get("/api/favorites")
    def favorites(request: Request):
        require(request)
        return idx.favorites()

    @app.post("/api/favorites")
    async def add_favorite(request: Request):
        require(request)
        body = await request.json()
        p, _ = resolve(str(body.get("path", "")))
        label = str(body.get("label") or p.name)[:80]
        idx.add_favorite(str(p), label, "folder" if p.is_dir() else kind_of(ext_of(p.name)))
        return idx.favorites()

    @app.delete("/api/favorites")
    def del_favorite(request: Request, path: str):
        require(request)
        idx.remove_favorite(path)
        return idx.favorites()

    # ------------------------------------------------------------------
    # Pastas indexadas (locais e de rede)
    # ------------------------------------------------------------------
    @app.post("/api/roots")
    async def add_root(request: Request):
        require(request)
        body = await request.json()
        raw = str(body.get("path", "")).strip()
        if not raw:
            err("path_required")
        real = os.path.realpath(os.path.expanduser(raw))
        if not os.path.isdir(real):
            err("not_dir")
        if any(os.path.normcase(r["path"]) == os.path.normcase(real) for r in cfg["roots"]):
            err("duplicate")
        color = body.get("color") if COLOR_RE.match(str(body.get("color", ""))) else "#5b8cff"
        root = {"id": secrets.token_hex(4), "path": real,
                "name": str(body.get("name") or os.path.basename(real) or real)[:60],
                "color": color, "network": bool(body.get("network")), "readonly": bool(body.get("readonly"))}
        cfg.update({"roots": cfg["roots"] + [root]})
        asyncio.get_running_loop().run_in_executor(None, idx.run)
        return settings_view()

    @app.post("/api/roots/{rid}")
    async def edit_root(request: Request, rid: str):
        require(request)
        body = await request.json()
        roots = [dict(r) for r in cfg["roots"]]
        for r in roots:
            if r["id"] == rid:
                if "name" in body:
                    r["name"] = str(body["name"])[:60]
                if COLOR_RE.match(str(body.get("color", ""))):
                    r["color"] = body["color"]
                for flag in ("network", "readonly"):
                    if flag in body:
                        r[flag] = bool(body[flag])
        cfg.update({"roots": roots})
        return settings_view()

    @app.delete("/api/roots/{rid}")
    def del_root(request: Request, rid: str):
        require(request)
        cfg.update({"roots": [r for r in cfg["roots"] if r["id"] != rid]})
        return settings_view()

    # ------------------------------------------------------------------
    # Índice
    # ------------------------------------------------------------------
    @app.post("/api/index/run")
    async def index_run(request: Request):
        require(request)
        if idx.status["running"]:
            return {"started": False}
        asyncio.get_running_loop().run_in_executor(None, idx.run)
        return {"started": True}

    @app.get("/api/index/status")
    def index_status(request: Request):
        require(request)
        return {"status": idx.status, "stats": idx.stats()}

    # ------------------------------------------------------------------
    # Configurações / personalização
    # ------------------------------------------------------------------
    @app.post("/api/settings")
    async def update_settings(request: Request):
        """Atualização parcial. Só aceita chaves conhecidas (lista branca)."""
        require(request)
        body = await request.json()
        patch: dict = {}
        if body.get("language") in LANGUAGES:
            patch["language"] = body["language"]
        if isinstance(body.get("ui"), dict):
            ui_in, ui = body["ui"], {}
            choices = {"theme": ("dark", "light", "auto"), "font": ("system", "rounded", "serif", "mono"),
                       "density": ("comfortable", "compact"), "tile_style": ("glass", "solid", "outline")}
            for k, opts in choices.items():
                if ui_in.get(k) in opts:
                    ui[k] = ui_in[k]
            if COLOR_RE.match(str(ui_in.get("accent", ""))):
                ui["accent"] = ui_in["accent"]
            for k in ("animated", "show_clock"):
                if k in ui_in:
                    ui[k] = bool(ui_in[k])
            if "blur" in ui_in:
                ui["blur"] = max(0, min(int(ui_in["blur"]), 40))
            for k, n in (("logo_text", 24), ("greeting", 80)):
                if k in ui_in:
                    ui[k] = str(ui_in[k])[:n]
            bg = ui_in.get("background")
            if isinstance(bg, dict) and bg.get("type") in ("preset", "color", "image"):
                val = str(bg.get("value", ""))[:80]
                if bg["type"] == "color" and not COLOR_RE.match(val):
                    err("bad_color")
                if bg["type"] == "image" and not (cfg.wallpapers_dir / val).is_file():
                    err("not_found")
                ui["background"] = {"type": bg["type"], "value": val}
            patch["ui"] = ui
        if isinstance(body.get("ai"), dict):
            a_in, a = body["ai"], {}
            if "enabled" in a_in:
                a["enabled"] = bool(a_in["enabled"])
            if a_in.get("provider") in ai_mod.PROVIDERS:
                a["provider"] = a_in["provider"]
            for k in ("model", "base_url"):
                if k in a_in:
                    a[k] = str(a_in[k]).strip()[:300]
            if a_in.get("api_key"):          # vazio = mantém a chave atual
                a["api_key"] = str(a_in["api_key"]).strip()
            if a_in.get("clear_key"):
                a["api_key"] = ""
            if "context_files" in a_in:
                a["context_files"] = max(0, min(int(a_in["context_files"]), 15))
            patch["ai"] = a
        if isinstance(body.get("index"), dict):
            i_in, i = body["index"], {}
            if "interval_minutes" in i_in:
                i["interval_minutes"] = max(0, min(int(i_in["interval_minutes"]), 1440))
            if "max_content_mb" in i_in:
                i["max_content_mb"] = max(1, min(int(i_in["max_content_mb"]), 500))
            if "include_hidden" in i_in:
                i["include_hidden"] = bool(i_in["include_hidden"])
            patch["index"] = i
        if "session_hours" in body:
            patch["session_hours"] = max(1, min(int(body["session_hours"]), 720))
            sessions.hours = patch["session_hours"]
        if isinstance(body.get("network"), dict) and "scan_enabled" in body["network"]:
            patch["network"] = {"scan_enabled": bool(body["network"]["scan_enabled"])}
        cfg.update(patch)
        return settings_view()

    @app.post("/api/wallpaper")
    async def upload_wallpaper(request: Request):
        """Recebe a imagem crua no corpo (sem multipart) e a define como fundo."""
        require(request)
        ctype = request.headers.get("content-type", "")
        exts = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
        if ctype not in exts:
            err("bad_image")
        data = await request.body()
        if len(data) > 20 * 1024 * 1024:
            err("too_large")
        cfg.wallpapers_dir.mkdir(parents=True, exist_ok=True)
        name = f"{secrets.token_hex(8)}.{exts[ctype]}"
        (cfg.wallpapers_dir / name).write_bytes(data)
        cfg.update({"ui": {"background": {"type": "image", "value": name}}})
        return settings_view()

    @app.get("/api/wallpaper/{name}")
    def get_wallpaper(request: Request, name: str):
        require(request)
        if not re.fullmatch(r"[0-9a-f]{16}\.(png|jpg|webp|gif)", name):
            err("not_found", 404)
        f = cfg.wallpapers_dir / name
        if not f.is_file():
            err("not_found", 404)
        return FileResponse(f, headers={"Cache-Control": "private, max-age=86400"})

    # ------------------------------------------------------------------
    # IA
    # ------------------------------------------------------------------
    @app.post("/api/ai/ask")
    async def ai_ask(request: Request):
        require(request)
        body = await request.json()
        ai_cfg = cfg["ai"]
        if not ai_cfg.get("enabled"):
            err("ai_disabled")
        question = str(body.get("question", "")).strip()[:4000]
        if not question:
            err("empty")
        sources, contexts = [], []
        n = ai_cfg.get("context_files", 5)
        only = body.get("path")   # pergunta sobre UM arquivo específico
        if only:
            p, _ = resolve(str(only))
            hits = [{"path": str(p), "name": p.name, "kind": kind_of(ext_of(p.name))}]
        else:
            kw = ai_mod.keywords(question)
            hits = idx.search(kw, "all", n)["items"] if kw and n else []
            if kw and n and not hits:   # nenhum resultado com todas: tenta só as 3 principais
                hits = idx.search(" ".join(kw.split()[:3]), "all", n)["items"]
        terms = ai_mod.keywords(question).split()
        for h in hits:
            text = idx.content_of(h["path"]) or ""
            if not text and only and can_extract(ext_of(h["name"])):
                text = extract_text(h["path"], ext_of(h["name"]))
            contexts.append({"name": h["name"], "path": h["path"],
                             "text": ai_mod.excerpt(text, terms) if text else "(sem texto: arquivo de mídia)"})
            sources.append({"path": h["path"], "name": h["name"], "kind": h.get("kind", "other")})
        try:
            loop = asyncio.get_running_loop()
            answer = await loop.run_in_executor(None, ai_mod.ask, ai_cfg, question, contexts, cfg["language"])
        except ai_mod.AIError as e:
            return JSONResponse({"error": "ai_error", "detail": str(e)}, status_code=502)
        return {"answer": answer, "sources": sources}

    # ------------------------------------------------------------------
    # Rede: sessões do Farol + dispositivos na LAN
    # ------------------------------------------------------------------
    @app.get("/api/network/sessions")
    def net_sessions(request: Request):
        tok = require(request)
        me = sessions.get(tok)
        return [{**s, "current": bool(me and s["id"] == me["id"])} for s in sessions.list()]

    @app.delete("/api/network/sessions/{sid}")
    def kick_session(request: Request, sid: str):
        require(request)
        return {"ok": sessions.revoke_id(sid)}

    @app.post("/api/network/scan")
    async def net_scan(request: Request):
        require(request)
        if not cfg["network"].get("scan_enabled", True):
            err("scan_disabled")
        # Cache de 20s para ninguém transformar o botão em metralhadora de pacotes.
        if net_cache.get("t", 0) > time.time() - 20:
            return net_cache["data"]
        data = await asyncio.get_running_loop().run_in_executor(None, netscan.scan)
        data["scanned_at"] = time.time()
        net_cache.update(t=time.time(), data=data)
        return data

    # ------------------------------------------------------------------
    # Modo Dev (terminal + SSH)
    # ------------------------------------------------------------------
    @app.post("/api/dev/enable")
    async def dev_enable(request: Request):
        """Liga/desliga o Modo Dev. SEMPRE exige a senha, mesmo já logado."""
        require(request)
        body = await request.json()
        if not verify_password(str(body.get("password", "")), cfg["auth"]):
            limiter.fail(client_ip(request))
            err("bad_password", 401)
        if devterm.DISABLED_BY_ENV and body.get("enabled"):
            err("dev_blocked", 403)
        dev = dict(cfg["dev"])
        dev["enabled"] = bool(body.get("enabled"))
        if "shell" in body:
            dev["shell"] = str(body["shell"])[:200]
        cfg.update({"dev": dev})
        return settings_view()

    @app.post("/api/dev/hosts")
    async def dev_add_host(request: Request):
        require(request)
        if not cfg["dev"]["enabled"]:
            err("dev_disabled", 403)
        body = await request.json()
        host = {"id": secrets.token_hex(4), "name": str(body.get("name") or body.get("host", ""))[:60],
                "host": str(body.get("host", "")).strip(), "port": body.get("port") or 22,
                "user": str(body.get("user", "")).strip(), "key_path": str(body.get("key_path", "")).strip()[:300]}
        try:
            devterm.validate_host(host)
            host["port"] = int(host["port"])
        except ValueError as e:
            err(str(e))
        dev = dict(cfg["dev"])
        dev["ssh_hosts"] = dev["ssh_hosts"] + [host]
        cfg.update({"dev": dev})
        return settings_view()

    @app.delete("/api/dev/hosts/{hid}")
    def dev_del_host(request: Request, hid: str):
        require(request)
        dev = dict(cfg["dev"])
        dev["ssh_hosts"] = [h for h in dev["ssh_hosts"] if h["id"] != hid]
        cfg.update({"dev": dev})
        return settings_view()

    @app.websocket("/api/dev/term")
    async def dev_term(ws: WebSocket, host: str = "", cols: int = 100, rows: int = 30):
        # 1) Autenticação: sessão + Modo Dev ligado + origem igual ao próprio Farol.
        origin = ws.headers.get("origin", "")
        own = ws.headers.get("host", "")
        if (not sessions.valid(ws.cookies.get(COOKIE)) or not cfg["dev"]["enabled"]
                or devterm.DISABLED_BY_ENV or not origin.split("://")[-1] == own):
            await ws.close(code=4403)
            return
        await ws.accept()
        # 2) Monta o comando: shell local ou ssh.
        try:
            if host:
                h = next((x for x in cfg["dev"]["ssh_hosts"] if x["id"] == host), None)
                if not h:
                    raise ValueError("unknown_host")
                cmd = devterm.ssh_command(h)
            else:
                cmd = devterm.default_shell(cfg["dev"].get("shell", ""))
        except ValueError as e:
            await ws.send_text(f"\r\n[Farol] erro: {e}\r\n")
            await ws.close()
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        decoder = codecs.getincrementaldecoder("utf-8")("replace")

        def on_output(data: bytes):
            loop.call_soon_threadsafe(queue.put_nowait, decoder.decode(data))

        def on_exit():
            loop.call_soon_threadsafe(queue.put_nowait, None)

        try:
            term = devterm.Terminal(cmd, on_output, on_exit, cols, rows)
        except Exception as e:  # noqa: BLE001
            await ws.send_text(f"\r\n[Farol] nao foi possivel abrir o terminal: {e}\r\n")
            await ws.close()
            return

        async def pump_out():
            while True:
                chunk = await queue.get()
                if chunk is None:
                    await ws.send_text("\r\n[Farol] sessao encerrada.\r\n")
                    await ws.close()
                    return
                await ws.send_text(chunk)

        sender = asyncio.create_task(pump_out())
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                if msg.get("t") == "i":
                    term.write(str(msg.get("d", "")))
                elif msg.get("t") == "r":
                    term.resize(msg.get("c", 100), msg.get("r", 30))
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            sender.cancel()
            term.close()

    # ------------------------------------------------------------------
    # Interface estática
    # ------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index_page():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    if start_indexer:
        @app.on_event("startup")
        def _start():
            idx.start_scheduler()

        @app.on_event("shutdown")
        def _stop():
            idx.stop()

    return app


def range_response(path: Path, request: Request, media_type: str, extra: dict) -> Response:
    """Envia o arquivo com suporte a 'Range' — é isso que permite pular
    para qualquer ponto de um vídeo ou música sem baixar tudo."""
    size = path.stat().st_size
    rng = request.headers.get("range", "")
    start, end, status = 0, size - 1, 200
    if rng.startswith("bytes=") and size > 0:
        try:
            s, e = rng[6:].split(",")[0].strip().split("-")
            if s == "":
                start, end = max(0, size - int(e)), size - 1
            else:
                start = int(s)
                end = min(int(e), size - 1) if e else size - 1
        except ValueError:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        if start > end or start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
    length = max(0, end - start + 1)

    def iterator():
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(512 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length), **extra}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(iterator(), status_code=status, media_type=media_type, headers=headers)
