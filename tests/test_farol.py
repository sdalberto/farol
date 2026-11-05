"""
Testes automáticos do Farol.  Rode com:  pip install -r requirements-dev.txt && pytest
Cobrem: senha, bloqueio de caminhos, busca (nome/conteúdo/operadores),
CSRF, login, streaming com Range, editor e Modo Dev desligado por padrão.
"""
import os
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

from farol.config import Config
from farol.indexer import Indexer, parse_query
from farol.security import hash_password, resolve_in_roots, verify_password
from farol.server import create_app

PW = "senha-de-teste-123"
H = {"X-Farol": "1"}


@pytest.fixture()
def env(tmp_path):
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "sub" / "relatorio_vendas.txt").write_text("Relatório de fibra óptica em Itapema", encoding="utf-8")
    (docs / "codigo.py").write_text("print('ola mundo')\n", encoding="utf-8")
    (docs / "musica.mp3").write_bytes(os.urandom(4000))
    (docs / "pagina.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    with zipfile.ZipFile(docs / "contrato.docx", "w") as z:
        z.writestr("word/document.xml", "<w:p><w:t>Contrato de banda larga</w:t></w:p>")
    cfg = Config(tmp_path / "home")
    cfg.data["auth"] = hash_password(PW)
    cfg.data["roots"] = [{"id": "r1", "path": os.path.realpath(docs), "name": "docs",
                          "color": "#5b8cff", "network": False, "readonly": False}]
    cfg.save()
    Indexer(cfg).run()
    client = TestClient(create_app(cfg, start_indexer=False))
    return cfg, client, docs


def login(client):
    r = client.post("/api/login", json={"password": PW}, headers=H)
    assert r.status_code == 200


def test_password_hash():
    a = hash_password("abcdefgh")
    assert verify_password("abcdefgh", a)
    assert not verify_password("errada", a)
    assert a["hash"] != "abcdefgh"


def test_resolve_blocks_escape(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    (root / "a.txt").write_text("x")
    roots = [{"path": str(root)}]
    assert resolve_in_roots(str(root / "a.txt"), roots)
    assert resolve_in_roots(str(root / ".." / "x"), roots) is None
    assert resolve_in_roots("/etc/passwd" if os.name != "nt" else "C:\\Windows\\win.ini", roots) is None


@pytest.mark.skipif(sys.platform == "win32", reason="symlink exige privilégio no Windows")
def test_symlink_escape_blocked(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    outside = tmp_path / "segredo.txt"
    outside.write_text("x")
    (root / "link.txt").symlink_to(outside)
    assert resolve_in_roots(str(root / "link.txt"), [{"path": str(root)}]) is None


def test_parse_query_is_safe():
    q = parse_query('fibra "banda larga" -cobre ext:pdf tipo:video NEAR( * ')
    assert q["exts"] == ["pdf"] and q["kinds"] == ["video"]
    assert '"banda larga"' in q["match"] and 'NOT "cobre"' in q["match"]


def test_auth_and_csrf(env):
    _, client, _ = env
    assert client.get("/api/search?q=x").status_code == 401
    assert client.post("/api/login", json={"password": PW}).status_code == 403      # sem X-Farol
    assert client.post("/api/login", json={"password": "errada"}, headers=H).status_code == 401
    login(client)
    assert client.get("/api/search?q=x").status_code == 200


def test_search(env):
    _, client, _ = env
    login(client)
    s = lambda q: client.get("/api/search", params={"q": q}).json()
    assert s("optica")["total"] == 1                 # conteúdo, sem acento
    assert s("vendas")["items"][0]["name"] == "relatorio_vendas.txt"   # nome
    assert s("banda larga")["items"][0]["name"] == "contrato.docx"      # docx
    assert s("tipo:audio")["total"] == 1
    assert s("ext:py")["total"] == 1
    assert s("fibra -itapema")["total"] == 0


def test_file_serving_is_safe(env):
    _, client, docs = env
    login(client)
    r = client.get("/api/file", params={"path": str(docs / "pagina.html")})
    assert r.headers["content-type"].startswith("text/plain")
    assert "sandbox" in r.headers["content-security-policy"]
    r = client.get("/api/file", params={"path": str(docs / "musica.mp3")}, headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and len(r.content) == 10
    assert client.get("/api/file", params={"path": str(docs.parent / "home" / "config.json")}).status_code == 403


def test_editor_save(env):
    cfg, client, docs = env
    login(client)
    r = client.post("/api/save", json={"path": str(docs / "codigo.py"), "content": "print('novo')\n"}, headers=H)
    assert r.json() == {"ok": True}
    assert (docs / "codigo.py").read_text() == "print('novo')\n"
    assert any(cfg.backups_dir.iterdir())           # backup criado
    assert client.get("/api/search", params={"q": "novo"}).json()["total"] == 1


def test_dev_mode_off_by_default(env):
    _, client, _ = env
    login(client)
    assert client.get("/api/bootstrap").json()["settings"]["dev"]["enabled"] is False
    assert client.post("/api/dev/enable", json={"password": "x", "enabled": True}, headers=H).status_code == 401
    r = client.post("/api/dev/enable", json={"password": PW, "enabled": True}, headers=H)
    assert r.json()["dev"]["enabled"] is True
    bad = client.post("/api/dev/hosts", json={"host": "-oProxyCommand=evil"}, headers=H)
    assert bad.json()["error"] == "invalid_host"


def test_ai_key_never_returned(env):
    _, client, _ = env
    login(client)
    r = client.post("/api/settings", json={"ai": {"api_key": "sk-secreta"}}, headers=H).json()
    assert r["ai"]["has_key"] is True and "sk-secreta" not in str(r)
