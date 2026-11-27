---
name: find-papers
description: >
  This skill should be used when the user asks to "find papers on", "search the literature",
  "get/download this paper", "add this to Zotero", gives a DOI or paper title to fetch, or wants
  sources for a research question. Covers searching online (CrossRef, arXiv, open-access sources, Sci-Hub), checking the
  user's Zotero library first, and downloading papers into the right Zotero collection.
metadata:
  version: "0.1.0"
---

# Find and add papers

Use the `sci-zotero-research` MCP tools. The user's Zotero library is the home for every paper.

## Workflow

1. **Check the library first.** Call `zotero_search` with the title, DOI or key terms. If the paper
   is already there, say so (with its collection) and use its key; don't download it again.
2. **Search online** with `find_papers` (DOI, arXiv ID/URL, title or keywords). Keyword searches
   return CrossRef results (journals and preprint servers: chemRxiv, bioRxiv, medRxiv, Research
   Square, SSRN...) and arXiv results. Mark preprints as such, and show where each PDF comes
   from (`pdf_source`: an open-access source, or Sci-Hub). Present results as a short
   numbered list: title, first author, year, venue, and whether a PDF is available.
   Let the user pick when there are several plausible matches; fetch directly when they gave an
   exact DOI or title.
3. **Download** with `download_paper(doi_or_url=<DOI or arXiv ID>)`. It saves to Zotero automatically.
   For arXiv-only papers pass the arXiv ID; they are saved as preprints with the arXiv PDF. If an
   arXiv result has a `published_doi`, prefer that DOI when the user wants the published version.
   - Pick `zotero_collection` from the collection list in the tool description by matching the
     paper's topic. Leave it empty (top level of the library) when nothing clearly fits. Never
     invent collection names.
   - Set `skip_zotero` only if the user explicitly said not to add the paper to Zotero.
   - Pass `output_path` only if the user asked for a local copy.
4. **Report** where each paper went (collection, PDF attached or not) and where the PDF came from.
   If no PDF was found, the item is still saved with metadata; say so. Give the user the links in
   `pdf_attempts` marked "blocked" or "rate-limited" (or a search result's `browser_pdf_url`):
   opening one in a browser with the Zotero connector attaches the PDF. Never try to get around
   a site's bot protection.

## Batches

For "find me N papers on X": search, show the list, and download the ones the user picks (or the
top N if they asked for that), one `download_paper` call each. Summarise in a table at the end.

## Notes

- New items take a few seconds to show up in `zotero_search`.
- If Zotero isn't running, tools return an error saying so: ask the user to open Zotero.
