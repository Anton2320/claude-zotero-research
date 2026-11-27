"""Open-access PDF routes for a DOI, tried before Sci-Hub.

- OpenAlex: every known open copy of a work - preprint servers (bioRxiv, medRxiv, chemRxiv,
  Research Square, Preprints.org, SSRN, OSF...), open-access journal versions and repositories.
- CrossRef: full-text links deposited by the publisher.
- Semantic Scholar: its openAccessPdf link.

Requests use an honest User-Agent. Sites that answer with a bot challenge (e.g. chemRxiv) are
reported as blocked and skipped, not worked around; their links are returned so the user can
save the paper from a browser instead.
Only depends on `requests` and the standard library.
"""
import logging
import os
from urllib.parse import urlparse

import requests

from scihub import _extract_pdf_url, get_crossref_item, normalize_doi

logger = logging.getLogger(__name__)

TIMEOUT = 30
MAX_ATTEMPTS = 8
MAX_SINGLE_LOOKUPS = 10
OPENALEX = "https://api.openalex.org/works"
SEMANTIC_SCHOLAR = "https://api.semanticscholar.org/graph/v1/paper"

_session = requests.Session()
_session.headers["User-Agent"] = "sci-zotero-research (Zotero research helper; open-access PDF lookup)"

# Preprint repositories by DOI prefix, for CrossRef records that don't name one.
PREPRINT_SERVERS = {
    "10.26434": "ChemRxiv",
    "10.1101": "bioRxiv",
    "10.21203": "Research Square",
    "10.20944": "Preprints.org",
    "10.2139": "SSRN",
    "10.31219": "OSF Preprints",
    "10.31234": "PsyArXiv",
    "10.31235": "SocArXiv",
    "10.22541": "Authorea",
    "10.48550": "arXiv",
}


# Hosts seen refusing automated PDF downloads (bot challenge or 403). Their links are tried
# last and offered to the user to open in a browser.
BROWSER_ONLY_HOSTS = ("chemrxiv.org", "mdpi.com", "pmc.ncbi.nlm.nih.gov", "europepmc.org")


def browser_only(url):
    host = urlparse(url).hostname or ""
    return any(host == h or host.endswith("." + h) for h in BROWSER_ONLY_HOSTS)


def preprint_server(doi):
    return PREPRINT_SERVERS.get(normalize_doi(doi).split("/", 1)[0], "")


def _openalex_params(params):
    key = os.environ.get("OPENALEX_API_KEY")
    return dict(params, api_key=key) if key else params


def _source_name(location):
    return (location.get("source") or {}).get("display_name") or "repository"


def _openalex_candidates(doi):
    try:
        r = _session.get(f"{OPENALEX}/doi:{doi}", timeout=TIMEOUT,
                         params=_openalex_params({"select": "best_oa_location,locations"}))
        if r.status_code != 200:
            return []
        work = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.info("OpenAlex lookup failed for %s: %s", doi, e)
        return []
    locations = [work.get("best_oa_location") or {}] + (work.get("locations") or [])
    out = []
    for loc in locations:
        if loc.get("pdf_url"):
            out.append({"url": loc["pdf_url"], "source": _source_name(loc), "kind": "pdf"})
        elif loc.get("is_oa") and loc.get("landing_page_url"):
            out.append({"url": loc["landing_page_url"], "source": _source_name(loc), "kind": "landing"})
    return out


def _crossref_candidates(doi):
    item = get_crossref_item(doi) or {}
    name = preprint_server(doi) or item.get("publisher") or "publisher"
    return [{"url": link["URL"], "source": name, "kind": "pdf"}
            for link in item.get("link", [])
            if link.get("URL") and link.get("content-type") in ("application/pdf", "unspecified")]


def _semantic_scholar_candidates(doi):
    try:
        r = _session.get(f"{SEMANTIC_SCHOLAR}/DOI:{doi}", params={"fields": "openAccessPdf"}, timeout=TIMEOUT)
        url = ((r.json() if r.status_code == 200 else {}).get("openAccessPdf") or {}).get("url")
    except (requests.RequestException, ValueError):
        url = None
    return [{"url": url, "source": "Semantic Scholar", "kind": "pdf"}] if url else []


def candidates(doi):
    """Open-access PDF and landing-page links for a DOI, best first, without duplicates."""
    doi = normalize_doi(doi)
    seen, out = set(), []
    for c in _openalex_candidates(doi) + _crossref_candidates(doi) + _semantic_scholar_candidates(doi):
        if c["url"] not in seen:
            seen.add(c["url"])
            out.append(c)
    return sorted(out, key=lambda c: browser_only(c["url"]))  # stable: keeps best-first otherwise


def _blocked(r):
    head = r.content[:5000]
    return r.status_code in (403, 429, 503) and (b"Just a moment" in head or b"challenge" in head
                                                 or "cf-mitigated" in r.headers)


def _get(url):
    """(response, outcome); outcome is '' when the response is a PDF."""
    try:
        r = _session.get(url, timeout=TIMEOUT)
    except requests.RequestException as e:
        return None, f"unreachable ({type(e).__name__})"
    if r.content.startswith(b"%PDF"):
        return r, ""
    if _blocked(r):
        return r, "blocked by bot protection; open it in a browser"
    if r.status_code == 429:
        return r, "rate-limited by the site; try again later or open it in a browser"
    return r, f"HTTP {r.status_code}, not a PDF"


