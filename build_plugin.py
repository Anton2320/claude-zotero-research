"""Validate the plugin and package it.

    python build_plugin.py           -> dist/sci-zotero-research.plugin   (install into Claude)
    python build_plugin.py --share   -> dist/sci-zotero-research-<version>.zip  (the whole project, to share)

Only whitelisted paths are packed, so local secrets (e.g. an API key file) never end up in them.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN = [".claude-plugin", "server", "skills", "README.md", "LICENSE"]
SHARE = PLUGIN + ["INSTALL.md", "install.py", "build_plugin.py", ".gitignore"]
EXCLUDE = re.compile(r"(__pycache__|\.pyc$|\.key$|api[- ]?key|Zotero API\.txt$)", re.I)


def validate():
    errors = []
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", manifest.get("name", "")):
        errors.append("plugin.json: name must be kebab-case")
    if "mcpServers" not in manifest:
        errors.append("plugin.json: mcpServers missing")
    for skill in (ROOT / "skills").iterdir():
        md = skill / "SKILL.md"
        if not md.exists():
            errors.append(f"{skill.name}: missing SKILL.md")
            continue
        front = re.match(r"---\n(.*?)\n---", md.read_text(encoding="utf-8"), re.S)
        if not front or f"name: {skill.name}" not in front.group(1) or "description:" not in front.group(1):
            errors.append(f"{skill.name}: frontmatter needs 'name: {skill.name}' and a description")
        elif re.search(r"<[^>\s]+>", front.group(1)):
            errors.append(f"{skill.name}: frontmatter/description cannot contain XML tags (e.g. <paper>)")
    if errors:
        sys.exit("Validation failed:\n  " + "\n  ".join(errors))
    return manifest


def _files(entries):
    files = []
    for entry in entries:
        p = ROOT / entry
        files += [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p]
    return [f for f in files if not EXCLUDE.search(f.relative_to(ROOT).as_posix())]


def _zip(out, files, prefix="", extra=()):
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, prefix + f.relative_to(ROOT).as_posix())
        for f, arcname in extra:
            z.write(f, prefix + arcname)
    return out


def main(share=False):
    manifest = validate()
    plugin = _zip(ROOT / "dist" / f"{manifest['name']}.plugin", _files(PLUGIN))
    print(f"Validated and packaged -> {plugin}")
    if share:
        name = f"{manifest['name']}-{manifest['version']}"
        out = _zip(ROOT / "dist" / f"{name}.zip", _files(SHARE), prefix=f"{name}/",
                   extra=[(plugin, f"dist/{plugin.name}")])
        print(f"Shareable project -> {out}")


if __name__ == "__main__":
    main(share="--share" in sys.argv)
