---
name: transcribe-paper
description: >
  This skill should be used when the user asks to "transcribe this paper", "convert the PDF to
  Markdown", "make a clean/high-quality text version", "fix the garbled equations", or when a
  paper's automatic conversion is poor (math-heavy, complex tables, multi-column layout).
metadata:
  version: "0.1.0"
---

# High-quality transcription (PDF → Markdown in Zotero)

`read_paper` already makes a fast automatic transcript. Use this skill when fidelity matters:
it reads page images and rewrites them as clean Markdown with LaTeX math.

## Workflow

1. Find the item key (`zotero_search`) and the page count (first `get_pdf_pages` call reports it).
2. Transcribe in batches of up to 5 pages with `get_pdf_pages(key, first_page, last_page)`.
   - If subagents are available, give each one a page range (e.g. 1–5, 6–10, …) with the rules
     below and have it return only the Markdown for its range. Run them in parallel.
   - Otherwise work through the batches in order.
3. Join the batches in page order, fix paragraphs and sentences split across batch boundaries,
   and save once with `save_markdown(key, markdown, kind="transcript")`. This replaces the
   automatic transcript note in Zotero and the local cache, so later `read_paper` calls use it.
4. Tell the user it's done and mention anything that couldn't be transcribed reliably.

## Transcription rules

- Faithful text: no summarising, no corrections of the authors' content. Mark unreadable spots
  as `[illegible]`.
- Structure: `#` for the title, `##`/`###` for sections; keep the paper's numbering.
- Drop running headers/footers, page numbers and line numbers. Join hyphenated line breaks.
- Math: inline `$...$`, display `$$...$$`, in standard LaTeX. Keep equation numbers as `\tag{n}`.
- Tables: Markdown tables; for very complex tables, a simplified table plus a note.
- Figures: `> [Figure N: caption] — one or two sentences describing what the figure shows.`
- Footnotes: `[^n]` markers with the footnote text at the end of the section.
- References: keep the reference list, one entry per line.
- Add `<!-- page N -->` at each page start so passages can be cited by page.
