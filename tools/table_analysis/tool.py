"""
title: Tabellenanalyse & Statistik
author: OpenAI
author_url: https://openai.com
git_url: https://gitlab.opencode.de/kommi/adapter/tabellen-analyse
description: Analysiert angehängte Excel-, CSV- und PDF-Dateien in Open WebUI, erstellt Profiling, Pivot-/Zeitraumanalysen und wendet statistische Methoden auf Tabellendaten an.
required_open_webui_version: 0.1.0
requirements: pandas,numpy,scipy,openpyxl,pdfplumber
version: 0.1.0
license: MIT No Attribution (MIT-0)
original_author: KommI – Kommunale Intelligenz (Boris van Benthem)
source_url: https://gitlab.opencode.de/kommi/adapter/tabellen-analyse
"""

# --------------------------------------------------------------------------
# Herkunft / Provenance
#
# Übernommen aus dem KommI-Adapter-Katalog (openCode). Der Code ist
# gegenüber dem Original unverändert; ergänzt wurden ausschließlich dieser
# Herkunftshinweis und Katalog-Metadaten im Kopf.
#
#   Projekt : Tabellen-Analyse
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/tabellen-analyse
#   Datei   : table_analysis.py
#   Autor   : KommI – Kommunale Intelligenz (Boris van Benthem)
#   Lizenz  : MIT No Attribution (MIT-0)
#
# LICENSE-Datei des Quellprojekts, wortgleich übernommen.
# --------------------------------------------------------------------------
# MIT No Attribution
#
# Copyright 2026 Boris van Benthem
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# --------------------------------------------------------------------------

from __future__ import annotations

import csv
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import pdfplumber
from pydantic import BaseModel, Field
from scipy import stats


