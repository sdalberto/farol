"""
Indexador e motor de busca do Farol (SQLite + FTS5).

Como funciona:
  1. Percorre as pastas cadastradas (inclusive pastas de rede montadas).
  2. Para cada arquivo novo ou alterado (tamanho/data mudaram) extrai o texto.
  3. Grava nome, pasta e conteúdo numa tabela FTS5 — o mesmo tipo de índice
     invertido usado por buscadores, com ranking BM25.

Operadores de busca suportados (estilo Google):
  "frase exata"   -palavra (excluir)   ext:pdf   tipo:video / kind:video
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time

from .extractors import can_extract, ext_of, extract_text, kind_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    root TEXT NOT NULL,
    name TEXT NOT NULL,
    ext TEXT, kind TEXT,
    size INTEGER, mtime REAL, indexed_at REAL
);
CREATE INDEX IF NOT EXISTS files_root ON files(root);
CREATE INDEX IF NOT EXISTS files_kind ON files(kind);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    name, folder, content,
    tokenize = "unicode61 remove_diacritics 2"
);
CREATE TABLE IF NOT EXISTS favorites(
    path TEXT PRIMARY KEY, label TEXT, kind TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS recent(path TEXT PRIMARY KEY, opened REAL);
"""

# Grupos usados pelas abas de filtro da interface.
KIND_GROUPS = {
    "docs": ("pdf", "doc", "sheet", "slide", "text"),
    "video": ("video",), "audio": ("audio",), "image": ("image",),
    "code": ("code",), "archive": ("archive",),
}
# Atalhos em pt/en/es para o operador tipo:
KIND_ALIASES = {
    "video": "video", "videos": "video", "vídeo": "video", "vídeos": "video",
    "audio": "audio", "musica": "audio", "música": "audio", "music": "audio", "musicas": "audio",
    "imagem": "image", "image": "image", "imagen": "image", "foto": "image", "fotos": "image",
    "doc": "docs", "docs": "docs", "documento": "docs", "documentos": "docs", "documents": "docs",
    "codigo": "code", "código": "code", "code": "code", "fonte": "code",
}


