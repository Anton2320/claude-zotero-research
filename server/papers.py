"""PDF -> Markdown conversion, the local Markdown cache, and Markdown <-> Zotero note HTML."""
import html
import os
import re
from pathlib import Path

import markdown as md_lib

RESEARCH_DIR = Path(os.path.expanduser(os.environ.get("RESEARCH_DIR", "~/Documents/Claude-Research")))
MARKDOWN_DIR = RESEARCH_DIR / "markdown"
NOTES_DIR = RESEARCH_DIR / "notes"

TRANSCRIPT_TAG = "claude-transcript"
NOTES_TAG = "claude-notes"


# --- Local cache ---------------------------------------------------------------

def _safe(name, limit=60):
    return re.sub(r"[^\w\- ]+", "", name).strip()[:limit].strip() or "untitled"


def cached_markdown_path(key):
    """Existing cache file for an item key, if any (files are named '<KEY> - <title>.md')."""
    if MARKDOWN_DIR.exists():
        for p in MARKDOWN_DIR.glob(f"{key}*.md"):
            return p
    return None


def write_cache(key, title, text):
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    old = cached_markdown_path(key)
    if old:
        old.unlink()
    path = MARKDOWN_DIR / f"{key} - {_safe(title)}.md"
    path.write_text(text, encoding="utf-8")
    return path


def write_notes_file(key, title, text):
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = NOTES_DIR / f"{key} - {_safe(title)}.md"
    path.write_text(text, encoding="utf-8")
    return path


# --- PDF ------------------------------------------------------------------------

def pdf_to_markdown(pdf_path):
    import pymupdf4llm  # imported lazily: it is slow to load
    return pymupdf4llm.to_markdown(str(pdf_path))


def page_count(pdf_path):
    import pymupdf
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def render_pages(pdf_path, first, last, dpi=130):
    """Render pages (1-based, inclusive) to PNG bytes. Returns [(page_no, png, text)]."""
    import pymupdf
    out = []
    with pymupdf.open(pdf_path) as doc:
        last = min(last, doc.page_count)
        for n in range(first, last + 1):
            page = doc[n - 1]
            png = page.get_pixmap(dpi=dpi).tobytes("png")
            out.append((n, png, page.get_text()))
    return out


# --- Markdown <-> Zotero note HTML ------------------------------------------------

_MATH_BLOCK = re.compile(r"\$\$(.+?)\$\$", re.S)
_MATH_INLINE = re.compile(r"(?<![\\$])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)")


def markdown_to_note_html(text):
    """Convert Markdown to Zotero note HTML, keeping $...$ / $$...$$ math as Zotero math nodes."""
    stash = []

    def keep(kind):
        def repl(m):
            stash.append((kind, m.group(1).strip()))
            return f"\x00MATH{len(stash) - 1}\x00"
        return repl

    text = _MATH_BLOCK.sub(keep("block"), text)
    text = _MATH_INLINE.sub(keep("inline"), text)
    out = md_lib.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])

    def restore(m):
        kind, tex = stash[int(m.group(1))]
        tex = html.escape(tex, quote=False)
        return f'<pre class="math">$${tex}$$</pre>' if kind == "block" else f'<span class="math">${tex}$</span>'

    out = re.sub(r"<p>\x00MATH(\d+)\x00</p>", restore, out)
    return re.sub(r"\x00MATH(\d+)\x00", restore, out)


def note_html_to_markdown(note):
    """Rough inverse of markdown_to_note_html, used when only the Zotero note exists."""
    s = note
    s = re.sub(r'<pre class="math">(.*?)</pre>', lambda m: "\n" + m.group(1) + "\n", s, flags=re.S)
    s = re.sub(r'<span class="math">(.*?)</span>', r"\1", s, flags=re.S)
    for n in range(6, 0, -1):
        s = re.sub(rf"<h{n}[^>]*>(.*?)</h{n}>", lambda m, n=n: "\n" + "#" * n + " " + m.group(1) + "\n", s, flags=re.S)
    s = re.sub(r"<li[^>]*>", "\n- ", s)
    s = re.sub(r"<(strong|b)>(.*?)</\1>", r"**\2**", s, flags=re.S)
    s = re.sub(r"<(em|i)>(.*?)</\1>", r"*\2*", s, flags=re.S)
    s = re.sub(r"<code>(.*?)</code>", r"`\1`", s, flags=re.S)
    s = re.sub(r"</(p|pre|tr|table|ul|ol|blockquote|div)>", "\n\n", s)
    s = re.sub(r"</t[dh]>", " | ", s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()
