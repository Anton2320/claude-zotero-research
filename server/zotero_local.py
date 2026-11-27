"""Save papers into a running Zotero desktop app via its local connector server.

This is the same HTTP API the Zotero browser extension uses (port 23119), so no API key
is required - Zotero just needs to be open. Requires Zotero 7 for PDF attachments.
If Zotero's local API is enabled (Settings > Advanced > "Allow other applications on this
computer to communicate with Zotero"), papers already in the library are detected and skipped.
"""
import json
import logging
import os
import re
import uuid

import requests

import arxiv
import openaccess
from scihub import fetch_pdf, get_crossref_item, normalize_doi

logger = logging.getLogger(__name__)

ZOTERO_URL = os.environ.get("ZOTERO_CONNECTOR_URL", "http://127.0.0.1:23119").rstrip("/")
TIMEOUT = 30

# CrossRef work type -> (Zotero item type, field that holds the container title)
_TYPE_MAP = {
    "journal-article": ("journalArticle", "publicationTitle"),
    "proceedings-article": ("conferencePaper", "proceedingsTitle"),
    "book-chapter": ("bookSection", "bookTitle"),
    "book-section": ("bookSection", "bookTitle"),
    "book-part": ("bookSection", "bookTitle"),
    "book": ("book", None),
    "monograph": ("book", None),
    "edited-book": ("book", None),
    "reference-book": ("book", None),
    "posted-content": ("preprint", "repository"),
    "report": ("report", None),
    "dissertation": ("thesis", None),
    "dataset": ("dataset", None),
}


class ZoteroError(Exception):
    pass


def _post(endpoint, payload=None, data=None, headers=None):
    try:
        r = requests.post(
            f"{ZOTERO_URL}/connector/{endpoint}",
            json=payload if data is None else None,
            data=data,
            headers=headers,
            timeout=TIMEOUT,
        )
    except requests.ConnectionError:
        raise ZoteroError("Zotero is not running (could not reach the Zotero desktop app on "
                          f"{ZOTERO_URL}). Start Zotero and try again.")
    if r.status_code >= 400:
        raise ZoteroError(f"Zotero rejected /connector/{endpoint}: HTTP {r.status_code} {r.text[:200]}")
    return r


def list_collections():
    """Return the library and its collections as [{id, name, level, path}]."""
    targets = _post("getSelectedCollection", {}).json().get("targets", [])
    stack, result = [], []
    for t in targets:
        level = t.get("level", 0)
        del stack[level:]
        stack.append(t["name"])
        result.append({"id": t["id"], "name": t["name"], "level": level, "path": " / ".join(stack)})
    return result


