# MediaWiki Suche

This Hub entry uses `tool.json` to select the native `mediawiki` implementation
in `backend/native/exec-runner/src/native_tools/mediawiki/`. `metadata.json`
preserves the original catalog metadata; version 0.4.1 makes the native format
available as an update to the previous 0.4 entry. The frozen runtime descriptor
retains the original version, public methods, Valves and citation flags.

The Rust implementation owns search pagination and query fallback, page metadata
and links, file extraction, upload-result handling and awaited progress/citation
events. Requests and pypdf remain third-party compatibility dependencies. Responses
are bounded to 32 MiB before JSON decoding; actual downloads also enforce the
configured `max_file_bytes` limit, including when server metadata is incorrect.

The recorded original behavior is retained: the HTTP session captures default
Valves during construction, so configured Basic Auth and TLS settings do not reach
that session. Missing upload callbacks return the original warning and filename
metadata. Twenty-five recorded service cases cover exact returned JSON text,
requests and events, including real text and PDF attachments.

`NOTICE` preserves the MediaWiki-Adapter provenance, original author and extension
attribution. The original source project declares no license. This native entry
does not grant a license to the original adapter or change the original rights
statement; the catalog notice provides for removal at the author's request.
