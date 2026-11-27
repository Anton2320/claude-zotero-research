---
name: read-paper
description: >
  This skill should be used when the user asks to "read this paper", "summarize a paper",
  "what does this paper say about", "explain the method/results of", "compare these papers", or
  asks any question whose answer is in papers stored in their Zotero library.
metadata:
  version: "0.1.0"
---

# Read papers from Zotero

## Workflow

1. **Locate the item.** Use `zotero_search` (title words, author, topic, or a phrase from the
   text). Confirm with the user if several items match. `zotero_get_item` gives the abstract,
   attachments and existing notes; check for earlier `claude-notes` before re-doing work.
2. **Read** with `read_paper(key)`. It returns Markdown in chunks of ~40k characters; keep
   calling with `offset=next_offset` until the parts needed are covered (read the whole paper
   for summaries or critiques).
3. **Check quality.** The first read converts the PDF automatically (fast converter) and saves
   the result as a `claude-transcript` note in Zotero. If equations, tables or reading order look
   garbled and they matter for the question, look at the relevant pages with `get_pdf_pages`,
   or offer a high-quality transcription (see the transcribe-paper skill).
4. **Answer** from the paper's text. Cite page or section for specific claims, quote sparingly,
   and keep what the paper says separate from your own interpretation.

## Figures and tables

Text extraction loses figures. When a figure or table matters, call `get_pdf_pages` for that
page (max 5 pages per call) and read the image.

## Several papers

For comparisons or literature overviews, read each paper, then synthesise in a table
(question/claim × paper). Offer to save the synthesis with `save_markdown(kind="notes")` on the
most relevant item.
