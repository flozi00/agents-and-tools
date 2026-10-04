# EUPrompt Hub

Public catalog of predefined assistants and tools for EUPrompt installations.
Installations browse this repo under **Workspace → Hub**, install items, and pull
updates when versions change here.

EU-Prompt images bundle this catalog at `/app/hub`, the default `HUB_URL`.
An operator can select a remote catalog or another local checkout through
`HUB_URL`. Remote catalogs are read live; bundled changes arrive with the
application image. This repository is embedded as the `hub/` git submodule.

## Layout

```
index.json                       generated catalog index (commit it)
scripts/generate_index.mjs       regenerates index.json, validates entries
scripts/check_tools.mjs          checks live native-runtime descriptors
tools/<tool_id>/tool.json        native implementation manifest
tools/<tool_id>/metadata.json    native catalog metadata
tools/<tool_id>/tool.py          external Python catalog compatibility
assistants/<assistant_id>/assistant.json
```

The backend reads `index.json`, each tool's selected source (`tool.json` for
`format: "primeline-native"`, otherwise `tool.py`), and
`assistants/<id>/assistant.json`. File locations are derived from ids, never
from paths inside the index. Both tool formats retain the installation's
existing access checks, valves and private execution VM.

## Tools

`tool_id` must be a lowercase Python identifier (letters, digits, underscores).
All 18 bundled tools use compiled native implementations. Their
`tool.json` has exactly three fields:

```json
{ "runtime": "primeline-native", "version": 1, "tool": "calculator" }
```

The integer `version` is the manifest format version. Catalog title,
description and tool version come from sibling `metadata.json`; the catalog
index marks these entries with `format: "primeline-native"`. Native entries
require an installation that supports this format. Unknown implementations,
fields or format versions are refused; the manifest cannot select an
executable or grant access.

Existing external Python catalogs and saved Python tools remain supported.
Their `tool.py` starts with a frontmatter docstring followed by a `class Tools`.
The frontmatter drives the catalog entry:

```python
"""
title: Rechner
description: Kurze Beschreibung für den Katalog.
version: 1.0.0
"""
```

Bump the catalog tool `version` on every content change — installations only
see an update when it differs from what they installed. Native implementation
changes also require the matching EU-Prompt execution image.

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
`tool.py` beziehungsweise in `metadata.json` bei nativen Werkzeugen.
Die ursprünglichen Herkunftsblöcke bleiben zusätzlich in
[SOURCE_NOTICES.md](SOURCE_NOTICES.md) erhalten; der native Ausführungsdienst
liefert die zugehörigen Hinweise und Lizenztexte mit.

## Workflow

1. Add or edit items.
2. `node scripts/generate_index.mjs` (validates and rewrites `index.json`).
3. `node scripts/check_tools.mjs` delegates each source to
   `primeline-exec-runner --describe-tool`, evaluating its live constructor and
   function schemas. Set `PRIMELINE_EXEC_RUNNER_BIN` if the native executable
   is not on PATH. Its interpreter needs the tool's external dependencies;
   missing dependencies produce skip notices, while dead host imports and
   invalid constructors or schemas fail. The command starts no listener and
   installs no packages.
4. Commit everything, including `index.json`.

The helpers require Node.js 18 or newer and use only built-in modules. They
work from a standalone Hub checkout; the checker additionally needs the
native runtime and its matching interpreter environment.
