# Sci-Zotero Research

A Claude plugin (Cowork / Claude Code) for research with your **local Zotero library**:

- **Find & download papers** from CrossRef and arXiv. PDFs come from arXiv, then open-access
  copies found through OpenAlex, CrossRef and Semantic Scholar (bioRxiv, medRxiv, chemRxiv,
  Research Square, open-access journals, repositories), and Sci-Hub last. Downloads go
  straight into the best-matching Zotero collection, or the top level of the library.
- **Read papers** from Zotero as Markdown. The first read converts the PDF and stores the
  transcript as a Zotero note.
- **High-quality transcription**: Claude reads page images and writes clean Markdown with math.
- **Reading notes & tags** saved to Zotero, with rendered math.

## Install

Needs [uv](https://docs.astral.sh/uv/) and Zotero 7. In Claude Code:

```
/plugin marketplace add Anton2320/claude-zotero-research
/plugin install sci-zotero-research@claude-zotero-research
```

Update with `/plugin marketplace update`. Zotero settings, the API key for notes and tags, and
Cowork setup: see **[INSTALL.md](INSTALL.md)**.

## Tools

| Tool | What it does |
|---|---|
| `find_papers` | Search CrossRef and arXiv by DOI/arXiv ID/title/keywords; shows where each PDF is available. |
| `download_paper` | Fetch the PDF (open access first) and add the paper to a Zotero collection (opt-out: `skip_zotero`). |
| `zotero_search` | Search your library, including PDF full text and notes. |
| `zotero_get_item` | Metadata, abstract, attachments and notes of an item. |
| `read_paper` | The paper as Markdown (cache → transcript note → PDF conversion), in chunks. |
| `get_pdf_pages` | Page images and text, for figures and high-quality transcription. |
| `save_markdown` | Save a transcript (replaces the old one) or reading notes as Zotero notes. |
| `add_tags` | Tag items. |

Skills: `find-papers`, `read-paper`, `transcribe-paper`, `paper-notes`.

## How it talks to Zotero

- **Reading** uses Zotero's local API on `127.0.0.1:23119` (Zotero must be running).
- **Adding papers** uses Zotero's connector endpoint, the same one the browser extension uses.
- **Notes and tags** go through the zotero.org web API (the local API is read-only) and reach the
  desktop app on its next sync.

## Files written

```
<RESEARCH_DIR>/            default: Cowork's files folder/Research, else ~/Documents/Claude-Research
├── markdown/   <ZoteroKey> - <title>.md   transcripts (cache for read_paper)
└── notes/      <ZoteroKey> - <title>.md   reading notes
```

## Development

Work in a clone of this repository. To try changes, run the server directly with
`uv run --script server/research_server.py`; helper modules in `server/` are reloaded while it
runs when their files change. `python build_plugin.py` validates and builds
`dist/sci-zotero-research.plugin` for Claude Desktop; `--share` also builds a project zip. Both use a
whitelist of files, so API key files are never packed.
