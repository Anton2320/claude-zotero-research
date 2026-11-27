"""arXiv lookup: metadata and search via the arXiv API, PDFs from arxiv.org.

arXiv-only papers have no CrossRef record (their DOIs, 10.48550/arXiv.<id>, are registered with
DataCite) and are rarely on Sci-Hub, so they are handled here instead.
Only depends on `requests` and the standard library.
"""
import logging
import re
import xml.etree.ElementTree as ET

import requests

from scihub import _session

logger = logging.getLogger(__name__)

API = "https://export.arxiv.org/api/query"
TIMEOUT = 30
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

_ID = r"(?P<id>\d{4}\.\d{4,5}|[a-z][a-z\-]*(?:\.[a-z]{2})?/\d{7})(?P<v>v\d+)?"
_FORMS = re.compile(
    r"^(?:arxiv:\s*"
    r"|(?:https?://)?(?:www\.|export\.)?arxiv\.org/(?:abs|pdf|html)/"
    r"|(?:doi:\s*|(?:https?://)?(?:dx\.)?doi\.org/)?10\.48550/arxiv\.)?"
    + _ID + r"(?:\.pdf)?/?(?:[?#].*)?$",
    re.I,
)


def parse_id(text):
    """arXiv ID (with version, if given) from an ID, arXiv URL or arXiv DOI; else ''."""
    m = _FORMS.match((text or "").strip())
    return (m.group("id") + (m.group("v") or "")) if m else ""


def _base(arxiv_id):
    return re.sub(r"v\d+$", "", arxiv_id)


def doi_for(arxiv_id):
    return f"10.48550/arXiv.{_base(arxiv_id)}"


def pdf_url(arxiv_id):
    return f"https://arxiv.org/pdf/{arxiv_id}"


def _text(el, path):
    found = el.find(path, NS)
    return re.sub(r"\s+", " ", found.text).strip() if found is not None and found.text else ""


def _entry(e):
    abs_url = _text(e, "a:id")
    m = re.search(r"arxiv\.org/abs/(.+)$", abs_url)
    if not m:
        return None  # error entry
    vid = m.group(1)
    primary = e.find("arxiv:primary_category", NS)
    return {
        "arxiv_id": _base(vid),
        "version": vid[len(_base(vid)):],
        "title": _text(e, "a:title"),
        "authors": [_text(a, "a:name") for a in e.findall("a:author", NS)],
        "published": _text(e, "a:published")[:10],
        "abstract": _text(e, "a:summary"),
        "category": primary.get("term", "") if primary is not None else "",
        "journal_ref": _text(e, "arxiv:journal_ref"),
        "published_doi": _text(e, "arxiv:doi"),
    }


def _query(params):
    r = _session.get(API, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    return [x for x in (_entry(e) for e in root.findall("a:entry", NS)) if x]


def get_metadata(arxiv_id):
    """arXiv metadata for an ID, or None if it doesn't exist."""
    try:
        entries = _query({"id_list": _base(arxiv_id), "max_results": 1})
    except (requests.RequestException, ET.ParseError) as e:
        logger.warning("arXiv lookup failed for %s: %s", arxiv_id, e)
        return None
    return entries[0] if entries else None


def to_result(meta):
    """Shape arXiv metadata like scihub.search_paper_by_doi results."""
    result = {
        "doi": doi_for(meta["arxiv_id"]),
        "arxiv_id": meta["arxiv_id"],
        "title": meta["title"],
        "author": ", ".join(meta["authors"]),
        "year": meta["published"][:4],
        "journal": meta["journal_ref"] or f"arXiv ({meta['category']})",
        "pdf_url": pdf_url(meta["arxiv_id"]),
        "source": "arXiv",
        "status": "success",
    }
    if meta["published_doi"]:
        result["published_doi"] = meta["published_doi"]
    return result


def search_by_id(arxiv_id):
    meta = get_metadata(arxiv_id)
    if not meta:
        return {"arxiv_id": arxiv_id, "status": "not_found", "error": f"No arXiv paper {arxiv_id}"}
    return to_result(meta)


# arXiv's search drops these, and an AND with a dropped word matches nothing.
_STOPWORDS = set("a an and are as at be but by for from has have in into is it its no not of on or "
                 "such that the their then there these they this to was we were will with all".split())


def search(keyword, num_results=10):
    """Search arXiv (all fields, every word required), most relevant first."""
    words = [w for w in re.findall(r"[\w\-]+", keyword) if w.lower() not in _STOPWORDS] or keyword.split()[:1]
    if not words:
        return []
    params = {"search_query": " AND ".join(f"all:{w}" for w in words),
              "max_results": max(1, min(int(num_results), 50)), "sortBy": "relevance"}
    try:
        return [to_result(m) for m in _query(params)]
    except (requests.RequestException, ET.ParseError) as e:
        logger.warning("arXiv search failed (%s): %s", keyword, e)
        return []


def to_zotero_item(meta):
    """Zotero 'preprint' item, like Zotero's own arXiv translator makes."""
    aid = meta["arxiv_id"]
    creators = []
    for name in meta["authors"]:
        parts = name.rsplit(" ", 1)
        creators.append({"firstName": parts[0], "lastName": parts[1], "creatorType": "author"}
                        if len(parts) == 2 else {"name": name, "creatorType": "author"})
    extra = [f"arXiv:{aid}" + (f" [{meta['category']}]" if meta["category"] else "")]
    if meta["journal_ref"]:
        extra.append(f"Published in: {meta['journal_ref']}")
    if meta["published_doi"]:
        extra.append(f"Published DOI: {meta['published_doi']}")
    z = {
        "itemType": "preprint",
        "title": meta["title"],
        "creators": creators,
        "date": meta["published"],
        "abstractNote": meta["abstract"],
        "repository": "arXiv",
        "archiveID": f"arXiv:{aid}",
        "DOI": doi_for(aid),
        "url": f"https://arxiv.org/abs/{aid}",
        "libraryCatalog": "arXiv.org",
        "extra": "\n".join(extra),
    }
    return {k: v for k, v in z.items() if v not in ("", [], None)}
