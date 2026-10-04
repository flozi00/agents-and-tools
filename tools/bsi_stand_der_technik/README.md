# BSI Stand-der-Technik Adapter

This catalog entry runs in the native EU-Prompt executor. Its implementation lives in `backend/native/exec-runner/src/native_tools/bsi/`.

Original author: Florian Schade – Hochsauerlandkreis. Source: https://gitlab.opencode.de/kommi/adapter/bsi_stand_der_technik_tools. The original project declares no license; the complete provenance and rights notice is retained in [SOURCE_NOTICES.md](../../SOURCE_NOTICES.md). No license grant is implied by this port.

All four operations retain OSCAL nesting, parameter substitution, scoring, draft filters, citations and progress. Catalog responses are bounded. Caches and throttling belong to each invocation.