def find_existing(doi):
    """Return items in the library with this DOI, or None if the local API is unavailable."""
    try:
        r = requests.get(f"{ZOTERO_URL}/api/users/0/items",
                         params={"q": doi, "qmode": "everything", "itemType": "-attachment"},
                         headers={"Zotero-API-Version": "3"}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None  # local API disabled
        items = r.json()
        names = {c["key"]: c["data"]["name"] for c in requests.get(
            f"{ZOTERO_URL}/api/users/0/collections", params={"limit": 100}, headers={"Zotero-API-Version": "3"},
            timeout=TIMEOUT).json()}
    except (requests.RequestException, ValueError, KeyError):
        return None
    found = []
    for i in items:
        d = i["data"]
        item_doi = d.get("DOI") or ""
        if not item_doi:
            m = re.search(r"^DOI:\s*(\S+)", d.get("extra", ""), re.I | re.M)
            item_doi = m.group(1) if m else ""
        if normalize_doi(item_doi).lower() == doi.lower():
            found.append({"key": i["key"], "title": d.get("title", ""),
                          "collections": [names.get(k, k) for k in d.get("collections", [])]})
    return found


def resolve_collection(collection):
    """Map a collection ID ("C2"), name or path to a target. Empty -> top of the first library."""
    targets = list_collections()
    if not targets:
        raise ZoteroError("Zotero returned no libraries or collections")
    if not collection or not collection.strip():
        return targets[0]
    wanted = collection.strip().lower()
    for key in ("id", "path", "name"):
        matches = [t for t in targets if t[key].lower() == wanted]
        if matches:
            return matches[0]
    matches = [t for t in targets if wanted in t["path"].lower()]
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(f'{t["path"]} ({t["id"]})' for t in targets)
    if matches:
        raise ZoteroError(f"'{collection}' is ambiguous. Matches: "
                          + ", ".join(f'{t["path"]} ({t["id"]})' for t in matches))
    raise ZoteroError(f"No Zotero collection matches '{collection}'. Available: {available}")


def _date_from_crossref(item):
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (item.get(key) or {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            return "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts[0]))
    return ""


def _crossref_to_zotero(item, doi):
    item_type, container_field = _TYPE_MAP.get(item.get("type", ""), ("journalArticle", "publicationTitle"))
    creators = []
    for role, creator_type in (("author", "author"), ("editor", "editor")):
        for a in item.get(role, []):
            if a.get("family"):
                creators.append({"firstName": a.get("given", ""), "lastName": a["family"],
                                 "creatorType": creator_type})
            elif a.get("name"):
                creators.append({"name": a["name"], "creatorType": creator_type})

    z = {
        "itemType": item_type,
        "title": (item.get("title") or [""])[0],
        "creators": creators,
        "date": _date_from_crossref(item),
        "DOI": doi,
        "url": item.get("URL") or f"https://doi.org/{doi}",
        "language": item.get("language", ""),
        "libraryCatalog": "CrossRef",
    }
    container = (item.get("container-title") or [""])[0]
    if item_type == "preprint" and not container:
        container = ((item.get("institution") or [{}])[0].get("name") or openaccess.preprint_server(doi)
                     or item.get("publisher", ""))
    if container_field and container:
        z[container_field] = container
    if item_type in ("journalArticle", "conferencePaper", "bookSection"):
        z["pages"] = item.get("page", "")
    if item_type == "journalArticle":
        z["volume"] = item.get("volume", "")
        z["issue"] = item.get("issue", "")
        z["ISSN"] = ", ".join(item.get("ISSN", []))
        z["journalAbbreviation"] = (item.get("short-container-title") or [""])[0]
    if item_type in ("book", "bookSection", "report", "thesis", "conferencePaper"):
        z["publisher"] = item.get("publisher", "")
    if item_type in ("book", "bookSection"):
        z["ISBN"] = ", ".join(item.get("ISBN", []))
    if item.get("abstract"):
        # CrossRef abstracts are JATS XML; strip the tags.
        z["abstractNote"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", item["abstract"])).strip()
    return {k: v for k, v in z.items() if v not in ("", [], None)}


def save_paper(doi, collection="", pdf=None, pdf_url="", allow_duplicate=False):
    """Create a Zotero item for a DOI, attach `pdf` (bytes) if given and file it in a collection.

    `collection` is a collection ID, name or path; empty saves to the top level of the library.
    An arXiv ID, URL or DOI (10.48550/arXiv.*) is saved as a preprint with arXiv metadata.
    """
    arxiv_id = arxiv.parse_id(doi)
    doi = arxiv.doi_for(arxiv_id) if arxiv_id else normalize_doi(doi)
    target = resolve_collection(collection)

    if not allow_duplicate:
        existing = find_existing(doi)
        if existing:
            return {"status": "already_exists", "doi": doi, "existing_items": existing,
                    "message": "This paper is already in Zotero; nothing was added."}

    if arxiv_id:
        meta = arxiv.get_metadata(arxiv_id)
        if not meta:
            raise ZoteroError(f"No arXiv metadata found for {arxiv_id}")
        item = arxiv.to_zotero_item(meta)
    else:
        cr = get_crossref_item(doi)
        if not cr:
            raise ZoteroError(f"No CrossRef metadata found for DOI {doi}. If it is an arXiv-only "
                              "paper, pass its arXiv ID instead.")
        item = _crossref_to_zotero(cr, doi)
    item["id"] = uuid.uuid4().hex[:8]
    session_id = uuid.uuid4().hex
    pdf_error = "" if pdf is not None else "No PDF available; saved metadata only"

    _post("saveItems", {"sessionID": session_id, "uri": item["url"], "items": [item]})

    attached = False
    if pdf is not None:
        metadata = {
            "sessionID": session_id,
            "parentItemID": item["id"],
            "title": "Full Text PDF",
            "url": pdf_url or item["url"],
        }
        try:
            _post("saveAttachment", data=pdf,
                  headers={"Content-Type": "application/pdf", "X-Metadata": json.dumps(metadata)})
            attached = True
        except ZoteroError as e:
            pdf_error = str(e)

    # Moves the saved item from Zotero's currently selected collection to the target.
    _post("updateSession", {"sessionID": session_id, "target": target["id"]})

    result = {
        "status": "success",
        "doi": doi,
        "title": item.get("title", ""),
        "item_type": item["itemType"],
        "collection": target["path"],
        "collection_id": target["id"],
        "pdf_attached": attached,
    }
    if pdf_error:
        result["pdf_error"] = pdf_error
    return result



# --- Local API (read-only) ---------------------------------------------------

API = f"{ZOTERO_URL}/api/users/0"
API_HEADERS = {"Zotero-API-Version": "3"}


def api_get(path, params=None, raw=False):
    try:
        r = requests.get(f"{API}/{path.lstrip('/')}", params=params, headers=API_HEADERS,
                         timeout=TIMEOUT, allow_redirects=False)
    except requests.ConnectionError:
        raise ZoteroError("Zotero is not running. Start the Zotero desktop app and try again.")
    if r.status_code == 403:
        raise ZoteroError("Zotero's local API is disabled. Enable it in Zotero: Settings > Advanced > "
                          "'Allow other applications on this computer to communicate with Zotero'.")
    if r.status_code == 404:
        raise ZoteroError(f"Not found in Zotero: {path}")
    if r.status_code >= 400:
        raise ZoteroError(f"Zotero local API error on {path}: HTTP {r.status_code} {r.text[:200]}")
    return r if raw else r.json()


def api_get_all(path, params=None):
    """Follow pagination (100 per page)."""
    params = dict(params or {}, limit=100, start=0)
    out = []
    while True:
        page = api_get(path, params)
        out.extend(page)
        if len(page) < 100:
            return out
        params["start"] += 100


def local_collections():
    """Collections from the local API as {key: {name, parent, path}} (keys like 'JYN2BIU4')."""
    cols = {c["key"]: {"name": c["data"]["name"], "parent": c["data"].get("parentCollection") or None}
            for c in api_get_all("collections")}
    for key, c in cols.items():
        parts, k = [], key
        while k and k in cols:
            parts.insert(0, cols[k]["name"])
            k = cols[k]["parent"]
        c["path"] = " / ".join(parts)
    return cols


def collection_key(collection):
    """Resolve a collection name, path or key to its local API key."""
    cols = local_collections()
    wanted = collection.strip().lower()
    for key, c in cols.items():
        if wanted in (key.lower(), c["name"].lower(), c["path"].lower()):
            return key
    matches = [k for k, c in cols.items() if wanted in c["path"].lower()]
    if len(matches) == 1:
        return matches[0]
    raise ZoteroError(f"No single Zotero collection matches '{collection}'. Available: "
                      + ", ".join(c["path"] for c in cols.values()))


def _creators_short(creators):
    names = [c.get("lastName") or c.get("name", "") for c in creators if c.get("creatorType") == "author"]
    names = [n for n in names if n] or [c.get("lastName") or c.get("name", "") for c in creators]
    if len(names) > 3:
        return f"{names[0]} et al."
    return ", ".join(n for n in names if n)


def _summary(item, col_names):
    d = item["data"]
    return {
        "key": item["key"],
        "title": d.get("title", ""),
        "authors": _creators_short(d.get("creators", [])),
        "year": (item.get("meta", {}).get("parsedDate") or d.get("date", ""))[:4],
        "type": d.get("itemType"),
        "DOI": d.get("DOI", ""),
        "collections": [col_names.get(k, k) for k in d.get("collections", [])],
        "tags": [t["tag"] for t in d.get("tags", [])],
    }


def search_items(query="", collection="", limit=25):
    """Search the library (titles, creators, full text, notes). Returns top-level items."""
    path = f"collections/{collection_key(collection)}/items" if collection else "items"
    params = {"qmode": "everything", "limit": 100, "sort": "dateModified", "direction": "desc"}
    if query:
        params["q"] = query
    else:
        path += "/top"
    hits = api_get(path, params)

    keys, seen = [], set()
    for h in hits:
        k = h["data"].get("parentItem") or h["key"]
        if k not in seen:
            seen.add(k)
            keys.append(k)
    keys = keys[:limit]
    if not keys:
        return []
    items = {}
    for i in range(0, len(keys), 50):
        for it in api_get("items", {"itemKey": ",".join(keys[i:i + 50])}):
            items[it["key"]] = it
    col_names = {k: c["path"] for k, c in local_collections().items()}
    return [_summary(items[k], col_names) for k in keys
            if k in items and items[k]["data"]["itemType"] not in ("attachment", "note", "annotation")]


def get_item(key):
    """Full metadata for an item plus its attachments and notes."""
    item = api_get(f"items/{key}")
    if item["data"].get("parentItem"):
        item = api_get(f"items/{item['data']['parentItem']}")
    col_names = {k: c["path"] for k, c in local_collections().items()}
    d = item["data"]
    result = _summary(item, col_names)
    result.update({k: d[k] for k in ("abstractNote", "publicationTitle", "proceedingsTitle", "bookTitle",
                                      "volume", "issue", "pages", "date", "url", "publisher")
                   if d.get(k)})
    result["attachments"], result["notes"] = [], []
    for c in api_get_all(f"items/{item['key']}/children"):
        cd = c["data"]
        if cd["itemType"] == "attachment":
            result["attachments"].append({"key": c["key"], "title": cd.get("title", ""),
                                          "contentType": cd.get("contentType", ""),
                                          "linkMode": cd.get("linkMode", "")})
        elif cd["itemType"] == "note":
            result["notes"].append({"key": c["key"], "title": note_title(cd.get("note", "")),
                                    "chars": len(cd.get("note", "")),
                                    "tags": [t["tag"] for t in cd.get("tags", [])]})
    return result


def note_title(html):
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()[:80]


def child_notes(key, tag=None):
    """Notes attached to an item as [{key, html, tags, version}], optionally filtered by tag."""
    notes = []
    for c in api_get_all(f"items/{key}/children"):
        cd = c["data"]
        tags = [t["tag"] for t in cd.get("tags", [])]
        if cd["itemType"] == "note" and (tag is None or tag in tags):
            notes.append({"key": c["key"], "html": cd.get("note", ""), "tags": tags, "version": c["version"]})
    return notes


def pdf_path(key):
    """Local file path of an item's PDF (the item itself if it is a PDF attachment)."""
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    item = api_get(f"items/{key}")
    if item["data"]["itemType"] == "attachment":
        candidates = [item]
    else:
        candidates = api_get_all(f"items/{key}/children")
    for att in candidates:
        ad = att["data"]
        if ad["itemType"] != "attachment" or ad.get("contentType") != "application/pdf":
            continue
        if ad.get("linkMode") == "linked_file" and ad.get("path"):
            path = ad["path"]
        else:
            url = api_get(f"items/{att['key']}/file/view/url", raw=True).text.strip()
            if not url.startswith("file:"):
                continue
            path = url2pathname(urlparse(url).path)
        if os.path.exists(path):
            return path
    raise ZoteroError(f"Item {key} has no PDF file on this computer.")
