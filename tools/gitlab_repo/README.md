# GitLab Repository Coding Tool

This native catalog tool preserves all 23 advertised operations: repository
and project reads, branches and forks, file commits, structured text edits,
merge requests, issues and their existing aliases. Admin `Valves` and per-user
`UserValves` retain their original defaults and validation.

Execution remains inside the private tool VM with canonical user settings
and callbacks. Project and path restrictions, protected branches, payload
limits, AI markers and feature controls stay enforced. Operations that need
confirmation retain the existing callback and its disabled-transport refusal.
Authenticated redirects refuse a change of origin before forwarding tokens
or cookies.

The native port corrects one legacy behavior: `commit_file_changes` created a
missing branch before checking dry-run settings. Since catalog version 0.3.5,
explicit dry runs and per-user `dry_run_only` validate changes without creating
a branch. A dedicated native service regression covers both settings.

`tool.json` selects the compiled Rust implementation in
`backend/native/exec-runner/src/native_tools/gitlab/`. `metadata.json` retains
the original catalog metadata; catalog version 0.3.5 records the native port.
Actual legacy helper, schema, file-edit, HTTP and event responses remain
frozen test fixtures in the native runtime.

The original source was `gitlab_adapter.py` from the
[KommI GitLab adapter](https://gitlab.opencode.de/kommi/adapter/gitlab-adapter).
The historical `author: OpenAI` field is preserved. The rights holder is
Boris van Benthem; the [MIT-0 license](LICENSE.MIT-0) and original
[provenance notices](../../SOURCE_NOTICES.md) are retained.
