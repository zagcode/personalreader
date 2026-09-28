"""Transforma o Markdown gerado pelo docling em blocos e frases para leitura.

Cada frase (segmento) é a unidade de síntese: o TTS gera uma frase por vez,
sob demanda, conforme o player avança.
"""

import html
import re

from .config import MAX_SEGMENT_CHARS

MIN_SEGMENT_CHARS = 25

_ABBREVIATIONS = {
    "sr", "sra", "srta", "dr", "dra", "prof", "profa", "mr", "mrs", "ms", "st",
    "jr", "vs", "e.g", "i.e", "fig", "pp", "nº", "vol",
    "cap", "art", "ex", "av", "min", "max", "aprox", "approx", "inc", "ltd",
}

_RE_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_RE_EMPH = re.compile(r"(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1")
_RE_CODE = re.compile(r"`([^`]+)`")
_RE_COMMENT = re.compile(r"<!--.*?-->", re.S)
_RE_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_RE_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
_RE_SPACES = re.compile(r"\s+")

# Fim de frase: pontuação seguida de espaço, ou pontuação CJK (que dispensa espaço).
_RE_SENT_END = re.compile(r"(?<=[.!?…])[\"'”’)\]]*\s+|(?<=[。！？])")
_RE_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RE_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}")


def clean_inline(text: str) -> str:
    text = _RE_COMMENT.sub("", text)
    text = _RE_IMAGE.sub("", text)
    text = _RE_LINK.sub(r"\1", text)
    text = _RE_CODE.sub(r"\1", text)
    for _ in range(2):  # ênfases aninhadas
        text = _RE_EMPH.sub(r"\2", text)
    text = _RE_TAG.sub("", text)
    text = _RE_ESCAPE.sub(r"\1", text)
    text = html.unescape(text)
    return _RE_SPACES.sub(" ", text).strip()


def _is_abbreviation(piece: str) -> bool:
    last = piece.rstrip().split(" ")[-1].rstrip(".").lower()
    if last in _ABBREVIATIONS:
        return True
    # Iniciais: "J. R. R. Tolkien"
    return len(last) == 1 and last.isalpha()


def split_sentences(text: str) -> list[str]:
    parts = [p for p in _RE_SENT_END.split(text) if p and p.strip()]
    sentences: list[str] = []
    for part in parts:
        part = part.strip()
        if sentences and _is_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)

    # Junta frases muito curtas à seguinte para não picotar a leitura.
    merged: list[str] = []
    for s in sentences:
        if merged and len(merged[-1]) < MIN_SEGMENT_CHARS and len(merged[-1]) + len(s) < MAX_SEGMENT_CHARS:
            merged[-1] = f"{merged[-1]} {s}"
        else:
            merged.append(s)

    out: list[str] = []
    for s in merged:
        out.extend(_split_long(s))
    return out


def _split_long(sentence: str) -> list[str]:
    """Quebra frases longas em pontos naturais (; : , e por fim espaço)."""
    if len(sentence) <= MAX_SEGMENT_CHARS:
        return [sentence]
    for sep in ("; ", ": ", ", ", " "):
        cut = sentence.rfind(sep, MAX_SEGMENT_CHARS // 3, MAX_SEGMENT_CHARS)
        if cut != -1:
            head = sentence[: cut + len(sep)].strip()
            return [head, *_split_long(sentence[cut + len(sep):].strip())]
    return [sentence[:MAX_SEGMENT_CHARS], *_split_long(sentence[MAX_SEGMENT_CHARS:])]


def _table_rows(lines: list[str]) -> list[str]:
    rows = []
    for line in lines:
        if _RE_TABLE_SEP.match(line):
            continue
        cells = [clean_inline(c) for c in line.strip().strip("|").split("|")]
        rows.append(" · ".join(c for c in cells if c))
    return [r for r in rows if r]


def segment_markdown(markdown: str) -> dict:
    """Retorna {"blocks": [...], "segments": [...]}.

    blocks: {"type", "level"?, "segments": [índices]} ou {"type": "table", "rows": [...]}
    segments: {"id", "block", "text"}
    """
    blocks: list[dict] = []
    segments: list[dict] = []

    def add_block(kind: str, text: str, **extra):
        text = clean_inline(text)
        if not text:
            return
        pieces = [text] if kind == "heading" else split_sentences(text)
        block = {"type": kind, **extra, "segments": []}
        for piece in pieces:
            block["segments"].append(len(segments))
            segments.append({"id": len(segments), "block": len(blocks), "text": piece})
        blocks.append(block)

    lines = markdown.replace("\r\n", "\n").split("\n")
    paragraph: list[str] = []
    i = 0

    def flush():
        if paragraph:
            add_block("paragraph", " ".join(paragraph))
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush()
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                i += 1
            i += 1
            continue

        if stripped.startswith("|"):
            flush()
            table = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table.append(lines[i])
                i += 1
            rows = _table_rows(table)
            if rows:
                blocks.append({"type": "table", "rows": rows, "segments": []})
            continue

        if not stripped or _RE_COMMENT.fullmatch(stripped):
            flush()
        elif m := _RE_HEADING.match(stripped):
            flush()
            add_block("heading", m.group(2), level=len(m.group(1)))
        elif _RE_LIST.match(line):
            flush()
            add_block("list", _RE_LIST.sub("", line))
        elif stripped.startswith(">"):
            flush()
            add_block("quote", stripped.lstrip("> "))
        else:
            paragraph.append(stripped)
        i += 1
    flush()

    return {"blocks": blocks, "segments": segments}
