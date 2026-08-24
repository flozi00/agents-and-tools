# EUPrompt Hub

Public catalog of predefined assistants and tools for EUPrompt installations.
Installations browse this repo under **Workspace → Hub**, install items, and pull
updates when versions change here.

Installations read this repo live via `HUB_URL`
(default `https://raw.githubusercontent.com/flozi00/agents-and-tools/main`), so
every merge to `main` is visible to all installations immediately — no redeploy.
For development this repo is embedded in the main repo as the `hub/` git
submodule; `HUB_URL` can also point to a local checkout.

## Layout

```
index.json                       generated catalog index (commit it)
scripts/generate_index.py        regenerates index.json, validates entries
tools/<tool_id>/tool.py          one tool per directory
assistants/<assistant_id>/assistant.json
```

The backend only ever reads `index.json`, `tools/<id>/tool.py`, and
`assistants/<id>/assistant.json` — file locations are derived from ids, never
from paths inside the index.

## Tools

`tool_id` must be a lowercase Python identifier (letters, digits, underscores).
`tool.py` is a standard EUPrompt tool module: a frontmatter docstring followed by
a `class Tools`. The frontmatter drives the catalog entry:

```python
"""
title: Rechner
description: Kurze Beschreibung für den Katalog.
version: 1.0.0
"""
```

Bump `version` on every content change — installations only see an update when
the version differs from what they installed.

## Assistants

`assistant_id` must be lowercase kebab-case. `assistant.json`:

```json
{
	"id": "email-profi",
	"name": "E-Mail-Profi",
	"version": "1.0.0",
	"description": "Kurze Beschreibung für den Katalog.",
	"system_prompt": "…",
	"params": { "temperature": 0.4 },
	"suggestion_prompts": [{ "content": "…" }],
	"tools": ["calculator"]
}
```

Optional keys: `profile_image_url` (https URL or data URI), `capabilities`,
`builtin_tools` (category toggles, e.g. `{ "web": true }`).

Portability rules — assistants must work on every installation, so a template
**never** contains: a base model (chosen at install time), access grants,
knowledge bases, or references to tool servers / MCP connections. `tools` may
only list tool ids from this hub; they are installed as dependencies.

## Übernommene Werkzeuge

Herkunft, Urheber und Lizenz übernommener Werkzeuge stehen in
[THIRD_PARTY.md](THIRD_PARTY.md) und zusätzlich im Kopf jeder betroffenen
`tool.py`, damit die Angabe auch bei einer installierten Kopie erhalten
bleibt.

## Workflow

1. Add or edit items.
2. `python3 scripts/generate_index.py` (validates and rewrites `index.json`).
3. `python3 scripts/check_tools.py` — lädt jede `tool.py` und baut ihre
   Function-Specs, wie es die Installation zur Laufzeit tut. Braucht die in
   den `requirements:` genannten Pakete.
4. Commit everything, including `index.json`.