class _TableAnalysisHelper:
    def __init__(self, valves: "Tools.Valves"):
        self.valves = valves

    async def _emit_status(
        self,
        emitter: Optional[Any],
        description: str,
        done: bool = False,
        status: str = "in_progress",
    ) -> None:
        if emitter is None:
            return
        try:
            await emitter(
                {
                    "type": "status",
                    "data": {
                        "status": status,
                        "description": description,
                        "done": done,
                    },
                }
            )
        except Exception:
            return

    async def _emit_start(
        self, emitter: Optional[Any], name: str, detail: str = ""
    ) -> None:
        message = f"{name}: Start"
        if detail:
            message += f" – {detail}"
        await self._emit_status(emitter, message, done=False, status="in_progress")

    async def _emit_end(
        self, emitter: Optional[Any], name: str, detail: str = ""
    ) -> None:
        message = f"{name}: Ende"
        if detail:
            message += f" – {detail}"
        await self._emit_status(emitter, message, done=True, status="complete")

    async def _emit_error(self, emitter: Optional[Any], name: str, detail: str) -> None:
        await self._emit_status(
            emitter, f"{name}: Fehler – {detail}", done=True, status="error"
        )

    def _json_default(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating, float)):
            if math.isnan(value) or math.isinf(value):
                return None
            return float(value)
        if isinstance(value, (np.bool_, bool)):
            return bool(value)
        if isinstance(value, (pd.Timestamp,)):
            return value.isoformat()
        if isinstance(value, (pd.Timedelta,)):
            return str(value)
        return value

    def _convert_for_json(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {str(k): self._convert_for_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._convert_for_json(v) for v in obj]
        if isinstance(obj, tuple):
            return [self._convert_for_json(v) for v in obj]
        if isinstance(obj, pd.DataFrame):
            return obj.replace({np.nan: None}).to_dict(orient="records")
        if isinstance(obj, pd.Series):
            return {
                str(k): self._convert_for_json(v)
                for k, v in obj.replace({np.nan: None}).to_dict().items()
            }
        return self._json_default(obj)

    def _to_json_text(self, payload: Any) -> str:
        return json.dumps(self._convert_for_json(payload), ensure_ascii=False, indent=2)

    def _apply_output_limit(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            rendered = self._to_json_text(payload)
        except Exception:
            return payload
        if len(rendered) <= self.valves.max_output_chars:
            return payload

        compact = dict(payload)
        compact["output_limited"] = True
        compact["output_limit"] = {
            "max_output_chars": self.valves.max_output_chars,
            "original_chars_estimate": len(rendered),
        }
        for key in [
            "preview",
            "descriptive_statistics",
            "correlations",
            "normality_tests",
            "outliers_iqr",
            "pivot",
            "time_series",
        ]:
            if key in compact:
                value = compact[key]
                if (
                    isinstance(value, list)
                    and len(value) > self.valves.max_rows_preview
                ):
                    compact[key] = value[: self.valves.max_rows_preview]
                elif isinstance(value, dict):
                    limited_items = list(value.items())[: self.valves.max_dict_items]
                    compact[key] = {k: v for k, v in limited_items}
        try:
            rendered2 = self._to_json_text(compact)
            if len(rendered2) <= self.valves.max_output_chars:
                return compact
        except Exception:
            return compact

        minimal = {
            "ok": compact.get("ok", True),
            "file": compact.get("file"),
            "shape": compact.get("shape"),
            "summary": compact.get(
                "summary", "Ergebnis wurde wegen Größenlimit zusammengefasst."
            ),
            "output_limited": True,
            "output_limit": compact["output_limit"],
        }
        return minimal

    def dumps(self, payload: dict[str, Any]) -> str:
        # Für Tabellenanalyse (vollständige Struktur wichtig) KEIN Output-Limit anwenden
        if "columns_list" not in payload:
            payload = self._apply_output_limit(payload)
        return json.dumps(self._convert_for_json(payload), ensure_ascii=False, indent=2)

    def _normalize_files(self, files: Optional[list]) -> list[dict[str, Any]]:
        if not files:
            return []
        normalized = []
        for item in files:
            if isinstance(item, dict):
                normalized.append(item)
            else:
                try:
                    normalized.append(dict(item))
                except Exception:
                    normalized.append({"raw": repr(item)})
        return normalized

    def _candidate_paths(self, item: dict[str, Any]) -> list[str]:
        paths = []
        direct_keys = ["path", "file_path", "local_path", "filepath", "full_path"]
        nested_keys = ["file", "meta", "data"]
        for key in direct_keys:
            value = item.get(key)
            if isinstance(value, str):
                paths.append(value)
        for key in nested_keys:
            nested = item.get(key)
            if isinstance(nested, dict):
                for dkey in direct_keys:
                    value = nested.get(dkey)
                    if isinstance(value, str):
                        paths.append(value)
        return [p for p in paths if p]

    def _candidate_names(self, item: dict[str, Any]) -> list[str]:
        names = []
        direct_keys = ["name", "filename", "file_name"]
        nested_keys = ["file", "meta", "data"]
        for key in direct_keys:
            value = item.get(key)
            if isinstance(value, str):
                names.append(value)
        for key in nested_keys:
            nested = item.get(key)
            if isinstance(nested, dict):
                for dkey in direct_keys:
                    value = nested.get(dkey)
                    if isinstance(value, str):
                        names.append(value)
        return [n for n in names if n]

    def _is_supported_file(self, name: str) -> bool:
        suffix = Path(name.lower()).suffix
        return suffix in {".csv", ".xlsx", ".xls", ".pdf"}

    def _select_file(
        self, files: Optional[list], file_name: str = ""
    ) -> dict[str, Any]:
        normalized = self._normalize_files(files)
        supported: list[dict[str, Any]] = []
        for item in normalized:
            names = self._candidate_names(item)
            if any(self._is_supported_file(name) for name in names):
                supported.append(item)

        if not supported:
            raise ValueError(
                "Keine unterstützte CSV-/Excel-/PDF-Datei im Anhang gefunden."
            )

        if file_name:
            for item in supported:
                if file_name in self._candidate_names(item):
                    return item
            raise ValueError(f"Datei '{file_name}' wurde im Anhang nicht gefunden.")

        return supported[0]

    def _resolve_existing_path(self, item: dict[str, Any]) -> str:
        for p in self._candidate_paths(item):
            if os.path.exists(p):
                return p
        raise ValueError(
            "Die angehängte Datei wurde erkannt, aber es konnte kein lesbarer lokaler Dateipfad ermittelt werden. "
            "Bitte prüfe die Dateimetadaten deiner Open-WebUI-Installation."
        )

    def _extract_sep_directive(
        self, path: str, encoding: str
    ) -> tuple[Optional[str], int, bool]:
        encodings = [encoding, "utf-8", "utf-8-sig", "latin-1", "cp1252"]
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc, errors="ignore") as handle:
                    first_line = handle.readline().strip()
                if first_line.lower().startswith("sep=") and len(first_line) >= 5:
                    return first_line.split("=", 1)[1].strip() or None, 1, True
                return None, 0, False
            except Exception:
                continue
        return None, 0, False

    def _sniff_csv_delimiter(self, path: str, encoding: str) -> Optional[str]:
        encodings = [encoding, "utf-8", "utf-8-sig", "latin-1", "cp1252"]
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc, errors="ignore") as handle:
                    sample = handle.read(4096)
                dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "	", "|"])
                return dialect.delimiter
            except Exception:
                continue
        return None

    def _read_csv(
        self, path: str, delimiter: str, encoding: str
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        sep_from_header, skiprows, sep_header_detected = self._extract_sep_directive(
            path, encoding
        )
        effective_delimiter = (
            sep_from_header
            or delimiter
            or self._sniff_csv_delimiter(path, encoding)
            or ","
        )
        encodings = [encoding, "utf-8", "utf-8-sig", "latin-1", "cp1252"]
        last_error = None
        for enc in encodings:
            try:
                df = pd.read_csv(
                    path, sep=effective_delimiter, encoding=enc, skiprows=skiprows
                )
                return df, {
                    "delimiter": effective_delimiter,
                    "skiprows": skiprows,
                    "sep_header_detected": sep_header_detected,
                    "encoding_used": enc,
                }
            except Exception as exc:
                last_error = exc
        raise ValueError(f"CSV-Datei konnte nicht gelesen werden: {last_error}")

    def _read_pdf_tables(
        self, path: str, table_index: int = 0, page_numbers: Optional[list[int]] = None
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        tables: list[dict[str, Any]] = []
        with pdfplumber.open(path) as pdf:
            pages = (
                range(len(pdf.pages))
                if not page_numbers
                else [p - 1 for p in page_numbers if p >= 1]
            )
            for page_no in pages:
                if page_no < 0 or page_no >= len(pdf.pages):
                    continue
                page = pdf.pages[page_no]
                extracted = page.extract_tables() or []
                for idx, table in enumerate(extracted):
                    if not table or len(table) < 1:
                        continue
                    header = table[0]
                    rows = table[1:] if len(table) > 1 else []
                    if not header:
                        continue
                    width = len(header)
                    cleaned_rows = []
                    for row in rows:
                        row = (row or [])[:width] + [None] * max(
                            0, width - len(row or [])
                        )
                        cleaned_rows.append(row[:width])
                    df = pd.DataFrame(cleaned_rows, columns=header)
                    tables.append(
                        {
                            "page": page_no + 1,
                            "table_on_page": idx,
                            "dataframe": df,
                        }
                    )
        if not tables:
            raise ValueError("In der PDF-Datei wurden keine Tabellen erkannt.")
        if table_index < 0 or table_index >= len(tables):
            raise ValueError(
                f"table_index {table_index} ist ungültig. Verfügbare Tabellen: 0 bis {len(tables)-1}."
            )
        selected = tables[table_index]
        return selected["dataframe"], {
            "table_index": table_index,
            "page": selected["page"],
            "detected_tables": len(tables),
            "available_tables": [
                {
                    "table_index": i,
                    "page": t["page"],
                    "rows": int(t["dataframe"].shape[0]),
                    "columns": int(t["dataframe"].shape[1]),
                }
                for i, t in enumerate(tables[: self.valves.max_tables_metadata])
            ],
        }

    def _parse_number_text(self, value: str) -> Optional[float]:
        text = str(value).strip().replace(" ", " ")
        if not text:
            return None
        text = text.replace("−", "-")
        match = re.match(
            r"^\s*([+-]?(?:\d+(?:[\.,]\d+)?|\d{1,3}(?:[\.,\s]\d{3})+(?:[\.,]\d+)?))(?:\s*([^\d\s].*?))?\s*$",
            text,
        )
        if not match:
            return None
        num = match.group(1).replace(" ", "")
        if "," in num and "." in num:
            if num.rfind(",") > num.rfind("."):
                num = num.replace(".", "").replace(",", ".")
            else:
                num = num.replace(",", "")
        elif num.count(",") > 1 and "." not in num:
            num = num.replace(",", "")
        elif num.count(".") > 1 and "," not in num:
            num = num.replace(".", "")
        elif "," in num and "." not in num:
            num = num.replace(",", ".")
        try:
            return float(num)
        except Exception:
            return None

    def _parse_value_and_unit(
        self, value: Any
    ) -> tuple[Optional[float], Optional[str], bool]:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None, None, False
        if isinstance(value, (int, float, np.integer, np.floating)) and not pd.isna(
            value
        ):
            return float(value), None, True
        text = str(value).strip().replace(" ", " ")
        if not text:
            return None, None, False
        text = text.replace("−", "-")
        match = re.match(
            r"^\s*([+-]?(?:\d+(?:[\.,]\d+)?|\d{1,3}(?:[\.,\s]\d{3})+(?:[\.,]\d+)?))(?:\s*([^\d].*?))?\s*$",
            text,
        )
        if not match:
            return None, None, False
        number = self._parse_number_text(match.group(1))
        unit = (match.group(2) or "").strip() or None
        if number is None:
            return None, None, False
        return number, unit, True

    def _extract_header_unit(self, column_name: str) -> tuple[str, Optional[str]]:
        name = str(column_name).strip()
        m = re.match(r"^(.*?)[\s_]*(?:\[([^\]]+)\]|\(([^\)]+)\))\s*$", name)
        if not m:
            return name, None
        base = (m.group(1) or name).strip()
        unit = (m.group(2) or m.group(3) or "").strip() or None
        if not unit or not base:
            return name, unit
        return base, unit

    def _clean_numeric_units(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        df = df.copy()
        column_units: dict[str, Any] = {}
        for col in df.columns:
            header_base, header_unit = self._extract_header_unit(col)
            series = df[col]
            if pd.api.types.is_numeric_dtype(series):
                if header_unit:
                    column_units[col] = {
                        "unit": header_unit,
                        "source": "column_name",
                        "parsed_numeric_values": int(series.notna().sum()),
                    }
                continue

            # Datums-/Zeitspalten nicht versehentlich als numerische Spalten mit "Einheit" interpretieren.
            try:
                dt_candidate = pd.to_datetime(series, errors="coerce")
                non_null_original = int(series.notna().sum())
                if (
                    non_null_original > 0
                    and int(dt_candidate.notna().sum()) / non_null_original
                    >= self.valves.datetime_parse_threshold
                ):
                    if header_unit:
                        column_units[col] = {
                            "unit": header_unit,
                            "source": "column_name",
                            "parsed_numeric_values": 0,
                        }
                    continue
            except Exception:
                pass

            parsed_values = []
            parse_success = 0
            non_null_count = 0
            units: list[str] = []
            for value in series.tolist():
                number, unit, ok = self._parse_value_and_unit(value)
                if (
                    value is not None
                    and not (isinstance(value, float) and math.isnan(value))
                    and str(value).strip() != ""
                ):
                    non_null_count += 1
                if ok:
                    parse_success += 1
                    parsed_values.append(number)
                    if unit:
                        units.append(unit)
                else:
                    parsed_values.append(np.nan)
            if non_null_count == 0:
                continue
            ratio = parse_success / non_null_count
            if ratio >= self.valves.numeric_parse_threshold:
                df[col] = pd.to_numeric(
                    pd.Series(parsed_values, index=series.index), errors="coerce"
                )
                unit_counts = pd.Series(units).value_counts().to_dict() if units else {}
                detected_unit = None
                mixed_units = False
                if unit_counts:
                    detected_unit = next(iter(unit_counts.keys()))
                    mixed_units = len(unit_counts) > 1
                if header_unit and not detected_unit:
                    detected_unit = header_unit
                if detected_unit or header_unit or unit_counts:
                    column_units[col] = {
                        "unit": detected_unit,
                        "source": "cell_values" if unit_counts else "column_name",
                        "mixed_units": mixed_units,
                        "unit_counts": dict(
                            list(unit_counts.items())[: self.valves.max_unique_preview]
                        ),
                        "parse_success_ratio": round(ratio, 4),
                        "parsed_numeric_values": int(df[col].notna().sum()),
                    }
            elif header_unit:
                column_units[col] = {
                    "unit": header_unit,
                    "source": "column_name",
                    "parsed_numeric_values": 0,
                }
        return df, column_units

    def _detect_datetime_columns(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        detected: dict[str, pd.Series] = {}
        for col in df.columns:
            series = df[col]
            converted = None
            if pd.api.types.is_datetime64_any_dtype(series):
                converted = pd.to_datetime(series, errors="coerce")
            elif pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(
                series
            ):
                converted = pd.to_datetime(series, errors="coerce")
            if converted is None:
                continue
            non_null_original = int(series.notna().sum())
            if non_null_original == 0:
                continue
            valid = int(converted.notna().sum())
            if valid / non_null_original >= self.valves.datetime_parse_threshold:
                detected[col] = converted
        return detected

    def _extract_time_coverage(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        coverage = []
        for col, converted in self._detect_datetime_columns(df).items():
            clean = converted.dropna()
            if clean.empty:
                continue
            coverage.append(
                {
                    "column": col,
                    "from": clean.min().isoformat(),
                    "to": clean.max().isoformat(),
                    "non_null_datetimes": int(clean.shape[0]),
                }
            )
        return coverage

    def _cleanup_dataframe(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        df, column_units = self._clean_numeric_units(df)
        time_coverage = self._extract_time_coverage(df)
        return df, {
            "column_units": column_units,
            "time_coverage": time_coverage,
        }

    def _load_dataframe(
        self,
        __files__: Optional[list],
        file_name: str = "",
        sheet_name: str = "",
        delimiter: str = ",",
        encoding: str = "utf-8",
        table_index: int = 0,
        page_numbers: Optional[list[int]] = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        item = self._select_file(__files__, file_name=file_name)
        path = self._resolve_existing_path(item)
        names = self._candidate_names(item)
        name = names[0] if names else os.path.basename(path)
        suffix = Path(name.lower()).suffix

        if suffix == ".csv":
            df, csv_meta = self._read_csv(path, delimiter=delimiter, encoding=encoding)
            meta = {"name": name, "path": path, "type": "csv", **csv_meta}
        elif suffix in {".xlsx", ".xls"}:
            xls = pd.ExcelFile(path)
            selected_sheet = sheet_name or xls.sheet_names[0]
            df = pd.read_excel(path, sheet_name=selected_sheet)
            meta = {
                "name": name,
                "path": path,
                "type": "excel",
                "sheet_name": selected_sheet,
                "available_sheets": list(xls.sheet_names),
            }
        elif suffix == ".pdf":
            df, pdf_meta = self._read_pdf_tables(
                path, table_index=table_index, page_numbers=page_numbers
            )
            meta = {"name": name, "path": path, "type": "pdf", **pdf_meta}
        else:
            raise ValueError(f"Nicht unterstütztes Dateiformat: {suffix}")

        df, derived_meta = self._cleanup_dataframe(df)
        meta.update(derived_meta)
        return df, meta

    def _column_profile(
        self, df: pd.DataFrame, column_units: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        column_units = column_units or {}
        result = {}
        for col in df.columns:
            series = df[col]
            entry: dict[str, Any] = {
                "dtype": str(series.dtype),
                "non_null": int(series.notna().sum()),
                "null": int(series.isna().sum()),
                "unique": int(series.nunique(dropna=True)),
            }
            if col in column_units:
                entry["unit_metadata"] = column_units[col]
            if pd.api.types.is_numeric_dtype(series):
                clean = series.dropna()
                if not clean.empty:
                    entry.update(
                        {
                            "min": self._json_default(clean.min()),
                            "max": self._json_default(clean.max()),
                            "mean": self._json_default(clean.mean()),
                            "median": self._json_default(clean.median()),
                            "std": (
                                self._json_default(clean.std(ddof=1))
                                if len(clean) > 1
                                else None
                            ),
                        }
                    )
            else:
                uniques = (
                    series.dropna()
                    .astype(str)
                    .value_counts()
                    .head(self.valves.max_unique_preview)
                )
                entry["top_values"] = uniques.to_dict()
            result[col] = entry
        return result

    def _descriptive_statistics(self, numeric_df: pd.DataFrame) -> dict[str, Any]:
        if numeric_df.empty:
            return {"message": "Keine numerischen Spalten gefunden."}
        desc = numeric_df.describe(percentiles=[0.25, 0.5, 0.75]).T
        desc["variance"] = numeric_df.var(ddof=1)
        desc["skewness"] = numeric_df.skew(numeric_only=True)
        desc["kurtosis"] = numeric_df.kurtosis(numeric_only=True)
        return desc.replace({np.nan: None}).to_dict(orient="index")

    def _correlations(self, numeric_df: pd.DataFrame) -> dict[str, Any]:
        if numeric_df.shape[1] < 2:
            return {
                "message": "Zu wenige numerische Spalten für eine Korrelationsanalyse."
            }
        pearson = numeric_df.corr(method="pearson").replace({np.nan: None})
        spearman = numeric_df.corr(method="spearman").replace({np.nan: None})
        return {"pearson": pearson.to_dict(), "spearman": spearman.to_dict()}

    def _normality_tests(self, numeric_df: pd.DataFrame) -> dict[str, Any]:
        results = {}
        if numeric_df.empty:
            return {"message": "Keine numerischen Spalten gefunden."}
        for col in numeric_df.columns:
            series = numeric_df[col].dropna()
            n = len(series)
            if n < 3:
                results[col] = {"message": "Zu wenige Werte für einen Normalitätstest."}
                continue
            sample = series
            if n > self.valves.max_sample_for_tests:
                sample = series.sample(
                    self.valves.max_sample_for_tests, random_state=42
                )
            entry: dict[str, Any] = {"n": int(n)}
            if 3 <= len(sample) <= 5000:
                stat, p = stats.shapiro(sample)
                entry["shapiro_wilk"] = {
                    "statistic": float(stat),
                    "p_value": float(p),
                    "normal_at_0_05": bool(p >= 0.05),
                }
            else:
                entry["shapiro_wilk"] = {
                    "message": "Shapiro-Wilk nur für 3 bis 5000 Werte sinnvoll/anwendbar."
                }
            z = np.abs(stats.zscore(sample, nan_policy="omit"))
            entry["zscore_abs_gt_3_count"] = int(np.sum(z > 3)) if np.size(z) else 0
            results[col] = entry
        return results

    def _outlier_analysis(self, numeric_df: pd.DataFrame) -> dict[str, Any]:
        results = {}
        if numeric_df.empty:
            return {"message": "Keine numerischen Spalten gefunden."}
        for col in numeric_df.columns:
            series = numeric_df[col].dropna()
            if len(series) < 4:
                results[col] = {"message": "Zu wenige Werte für IQR-Ausreißeranalyse."}
                continue
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            mask = (series < lower) | (series > upper)
            results[col] = {
                "q1": self._json_default(q1),
                "q3": self._json_default(q3),
                "iqr": self._json_default(iqr),
                "lower_bound": self._json_default(lower),
                "upper_bound": self._json_default(upper),
                "outlier_count": int(mask.sum()),
            }
        return results

    def _group_comparison(
        self, df: pd.DataFrame, target_column: str, group_column: str, alpha: float
    ) -> dict[str, Any]:
        if target_column not in df.columns:
            return {"error": f"Zielspalte '{target_column}' nicht gefunden."}
        if group_column not in df.columns:
            return {"error": f"Gruppenspalte '{group_column}' nicht gefunden."}
        if not pd.api.types.is_numeric_dtype(df[target_column]):
            return {"error": f"Zielspalte '{target_column}' ist nicht numerisch."}

        clean = df[[target_column, group_column]].dropna().copy()
        grouped = []
        group_sizes = {}
        for group_name, part in clean.groupby(group_column):
            values = part[target_column].astype(float).values
            if len(values) > 0:
                grouped.append((str(group_name), values))
                group_sizes[str(group_name)] = int(len(values))

        if len(grouped) < 2:
            return {
                "error": "Für einen Gruppenvergleich werden mindestens zwei Gruppen benötigt."
            }

        result: dict[str, Any] = {
            "target_column": target_column,
            "group_column": group_column,
            "alpha": alpha,
            "group_sizes": group_sizes,
        }
        if len(grouped) == 2:
            (_, g1), (_, g2) = grouped
            stat, p = stats.ttest_ind(g1, g2, equal_var=False, nan_policy="omit")
            result.update(
                {
                    "test": "welch_t_test",
                    "statistic": float(stat),
                    "p_value": float(p),
                    "significant": bool(p < alpha),
                }
            )
            return result
        arrays = [vals for _, vals in grouped]
        stat, p = stats.f_oneway(*arrays)
        result.update(
            {
                "test": "anova_one_way",
                "statistic": float(stat),
                "p_value": float(p),
                "significant": bool(p < alpha),
                "groups": [name for name, _ in grouped],
            }
        )
        return result

    def _safe_preview(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        preview = df.iloc[
            : self.valves.max_rows_preview, : self.valves.max_columns_preview
        ].copy()
        preview = preview.replace({np.nan: None})
        return preview.to_dict(orient="records")

    def _pivot_analysis(
        self,
        df: pd.DataFrame,
        index_columns: list[str],
        value_columns: list[str],
        aggfunc: str,
        column_columns: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        pivot = pd.pivot_table(
            df,
            index=index_columns,
            values=value_columns or None,
            columns=column_columns or None,
            aggfunc=aggfunc,
            dropna=False,
        ).reset_index()
        pivot.columns = [
            (
                "_".join([str(x) for x in col if str(x) != ""]).strip("_")
                if isinstance(col, tuple)
                else str(col)
            )
            for col in pivot.columns
        ]
        return (
            self._safe_preview(pivot)
            if len(pivot) > self.valves.max_rows_preview
            else pivot.replace({np.nan: None}).to_dict(orient="records")
        )

    def _time_series_analysis(
        self,
        df: pd.DataFrame,
        date_column: str,
        value_columns: list[str],
        frequency: str,
        group_columns: Optional[list[str]] = None,
        rolling_window: int = 0,
    ) -> list[dict[str, Any]]:
        if date_column not in df.columns:
            raise ValueError(f"Datums-Spalte '{date_column}' nicht gefunden.")
        ts = df.copy()
        ts[date_column] = pd.to_datetime(ts[date_column], errors="coerce")
        ts = ts.dropna(subset=[date_column])
        if ts.empty:
            raise ValueError("Keine auswertbaren Datumswerte gefunden.")
        group_columns = group_columns or []
        numeric_values = [
            c
            for c in value_columns
            if c in ts.columns and pd.api.types.is_numeric_dtype(ts[c])
        ]
        if not numeric_values:
            raise ValueError(
                "Keine numerischen value_columns für die Zeitreihenanalyse gefunden."
            )
        grouped = ts.set_index(date_column)
        if group_columns:
            aggregated = (
                grouped.groupby(group_columns + [pd.Grouper(freq=frequency)])[
                    numeric_values
                ]
                .mean()
                .reset_index()
            )
        else:
            aggregated = (
                grouped[numeric_values].resample(frequency).mean().reset_index()
            )
        if rolling_window and rolling_window > 1:
            for col in numeric_values:
                aggregated[f"{col}_rolling_mean_{rolling_window}"] = (
                    aggregated[col].rolling(rolling_window).mean()
                )
        aggregated = aggregated.replace({np.nan: None})
        return (
            self._safe_preview(aggregated)
            if len(aggregated) > self.valves.max_rows_preview
            else aggregated.to_dict(orient="records")
        )


class Tools:
    class Valves(BaseModel):
        max_rows_preview: int = Field(
            default=12, description="Maximale Anzahl Zeilen in der Vorschau"
        )
        max_columns_preview: int = Field(
            default=12, description="Maximale Anzahl Spalten in der Vorschau"
        )
        max_unique_preview: int = Field(
            default=20, description="Maximale Anzahl eindeutiger Werte in Kategorien"
        )
        max_sample_for_tests: int = Field(
            default=5000, description="Maximale Stichprobe für aufwändige Tests"
        )
        max_output_chars: int = Field(
            default=18000, description="Maximale JSON-Ausgabegröße an das LLM"
        )
        max_dict_items: int = Field(
            default=12,
            description="Maximale Anzahl Dict-Einträge in gekürzten Ausgaben",
        )
        max_tables_metadata: int = Field(
            default=20, description="Maximal anzuzeigende PDF-Tabellenmetadaten"
        )
        numeric_parse_threshold: float = Field(
            default=0.7,
            description="Mindestanteil parsebarer Zellen, um eine Textspalte als numerisch zu interpretieren",
        )
        datetime_parse_threshold: float = Field(
            default=0.6,
            description="Mindestanteil parsebarer Zeitwerte, um eine Spalte als Zeitspalte zu werten",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._helper = _TableAnalysisHelper(self.valves)

    async def list_attached_tables(
        self, __files__: Optional[list] = None, __event_emitter__: Optional[Any] = None
    ) -> str:
        await self._helper._emit_start(__event_emitter__, "list_attached_tables")
        try:
            supported = []
            for item in self._helper._normalize_files(__files__):
                names = self._helper._candidate_names(item)
                if any(self._helper._is_supported_file(name) for name in names):
                    supported.append(
                        {
                            "name": names[0] if names else item.get("name"),
                            "path": next(
                                iter(self._helper._candidate_paths(item)), None
                            ),
                            "size": item.get("size"),
                            "type": item.get("content_type"),
                        }
                    )
            if not supported:
                payload = {
                    "ok": False,
                    "message": "Keine unterstützte CSV-/Excel-/PDF-Datei im Anhang gefunden.",
                    "supported_extensions": [".csv", ".xlsx", ".xls", ".pdf"],
                }
            else:
                payload = {"ok": True, "files": supported}
            await self._helper._emit_end(
                __event_emitter__,
                "list_attached_tables",
                f"{len(supported)} unterstützte Datei(en)",
            )
            return self._helper.dumps(payload)
        except Exception as exc:
            await self._helper._emit_error(
                __event_emitter__, "list_attached_tables", str(exc)
            )
            return self._helper.dumps({"ok": False, "error": str(exc)})

    async def profile_table(
        self,
        file_name: str = "",
        sheet_name: str = "",
        delimiter: str = ",",
        encoding: str = "utf-8",
        table_index: int = 0,
        page_numbers: Optional[list[int]] = None,
        __files__: Optional[list] = None,
        __event_emitter__: Optional[Any] = None,
    ) -> str:
        await self._helper._emit_start(__event_emitter__, "profile_table")
        try:
            df, meta = self._helper._load_dataframe(
                __files__=__files__,
                file_name=file_name,
                sheet_name=sheet_name,
                delimiter=delimiter,
                encoding=encoding,
                table_index=table_index,
                page_numbers=page_numbers,
            )
            profile = {
                "columns_list": list(df.columns),
                "ok": True,
                "file": meta,
                "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
                "columns": self._helper._column_profile(df, meta.get("column_units")),
                "missing_values": {
                    col: int(df[col].isna().sum()) for col in df.columns
                },
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "summary": f"Profil erstellt für {meta.get('name')} mit {df.shape[0]} Zeilen und {df.shape[1]} Spalten.",
                "preview": self._helper._safe_preview(df),
            }
            await self._helper._emit_end(
                __event_emitter__,
                "profile_table",
                f"{df.shape[0]} Zeilen, {df.shape[1]} Spalten",
            )
            return self._helper.dumps(profile)
        except Exception as exc:
            await self._helper._emit_error(__event_emitter__, "profile_table", str(exc))
            return self._helper.dumps({"ok": False, "error": str(exc)})

    async def analyze_statistics(
        self,
        file_name: str = "",
        sheet_name: str = "",
        target_column: str = "",
        group_column: str = "",
        alpha: float = 0.05,
        delimiter: str = ",",
        encoding: str = "utf-8",
        table_index: int = 0,
        page_numbers: Optional[list[int]] = None,
        __files__: Optional[list] = None,
        __event_emitter__: Optional[Any] = None,
    ) -> str:
        await self._helper._emit_start(__event_emitter__, "analyze_statistics")
        try:
            df, meta = self._helper._load_dataframe(
                __files__=__files__,
                file_name=file_name,
                sheet_name=sheet_name,
                delimiter=delimiter,
                encoding=encoding,
                table_index=table_index,
                page_numbers=page_numbers,
            )
            numeric_df = df.select_dtypes(include=[np.number]).copy()
            categorical_cols = [c for c in df.columns if c not in numeric_df.columns]
            result: dict[str, Any] = {
                "ok": True,
                "file": meta,
                "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
                "numeric_columns": list(numeric_df.columns),
                "categorical_columns": categorical_cols,
                "descriptive_statistics": self._helper._descriptive_statistics(
                    numeric_df
                ),
                "correlations": self._helper._correlations(numeric_df),
                "normality_tests": self._helper._normality_tests(numeric_df),
                "outliers_iqr": self._helper._outlier_analysis(numeric_df),
                "summary": f"Statistische Analyse für {meta.get('name')} mit {len(numeric_df.columns)} numerischen Spalten erstellt.",
            }
            if target_column and group_column:
                result["group_comparison"] = self._helper._group_comparison(
                    df=df,
                    target_column=target_column,
                    group_column=group_column,
                    alpha=alpha,
                )
            await self._helper._emit_end(
                __event_emitter__,
                "analyze_statistics",
                f"{len(numeric_df.columns)} numerische Spalten",
            )
            return self._helper.dumps(result)
        except Exception as exc:
            await self._helper._emit_error(
                __event_emitter__, "analyze_statistics", str(exc)
            )
            return self._helper.dumps({"ok": False, "error": str(exc)})

    async def analyze_pivot(
        self,
        file_name: str = "",
        sheet_name: str = "",
        index_columns: str = "",
        value_columns: str = "",
        column_columns: str = "",
        aggfunc: str = "sum",
        delimiter: str = ",",
        encoding: str = "utf-8",
        table_index: int = 0,
        page_numbers: Optional[list[int]] = None,
        __files__: Optional[list] = None,
        __event_emitter__: Optional[Any] = None,
    ) -> str:
        await self._helper._emit_start(__event_emitter__, "analyze_pivot")
        try:
            df, meta = self._helper._load_dataframe(
                __files__=__files__,
                file_name=file_name,
                sheet_name=sheet_name,
                delimiter=delimiter,
                encoding=encoding,
                table_index=table_index,
                page_numbers=page_numbers,
            )
            idx = [c.strip() for c in index_columns.split(",") if c.strip()]
            vals = [c.strip() for c in value_columns.split(",") if c.strip()]
            cols = [c.strip() for c in column_columns.split(",") if c.strip()]
            payload = {
                "ok": True,
                "file": meta,
                "index_columns": idx,
                "value_columns": vals,
                "column_columns": cols,
                "aggfunc": aggfunc,
                "pivot": self._helper._pivot_analysis(
                    df, idx, vals, aggfunc, cols or None
                ),
                "summary": f"Pivot-Analyse für {meta.get('name')} erstellt.",
            }
            await self._helper._emit_end(__event_emitter__, "analyze_pivot")
            return self._helper.dumps(payload)
        except Exception as exc:
            await self._helper._emit_error(__event_emitter__, "analyze_pivot", str(exc))
            return self._helper.dumps({"ok": False, "error": str(exc)})

    async def analyze_time_series(
        self,
        file_name: str = "",
        sheet_name: str = "",
        date_column: str = "",
        value_columns: str = "",
        group_columns: str = "",
        frequency: str = "M",
        rolling_window: int = 0,
        delimiter: str = ",",
        encoding: str = "utf-8",
        table_index: int = 0,
        page_numbers: Optional[list[int]] = None,
        __files__: Optional[list] = None,
        __event_emitter__: Optional[Any] = None,
    ) -> str:
        await self._helper._emit_start(__event_emitter__, "analyze_time_series")
        try:
            df, meta = self._helper._load_dataframe(
                __files__=__files__,
                file_name=file_name,
                sheet_name=sheet_name,
                delimiter=delimiter,
                encoding=encoding,
                table_index=table_index,
                page_numbers=page_numbers,
            )
            vals = [c.strip() for c in value_columns.split(",") if c.strip()]
            groups = [c.strip() for c in group_columns.split(",") if c.strip()]
            payload = {
                "ok": True,
                "file": meta,
                "date_column": date_column,
                "value_columns": vals,
                "group_columns": groups,
                "frequency": frequency,
                "rolling_window": rolling_window,
                "time_series": self._helper._time_series_analysis(
                    df, date_column, vals, frequency, groups or None, rolling_window
                ),
                "summary": f"Zeitraumanalyse für {meta.get('name')} erstellt.",
            }
            await self._helper._emit_end(__event_emitter__, "analyze_time_series")
            return self._helper.dumps(payload)
        except Exception as exc:
            await self._helper._emit_error(
                __event_emitter__, "analyze_time_series", str(exc)
            )
            return self._helper.dumps({"ok": False, "error": str(exc)})
