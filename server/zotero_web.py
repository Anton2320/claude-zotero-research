"""Write notes and tags to Zotero through the Zotero web API (api.zotero.org).

Zotero's local API is read-only, so writes go through the web API and reach the desktop app
on its next sync. Needs an API key with write access (zotero.org/settings/keys), found in:
ZOTERO_API_KEY, the file named by ZOTERO_API_KEY_FILE, or ~/.claude-research/zotero-api-key.txt.
"""
import os
import re
from pathlib import Path

import requests

BASE = "https://api.zotero.org"
TIMEOUT = 30
DEFAULT_KEY_FILE = Path.home() / ".claude-research" / "zotero-api-key.txt"

_user_id = None


class ZoteroWebError(Exception):
    pass


def _api_key():
    key = os.environ.get("ZOTERO_API_KEY", "").strip()
    key_file = os.environ.get("ZOTERO_API_KEY_FILE") or DEFAULT_KEY_FILE
    if not key and os.path.exists(key_file):
        try:
            with open(key_file, encoding="utf-8-sig") as f:
                found = re.findall(r"\b[A-Za-z0-9]{24}\b", f.read())
            key = found[-1] if found else ""
        except OSError as e:
            raise ZoteroWebError(f"Could not read {key_file}: {e}")
    if not key:
        raise ZoteroWebError(f"No Zotero web API key found (ZOTERO_API_KEY, ZOTERO_API_KEY_FILE or {DEFAULT_KEY_FILE}). "
                             "Writing notes and tags needs one; create it at https://www.zotero.org/settings/keys")
    return key


def is_configured():
    try:
        _api_key()
        return True
    except ZoteroWebError:
        return False


def _request(method, path, **kwargs):
    global _user_id
    headers = {"Zotero-API-Key": _api_key(), "Zotero-API-Version": "3", **kwargs.pop("headers", {})}
    if _user_id is None and path != "/keys/current":
        _user_id = _request("GET", "/keys/current").json()["userID"]
    url = BASE + path.replace("{user}", f"users/{_user_id}")
    try:
        r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as e:
        raise ZoteroWebError(f"Could not reach api.zotero.org: {e}")
    if r.status_code == 403:
        raise ZoteroWebError("The Zotero API key was rejected or lacks write access.")
    if r.status_code == 404:
        raise ZoteroWebError("Item not found on zotero.org. If it was added just now, wait for Zotero to "
                             "sync (or click the sync button in Zotero) and try again.")
    if r.status_code >= 400:
        raise ZoteroWebError(f"Zotero web API error: HTTP {r.status_code} {r.text[:300]}")
    return r


def _write_result(r):
    body = r.json()
    if body.get("failed"):
        failure = next(iter(body["failed"].values()))
        msg = failure.get("message", "")
        if "parent" in msg.lower():
            msg += " (the parent item may not have synced to zotero.org yet; sync Zotero and retry)"
        raise ZoteroWebError(f"Zotero refused the write: {msg}")
    return next(iter(body["successful"].values()))["key"]


def create_note(parent_key, html, tags=()):
    """Add a child note to an item. Returns the new note's key."""
    r = _request("POST", "/{user}/items", json=[{
        "itemType": "note", "parentItem": parent_key, "note": html,
        "tags": [{"tag": t} for t in tags],
    }])
    return _write_result(r)


def update_note(note_key, html):
    """Replace a note's content, keeping its tags. Returns the note key."""
    current = _request("GET", f"/{{user}}/items/{note_key}").json()
    _request("PATCH", f"/{{user}}/items/{note_key}", json={"note": html},
             headers={"If-Unmodified-Since-Version": str(current["version"])})
    return note_key


def add_tags(item_key, tags):
    """Add tags to an item (existing tags are kept). Returns the full tag list."""
    current = _request("GET", f"/{{user}}/items/{item_key}").json()
    existing = current["data"].get("tags", [])
    names = {t["tag"] for t in existing}
    merged = existing + [{"tag": t} for t in tags if t not in names]
    _request("PATCH", f"/{{user}}/items/{item_key}", json={"tags": merged},
             headers={"If-Unmodified-Since-Version": str(current["version"])})
    return [t["tag"] for t in merged]


def find_child_note(parent_key, tag):
    """Key of the first child note with `tag`, looked up on zotero.org (sees unsynced-to-desktop notes)."""
    r = _request("GET", f"/{{user}}/items/{parent_key}/children", params={"itemType": "note", "tag": tag})
    items = r.json()
    return items[0]["key"] if items else None
