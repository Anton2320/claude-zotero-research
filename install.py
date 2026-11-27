# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.31"]
# ///
"""Set up Sci-Zotero Research on this computer. Safe to re-run.

    uv run install.py                      # interactive
    uv run install.py --yes --key-file K   # non-interactive (e.g. run by an AI assistant)

Steps: store and verify the Zotero API key, check Zotero, register the MCP server in Claude
Desktop's config (needed for Cowork), and build the plugin file. Python packages are not
installed here: the server declares them itself and `uv run` fetches them into its cache.
Run it from the folder where the project will stay; Claude Desktop runs the server from here.
"""
import argparse
import getpass
import json
import os
import platform
import re
import shutil
import sys
import time
from pathlib import Path

import build_plugin

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server" / "research_server.py"
KEY_FILE = Path.home() / ".claude-research" / "zotero-api-key.txt"
ZOTERO = "http://127.0.0.1:23119"


def step(msg):
    print(f"\n== {msg}")


def ask(question, assume_yes):
    if assume_yes:
        return True
    return input(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes")


def desktop_config_path():
    system = platform.system()
    if system == "Windows":
        return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def setup_key(key_file_arg, assume_yes):
    import requests

    step("Zotero web API key (for writing notes and tags)")
    key = ""
    source = Path(key_file_arg) if key_file_arg else None
    if source is None and KEY_FILE.exists():
        source = KEY_FILE
    if source:
        found = re.findall(r"\b[A-Za-z0-9]{24}\b", source.read_text(encoding="utf-8-sig"))
        key = found[-1] if found else ""
        if not key:
            print(f"No 24-character key found in {source}.")
    if not key and not assume_yes:
        print("Create one at https://www.zotero.org/settings/keys (allow library access, notes and write).")
        key = getpass.getpass("Paste the key (input hidden, Enter to skip): ").strip()
    if not key:
        print("Skipped: Claude can read your library but won't be able to save notes or tags.")
        return
    try:
        r = requests.get("https://api.zotero.org/keys/current",
                         headers={"Zotero-API-Key": key, "Zotero-API-Version": "3"}, timeout=20)
    except requests.RequestException as e:
        print(f"Could not verify the key ({e}); storing it anyway.")
        r = None
    if r is not None and r.status_code != 200:
        sys.exit(f"Zotero rejected the key (HTTP {r.status_code}). Check it and run again.")
    if r is not None:
        access = r.json().get("access", {}).get("user", {})
        print(f"Key OK for Zotero user {r.json().get('userID')}; write access: {access.get('write', False)}")
        if not access.get("write"):
            print("WARNING: this key can't write. Enable 'Allow write access' for it on zotero.org.")
    KEY_FILE.parent.mkdir(exist_ok=True)
    KEY_FILE.write_text(key + "\n", encoding="utf-8")
    if platform.system() != "Windows":
        KEY_FILE.chmod(0o600)
    print(f"Stored in {KEY_FILE}")


def check_zotero():
    import requests

    step("Checking Zotero")
    try:
        requests.get(f"{ZOTERO}/connector/ping", timeout=5)
    except requests.RequestException:
        print("Zotero isn't running. Start Zotero 7 and re-run this check later (the rest still works).")
        return
    r = requests.get(f"{ZOTERO}/api/users/0/collections?limit=1", timeout=5)
    if r.status_code == 200:
        print("Zotero is running and its local API is enabled.")
    else:
        print("Zotero is running but its local API is OFF. Enable it: Zotero Settings > Advanced > "
              "'Allow other applications on this computer to communicate with Zotero'.")


def register_desktop(assume_yes, skip):
    step("Registering the MCP server in Claude Desktop (needed for Cowork)")
    if skip:
        print("Skipped (--skip-desktop).")
        return
    path = desktop_config_path()
    try:
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError as e:
        sys.exit(f"{path} isn't valid JSON ({e}); left it untouched. Fix it or add the entry by hand "
                 "(see INSTALL.md), then re-run.")
    files_dir = cfg.get("coworkUserFilesPath")
    research_dir = Path(files_dir) / "Research" if files_dir else Path.home() / "Documents" / "Claude-Research"
    uv = shutil.which("uv")
    if not uv:
        sys.exit("uv isn't on PATH. Install it (https://docs.astral.sh/uv/) and run again.")
    entry = {
        "command": uv,
        "args": ["run", "--quiet", "--script", str(SERVER)],
        "env": {"RESEARCH_DIR": str(research_dir), "PYTHONIOENCODING": "utf-8"},
    }
    if cfg.get("mcpServers", {}).get("sci-zotero-research") == entry:
        print(f"Already registered in {path}")
        return
    print(f"Config: {path}\nServer: {uv} run --script {SERVER}\nFiles:  {research_dir}")
    if not ask("Add/update the 'sci-zotero-research' entry?", assume_yes):
        print("Skipped.")
        return
    if path.exists():
        backup = path.with_suffix(f".json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg.setdefault("mcpServers", {})["sci-zotero-research"] = entry
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("Registered. Fully quit Claude Desktop (including the tray/menu-bar icon) and reopen it.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="don't ask questions; accept defaults")
    parser.add_argument("--key-file", help="text file containing the Zotero API key")
    parser.add_argument("--skip-desktop", action="store_true", help="don't touch Claude Desktop's config")
    args = parser.parse_args()

    setup_key(args.key_file, args.yes)
    check_zotero()
    register_desktop(args.yes, args.skip_desktop)
    step("Building the plugin")
    build_plugin.main()
    print(f"\nDone. Restart Claude Desktop, then add {ROOT / 'dist' / 'sci-zotero-research.plugin'} "
          "as a plugin (INSTALL.md, step 6).")


if __name__ == "__main__":
    main()
