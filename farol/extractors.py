"""
Extração de texto dos arquivos, para a busca por CONTEÚDO.

Quase tudo usa só a biblioteca padrão do Python:
  - Office moderno (docx, xlsx, pptx) e LibreOffice (odt, ods, odp) são ZIPs
    com XML dentro — lemos o XML e tiramos as tags.
  - EPUB também é ZIP com XHTML.
  - PDF usa a biblioteca 'pypdf' (opcional: se não estiver instalada, o PDF
    continua sendo encontrado pelo nome).

Quer suportar um formato novo? Crie uma função _extrair_xxx e registre a
extensão no dicionário EXTRACTORS no fim do arquivo.
"""
from __future__ import annotations

import html
import re
import zipfile

# ---- Classificação por extensão ------------------------------------------
VIDEO = {"mp4", "m4v", "webm", "mkv", "mov", "avi", "ogv", "wmv", "flv", "3gp", "ts"}
AUDIO = {"mp3", "wav", "ogg", "oga", "opus", "flac", "m4a", "aac", "wma", "aiff", "mid"}
IMAGE = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "ico", "avif", "heic", "tif", "tiff"}
CODE = {
    "py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "php", "java", "kt", "c", "h", "cpp", "hpp",
    "cc", "cs", "go", "rs", "rb", "swift", "dart", "lua", "pl", "r", "scala", "sql", "sh",
    "bash", "zsh", "ps1", "bat", "cmd", "html", "htm", "css", "scss", "sass", "less", "vue",
    "svelte", "json", "yaml", "yml", "toml", "ini", "cfg", "conf", "env", "xml", "gradle",
    "dockerfile", "makefile", "tf", "graphql", "proto",
}
TEXT = {"txt", "md", "markdown", "rst", "log", "csv", "tsv", "srt", "vtt", "tex", "nfo", "rtf"}
DOC = {"docx", "odt", "doc", "pages", "epub"}
SHEET = {"xlsx", "ods", "xls", "numbers"}
SLIDE = {"pptx", "odp", "ppt", "key"}
ARCHIVE = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso"}

# Arquivos editáveis no editor de código/texto embutido.
EDITABLE = CODE | (TEXT - {"rtf"})


def kind_of(ext: str) -> str:
    """Retorna a "categoria" do arquivo usada nos filtros da busca."""
    e = ext.lower()
    if e in VIDEO: return "video"
    if e in AUDIO: return "audio"
    if e in IMAGE: return "image"
    if e == "pdf": return "pdf"
    if e in DOC: return "doc"
    if e in SHEET: return "sheet"
    if e in SLIDE: return "slide"
    if e in CODE: return "code"
    if e in TEXT: return "text"
    if e in ARCHIVE: return "archive"
    return "other"


def ext_of(name: str) -> str:
    """Extensão em minúsculo. Trata 'Dockerfile' e 'Makefile' como código."""
    low = name.lower()
    if low in ("dockerfile", "makefile"):
        return low
    return low.rsplit(".", 1)[1] if "." in low else ""


# ---- Utilitários ----------------------------------------------------------
MAX_CHARS = 400_000          # limite de texto guardado por arquivo no índice
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\r\f\v]+")
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """Tenta UTF-8 (com e sem BOM); se falhar, cai para Windows-1252 (muito comum no Brasil)."""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc), "utf-8"
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def _xml_to_text(xml: str, para_tags: tuple[str, ...] = ()) -> str:
    for tag in para_tags:                       # fim de parágrafo vira quebra de linha
        xml = xml.replace(f"</{tag}>", "\n")
    text = html.unescape(_TAG.sub(" ", xml))
    return _SPACES.sub(" ", text)


def _clean(text: str) -> str:
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[:MAX_CHARS]


# ---- Extratores -----------------------------------------------------------
def _extrair_texto(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read(MAX_CHARS * 2)
    return decode_bytes(raw)[0]


def _extrair_html(path: str) -> str:
    raw = _extrair_texto(path)
    return _xml_to_text(_SCRIPT.sub(" ", raw), ("p", "div", "li", "h1", "h2", "h3", "tr"))


def _extrair_rtf(path: str) -> str:
    raw = _extrair_texto(path)
    raw = re.sub(r"\\par[d]?", "\n", raw)
    raw = re.sub(r"\\'[0-9a-f]{2}", " ", raw)
    raw = re.sub(r"\\[a-z]+-?\d* ?", "", raw)
    return raw.replace("{", "").replace("}", "")


def _zip_read(z: zipfile.ZipFile, name: str) -> str:
    try:
        return z.read(name).decode("utf-8", "ignore")
    except KeyError:
        return ""


def _extrair_docx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        return _xml_to_text(_zip_read(z, "word/document.xml"), ("w:p",))


def _extrair_xlsx(path: str) -> str:
    # As células de texto ficam em sharedStrings; números ficam nas planilhas.
    with zipfile.ZipFile(path) as z:
        parts = [_xml_to_text(_zip_read(z, "xl/sharedStrings.xml"), ("si",))]
        for n in sorted(z.namelist()):
            if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"):
                vals = re.findall(r"<v>([^<]{1,60})</v>", _zip_read(z, n))
                parts.append(" ".join(vals[:5000]))
        return "\n".join(parts)


def _extrair_pptx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        slides = sorted(
            (n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
            key=lambda n: int(re.findall(r"\d+", n)[-1]),
        )
        return "\n\n".join(_xml_to_text(_zip_read(z, n), ("a:p",)) for n in slides)


def _extrair_odf(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        return _xml_to_text(_zip_read(z, "content.xml"), ("text:p", "text:h"))


def _extrair_epub(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        parts = []
        for n in z.namelist():
            if n.endswith((".xhtml", ".html", ".htm")):
                parts.append(_xml_to_text(_SCRIPT.sub(" ", _zip_read(z, n)), ("p", "h1", "h2", "div")))
                if sum(map(len, parts)) > MAX_CHARS:
                    break
        return "\n".join(parts)


def _extrair_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader  # import tardio: pypdf é opcional
    except ImportError:
        return ""
    reader = PdfReader(path)
    out, total = [], 0
    for i, page in enumerate(reader.pages):
        if i >= 300 or total > MAX_CHARS:
            break
        txt = page.extract_text() or ""
        out.append(txt)
        total += len(txt)
    return "\n".join(out)


EXTRACTORS = {
    **{e: _extrair_texto for e in (CODE | TEXT) - {"html", "htm", "rtf"}},
    "html": _extrair_html, "htm": _extrair_html, "rtf": _extrair_rtf,
    "docx": _extrair_docx, "xlsx": _extrair_xlsx, "pptx": _extrair_pptx,
    "odt": _extrair_odf, "ods": _extrair_odf, "odp": _extrair_odf,
    "epub": _extrair_epub, "pdf": _extrair_pdf,
}


def can_extract(ext: str) -> bool:
    return ext.lower() in EXTRACTORS


def extract_text(path: str, ext: str) -> str:
    """Extrai o texto; qualquer erro (arquivo corrompido, protegido...) vira string vazia."""
    fn = EXTRACTORS.get(ext.lower())
    if not fn:
        return ""
    try:
        return _clean(fn(path))
    except Exception:  # noqa: BLE001 - um arquivo ruim não pode derrubar a indexação
        return ""
