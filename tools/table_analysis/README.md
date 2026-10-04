# Tabellenanalyse & Statistik

The catalog entry executes the native implementation in
`backend/native/exec-runner/src/native_tools/table_analysis/`.
It preserves the original KommI adapter's five operations and uses pandas,
NumPy, SciPy, openpyxl, and pdfplumber for the existing file and numerical
primitives. Its recorded compatibility cases cover CSV, Excel sheets, PDF
tables, statistics, pivot and time-series analysis, progress events, and
refusals.

The original adapter was written by Boris van Benthem, KommI – Kommunale
Intelligenz: https://gitlab.opencode.de/kommi/adapter/tabellen-analyse.
Its MIT No Attribution license and copyright are preserved in
[LICENSE.MIT-0](LICENSE.MIT-0). Catalog provenance also remains in
`metadata.json` and the native descriptor.

The original helper captured default Valves before the executor replaced the
tool's Valves. The native replacement preserves that recorded behavior;
validated configuration values do not change the helper's runtime limits.
