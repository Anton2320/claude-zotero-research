# Installing Sci-Zotero Research

Sci-Zotero Research connects Claude (Claude Code and Cowork) to your **Zotero** library. Claude can
find and download papers into the right collection, read PDFs as Markdown, make high-quality
transcripts, and save reading notes and tags back to Zotero.

About 10 minutes. Works on Linux, macOS and Windows.

---

## What you need

- **Zotero 7** desktop app (https://www.zotero.org/download), signed in to a zotero.org account
  with **sync turned on** (Zotero Settings → Sync). Sync is how Claude's notes get into your library.
- **Claude Code** and/or **Claude Desktop** (for Cowork).
- **uv** (https://docs.astral.sh/uv/getting-started/installation/), e.g. `brew install uv`.
  The server declares its own Python packages, and `uv run` fetches them, and a suitable Python
  if needed, into uv's cache. Nothing is installed into your system Python and there's no
  virtual environment to manage.

---

## Step 1: Turn on Zotero's local API

In Zotero: **Settings → Advanced → General → "Allow other applications on this computer to
communicate with Zotero"**: tick it. Keep Zotero open whenever you use Sci-Zotero Research.

## Step 2: Create a Zotero API key

1. Go to https://www.zotero.org/settings/keys and click **Create new private key**.
2. Name it e.g. "Sci-Zotero Research".
3. Under **Personal Library**, tick **Allow library access**, **Allow notes access** and
   **Allow write access**.
4. Save the key (24 letters and numbers) into the file `~/.claude-research/zotero-api-key.txt`.
   Keep it private.

Without a key everything still works, but Claude can't save notes or tags into Zotero.

## Step 3: Install the plugin

In Claude Code:

```
/plugin marketplace add <owner>/claude-zotero-research
/plugin install sci-zotero-research@claude-zotero-research
```

`<owner>/claude-zotero-research` is the GitHub repository this file is in (see the README). Claude keeps the installed
copy; get new versions with `/plugin marketplace update`. The plugin brings the tools and four
skills, which Claude uses automatically: **find-papers**, **read-paper**, **transcribe-paper**
and **paper-notes**.

The first start of the server takes a minute while uv downloads the packages; later starts are
fast.

## Step 4 (Cowork only): register the server in Claude Desktop

Cowork runs Claude inside a virtual machine, where a server started from the plugin can't reach
Zotero on your computer. Servers listed in Claude Desktop's own config run on your computer and
are passed through to Cowork. To register it there, clone the repository to a folder you'll keep
and run the installer from it:

```
git clone https://github.com/<owner>/claude-zotero-research.git
cd claude-zotero-research
uv run install.py
```

The installer checks your API key with zotero.org, checks that Zotero is running with the local
API on, and adds the server to `claude_desktop_config.json` after asking you (a backup is made
first). It also builds `dist/sci-zotero-research.plugin`, which you can add to Claude Desktop as a
plugin (drag it into a Cowork conversation) for the skills. It's safe to run again at any time.
Then fully quit Claude Desktop and open it again: it only reads its server list at startup.

Don't register the server in both places in the same app; you'd see every tool twice.

## Step 5: Check it works

With Zotero open, start a new conversation and ask:

> Search my Zotero library for papers about <a topic you have>.

Claude should list items from your library. Then try:

> Read the first one and give me a summary with notes saved to Zotero.

Output files (Markdown transcripts and notes) go to `Documents/Claude-Research`, or to `Research`
inside Cowork's files folder when the installer registered the server for Cowork.

---

## Settings

All optional, as environment variables in the server's `env` block:

| Variable | What it does |
|---|---|
| `RESEARCH_DIR` | Output folder for transcripts and notes. |
| `ZOTERO_API_KEY` / `ZOTERO_API_KEY_FILE` | The key itself, or another key file location. |
| `ZOTERO_CONNECTOR_URL` | Zotero's address (default `http://127.0.0.1:23119`). |
| `OPENALEX_API_KEY` | OpenAlex works without a key, but then shares a small free daily budget with everyone on your IP address. A free key (https://openalex.org/settings/api) gives you your own. |
| `SCIHUB_MIRRORS` | Comma-separated Sci-Hub mirror URLs; an empty value turns Sci-Hub off. |

## PDF sources

PDFs come from arXiv for arXiv papers. For other DOIs, open-access copies found through
OpenAlex, CrossRef and Semantic Scholar are tried first (bioRxiv, medRxiv, chemRxiv, Research
Square, open-access journals, repositories), and Sci-Hub last.

Some sites (chemRxiv, MDPI, PubMed Central, Europe PMC) refuse automated downloads. The tools
don't work around that; they return the link so you can open it in a browser and save it with
the Zotero connector.

### Note on Sci-Hub

Whether downloading from Sci-Hub is legal depends on where you live; you're responsible for how
you use it. Turn it off with an empty `SCIHUB_MIRRORS`. Everything else works without it.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| The sci-zotero-research server fails to start | Run `uv run --script server/research_server.py` in the plugin folder and read the error. It should log your Zotero collections and wait for input (Ctrl+C to stop). If Claude can't find `uv`, make sure it's on the PATH Claude is started with. |
| "Zotero is not running" | Open Zotero 7. |
| "Zotero's local API is disabled" | Step 1. |
| Claude doesn't know your collections | Zotero was closed when the server started. Open Zotero and start a new conversation (Claude Desktop: restart it). Same after adding or renaming collections. |
| Notes/tags: "No Zotero web API key found" | Step 2. |
| Notes/tags: "Item not found on zotero.org" | The item hasn't synced yet. Click Zotero's sync button, try again. |

---

## Instructions for an AI assistant doing this install

- **Ask the user** whether they use Claude Code, Cowork or both. The Zotero API key is a
  secret: ask the user to save it into the key file themselves. Don't ask them to paste it into
  chat, and never print, log or copy the key anywhere else.
- **Steps the user must do themselves** (GUI or account settings): step 1, step 2, the
  `/plugin` commands in step 3, and restarting Claude Desktop.
- **Cowork installer, non-interactively**: `uv run install.py --yes --key-file "<key file>"`.
  `--yes` accepts all prompts, including the Claude Desktop config change; ask the user before
  using it. `--skip-desktop` leaves Claude Desktop's config alone.
- **Verify**: the installer prints "Key OK … write access: True", "Zotero is running and its
  local API is enabled" and "Registered" (or "Already registered").
