# /// script
# requires-python = ">=3.10,<3.15"  # on 3.15, pymupdf4llm resolves to an empty placeholder package
# dependencies = [
#     "mcp>=1.10",
#     "requests>=2.31",
#     "pymupdf4llm>=0.0.17",
#     "markdown>=3.5",
# ]
# ///
"""Sci-Zotero Research MCP server: open access + arXiv + Sci-Hub + Zotero + PDF->Markdown, running on this machine."""
import asyncio
import importlib
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))

try:  # mcp >= 2.0
    from mcp.server.mcpserver import Image, MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer, Image

import arxiv
import openaccess
import papers
import scihub
import zotero_local
import zotero_web

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

mcp = MCPServer("sci-zotero-research")


def _collections_text():
    """Zotero collections, read once at startup, for tool descriptions."""
    try:
        targets = zotero_local.list_collections()
    except Exception as e:
        logging.warning(f"Zotero not available at startup: {e}")
        return "Zotero was not running when this server started, so its collections are unknown."
    logging.info("Zotero collections: " + "; ".join(t["path"] for t in targets))
    lines = [f"  - {t['path'].split(' / ', 1)[-1]}" for t in targets[1:]]
    return f'Zotero collections in "{targets[0]["name"]}":\n' + "\n".join(lines or ["  (none)"])


COLLECTIONS = _collections_text()
WRITE_NOTE = ("" if zotero_web.is_configured() else
              "\nNOTE: no Zotero web API key is configured, so results are only saved as local files.")


# Helper modules are reloaded when their files change, so fixes to them apply without restarting
# the server. Changes to this file (tool names, arguments, descriptions) still need a restart.
_MODULES = [scihub, arxiv, openaccess, papers, zotero_web, zotero_local]  # dependency order
_HERE = Path(__file__).parent


def _mtimes():
    return {f: f.stat().st_mtime for f in _HERE.glob("*.py")}


_LOADED = _mtimes()


def _reload_if_changed():
    global _LOADED
    now = _mtimes()
    if now == _LOADED:
        return
    for i, m in enumerate(_MODULES):
        try:
            _MODULES[i] = importlib.reload(m)
        except Exception as e:  # keep serving the old code rather than breaking every tool
            logging.error(f"Reloading {m.__name__} failed, keeping the old version: {e}")
    _LOADED = now
    logging.info("Reloaded helper modules after a code change")


async def _run(fn, *args):
    _reload_if_changed()
    fn = getattr(sys.modules[fn.__module__], fn.__name__, fn)  # the reloaded version, if any
    return await asyncio.to_thread(fn, *args)


def _error(e):
    return {"status": "error", "error": str(e)}


# --- Finding and downloading papers --------------------------------------------------

