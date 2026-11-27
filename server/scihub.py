"""Paper lookup via CrossRef (metadata/search) and Sci-Hub mirrors (PDF links).

Sci-Hub is the last resort; openaccess.py tries legal open-access copies first.

Only depends on `requests` and the standard library.
"""
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin

import requests

logger = logging.getLogger(__name__)

# Mirrors are tried in order. Override with a comma-separated SCIHUB_MIRRORS env var,
# e.g. SCIHUB_MIRRORS="https://sci-hub.al,https://sci-hub.ee"
DEFAULT_MIRRORS = [
    "https://sci-hub.al",
    "https://sci-hub.ee",
    "https://sci-hub.ren",
    "https://sci-hub.se",
    "https://sci-hub.st",
    "https://sci-hub.ru",
]
MIRRORS = [
    m.strip().rstrip("/")
    for m in os.environ.get("SCIHUB_MIRRORS", ",".join(DEFAULT_MIRRORS)).split(",")
    if m.strip()
]

TIMEOUT = 20
CROSSREF_API = "https://api.crossref.org/works"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

_session = requests.Session()
_session.headers.update(HEADERS)


def normalize_doi(doi):
    """Strip URL/`doi:` prefixes and whitespace from a DOI."""
    doi = doi.strip()
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi


# --- CrossRef ---------------------------------------------------------------

def _crossref_item_to_metadata(item):
    authors = []
    for a in item.get("author", []):
        name = " ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name", "")
        if name:
            authors.append(name)
    year = ""
    for key in ("published-print", "published-online", "issued", "created"):
        parts = item.get(key, {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            year = str(parts[0][0])
            break
    return {
        "doi": item.get("DOI", ""),
        "title": (item.get("title") or [""])[0],
        "author": ", ".join(authors),
        "year": year,
        "journal": (item.get("container-title") or [""])[0],
    }


def get_crossref_item(doi):
    """Return the raw CrossRef record for a DOI, or None if not found."""
    try:
        r = _session.get(f"{CROSSREF_API}/{requests.utils.quote(doi)}", timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()["message"]
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("CrossRef lookup failed for %s: %s", doi, e)
    return None


def get_crossref_metadata(doi):
    """Return metadata for a DOI from CrossRef, or None if not found."""
    item = get_crossref_item(doi)
    return _crossref_item_to_metadata(item) if item else None


def _crossref_search(params):
    try:
        r = _session.get(CROSSREF_API, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return [_crossref_item_to_metadata(i) for i in r.json()["message"]["items"]]
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("CrossRef search failed (%s): %s", params, e)
        return []


# --- Sci-Hub ----------------------------------------------------------------

class _PdfLinkParser(HTMLParser):
    """Find the PDF link on a Sci-Hub article page."""

    def __init__(self):
        super().__init__()
        self.pdf_url = None

    def handle_starttag(self, tag, attrs):
        if self.pdf_url:
            return
        a = dict(attrs)
        if tag == "meta" and a.get("name") == "citation_pdf_url":
            self.pdf_url = a.get("content")
        elif tag in ("embed", "iframe") and (a.get("id") == "pdf" or a.get("type") == "application/pdf"):
            self.pdf_url = a.get("src")
        elif tag == "object" and a.get("type") == "application/pdf":
            self.pdf_url = a.get("data")
        elif tag == "button" and "location.href" in (a.get("onclick") or ""):
            m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", a["onclick"])
            if m and ".pdf" in m.group(1):
                self.pdf_url = m.group(1)


def _extract_pdf_url(html, page_url):
    parser = _PdfLinkParser()
    parser.feed(html)
    if not parser.pdf_url:
        return None
    url = parser.pdf_url.replace("\\/", "/").split("#")[0]  # onclick URLs are JS-escaped
    if url.startswith("//"):
        url = "https:" + url
    return urljoin(page_url, url)


def find_pdf_url(doi):
    """Try each Sci-Hub mirror and return (pdf_url, mirror) or (None, None)."""
    for mirror in MIRRORS:
        page_url = f"{mirror}/{doi}"
        try:
            r = _session.get(page_url, timeout=TIMEOUT)
        except requests.RequestException as e:
            logger.info("Mirror %s unreachable: %s", mirror, e)
            continue
        if r.status_code != 200:
            logger.info("Mirror %s returned HTTP %s", mirror, r.status_code)
            continue
        if r.headers.get("Content-Type", "").startswith("application/pdf"):
            return page_url, mirror
        pdf_url = _extract_pdf_url(r.text, r.url)
        if pdf_url:
            return pdf_url, mirror
        logger.info("Mirror %s has no PDF for %s (or showed a captcha)", mirror, doi)
    return None, None


# --- Public API -------------------------------------------------------------

def search_paper_by_doi(doi):
    """Look up a paper by DOI: CrossRef metadata plus a Sci-Hub PDF link."""
    doi = normalize_doi(doi)
    result = get_crossref_metadata(doi) or {"doi": doi, "title": "", "author": "", "year": "", "journal": ""}
    pdf_url, mirror = find_pdf_url(doi)
    if pdf_url:
        result.update(pdf_url=pdf_url, mirror=mirror, status="success")
    else:
        result.update(pdf_url="", status="not_found",
                      error="No PDF found on any Sci-Hub mirror (tried: " + ", ".join(MIRRORS) + ")")
    return result


# Without this, CrossRef keyword hits are dominated by peer reviews and supplementary files.
PAPER_TYPES = ",".join("type:" + t for t in (
    "journal-article", "posted-content", "proceedings-article", "book-chapter", "book",
    "monograph", "report", "dissertation"))


def search_papers_by_keyword(keyword, num_results=10):
    """Search CrossRef by keyword and check Sci-Hub availability for each hit."""
    num_results = max(1, min(int(num_results), 50))
    dois = [i["doi"] for i in _crossref_search({"query": keyword, "rows": num_results, "filter": PAPER_TYPES})
            if i["doi"] and i["title"]]
    if not dois:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(dois))) as pool:
        return list(pool.map(search_paper_by_doi, dois))


def fetch_pdf(pdf_url_or_doi):
    """Fetch a PDF into memory. Accepts a direct PDF URL or a DOI.

    Returns (content: bytes | None, url: str, error: str).
    """
    target = pdf_url_or_doi.strip()
    if not target.lower().startswith(("http://", "https://")) or "doi.org/" in target.lower():
        pdf_url, _ = find_pdf_url(normalize_doi(target))
        if not pdf_url:
            return None, "", f"No PDF found on Sci-Hub for {target}"
        target = pdf_url

    try:
        r = _session.get(target, timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        return None, target, f"Download failed: {e}"

    if not r.content.startswith(b"%PDF"):
        return None, target, f"URL did not return a PDF (Content-Type: {r.headers.get('Content-Type')})"
    return r.content, target, ""


def save_pdf(content, output_path):
    """Write PDF bytes to disk, creating parent directories. Returns the absolute path."""
    output_path = os.path.abspath(os.path.expanduser(output_path))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(content)
    return output_path


def doi_from_url(url):
    """Best-effort DOI extraction from a PDF URL like https://host/pdf/10.1038/nature09492.pdf."""
    m = re.search(r"(10\.\d{4,9}/[^?#]+?)(?:\.pdf)?(?:[?#]|$)", unquote(url))
    return m.group(1) if m else ""
