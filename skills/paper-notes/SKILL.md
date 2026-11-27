---
name: paper-notes
description: >
  This skill should be used when the user asks to "take notes on", "make notes for",
  "annotate", "critique", "write a reading summary", "save this to Zotero", or "tag this paper",
  or after reading a paper together when the discussion is worth keeping.
metadata:
  version: "0.1.0"
---

# Reading notes in Zotero

Notes are saved as Zotero child notes (tag `claude-notes`) and as local Markdown files.

## Workflow

1. Read the paper (read-paper skill) unless it was just read in this conversation.
2. Check `zotero_get_item` for existing `claude-notes`; build on them rather than duplicating.
3. Write the note with the structure below, adapted to what the user cares about. Fold in points
   from the conversation (the user's own ideas labelled as such).
4. Save with `save_markdown(key, markdown, kind="notes", title=...)`.
5. Offer tags with `add_tags` (e.g. `read`, a topic, a method, a project name). Keep tag names
   consistent with tags already in the library (see `zotero_search` results).

## Note structure

```markdown
## Summary
Two or three sentences: question, approach, main finding.

## Key claims
- Claim — evidence (section/page, figure/table).

## Methods
Data, design, analysis; anything unusual.

## Results
Main numbers with units and uncertainty. Math as $...$.

## Limitations and open questions
What the paper doesn't show; threats to validity.

## Relevance
How it connects to the user's project and other papers in the library.

## Quotes
> "Short quote." (p. N)
```

Keep notes dense and specific: numbers, conditions and page references beat adjectives.
