"""
title: Niotix Sensor Data Fetch
author: Boris van Benthem
description: Abfragen über die Niotix X-API: (1) Messwerte via POST /xapi/v1/influxdb/query; (2) Sensorliste via GET /xapi/v1/virtual-devices; (3) gültige State Identifier eines Sensors (SHOW TAG VALUES, ohne Zeitfilter). Zeigt Tabellen & Citations in der WebUI.
version: 0.1.1
requirements: aiohttp
license: MIT
original_author: Boris van Benthem
source_url: https://gitlab.opencode.de/kommi/adapter/niotix-adapter
"""

# --------------------------------------------------------------------------
# Herkunft / Provenance
#
# Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
# Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
# unverändert.
#
#   Projekt : Niotix-Adapter
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/niotix-adapter
#   Datei   : niotix-adapter.py
#   Autor   : Boris van Benthem
#   Lizenz  : MIT
#
# Im Kopf der Originaldatei als "license: MIT" deklariert. Das Quellprojekt
# enthält keine LICENSE-Datei; Rechteinhaber ist der dort genannte Autor.
# Der nachfolgende Lizenztext ist die Standardfassung der MIT-Lizenz.
# --------------------------------------------------------------------------
# MIT License
#
# Copyright (c) Boris van Benthem
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# --------------------------------------------------------------------------

from datetime import datetime
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field
import aiohttp


