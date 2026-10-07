# EUPrompt Hub

Public catalog of predefined assistants, tools and apps for EUPrompt installations.
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
scripts/add_app.mjs              adds an app exported from EU-Prompt
tools/<tool_id>/tool.json        native implementation manifest
tools/<tool_id>/metadata.json    native catalog metadata
tools/<tool_id>/tool.py          external Python catalog compatibility
assistants/<assistant_id>/assistant.json
apps/<app_id>/app.json
```

The backend reads `index.json`, each tool's selected source (`tool.json` for
`format: "primeline-native"`, otherwise `tool.py`), and
`assistants/<id>/assistant.json` and `apps/<id>/app.json`. File locations are derived from ids, never
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
`builtin_tools` (category toggles, e.g. `{ "web": true }`), `apps` (hub app ids;
each is created as a new app when the assistant is first installed).

Portability rules — assistants must work on every installation, so a template
**never** contains: a base model (chosen at install time), access grants,
knowledge bases, or references to tool servers / MCP connections. `tools` may
only list tool ids from this hub; they are installed as dependencies. `apps` may
only list app ids from this hub.

## Apps

An app is a ready-made EU-Prompt app (record types, views, dashboard,
automations, optional sample records) in the portable template format the app
page downloads (**App → Settings → Download template**). `app_id` must be
lowercase kebab-case; `app.json` needs `id`, `name`, `version`, `description`
and non-empty `record_types`.

Every installation lists hub apps in its app template gallery, and agents find
them through `list_app_templates`, so anyone allowed to create apps — and their
agents — can install one. Each install creates a new app; its automations start
paused and the creator decides who gets access.

To share an app:

```sh
node scripts/add_app.mjs ~/Downloads/my-app.json [app-id] [version]
```

The script derives a kebab-case id, sets `version` (default `1.0.0`), removes
installation-local keys (`access_grants`, `exported_at`, `source_project_id`,
`source_project_name`) and regenerates `index.json`. It warns when records are
included: publish only sample data, never client data. Bump `version` when you
replace an app.

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