@mcp.tool()
async def find_papers(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Find papers online by DOI, arXiv ID, title or keywords.

    Keywords and titles search both CrossRef (journals and preprint servers such as chemRxiv,
    bioRxiv, medRxiv, Research Square, SSRN) and arXiv. PDF availability is checked on
    open-access sources (via OpenAlex) first, then Sci-Hub. Use zotero_search instead to look
    inside the user's own library.

    Args:
        query: A DOI, an arXiv ID or URL (e.g. 2301.12345, arxiv.org/abs/...), a title, or keywords.
        limit: Maximum number of results per source (1-20, default 5). Ignored for a DOI/arXiv ID.

    Returns:
        List of papers with doi, title, author, year, journal, pdf_url and status
        ("success" = PDF available, "not_found" otherwise), and pdf_source (e.g. "bioRxiv",
        "Sci-Hub"). Preprints have preprint_server. browser_pdf_url is an open-access PDF on a
        site that blocks automated downloads (e.g. chemRxiv): give it to the user to open. arXiv results also have source="arXiv",
        arxiv_id and, if the paper was later published, published_doi.
    """
    try:
        q = query.strip()
        arxiv_id = arxiv.parse_id(q)
        if arxiv_id:
            return [await _run(arxiv.search_by_id, arxiv_id)]
        if re.match(r"^(doi:\s*|https?://(dx\.)?doi\.org/)?10\.\d{4,9}/\S+$", q, re.I):
            return await _run(openaccess.annotate, [await _run(scihub.search_paper_by_doi, q)])
        limit = max(1, min(limit, 20))
        crossref, preprints = await asyncio.gather(_run(scihub.search_papers_by_keyword, q, limit),
                                                   _run(arxiv.search, q, limit))
        seen = {r["doi"].lower() for r in crossref if r.get("doi")}
        crossref = await _run(openaccess.annotate, crossref)
        return crossref + [p for p in preprints if p.get("published_doi", "").lower() not in seen]
    except Exception as e:
        return [_error(e)]


DOWNLOAD_DESCRIPTION = f"""
Download a paper PDF and add it to the user's Zotero library. PDFs come from arXiv for arXiv
papers; for other DOIs, open-access copies are tried first (preprint servers such as bioRxiv,
medRxiv, chemRxiv, Research Square; open-access journals; repositories) and Sci-Hub last.
arXiv and other preprints are saved as preprints. If every source fails or is blocked, the
'pdf_attempts' list has the links tried: offer them to the user to open in a browser (the
Zotero browser connector can then save the PDF).

Every download is saved to Zotero (full metadata + PDF attached) unless skip_zotero is true.
Only set skip_zotero when the user explicitly asks not to save to Zotero. Choose
zotero_collection by matching the paper's topic against the collections below; if none clearly
fits, leave it empty to save at the top level of the library. Tell the user where it was saved.
Papers already in Zotero (same DOI) are not added again.

{COLLECTIONS}

Args:
    doi_or_url: A DOI (preferred), an arXiv ID/URL (e.g. 2301.12345), or a direct PDF URL
        from find_papers' 'pdf_url' field.
    zotero_collection: Collection name from the list above. Empty = top level of the library.
    skip_zotero: Set true ONLY if the user explicitly asked not to add the paper to Zotero.
    output_path: Optional file path to also save the PDF locally.
    doi: The paper's DOI, needed only if doi_or_url is a URL that doesn't contain it.

Returns:
    Dictionary with 'zotero' (status "success" / "already_exists" / "skipped" / "error",
    collection, pdf_attached) and 'file' if saved locally. Zotero item keys are not returned
    for new items; use zotero_search to find the item afterwards.
"""


@mcp.tool(description=DOWNLOAD_DESCRIPTION)
async def download_paper(doi_or_url: str, zotero_collection: str = "", skip_zotero: bool = False,
                         output_path: str = "", doi: str = "") -> Dict[str, Any]:
    if skip_zotero and not output_path:
        return _error("Nothing to do: give an output_path or don't skip Zotero.")
    result: Dict[str, Any] = {}
    try:
        arxiv_id = arxiv.parse_id(doi_or_url) or (arxiv.parse_id(doi) if doi else "")
        got = await _run(openaccess.fetch_any, doi_or_url, doi, arxiv_id)
        content, source_url = got["content"], got["url"]
        result["pdf_found"] = content is not None
        if content is not None:
            result["pdf_source"] = got["source"]
        elif got["error"]:
            result["pdf_error"] = got["error"]
        if got["tried"] and content is None:
            result["pdf_attempts"] = got["tried"]
        if content is not None and output_path:
            result["file"] = await _run(scihub.save_pdf, content, output_path)
        if skip_zotero:
            result["zotero"] = {"status": "skipped"}
        else:
            target = doi_or_url.strip()
            is_url = target.lower().startswith(("http://", "https://")) and "doi.org/" not in target.lower()
            paper_doi = scihub.normalize_doi(doi) if doi else (scihub.doi_from_url(target) if is_url
                                                                else scihub.normalize_doi(target))
            if arxiv_id:
                paper_doi = arxiv_id
            if not paper_doi:
                result["zotero"] = _error("Couldn't tell the DOI from the URL; call again with the doi argument.")
            else:
                try:
                    result["zotero"] = await _run(zotero_local.save_paper, paper_doi, zotero_collection,
                                                  content, source_url)
                except Exception as e:
                    result["zotero"] = _error(e)
    except Exception as e:
        return _error(f"Download failed: {e}")
    ok = result.get("zotero", {}).get("status") in ("success", "already_exists")
    result["status"] = "success" if result.get("file") or ok else "error"
    return result


# --- Reading the Zotero library -----------------------------------------------------

@mcp.tool(description=f"""
Search the user's Zotero library (titles, authors, tags, notes and PDF full text).

{COLLECTIONS}

Args:
    query: Search words. Empty lists the most recently modified items.
    collection: Optional collection name to search within.
    limit: Maximum number of items (default 20).

Returns:
    List of items with key, title, authors, year, type, DOI, collections and tags. Use the
    key with zotero_get_item, read_paper, get_pdf_pages, save_markdown and add_tags.
""")
async def zotero_search(query: str = "", collection: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    try:
        return await _run(zotero_local.search_items, query, collection, max(1, min(limit, 100)))
    except Exception as e:
        return [_error(e)]


@mcp.tool()
async def zotero_get_item(key: str) -> Dict[str, Any]:
    """
    Get a Zotero item's full metadata (incl. abstract) and its attachments and notes.

    Args:
        key: Zotero item key from zotero_search (an attachment or note key resolves to its parent).
    """
    try:
        return await _run(zotero_local.get_item, key)
    except Exception as e:
        return _error(e)


def _read_paper(key, offset, max_chars, refresh):
    item = zotero_local.get_item(key)
    key, title = item["key"], item["title"]
    text, source, note_status = None, "", ""

    cached = papers.cached_markdown_path(key)
    if cached and not refresh:
        text, source = cached.read_text(encoding="utf-8"), "local markdown cache"
    if text is None and not refresh:
        notes = zotero_local.child_notes(key, papers.TRANSCRIPT_TAG)
        if notes:
            text, source = papers.note_html_to_markdown(notes[0]["html"]), "Zotero transcript note"
            papers.write_cache(key, title, text)
    if text is None:
        pdf = zotero_local.pdf_path(key)
        text = papers.pdf_to_markdown(pdf)
        source = "converted from PDF (pymupdf4llm)"
        papers.write_cache(key, title, text)
        note_status = _save_transcript_note(key, text, auto=True)

    total = len(text)
    chunk = text[offset:offset + max_chars]
    result = {"key": key, "title": title, "source": source, "total_chars": total,
              "offset": offset, "text": chunk}
    if offset + max_chars < total:
        result["next_offset"] = offset + max_chars
        result["note"] = f"Showing {offset}-{offset + len(chunk)} of {total} chars; call again with offset={offset + max_chars}."
    if note_status:
        result["zotero_note"] = note_status
    return result


def _save_transcript_note(key, text, auto=False):
    if not zotero_web.is_configured():
        return "not saved to Zotero (no web API key); kept in the local cache"
    html = papers.markdown_to_note_html(text)
    tags = [papers.TRANSCRIPT_TAG] + (["auto-converted"] if auto else [])
    try:
        existing = zotero_web.find_child_note(key, papers.TRANSCRIPT_TAG)
        if existing:
            zotero_web.update_note(existing, html)
            return f"updated transcript note {existing}"
        return f"saved as transcript note {zotero_web.create_note(key, html, tags)}"
    except Exception as e:
        return f"not saved to Zotero: {e}"


@mcp.tool()
async def read_paper(key: str, offset: int = 0, max_chars: int = 40000, refresh: bool = False) -> Dict[str, Any]:
    """
    Read a paper from the Zotero library as Markdown.

    Uses, in order: the local Markdown cache, a Zotero note tagged 'claude-transcript', or a fresh
    conversion of the attached PDF (which is then cached and saved to Zotero as a transcript note).
    The fast converter can garble complex equations or tables; if so, make a high-quality
    transcript with get_pdf_pages + save_markdown(kind="transcript").

    Args:
        key: Zotero item key.
        offset: Character offset to start from (for long papers; see next_offset).
        max_chars: Maximum characters to return (default 40000).
        refresh: Ignore the cache/note and re-convert the PDF.
    """
    try:
        return await _run(_read_paper, key, max(0, offset), max(1000, max_chars), refresh)
    except Exception as e:
        return _error(e)


def _pdf_pages(key, first_page, last_page):
    path = zotero_local.pdf_path(key)
    total = papers.page_count(path)
    last_page = min(last_page, first_page + 4, total)
    out: List[Any] = [f"PDF pages {first_page}-{last_page} of {total} (item {key})."]
    for n, png, text in papers.render_pages(path, first_page, last_page):
        out.append(f"--- Page {n} (image follows; extracted text for reference below) ---\n{text[:6000]}")
        out.append(Image(data=png, format="png"))
    if last_page < total:
        out.append(f"More pages remain: call again with first_page={last_page + 1}.")
    return out


@mcp.tool(structured_output=False)  # returns images, which can't be structured JSON
async def get_pdf_pages(key: str, first_page: int = 1, last_page: int = 3) -> List[Any]:
    """
    Get page images (plus raw extracted text) of a Zotero item's PDF, at most 5 pages per call.

    Use this for high-quality transcription or to look at figures, tables and equations: read
    the images, write faithful Markdown (math as $...$ / $$...$$ LaTeX, tables as Markdown
    tables, figures described in [Figure N: ...] blocks) and save it with save_markdown.

    Args:
        key: Zotero item key (parent item or PDF attachment).
        first_page: First page, 1-based.
        last_page: Last page (inclusive; capped at first_page + 4).
    """
    try:
        return await _run(_pdf_pages, key, max(1, first_page), max(first_page, last_page))
    except Exception as e:
        return [f"Error: {e}"]


def _save_markdown(key, markdown, kind, title):
    item = zotero_local.get_item(key)
    key = item["key"]
    if kind == "transcript":
        path = papers.write_cache(key, item["title"], markdown)
        return {"status": "success", "file": str(path), "zotero_note": _save_transcript_note(key, markdown)}

    heading = title or f"Notes: {item['title']}"
    if not markdown.lstrip().startswith("#"):
        markdown = f"# {heading}\n\n{markdown}"
    path = papers.write_notes_file(key, heading, markdown)
    result = {"status": "success", "file": str(path)}
    if zotero_web.is_configured():
        try:
            note = zotero_web.create_note(key, papers.markdown_to_note_html(markdown), [papers.NOTES_TAG])
            result["zotero_note"] = f"saved as note {note}"
        except Exception as e:
            result["zotero_note"] = f"not saved to Zotero: {e}"
    else:
        result["zotero_note"] = "not saved to Zotero (no web API key)"
    return result


@mcp.tool(description=f"""
Save Markdown to a Zotero item as a child note (and to a local .md file).

kind="transcript": the full text of the paper. Replaces the item's existing transcript note
    (tag 'claude-transcript') and the local cache that read_paper uses.
kind="notes": reading notes, summaries, critiques. Always adds a new note (tag 'claude-notes').

Math written as $...$ or $$...$$ is kept as rendered math in Zotero.{WRITE_NOTE}

Args:
    key: Zotero item key.
    markdown: The Markdown content.
    kind: "transcript" or "notes".
    title: Heading for notes (default "Notes: <paper title>"); ignored for transcripts.
""")
async def save_markdown(key: str, markdown: str, kind: str = "notes", title: str = "") -> Dict[str, Any]:
    if kind not in ("transcript", "notes"):
        return _error("kind must be 'transcript' or 'notes'")
    try:
        return await _run(_save_markdown, key, markdown, kind, title)
    except Exception as e:
        return _error(e)


@mcp.tool()
async def add_tags(key: str, tags: List[str]) -> Dict[str, Any]:
    """
    Add tags to a Zotero item (existing tags are kept). Changes reach the desktop app on its next sync.

    Args:
        key: Zotero item key.
        tags: Tags to add, e.g. ["read", "methods: survey"].
    """
    try:
        return {"status": "success", "tags": await _run(zotero_web.add_tags, key, tags)}
    except Exception as e:
        return _error(e)


if __name__ == "__main__":
    logging.info(f"Starting Sci-Zotero Research MCP server (files in {papers.RESEARCH_DIR})")
    mcp.run(transport="stdio")