class Tools:
    class Valves(BaseModel):
        NIOTIX_BASE_URL: str = Field(
            "", description="z. B. https://xapi.niota.io/xapi/v1/"
        )
        NIOTIX_API_KEY: str = Field(
            "", description="Niotix API-Key für Header x-api-key"
        )

    class UserValves(BaseModel):
        NIOTIX_BASE_URL: str = Field(
            "", description="(User) Base URL (…/xapi/v1/ oder …/xapi/v1/influxdb)"
        )
        NIOTIX_API_KEY: str = Field("", description="(User) API-Key (x-api-key)")

    def __init__(self):
        self.valves = self.Valves()
        # Wir senden eigene Citations in den Chat
        self.citation = False

    # ---------- Hilfsfunktionen ----------
    @staticmethod
    def _mk_table_md(
        columns: List[str], rows: List[Dict[str, Any]], max_rows: int = 10
    ) -> str:
        header = "| " + " | ".join(columns) + " |"
        separator = "|" + "|".join(["---"] * len(columns)) + "|"
        lines = [header, separator]
        for r in rows[:max_rows]:
            lines.append("| " + " | ".join(str(r.get(c, "")) for c in columns) + " |")
        if len(rows) > max_rows:
            lines.append(
                "| "
                + " | ".join(["…"] * len(columns))
                + f" | ({len(rows)-max_rows} weitere Zeilen)"
            )
        return "\n".join(lines)

    @staticmethod
    async def _emit(__event_emitter__, etype: str, data: Dict[str, Any]):
        if __event_emitter__:
            await __event_emitter__({"type": etype, "data": data})

    @staticmethod
    def _escape_influx_str(val: str) -> str:
        return val.replace("\\", "\\\\").replace("'", "\\'")

    @staticmethod
    def _sanitize_range(r: str) -> str:
        # akzeptiert "1h", "7d", "30m" oder "-1h" etc.; entferne führendes Minus
        return (r or "1h").lstrip().lstrip("-").strip() or "1h"

    @staticmethod
    def _base_for_rest(base_url: str) -> str:
        """
        Liefert eine Basis, die auf /v1 endet (ohne /influxdb…).
        """
        b = base_url.rstrip("/")
        if b.endswith("/influxdb/query"):
            b = b[: -len("/influxdb/query")]
        if b.endswith("/influxdb"):
            b = b[: -len("/influxdb")]
        if b.endswith("/v1/"):
            b = b[:-1]
        if not b.endswith("/v1"):
            if "/v1" not in b:
                b = b + "/v1"
        return b

    @staticmethod
    def _build_endpoint_influx(base_url: str) -> str:
        b = base_url.rstrip("/")
        if b.endswith("/influxdb/query"):
            return b
        if b.endswith("/influxdb"):
            return b + "/query"
        if b.endswith("/v1") or b.endswith("/v1/"):
            return b.rstrip("/") + "/influxdb/query"
        return b + "/influxdb/query"

    # ---------- Influx-Query (Messwerte) ----------
    @staticmethod
    def _build_query(
        sensor_name: str,
        time_range: str,
        state_identifier: str,
        influxql: Optional[str],
    ) -> str:
        """
        Default-InfluxQL:
        - Pflicht-Tags: dtwin_title::tag, state_identifier::tag
        - Zeitbedingung Pflicht
        - Aggregation: last(value_string), mean(value_number) gruppiert nach 1h (fill(previous))
        """
        if influxql and influxql.strip():
            return influxql.strip()

        esc = Tools._escape_influx_str
        rng = Tools._sanitize_range(time_range)

        where_parts = [
            f"\"dtwin_title\"::tag = '{esc(sensor_name)}'",
            f"\"state_identifier\"::tag = '{esc(state_identifier)}'",
            f"time >= now() - {rng}",
        ]
        where_clause = " AND ".join(where_parts)

        return (
            'SELECT last("value_string"), mean("value_number") '
            f'FROM "states_history" WHERE {where_clause} '
            "GROUP BY time(1h) fill(previous)"
        )

    # ---------- Sensor Data ----------
    async def get_sensor_data(
        self,
        sensor_name: str,
        state_identifier: str,
        time_range: str = "1h",
        influxql: Optional[str] = None,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __messages__: Optional[List[dict]] = None,
        __model__: Optional[dict] = None,
    ) -> Dict[str, Any]:

        await self._emit(
            __event_emitter__,
            "status",
            {
                "description": f"🔎 Frage Niotix … (Sensor: {sensor_name}, state_identifier: {state_identifier})",
                "done": False,
                "hidden": False,
            },
        )

        # Valves (User überschreibt Admin)
        uv = (__user__ or {}).get("valves") if isinstance(__user__, dict) else None
        base_url = (
            uv.NIOTIX_BASE_URL
            if (uv and getattr(uv, "NIOTIX_BASE_URL", ""))
            else self.valves.NIOTIX_BASE_URL
        ).strip()
        api_key = (
            uv.NIOTIX_API_KEY
            if (uv and getattr(uv, "NIOTIX_API_KEY", ""))
            else self.valves.NIOTIX_API_KEY
        ).strip()
        if not base_url or not api_key:
            raise RuntimeError(
                "Bitte NIOTIX_BASE_URL und NIOTIX_API_KEY in den Valves setzen."
            )

        endpoint = self._build_endpoint_influx(base_url)
        q = self._build_query(sensor_name, time_range, state_identifier, influxql)

        headers = {"Accept": "application/json", "x-api-key": api_key}
        data = {"q": q}
        url_preview = endpoint
        query_preview = q

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint, headers=headers, data=data) as resp:
                body_text = await resp.text()
                if resp.status != 200:
                    await self._emit(
                        __event_emitter__,
                        "citation",
                        {
                            "document": [
                                f"POST {url_preview}",
                                f"Query:\n{query_preview}",
                            ],
                            "metadata": [
                                {
                                    "date_accessed": datetime.utcnow().isoformat()
                                    + "Z",
                                    "source": "Niotix API Fehler",
                                }
                            ],
                            "source": {
                                "name": "Niotix Influx Query Endpoint",
                                "url": url_preview,
                            },
                        },
                    )
                    raise RuntimeError(
                        f"Niotix API Fehler: HTTP {resp.status} – {body_text[:800]}{'…' if len(body_text)>800 else ''}"
                    )
                influx = await resp.json()

        results = influx.get("results", [])
        series = results[0].get("series", []) if results else []

        # ---------- KEINE DATEN? -> State-Identifier vorschlagen ----------
        if not series or not series[0].get("values"):
            # Citation für leeres Resultset
            await self._emit(
                __event_emitter__,
                "citation",
                {
                    "document": [
                        f"POST {url_preview}",
                        f"Query:\n{query_preview}",
                        "Hinweis: Keine Daten für den angefragten State.",
                    ],
                    "metadata": [
                        {
                            "date_accessed": datetime.utcnow().isoformat() + "Z",
                            "source": "Leeres Resultset",
                        }
                    ],
                    "source": {
                        "name": "Niotix Influx Query Endpoint",
                        "url": url_preview,
                    },
                },
            )

            # Hinweis im Chat
            await self._emit(
                __event_emitter__,
                "message",
                {
                    "content": (
                        f"⚠️ Für **{sensor_name}** mit `state_identifier` **{state_identifier}** "
                        f"wurden im Zeitraum **{self._sanitize_range(time_range)}** keine Messwerte gefunden.\n\n"
                        "Bitte wähle einen **gültigen State Identifier** aus der folgenden Liste."
                    )
                },
            )

            # Gültige State Identifier ermitteln und direkt anzeigen
            sids = await self.get_state_identifiers(
                sensor_name=sensor_name,
                __event_emitter__=__event_emitter__,
                __user__=__user__,
                __metadata__=__metadata__,
                __messages__=__messages__,
                __model__=__model__,
            )

            # Abschlussstatus (Fehlerfall)
            await self._emit(
                __event_emitter__,
                "status",
                {
                    "description": "❌ Keine Messwerte gefunden – State Identifier vorgeschlagen",
                    "done": True,
                    "hidden": False,
                },
            )

            return {
                "error": (
                    f"Keine Messwerte vorhanden für state_identifier '{state_identifier}'. "
                    "Bitte einen gültigen State Identifier aus der Liste auswählen."
                ),
                "state_identifiers": sids.get("rows", []),
                "meta": {
                    "sensor_name": sensor_name,
                    "state_identifier": state_identifier,
                    "time_range": self._sanitize_range(time_range),
                    "fetched_at": datetime.utcnow().isoformat() + "Z",
                    "base_url_used": base_url,
                    "endpoint_used": endpoint,
                    "row_count": 0,
                    "auth_used": "x-api-key",
                    "influxql": q,
                },
            }

        # ---------- DATEN VORHANDEN ----------
        columns = series[0].get("columns", [])
        values = series[0].get("values", [])
        rows = [{columns[i]: v[i] for i in range(len(columns))} for v in values]

        # Citation bei Erfolg
        await self._emit(
            __event_emitter__,
            "citation",
            {
                "document": [f"POST {url_preview}", f"Query:\n{query_preview}"],
                "metadata": [
                    {
                        "date_accessed": datetime.utcnow().isoformat() + "Z",
                        "source": "Abfrage erfolgreich",
                    }
                ],
                "source": {"name": "Niotix Influx Query Endpoint", "url": url_preview},
            },
        )

        # Rohdaten-Preview als Tabelle
        table_md = self._mk_table_md(columns, rows, max_rows=10)
        await self._emit(
            __event_emitter__,
            "message",
            {"content": f"### 📎 Quellausgabe (Rohdaten-Vorschau)\n\n{table_md}"},
        )
        await self._emit(
            __event_emitter__,
            "status",
            {
                "description": f"✅ Abfrage abgeschlossen (Sensor: {sensor_name}, state_identifier: {state_identifier})",
                "done": True,
                "hidden": False,
            },
        )

        return {
            "columns": columns,
            "rows": rows,
            "meta": {
                "sensor_name": sensor_name,
                "state_identifier": state_identifier,
                "time_range": time_range,
                "fetched_at": datetime.utcnow().isoformat() + "Z",
                "base_url_used": base_url,
                "endpoint_used": endpoint,
                "row_count": len(rows),
                "auth_used": "x-api-key",
                "influxql": q,
            },
        }

    # ---------- State Identifier (SHOW TAG VALUES, ohne Zeitfilter) ----------
    async def get_state_identifiers(
        self,
        sensor_name: str,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __messages__: Optional[List[dict]] = None,
        __model__: Optional[dict] = None,
    ) -> Dict[str, Any]:

        # Valves (User überschreibt Admin)
        uv = (__user__ or {}).get("valves") if isinstance(__user__, dict) else None
        base_url = (
            uv.NIOTIX_BASE_URL
            if (uv and getattr(uv, "NIOTIX_BASE_URL", ""))
            else self.valves.NIOTIX_BASE_URL
        ).strip()
        api_key = (
            uv.NIOTIX_API_KEY
            if (uv and getattr(uv, "NIOTIX_API_KEY", ""))
            else self.valves.NIOTIX_API_KEY
        ).strip()
        if not base_url or not api_key:
            raise RuntimeError(
                "Bitte NIOTIX_BASE_URL und NIOTIX_API_KEY in den Valves setzen."
            )

        endpoint = self._build_endpoint_influx(base_url)
        esc_name = self._escape_influx_str(sensor_name)
        q = f'SHOW TAG VALUES WITH KEY = "state_identifier" WHERE "dtwin_title"::tag = \'{esc_name}\''

        headers = {"Accept": "application/json", "x-api-key": api_key}
        data = {"q": q}
        url_preview = endpoint
        query_preview = q

        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint, headers=headers, data=data) as resp:
                body_text = await resp.text()
                if resp.status != 200:
                    await self._emit(
                        __event_emitter__,
                        "citation",
                        {
                            "document": [
                                f"POST {url_preview}",
                                f"Query:\n{query_preview}",
                            ],
                            "metadata": [
                                {
                                    "date_accessed": datetime.utcnow().isoformat()
                                    + "Z",
                                    "source": "State Identifier – Fehler",
                                }
                            ],
                            "source": {
                                "name": "Niotix Influx Query Endpoint",
                                "url": url_preview,
                            },
                        },
                    )
                    raise RuntimeError(
                        f"Niotix API Fehler: HTTP {resp.status} – {body_text[:800]}{'…' if len(body_text)>800 else ''}"
                    )
                influx = await resp.json()

        # Auswertung SHOW TAG VALUES: columns ["key","value"], values [["state_identifier","<sid>"], ...]
        results = influx.get("results", [])
        series = results[0].get("series", []) if results else []
        rows: List[Dict[str, Any]] = []
        if series:
            for s in series:
                values = s.get("values", []) or []
                for v in values:
                    sid = v[1] if len(v) > 1 else None
                    if sid:
                        rows.append({"state_identifier": sid})

        columns = ["state_identifier"]

        # Citation (erfolgreich)
        await self._emit(
            __event_emitter__,
            "citation",
            {
                "document": [f"POST {url_preview}", f"Query:\n{query_preview}"],
                "metadata": [
                    {
                        "date_accessed": datetime.utcnow().isoformat() + "Z",
                        "source": "State Identifier – SHOW TAG VALUES",
                    }
                ],
                "source": {"name": "Niotix Influx Query Endpoint", "url": url_preview},
            },
        )

        # Tabelle im Chat
        table_md = self._mk_table_md(columns, rows, max_rows=25)
        await self._emit(
            __event_emitter__,
            "message",
            {
                "content": f"### 🧭 Gültige State Identifier für **{sensor_name}**\n\n{table_md}"
            },
        )
        await self._emit(
            __event_emitter__,
            "status",
            {
                "description": "✅ State Identifier ermittelt",
                "done": True,
                "hidden": False,
            },
        )

        return {
            "columns": columns,
            "rows": rows,
            "meta": {
                "sensor_name": sensor_name,
                "fetched_at": datetime.utcnow().isoformat() + "Z",
                "base_url_used": base_url,
                "endpoint_used": endpoint,
                "row_count": len(rows),
                "influxql": q,
            },
        }

    # ---------- Virtual Devices ----------
    async def get_virtual_devices(
        self,
        search: Optional[str] = None,
        page: int = 0,
        size: int = 50,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __messages__: Optional[List[dict]] = None,
        __model__: Optional[dict] = None,
    ) -> Dict[str, Any]:

        # Valves (User überschreibt Admin)
        uv = (__user__ or {}).get("valves") if isinstance(__user__, dict) else None
        base_url = (
            uv.NIOTIX_BASE_URL
            if (uv and getattr(uv, "NIOTIX_BASE_URL", ""))
            else self.valves.NIOTIX_BASE_URL
        ).strip()
        api_key = (
            uv.NIOTIX_API_KEY
            if (uv and getattr(uv, "NIOTIX_API_KEY", ""))
            else self.valves.NIOTIX_API_KEY
        ).strip()
        if not base_url or not api_key:
            raise RuntimeError(
                "Bitte NIOTIX_BASE_URL und NIOTIX_API_KEY in den Valves setzen."
            )

        rest_base = self._base_for_rest(base_url)
        endpoint = rest_base + "/virtual-devices"

        headers = {"Accept": "application/json", "x-api-key": api_key}
        params = {"page": page, "size": size}
        if search and search.strip():
            params["search"] = search.strip()

        # Vorschau-URL für Citation
        qp = f"?page={page}&size={size}" + (
            f"&search={search.strip()}" if search and search.strip() else ""
        )
        url_preview = endpoint + qp

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(endpoint, headers=headers, params=params) as resp:
                body_text = await resp.text()
                if resp.status != 200:
                    await self._emit(
                        __event_emitter__,
                        "citation",
                        {
                            "document": [f"GET {url_preview}"],
                            "metadata": [
                                {
                                    "date_accessed": datetime.utcnow().isoformat()
                                    + "Z",
                                    "source": "Niotix X‑API – Fehler",
                                }
                            ],
                            "source": {
                                "name": "Niotix X‑API – Virtual Devices",
                                "url": url_preview,
                            },
                        },
                    )
                    raise RuntimeError(
                        f"Niotix API Fehler: HTTP {resp.status} – {body_text[:800]}{'…' if len(body_text)>800 else ''}"
                    )
                data = await resp.json()

        # Response tolerant parsen (Array ODER Objekt mit items/content)
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            if isinstance(data.get("items"), list):
                items = data["items"]
            elif isinstance(data.get("content"), list):
                items = data["content"]
            else:
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        items = v
                        break

        # Relevante Felder abbilden – Name sicher aus meta.name
        rows: List[Dict[str, Any]] = []
        for it in items:
            dev_id = it.get("id") or it.get("identifier") or it.get("uuid")
            meta = it.get("meta") if isinstance(it.get("meta"), dict) else {}
            name = (meta or {}).get("name")
            # Typ aus meta.type, ansonsten deviceType/deviceDriver-Fallbacks
            type_val = (meta or {}).get("type")
            if not type_val:
                dt = it.get("deviceType") or {}
                dd = it.get("deviceDriver") or {}
                if isinstance(dt, dict):
                    type_val = dt.get("title") or dt.get("name") or dt.get("key")
                if not type_val and isinstance(dd, dict):
                    type_val = dd.get("title") or dd.get("name") or dd.get("key")

            rows.append({"id": dev_id, "name": name, "type": type_val})

        columns = ["id", "name", "type"]

        # Citation zur Nachvollziehbarkeit
        await self._emit(
            __event_emitter__,
            "citation",
            {
                "document": [f"GET {url_preview}"],
                "metadata": [
                    {
                        "date_accessed": datetime.utcnow().isoformat() + "Z",
                        "source": "Abfrage erfolgreich",
                    }
                ],
                "source": {
                    "name": "Niotix X‑API – Virtual Devices",
                    "url": url_preview,
                },
            },
        )

        # Tabelle im Chat
        table_md = self._mk_table_md(columns, rows, max_rows=15)
        await self._emit(
            __event_emitter__,
            "message",
            {"content": f"### 📇 Verfügbare Sensoren (Virtual Devices)\n\n{table_md}"},
        )
        await self._emit(
            __event_emitter__,
            "status",
            {
                "description": "✅ Sensorliste (Virtual Devices) geladen",
                "done": True,
                "hidden": False,
            },
        )

        return {
            "columns": columns,
            "rows": rows,
            "meta": {
                "count": len(rows),
                "page": page,
                "size": size,
                "base_url_used": rest_base,
                "endpoint_used": endpoint,
            },
        }

    # ---------- Toolspec ----------
    def list_tools(self):
        return tool_spec

    async def call_function(self, name: str, arguments: dict):
        if name == "get_sensor_data":
            return await self.get_sensor_data(
                sensor_name=arguments.get("sensor_name"),
                state_identifier=arguments.get("state_identifier"),
                time_range=arguments.get("time_range", "1h"),
                influxql=arguments.get("influxql"),
                __event_emitter__=arguments.get("__event_emitter__"),
                __user__=arguments.get("__user__"),
                __metadata__=arguments.get("__metadata__"),
                __messages__=arguments.get("__messages__"),
                __model__=arguments.get("__model__"),
            )
        if name == "get_state_identifiers":
            return await self.get_state_identifiers(
                sensor_name=arguments.get("sensor_name"),
                __event_emitter__=arguments.get("__event_emitter__"),
                __user__=arguments.get("__user__"),
                __metadata__=arguments.get("__metadata__"),
                __messages__=arguments.get("__messages__"),
                __model__=arguments.get("__model__"),
            )
        if name == "get_virtual_devices":
            return await self.get_virtual_devices(
                search=arguments.get("search"),
                page=int(arguments.get("page", 0)),
                size=int(arguments.get("size", 50)),
                __event_emitter__=arguments.get("__event_emitter__"),
                __user__=arguments.get("__user__"),
                __metadata__=arguments.get("__metadata__"),
                __messages__=arguments.get("__messages__"),
                __model__=arguments.get("__model__"),
            )
        raise ValueError(f"Unknown function: {name}")


