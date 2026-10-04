# GitLab CI Pipeline Results Tool

This native catalog tool preserves the seven read-only GitLab operations:
pipeline listing and lookup, pipeline details and jobs, bounded job traces,
test reports and debugging summaries. It does not create, retry, cancel or
modify pipelines, jobs or repository content.

Configure the same admin `Valves` and per-user `UserValves`. Existing OAuth
credentials take precedence over the admin token. Project restrictions,
trace bounds and secret redaction remain enforced in the private execution
VM. Status events use the existing authenticated callback. Authenticated
redirects refuse a change of origin before forwarding tokens or cookies.

`tool.json` selects the compiled Rust implementation in
`backend/native/exec-runner/src/native_tools/gitlab/`. `metadata.json` retains
the original catalog metadata; catalog version 0.1.1 records the native port.
Actual legacy helper, schema, HTTP and event responses remain frozen test
fixtures in the native runtime.

The original source was `gitlab_ci_pipeline_adapter.py` from the
[KommI GitLab adapter](https://gitlab.opencode.de/kommi/adapter/gitlab-adapter).
The historical `author: OpenAI` field is preserved. The rights holder is
Boris van Benthem; the [MIT-0 license](LICENSE.MIT-0) and original
[provenance notices](../../SOURCE_NOTICES.md) are retained.