def fetch(doi):
    """Download an open-access PDF for a DOI.

    Returns (content | None, url, source, tried) where tried lists {source, url, outcome} for
    every link attempted.
    """
    tried = []
    for c in candidates(doi)[:MAX_ATTEMPTS]:
        r, outcome = _get(c["url"])
        if c["kind"] == "landing" and r is not None and outcome.startswith("HTTP 200"):
            pdf_url = _extract_pdf_url(r.text, r.url)  # citation_pdf_url meta tag, as repositories use
            if pdf_url:
                tried.append({"source": c["source"], "url": c["url"], "outcome": "landing page, PDF link found"})
                c = dict(c, url=pdf_url)
                r, outcome = _get(pdf_url)
            else:
                outcome = "landing page without a PDF link"
        tried.append({"source": c["source"], "url": c["url"], "outcome": outcome or "PDF downloaded"})
        if not outcome:
            return r.content, c["url"], c["source"], tried
    return None, "", "", tried


def availability(dois):
    """{doi (lowercase): {pdf_url, source}} for DOIs with an open-access PDF, via batched OpenAlex
    lookups. DOIs that come back under another DOI (OpenAlex merges a preprint with its journal
    version) are looked up one by one, up to MAX_SINGLE_LOOKUPS."""
    dois = [normalize_doi(d) for d in dois if d]
    out, returned = {}, set()
    for i in range(0, len(dois), 50):
        try:
            r = _session.get(OPENALEX, timeout=TIMEOUT, params=_openalex_params({
                "filter": "doi:" + "|".join(dois[i:i + 50]), "select": "doi,best_oa_location", "per_page": 50}))
            works = r.json().get("results", []) if r.status_code == 200 else []
        except (requests.RequestException, ValueError) as e:
            logger.info("OpenAlex batch lookup failed: %s", e)
            continue
        for w in works:
            loc = w.get("best_oa_location") or {}
            if loc.get("pdf_url") and w.get("doi"):
                out[normalize_doi(w["doi"]).lower()] = {"pdf_url": loc["pdf_url"], "source": _source_name(loc)}
            if w.get("doi"):
                returned.add(normalize_doi(w["doi"]).lower())
    for doi in [d for d in dois if d.lower() not in returned][:MAX_SINGLE_LOOKUPS]:
        pdfs = [c for c in _openalex_candidates(doi) if c["kind"] == "pdf"]
        if pdfs:
            out[doi.lower()] = {"pdf_url": pdfs[0]["url"], "source": pdfs[0]["source"]}
    return out


# --- Download order: arXiv -> open access -> Sci-Hub ----------------------------------

def _is_plain_url(target):
    t = target.strip().lower()
    return t.startswith(("http://", "https://")) and "doi.org/" not in t


def fetch_any(target, doi="", arxiv_id=""):
    """PDF for an arXiv ID, a DOI or a direct URL.

    DOIs try open-access copies first and Sci-Hub last. A direct URL that fails falls back to
    `doi`, if given. Returns {content, url, source, error, tried}.
    """
    import arxiv  # local import: arxiv imports scihub, as this module does
    import scihub

    if arxiv_id:
        content, url, err = scihub.fetch_pdf(arxiv.pdf_url(arxiv_id))
        return {"content": content, "url": url, "source": "arXiv" if content else "", "error": err, "tried": []}

    tried, errors = [], []
    if _is_plain_url(target):
        content, url, err = scihub.fetch_pdf(target)
        if content:
            return {"content": content, "url": url, "source": "direct link", "error": "", "tried": []}
        errors.append(err)
        target = doi
    if target:
        content, url, source, tried = fetch(target)
        if content:
            return {"content": content, "url": url, "source": source, "error": "", "tried": tried}
        if scihub.MIRRORS:
            content, url, err = scihub.fetch_pdf(normalize_doi(target))
            if content:
                return {"content": content, "url": url, "source": "Sci-Hub", "error": "", "tried": tried}
            errors.append(err)
        errors.insert(0, "No downloadable open-access copy (see pdf_attempts)" if tried
                      else "No open-access copy listed")
    return {"content": None, "url": "", "source": "", "error": "; ".join(e for e in errors if e), "tried": tried}


def annotate(results):
    """Mark find_papers results that have an open-access PDF (preferred over Sci-Hub links)."""
    oa = availability([r["doi"] for r in results if r.get("doi") and r.get("source") != "arXiv"])
    for r in results:
        if r.get("source") == "arXiv" or not r.get("doi"):
            continue
        hit = oa.get(normalize_doi(r["doi"]).lower())
        if hit and browser_only(hit["pdf_url"]):
            r["browser_pdf_url"] = hit["pdf_url"]  # open access, but the site blocks automated downloads
            hit = None
        if hit:
            r.update(pdf_url=hit["pdf_url"], pdf_source=hit["source"], status="success")
            r.pop("error", None)
        elif r.get("status") == "success":
            r["pdf_source"] = "Sci-Hub"
        server = preprint_server(r["doi"])
        if server:
            r["preprint_server"] = server
    return results