def _split_name(name: str) -> str:
    """'relatorio_final-2024.pdf' -> 'relatorio_final-2024.pdf relatorio final 2024 pdf'.
    Assim a busca acha pedaços do nome mesmo com _ - . e camelCase."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"[_\-.()\[\]]+", " ", spaced)
    return f"{name} {spaced}"


def parse_query(q: str) -> dict:
    """Converte o texto digitado em uma expressão FTS5 segura + filtros.

    Todo termo vai entre aspas, então o usuário NÃO consegue injetar sintaxe
    FTS5 (evita erros e consultas maliciosas)."""
    exts, kinds = [], []
    phrases = [p.strip() for p in re.findall(r'"([^"]+)"', q) if p.strip()]
    rest = re.sub(r'"[^"]*"', " ", q)
    pos, neg = [], []
    for tok in rest.split():
        low = tok.lower()
        if low.startswith("ext:") and len(low) > 4:
            exts.append(low[4:].lstrip("."))
            continue
        if low.startswith(("tipo:", "kind:", "type:")):
            k = KIND_ALIASES.get(low.split(":", 1)[1])
            if k:
                kinds.append(k)
            continue
        words = re.findall(r"\w+", low)
        if tok.startswith("-") and len(tok) > 1:
            neg.extend(words)
        else:
            pos.extend(words)
    parts = [f'"{p.replace(chr(34), "")}"' for p in phrases] + [f'"{w}"*' for w in pos]
    match = " ".join(parts)
    if match and neg:
        match += "".join(f' NOT "{w}"' for w in neg)
    return {"match": match, "exts": exts, "kinds": kinds, "terms": pos + phrases}


class Indexer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.db_path = str(cfg.db_path)
        self._local = threading.local()
        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self.status = {"running": False, "scanned": 0, "indexed": 0, "removed": 0,
                       "current": "", "started": None, "finished": None, "errors": []}
        cfg.home.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    # Uma conexão por thread (SQLite em modo WAL permite ler enquanto indexa).
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.db_path, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
        return c

    # ------------------------------------------------------------------
    # Indexação
    # ------------------------------------------------------------------
    def _walk(self, root: str):
        idx = self.cfg["index"]
        excl = set(idx.get("exclude", []))
        hidden = idx.get("include_hidden", False)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # Alterar dirnames no lugar faz o os.walk pular essas pastas.
            dirnames[:] = [d for d in dirnames if d not in excl and (hidden or not d.startswith("."))]
            for fn in filenames:
                if not hidden and fn.startswith("."):
                    continue
                full = os.path.join(dirpath, fn)
                if not os.path.islink(full):   # links simbólicos são ignorados (segurança)
                    yield full

    def _index_one(self, c, path: str, root: str, st, old_id=None) -> None:
        name = os.path.basename(path)
        ext = ext_of(name)
        kind = kind_of(ext)
        max_bytes = self.cfg["index"].get("max_content_mb", 25) * 1024 * 1024
        content = extract_text(path, ext) if can_extract(ext) and st.st_size <= max_bytes else ""
        rel = os.path.relpath(os.path.dirname(path), root)
        folder = "" if rel == "." else _split_name(rel.replace(os.sep, " "))
        now = time.time()
        if old_id:
            c.execute("UPDATE files SET name=?,ext=?,kind=?,size=?,mtime=?,indexed_at=? WHERE id=?",
                      (name, ext, kind, st.st_size, st.st_mtime, now, old_id))
            c.execute("DELETE FROM fts WHERE rowid=?", (old_id,))
            fid = old_id
        else:
            cur = c.execute(
                "INSERT INTO files(path,root,name,ext,kind,size,mtime,indexed_at) VALUES(?,?,?,?,?,?,?,?)",
                (path, root, name, ext, kind, st.st_size, st.st_mtime, now))
            fid = cur.lastrowid
        c.execute("INSERT INTO fts(rowid,name,folder,content) VALUES(?,?,?,?)",
                  (fid, _split_name(name), folder, content))

    def _delete_ids(self, c, ids: list[int]) -> None:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            c.execute(f"DELETE FROM fts WHERE rowid IN ({marks})", chunk)
            c.execute(f"DELETE FROM files WHERE id IN ({marks})", chunk)

    def run(self) -> bool:
        """Indexação completa e incremental. Retorna False se já houver uma rodando."""
        if not self._run_lock.acquire(blocking=False):
            return False
        st = self.status
        st.update(running=True, scanned=0, indexed=0, removed=0, current="",
                  started=time.time(), finished=None, errors=[])
        try:
            c = self.conn()
            roots = [r["path"] for r in self.cfg["roots"]]
            # 1) Remove arquivos de pastas que foram descadastradas.
            for row in c.execute("SELECT DISTINCT root FROM files").fetchall():
                if row["root"] not in roots:
                    ids = [r[0] for r in c.execute("SELECT id FROM files WHERE root=?", (row["root"],))]
                    self._delete_ids(c, ids)
                    st["removed"] += len(ids)
            c.commit()
            # 2) Percorre cada pasta.
            for root in roots:
                if self._stop.is_set():
                    break
                if not os.path.isdir(root):
                    st["errors"].append(f"offline: {root}")   # ex.: pasta de rede desconectada
                    continue
                existing = {r["path"]: (r["id"], r["size"], r["mtime"])
                            for r in c.execute("SELECT id,path,size,mtime FROM files WHERE root=?", (root,))}
                seen, batch = set(), 0
                for path in self._walk(root):
                    if self._stop.is_set():
                        break
                    try:
                        s = os.stat(path)
                    except OSError:
                        continue
                    seen.add(path)
                    st["scanned"] += 1
                    old = existing.get(path)
                    if old and old[1] == s.st_size and abs((old[2] or 0) - s.st_mtime) < 1e-3:
                        continue          # não mudou: pula (indexação incremental)
                    st["current"] = path
                    try:
                        self._index_one(c, path, root, s, old[0] if old else None)
                        st["indexed"] += 1
                        batch += 1
                    except Exception as exc:  # noqa: BLE001
                        if len(st["errors"]) < 50:
                            st["errors"].append(f"{path}: {exc}")
                    if batch >= 200:
                        c.commit()
                        batch = 0
                c.commit()
                # 3) Remove do índice o que sumiu do disco.
                if not self._stop.is_set():
                    gone = [v[0] for k, v in existing.items() if k not in seen]
                    self._delete_ids(c, gone)
                    st["removed"] += len(gone)
                    c.commit()
            return True
        finally:
            st.update(running=False, current="", finished=time.time())
            self._run_lock.release()

    def reindex_file(self, path: str, root: str) -> None:
        """Atualiza um único arquivo (usado depois de salvar no editor)."""
        c = self.conn()
        row = c.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
        self._index_one(c, path, root, os.stat(path), row["id"] if row else None)
        c.commit()

    def start_scheduler(self) -> None:
        """Thread em segundo plano: indexa ao iniciar e depois a cada N minutos."""
        def loop():
            while not self._stop.is_set():
                if self.cfg["roots"]:
                    self.run()
                minutes = self.cfg["index"].get("interval_minutes", 30) or 0
                waited = 0
                # Se o intervalo for 0, só reindexa quando o usuário pedir.
                while not self._stop.is_set() and (minutes == 0 or waited < minutes * 60):
                    time.sleep(1)
                    waited += 1
        threading.Thread(target=loop, name="farol-indexer", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Busca
    # ------------------------------------------------------------------
    def search(self, q: str, kind: str = "all", limit: int = 30, offset: int = 0) -> dict:
        pq = parse_query(q or "")
        kinds = set()
        for k in pq["kinds"] + ([kind] if kind and kind != "all" else []):
            kinds.update(KIND_GROUPS.get(k, (k,)))
        where, args = [], []
        if kinds:
            where.append(f"f.kind IN ({','.join('?' * len(kinds))})")
            args += sorted(kinds)
        if pq["exts"]:
            where.append(f"f.ext IN ({','.join('?' * len(pq['exts']))})")
            args += pq["exts"]
        extra = (" AND " + " AND ".join(where)) if where else ""
        c = self.conn()
        cols = "f.path,f.name,f.ext,f.kind,f.size,f.mtime,f.root"
        t0 = time.time()

        if not pq["match"]:
            # Sem texto (ex.: só "tipo:video"): lista os mais recentes do filtro.
            if not where:
                return {"total": 0, "items": [], "ms": 0}
            sql_where = " AND ".join(where)
            total = c.execute(f"SELECT COUNT(*) FROM files f WHERE {sql_where}", args).fetchone()[0]
            rows = c.execute(f"SELECT {cols}, '' AS snip FROM files f WHERE {sql_where} "
                             "ORDER BY f.mtime DESC LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
        else:
            try:
                # \x02 e \x03 marcam o trecho encontrado; a interface troca por <mark>.
                base = f"FROM fts JOIN files f ON f.id = fts.rowid WHERE fts MATCH ?{extra}"
                total = c.execute(f"SELECT COUNT(*) {base}", [pq["match"]] + args).fetchone()[0]
                rows = c.execute(
                    f"SELECT {cols}, snippet(fts, -1, char(2), char(3), '…', 24) AS snip {base} "
                    "ORDER BY bm25(fts, 10.0, 3.0, 1.0) LIMIT ? OFFSET ?",
                    [pq["match"]] + args + [limit, offset]).fetchall()
            except sqlite3.OperationalError:
                # Plano B: busca simples por nome.
                like = f"%{q.strip()}%"
                total = c.execute("SELECT COUNT(*) FROM files f WHERE f.name LIKE ?", (like,)).fetchone()[0]
                rows = c.execute(f"SELECT {cols}, '' AS snip FROM files f WHERE f.name LIKE ? "
                                 "ORDER BY f.mtime DESC LIMIT ? OFFSET ?", (like, limit, offset)).fetchall()
        return {"total": total, "items": [dict(r) for r in rows], "ms": int((time.time() - t0) * 1000)}

    def content_of(self, path: str) -> str:
        """Texto indexado de um arquivo (usado como contexto para a IA)."""
        row = self.conn().execute(
            "SELECT fts.content FROM fts JOIN files f ON f.id=fts.rowid WHERE f.path=?", (path,)).fetchone()
        return row[0] if row else ""

    def stats(self) -> dict:
        c = self.conn()
        kinds = {r["kind"]: {"count": r["n"], "size": r["s"] or 0}
                 for r in c.execute("SELECT kind, COUNT(*) n, SUM(size) s FROM files GROUP BY kind")}
        total = sum(k["count"] for k in kinds.values())
        return {"total": total, "kinds": kinds}

    # ------------------------------------------------------------------
    # Favoritos e recentes
    # ------------------------------------------------------------------
    def favorites(self) -> list[dict]:
        return [dict(r) for r in self.conn().execute("SELECT * FROM favorites ORDER BY created")]

    def add_favorite(self, path: str, label: str, kind: str) -> None:
        c = self.conn()
        c.execute("INSERT OR REPLACE INTO favorites(path,label,kind,created) VALUES(?,?,?,?)",
                  (path, label, kind, time.time()))
        c.commit()

    def remove_favorite(self, path: str) -> None:
        c = self.conn()
        c.execute("DELETE FROM favorites WHERE path=?", (path,))
        c.commit()

    def touch_recent(self, path: str) -> None:
        c = self.conn()
        c.execute("INSERT OR REPLACE INTO recent(path,opened) VALUES(?,?)", (path, time.time()))
        c.execute("DELETE FROM recent WHERE path NOT IN (SELECT path FROM recent ORDER BY opened DESC LIMIT 30)")
        c.commit()

    def recent(self, limit: int = 12) -> list[dict]:
        return [dict(r) for r in self.conn().execute(
            "SELECT f.path,f.name,f.ext,f.kind,f.size,f.mtime,r.opened FROM recent r "
            "JOIN files f ON f.path=r.path ORDER BY r.opened DESC LIMIT ?", (limit,))]