# ---------- Toolspec (unter der Klasse) ----------
tool_spec = [
    {
        "type": "function",
        "function": {
            "name": "get_sensor_data",
            "description": "Fragt Messwerte aus Niotix ab (POST /xapi/v1/influxdb/query). "
            "Pflicht: sensor_name (dtwin_title::tag) und state_identifier::tag. "
            "Bei leerem Ergebnis werden gültige State Identifier (SHOW TAG VALUES) nachgereicht.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sensor_name": {
                        "type": "string",
                        "description": "Pflicht: dtwin_title::tag",
                    },
                    "state_identifier": {
                        "type": "string",
                        "description": "Pflicht: state_identifier::tag",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "z. B. 1h, 7d, 30m",
                        "default": "1h",
                    },
                    "influxql": {
                        "type": "string",
                        "description": "Optional eigene InfluxQL-Query",
                    },
                },
                "required": ["sensor_name", "state_identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_state_identifiers",
            "description": "Liefert gültige state_identifier eines Sensors ohne Zeitfilter via SHOW TAG VALUES.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sensor_name": {
                        "type": "string",
                        "description": "Pflicht: dtwin_title::tag",
                    }
                },
                "required": ["sensor_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_virtual_devices",
            "description": "Listet verfügbare Sensoren über GET /xapi/v1/virtual-devices (meta.name als Name).",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "page": {"type": "integer", "default": 0},
                    "size": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        },
    },
]
