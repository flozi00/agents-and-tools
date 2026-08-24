"""
title: Open Street Map Agent
author: Boris van Benthem (Stadt Oberhausen)
description: Abfrage für Daten aus Open Street Map und Verarbeitung im Sprachmodell. Findet Koordinaten zu Orten, kann Distanzen zwischen Orten berechnen und herausfinden, Ob Adressen in Stadteilen liegen. Alle erarbeiteten Daten können in einer Karte dargestellt werden.
version: 0.3.1
requirements: requests
license: MIT
original_author: Boris van Benthem (Stadt Oberhausen)
source_url: https://gitlab.opencode.de/kommi/adapter/osm-adapter
"""

# --------------------------------------------------------------------------
# Herkunft / Provenance
#
# Übernommen aus dem KommI-Adapter-Katalog (openCode). Der Code ist
# gegenüber dem Original unverändert; ergänzt wurden ausschließlich dieser
# Herkunftshinweis und Katalog-Metadaten im Kopf.
#
#   Projekt : OSM-Adapter
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/osm-adapter
#   Datei   : osm-adapter.py
#   Autor   : Boris van Benthem (Stadt Oberhausen)
#   Lizenz  : MIT
#
# Im Kopf der Originaldatei als "license: MIT" deklariert. Das Quellprojekt
# enthält keine LICENSE-Datei; Rechteinhaber ist der dort genannte Autor.
# Der nachfolgende Lizenztext ist die Standardfassung der MIT-Lizenz.
# --------------------------------------------------------------------------
# MIT License
#
# Copyright (c) Boris van Benthem (Stadt Oberhausen)
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

import time
import json
import math
import re
import requests
from urllib.parse import quote
from typing import Any, Union, Optional, List, Dict, Callable, Awaitable, Tuple
from pydantic import BaseModel, Field

# Target: OpenWebUI Tools Function


JsonDict = Dict[str, Any]
EventEmitter = Optional[Callable[[JsonDict], Awaitable[Any]]]
PointGeom = Dict[str, Any]  # {"type":"Point","coordinates":[lon,lat]}
PolygonGeom = Dict[str, Any]  # Polygon|MultiPolygon


class GeoHelpers:
    """Interne Hilfsklasse für GeoStore-, Event-, Nominatim- und Geometrie-Operationen.

    Die OpenWebUI-Tool-Klasse ``Tools`` enthält dadurch nur noch die öffentlich
    vom LLM aufrufbaren Tool-Methoden sowie die Valves/UserValves-Konfiguration.
    Alle Implementierungsdetails liegen in dieser separaten Klasse und sind
    zusätzlich per Unterstrich-Präfix als interne API markiert. Dadurch werden
    sie nicht als Tools für das Sprachmodell angeboten.
    """

    # Klassenweiter Store (pro chat_id)
    _geoStore: Dict[str, Dict[str, Any]] = {}

    # Caches (prozessweit, bewusst simpel)
    _geocode_cache: Dict[Tuple[str, str], PointGeom] = {}
    _boundary_cache: Dict[Tuple[str, str], PolygonGeom] = {}

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "GeocoderScript/1.1 (boris.vanbenthem@oberhausen.de)",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            }
        )
        self._last_call_ts = 0.0
        self._min_interval_s = 1.0  # freundliches Throttling für Nominatim

    # ---------- Meta / Store / Valves ----------

    @staticmethod
    def _chat_id(__metadata__: Optional[dict]) -> str:
        return str((__metadata__ or {}).get("chat_id", "__default__"))

    def _ensure_geo_store(self, __metadata__: Optional[dict]) -> Dict[str, Any]:
        chat_id = self._chat_id(__metadata__)
        store = GeoHelpers._geoStore.get(chat_id) or {}
        store.setdefault("geojson", {"type": "FeatureCollection", "features": []})
        store.setdefault("tests", [])
        store.setdefault("__debug__", False)
        GeoHelpers._geoStore[chat_id] = store
        return store

    @staticmethod
    def _fc(geo_store: Dict[str, Any]) -> Dict[str, Any]:
        return geo_store["geojson"]

    @staticmethod
    def _user_valves(__user__: Optional[dict]) -> Dict[str, Any]:
        v = ((__user__ or {}).get("valves")) or {}
        if hasattr(v, "dict"):
            try:
                return v.dict()
            except Exception:
                pass
        return dict(v) if isinstance(v, dict) else {}

    def _nominatim_base(self, __user__: Optional[dict]) -> str:
        valves = self._user_valves(__user__)
        base = (
            (valves.get("NOMINATIM_BASE_URL") or "https://nominatim.openstreetmap.org")
            .strip()
            .rstrip("/")
        )
        return base or "https://nominatim.openstreetmap.org"

    def _is_debug(self, __metadata__: Optional[dict], __user__: Optional[dict]) -> bool:
        valves = self._user_valves(__user__)
        return bool(valves.get("DEBUG_NOTIFICATIONS")) or bool(
            self._ensure_geo_store(__metadata__).get("__debug__", False)
        )

    def _throttle(self):
        elapsed = time.time() - self._last_call_ts
        if elapsed < self._min_interval_s:
            time.sleep(self._min_interval_s - elapsed)
        self._last_call_ts = time.time()

    # ---------- Event Helpers ----------

    @staticmethod
    async def _emit_status(
        description: str, done: bool, __event_emitter__: EventEmitter
    ):
        if __event_emitter__:
            await __event_emitter__(
                {"type": "status", "data": {"description": description, "done": done}}
            )

    @staticmethod
    async def _emit_notification(
        title: str, content: str, __event_emitter__: EventEmitter
    ):
        if __event_emitter__:
            await __event_emitter__(
                {"type": "notification", "data": {"title": title, "content": content}}
            )

    async def _emit_debug_state(
        self, __metadata__, __user__, stage: str, __event_emitter__
    ):
        if not self._is_debug(__metadata__, __user__):
            return
        store = self._ensure_geo_store(__metadata__)
        dump = json.dumps(store, ensure_ascii=False, indent=2)
        await self._emit_notification(
            f"GeoStore Debug ({stage})", f"```json\n{dump}\n```", __event_emitter__
        )

    @staticmethod
    async def _emit_html(
        html: str,
        __user__: Optional[dict] = None,
        __event_emitter__: EventEmitter = None,
    ):
        if __event_emitter__ is None:
            return

        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Bereite HTML-Ausgabe vor...", "done": False},
            }
        )
        valves = GeoHelpers._user_valves(__user__)
        delivery = (valves.get("HTML_DELIVERY") or "data_url").strip().lower()

        try:
            if delivery == "attachment":
                await __event_emitter__(
                    {
                        "type": "file",
                        "data": {
                            "mime_type": "text/html",
                            "name": "geo_viewer.html",
                            "content": html,
                        },
                    }
                )
                await __event_emitter__(
                    {
                        "type": "message",
                        "data": {
                            "content": "Die Karte wurde als **geo_viewer.html** angehängt."
                        },
                    }
                )
            elif delivery == "raw":
                await __event_emitter__({"type": "message", "data": {"content": html}})
            elif delivery == "codeblock":
                await __event_emitter__(
                    {
                        "type": "message",
                        "data": {"content": "```html\n" + html + "\n```"},
                    }
                )
            else:
                url = "data:text/html;charset=utf-8," + quote(html)
                text = (
                    f"[Karte in neuem Tab öffnen]({url})\n\n"
                    "_Tipp: Bei Problemen HTML_DELIVERY auf `attachment` umstellen._"
                )
                await __event_emitter__({"type": "message", "data": {"content": text}})
        finally:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": "HTML-Ausgabe abgeschlossen.",
                        "done": True,
                    },
                }
            )

    # ---------- Geometrie & Utilities ----------

    @staticmethod
    def _point_on_segment(px, py, x1, y1, x2, y2, eps: float = 1e-12) -> bool:
        cross = (py - y1) * (x2 - x1) - (px - x1) * (y2 - y1)
        if abs(cross) > eps:
            return False
        dot = (px - x1) * (px - x2) + (py - y1) * (py - y2)
        return dot <= eps

    @staticmethod
    def _ray_casting_in_ring(lon: float, lat: float, ring: List[List[float]]) -> bool:
        inside = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if GeoHelpers._point_on_segment(lon, lat, x1, y1, x2, y2):
                return True
            if (y1 > lat) != (y2 > lat):
                x_intersect = (x2 - x1) * (lat - y1) / (
                    (y2 - y1) if (y2 - y1) != 0 else 1e-12
                ) + x1
                if lon < x_intersect:
                    inside = not inside
        return inside

    @staticmethod
    def _is_point_in_polygon(point: PointGeom, polygon: PolygonGeom) -> bool:
        lon, lat = point["coordinates"]
        geo_type = polygon.get("type")
        if geo_type == "Polygon":
            rings = polygon.get("coordinates", [])
            if not rings:
                return False
            if not GeoHelpers._ray_casting_in_ring(lon, lat, rings[0]):
                return False
            for hole in rings[1:]:
                if GeoHelpers._ray_casting_in_ring(lon, lat, hole):
                    return False
            return True
        if geo_type == "MultiPolygon":
            for rings in polygon.get("coordinates", []):
                if not rings:
                    continue
                if GeoHelpers._ray_casting_in_ring(lon, lat, rings[0]):
                    in_hole = any(
                        GeoHelpers._ray_casting_in_ring(lon, lat, hole)
                        for hole in rings[1:]
                    )
                    if not in_hole:
                        return True
            return False
        raise ValueError(f"Unsupported GeoJSON type: {geo_type}")

    @staticmethod
    def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        R = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    @staticmethod
    def _distance_of_point_geoms(p1: PointGeom, p2: PointGeom) -> Dict[str, float]:
        (lon1, lat1) = p1["coordinates"]
        (lon2, lat2) = p2["coordinates"]
        meters = GeoHelpers._haversine_m(lon1, lat1, lon2, lat2)
        return {"meters": meters, "kilometers": meters / 1000.0}

    @staticmethod
    def _try_parse_coord_string(value: str) -> Optional[List[float]]:
        """
        Akzeptiert Strings wie "lat, lon" | "lon, lat" | "lat lon" | "lon lat" | "lat;lon".
        Heuristik:
          - Wenn einer > 90 → das ist long.
          - Sind beide <= 90 → übliches "lat, lon" → drehen auf [lon, lat].
        Rückgabe: [lon, lat]
        """
        s = value.strip().replace(";", ",")
        parts = [p for p in re.split(r"[,\s]+", s) if p]
        if len(parts) != 2:
            return None
        try:
            a = float(parts[0])
            b = float(parts[1])
        except ValueError:
            return None
        abs_a, abs_b = abs(a), abs(b)
        if abs_a > 90 and abs_b <= 90:
            return [a, b]
        if abs_b > 90 and abs_a <= 90:
            return [b, a]
        if abs_a <= 90 and abs_b <= 90:
            return [b, a]
        return None

    @staticmethod
    def _last_feature_of_type(gs: JsonDict, geom_types: Union[str, List[str]]) -> Optional[JsonDict]:
        if isinstance(geom_types, str):
            geom_types = [geom_types]
        for feat in reversed(gs["geojson"]["features"]):
            if feat.get("geometry", {}).get("type") in geom_types:
                return feat
        return None

    @staticmethod
    def _last_point_geometry(gs: JsonDict) -> Optional[PointGeom]:
        feat = GeoHelpers._last_feature_of_type(gs, "Point")
        return feat["geometry"] if feat else None

    @staticmethod
    def _last_boundary_geometry(gs: JsonDict) -> Optional[PolygonGeom]:
        feat = GeoHelpers._last_feature_of_type(gs, ["Polygon", "MultiPolygon"])
        return feat["geometry"] if feat else None

    def _point_from_store_index(
        self, idx: int, __metadata__: Optional[dict]
    ) -> Optional[PointGeom]:
        gs = self._ensure_geo_store(__metadata__)
        pts = [
            f["geometry"]
            for f in gs["geojson"]["features"]
            if f.get("geometry", {}).get("type") == "Point"
        ]
        try:
            return pts[idx]
        except Exception:
            return None

    def _nominatim_search(
        self, base: str, params: Dict[str, Any], timeout: int = 30
    ) -> Optional[List[Dict[str, Any]]]:
        self._throttle()
        try:
            resp = self.session.get(f"{base}/search", params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    async def _geocode(self, q: str, __user__: Optional[dict]) -> Optional[PointGeom]:
        base = self._nominatim_base(__user__)
        cache_key = (base, q.strip().lower())
        if cache_key in GeoHelpers._geocode_cache:
            return GeoHelpers._geocode_cache[cache_key]
        data = self._nominatim_search(
            base, {"q": q, "format": "json", "limit": 1}, timeout=15
        )
        if not data:
            return None
        try:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
        except Exception:
            return None
        point = {"type": "Point", "coordinates": [lon, lat]}
        GeoHelpers._geocode_cache[cache_key] = point
        return point

    async def _fetch_boundary(
        self, q: str, __user__: Optional[dict]
    ) -> Optional[PolygonGeom]:
        base = self._nominatim_base(__user__)
        cache_key = (base, q.strip().lower())
        if cache_key in GeoHelpers._boundary_cache:
            return GeoHelpers._boundary_cache[cache_key]
        data = self._nominatim_search(
            base,
            {
                "q": q,
                "format": "json",
                "polygon_geojson": 1,
                "polygon_threshold": 0.001,
                "limit": 1,
                "addressdetails": 0,
            },
            timeout=30,
        )
        if not data:
            return None
        gj = data[0].get("geojson")
        if not gj or gj.get("type") not in ("Polygon", "MultiPolygon"):
            return None
        GeoHelpers._boundary_cache[cache_key] = gj
        return gj

    def _add_point_feature(
        self, gs: JsonDict, lon: float, lat: float, address: Optional[str] = None
    ) -> JsonDict:
        feat = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": {"kind": "point"},
        }
        if address:
            feat["properties"]["address"] = address
        self._fc(gs)["features"].append(feat)
        return feat

    def _add_boundary_feature(
        self, gs: JsonDict, geometry: PolygonGeom, label: str
    ) -> JsonDict:
        feat = {
            "type": "Feature",
            "geometry": geometry,
            "properties": {"kind": "boundary", "label": label},
        }
        self._fc(gs)["features"].append(feat)
        return feat


class Tools:
    """
    Öffentliche Geo-Tool-API für Open WebUI:
    - Klassenweiter GeoStore pro chat_id:
      { "geojson": FeatureCollection, "tests":[...], "__debug__": bool }
    - Öffentliche API (6 Methoden):
      * set_debug(enabled)
      * add_points(items)                 -> Punkte hinzufügen/auflösen
      * set_boundary(boundary_for=None)   -> Boundary setzen/verwenden
      * within(points=None, boundary_for=None) -> Punkt(e) in Boundary prüfen
      * distance(points=None, mode='pairwise'|'path') -> Distanzen
      * render_geodata()                  -> Karte ausgeben
    - „GeoStore-first“: Wenn Argumente fehlen, werden vorhandene Daten genutzt.
    - Caching & Throttling für Nominatim.
    """

    # --- Valves / UserValves (für OpenWebUI) ---
    class Valves(BaseModel):
        NOMINATIM_BASE_URL: str = Field(
            default="https://nominatim.openstreetmap.org",
            description="Basis-URL für Nominatim (ohne abschließenden Slash).",
        )
        NOMINATIM_USER_AGENT: str = Field(
            default="GeocoderScript/1.1 (your-mail@city.de)",
            description="User Agent für OSM Nominatim Abfrage.",
        )

    class UserValves(BaseModel):
        DEBUG_NOTIFICATIONS: bool = Field(
            default=False,
            description="Wenn aktiv, werden vor/nach jedem Funktionsaufruf GeoStore-Dumps gesendet.",
        )
        NOMINATIM_BASE_URL: str = Field(
            default="https://nominatim.openstreetmap.org",
            description="Basis-URL für Nominatim (ohne abschließenden Slash).",
        )
        HTML_DELIVERY: str = Field(
            default="data_url",
            description="Wie HTML ausgegeben wird: 'data_url' | 'attachment' | 'codeblock' | 'raw'",
        )

    def __init__(self):
        self.geo = GeoHelpers()

    async def set_debug(
        self,
        enabled: bool,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__: EventEmitter = None,
    ) -> Dict[str, Any]:
        await self.geo._emit_status("Aufruf: set_debug", False, __event_emitter__)
        store = self.geo._ensure_geo_store(__metadata__)
        store["__debug__"] = bool(enabled)
        await self.geo._emit_notification(
            "Debugging umgeschaltet",
            f"Debugging ist jetzt {'AKTIV' if store['__debug__'] else 'INAKTIV'}.",
            __event_emitter__,
        )
        await self.geo._emit_debug_state(__metadata__, __user__, "post", __event_emitter__)
        await self.geo._emit_status("Abgeschlossen: set_debug", True, __event_emitter__)
        return {"debug": store["__debug__"]}

    async def add_points(
        self,
        items: Union[
            str,
            int,
            Tuple[float, float],
            List[Union[str, int, Tuple[float, float], List[float], Dict[str, Any]]],
            List[float],
            Dict[str, Any],
        ],
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__: EventEmitter = None,
    ) -> Dict[str, Any]:
        """
        Nimmt 1..n Items (Adresse | GeoJSON-Point | [lon,lat] | Koord-String | Index) und
        speichert sie als Point-Features. Liefert deren Geometrien + Indizes zurück.
        """
        await self.geo._emit_status("Aufruf: add_points", False, __event_emitter__)
        await self.geo._emit_debug_state(__metadata__, __user__, "pre", __event_emitter__)
        gs = self.geo._ensure_geo_store(__metadata__)
        if not isinstance(items, list):
            items = [items]

        results: List[Dict[str, Any]] = []

        for v in items:
            geom: Optional[PointGeom] = None
            label: Optional[str] = None

            # Index?
            if isinstance(v, int):
                geom = self.geo._point_from_store_index(v, __metadata__)
                label = f"index:{v}"
            elif isinstance(v, str) and re.fullmatch(r"#?-?\d+", v.strip()):
                try:
                    idx = int(v[1:]) if v.startswith("#") else int(v)
                    geom = self.geo._point_from_store_index(idx, __metadata__)
                    label = f"index:{idx}"
                except Exception:
                    geom = None

            # GeoJSON Point?
            if (
                geom is None
                and isinstance(v, dict)
                and v.get("type") == "Point"
                and "coordinates" in v
            ):
                try:
                    lon, lat = float(v["coordinates"][0]), float(v["coordinates"][1])
                except Exception:
                    lon = lat = None
                if lon is not None and lat is not None:
                    geom = {"type": "Point", "coordinates": [lon, lat]}
                    label = "geojson"

            # [lon,lat] | (lon,lat)?
            if geom is None and isinstance(v, (list, tuple)) and len(v) == 2:
                try:
                    lon, lat = float(v[0]), float(v[1])
                    geom = {"type": "Point", "coordinates": [lon, lat]}
                    label = "coords"
                except Exception:
                    pass

            # Koordinaten-String?
            if geom is None and isinstance(v, str):
                coords = GeoHelpers._try_parse_coord_string(v)
                if coords:
                    lon, lat = coords
                    geom = {"type": "Point", "coordinates": [lon, lat]}
                    label = f"coords:{lon:.6f},{lat:.6f}"

            # Adresse?
            if geom is None and isinstance(v, str):
                geocoded = await self.geo._geocode(v, __user__)
                if geocoded:
                    geom = geocoded
                    label = v

            if not geom:
                results.append(
                    {"input": v, "error": "Punkt konnte nicht bestimmt werden."}
                )
                continue

            # Speichern
            feat = self.geo._add_point_feature(
                gs, geom["coordinates"][0], geom["coordinates"][1], address=label
            )
            results.append(
                {"input": v, "point": feat["geometry"], "index": None}
            )  # Index optional

        # Indizes nachträglich befüllen (Positionen der zuletzt hinzugefügten Punkte)
        all_pts = [
            f
            for f in gs["geojson"]["features"]
            if f.get("geometry", {}).get("type") == "Point"
        ]
        for r in reversed(results):
            if "point" in r:
                for i in range(len(all_pts) - 1, -1, -1):
                    if all_pts[i]["geometry"] == r["point"] and r.get("index") is None:
                        r["index"] = i
                        break

        out = {"count": len(results), "results": results}
        await self.geo._emit_debug_state(__metadata__, __user__, "post", __event_emitter__)
        await self.geo._emit_status("Abgeschlossen: add_points", True, __event_emitter__)
        return out

    async def set_boundary(
        self,
        boundary_for: Optional[str] = None,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__: EventEmitter = None,
    ) -> Dict[str, Any]:
        """
        Setzt/holt eine Boundary:
        - Wenn boundary_for angegeben, via Nominatim laden und speichern.
        - Sonst: letzte gespeicherte Boundary verwenden.
        """
        await self.geo._emit_status("Aufruf: set_boundary", False, __event_emitter__)
        await self.geo._emit_debug_state(__metadata__, __user__, "pre", __event_emitter__)

        gs = self.geo._ensure_geo_store(__metadata__)

        if boundary_for:
            poly = await self.geo._fetch_boundary(boundary_for, __user__)
            if not poly:
                out = {
                    "error": "Kein gültiges Boundary-Polygon gefunden.",
                    "requested": boundary_for,
                }
            else:
                self.geo._add_boundary_feature(gs, poly, label=boundary_for)
                out = {"boundary_for": boundary_for, "geojson": poly}
        else:
            poly = GeoHelpers._last_boundary_geometry(gs)
            if not poly:
                out = {"error": "Keine Boundary im GeoStore vorhanden."}
            else:
                out = {"boundary_for": None, "geojson": poly}

        await self.geo._emit_debug_state(__metadata__, __user__, "post", __event_emitter__)
        await self.geo._emit_status("Abgeschlossen: set_boundary", True, __event_emitter__)
        return out

    async def within(
        self,
        points: Optional[
            Union[
                str,
                int,
                Tuple[float, float],
                List[Union[str, int, Tuple[float, float], List[float], Dict[str, Any]]],
                List[float],
                Dict[str, Any],
            ]
        ] = None,
        boundary_for: Optional[str] = None,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__: EventEmitter = None,
    ) -> Dict[str, Any]:
        """
        Prüft 1..n Punkt(e) gegen eine Boundary.
        - points None  -> alle gespeicherten Punkte verwenden.
        - boundary_for None -> letzte gespeicherte Boundary verwenden.
        Speichert jeden Test in gs["tests"].
        """
        await self.geo._emit_status("Aufruf: within", False, __event_emitter__)
        await self.geo._emit_debug_state(__metadata__, __user__, "pre", __event_emitter__)

        gs = self.geo._ensure_geo_store(__metadata__)

        # Boundary sicherstellen
        ensured = await self.set_boundary(
            boundary_for, __user__, __metadata__, __event_emitter__=None
        )
        if ensured.get("error"):
            out = {"error": f"Boundary-Fehler: {ensured['error']}"}
            await self.geo._emit_debug_state(
                __metadata__, __user__, "post", __event_emitter__
            )
            await self.geo._emit_status("Abgeschlossen: within", True, __event_emitter__)
            return out
        polygon_geo = ensured["geojson"]
        polygon_label = ensured.get("boundary_for")

        # Punkte bestimmen
        selected: List[PointGeom] = []
        if points is None:
            feats = gs["geojson"]["features"]
            selected = [
                f["geometry"]
                for f in feats
                if f.get("geometry", {}).get("type") == "Point"
            ]
            if not selected:
                out = {"error": "Keine Punkte im GeoStore vorhanden."}
                await self.geo._emit_debug_state(
                    __metadata__, __user__, "post", __event_emitter__
                )
                await self.geo._emit_status(
                    "Abgeschlossen: within", True, __event_emitter__
                )
                return out
        else:
            added = await self.add_points(
                points, __user__, __metadata__, __event_emitter__=None
            )
            # nur erfolgreich hinzugefügte Punkte verwenden (auch Indizes ermittelt)
            for r in added["results"]:
                if "point" in r:
                    selected.append(r["point"])

        # Prüfung & Persist
        results: List[JsonDict] = []
        feats = gs["geojson"]["features"]
        point_feats = [f for f in feats if f.get("geometry", {}).get("type") == "Point"]

        def address_of_point(p: PointGeom) -> Optional[str]:
            # Suche die Feature-Properties des zugehörigen Punktes (für Label im Popup)
            for f in reversed(point_feats):
                if f.get("geometry") == p:
                    props = f.get("properties", {}) or {}
                    return props.get("address") or props.get("label")
            return None

        for p in selected:
            try:
                inside = GeoHelpers._is_point_in_polygon(p, polygon_geo)
                addr = address_of_point(p)
                item = {"inside": inside, "point": p}
                if addr:
                    item["address"] = addr
                if polygon_label:
                    item["boundary_for"] = polygon_label
                results.append(item)
                gs["tests"].append(item.copy())
            except Exception as e:
                addr = address_of_point(p)
                item = {
                    "inside": False,
                    "point": p,
                    "error": f"Fehler bei Prüfung: {e}",
                }
                if addr:
                    item["address"] = addr
                if polygon_label:
                    item["boundary_for"] = polygon_label
                results.append(item)
                gs["tests"].append(item.copy())

        out = {"boundary_for": polygon_label, "results": results, "count": len(results)}

        await self.geo._emit_debug_state(__metadata__, __user__, "post", __event_emitter__)
        await self.geo._emit_status("Abgeschlossen: within", True, __event_emitter__)
        return out

    async def distance(
        self,
        points: Optional[
            Union[
                List[Union[str, int, Tuple[float, float], List[float], Dict[str, Any]]],
                Union[str, int, Tuple[float, float], List[float], Dict[str, Any]],
            ]
        ] = None,
        mode: str = "pairwise",
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__: EventEmitter = None,
    ) -> Dict[str, Any]:
        """
        Distanzen für >=2 Punkte.
        - points None  -> alle gespeicherten Punkte (mind. 2 erforderlich)
        - mode: 'pairwise' | 'path'
        Speichert jede Distanz als Test in gs["tests"].
        """
        await self.geo._emit_status("Aufruf: distance", False, __event_emitter__)
        await self.geo._emit_debug_state(__metadata__, __user__, "pre", __event_emitter__)
        gs = self.geo._ensure_geo_store(__metadata__)

        # Punkte bestimmen
        resolved: List[PointGeom] = []
        if points is None:
            feats = gs["geojson"]["features"]
            resolved = [
                f["geometry"]
                for f in feats
                if f.get("geometry", {}).get("type") == "Point"
            ]
        else:
            added = await self.add_points(
                points, __user__, __metadata__, __event_emitter__=None
            )
            for r in added["results"]:
                if "point" in r:
                    resolved.append(r["point"])

        if len(resolved) < 2:
            out = {
                "error": "Bitte mindestens zwei Punkte bereitstellen oder im GeoStore haben."
            }
            await self.geo._emit_debug_state(
                __metadata__, __user__, "post", __event_emitter__
            )
            await self.geo._emit_status("Abgeschlossen: distance", True, __event_emitter__)
            return out

        out: Dict[str, Any] = {"mode": mode, "count_points": len(resolved)}

        if mode == "pairwise":
            pairs: List[Dict[str, Any]] = []
            n = len(resolved)
            for i in range(n):
                for j in range(i + 1, n):
                    dist = GeoHelpers._distance_of_point_geoms(resolved[i], resolved[j])
                    km = dist["kilometers"]
                    pairs.append({"pair": [i, j], **dist})
                    gs["tests"].append(
                        {
                            "type": "distance",
                            "a": resolved[i],
                            "b": resolved[j],
                            **dist,
                            "label": f"{km:.3f} km",
                        }
                    )
            out["pairs"] = pairs

        elif mode == "path":
            segs: List[Dict[str, Any]] = []
            total_m = 0.0
            for i in range(len(resolved) - 1):
                dist = GeoHelpers._distance_of_point_geoms(resolved[i], resolved[i + 1])
                km = dist["kilometers"]
                total_m += dist["meters"]
                segs.append({"segment": [i, i + 1], **dist})
                gs["tests"].append(
                    {
                        "type": "distance",
                        "a": resolved[i],
                        "b": resolved[i + 1],
                        **dist,
                        "label": f"{km:.3f} km",
                    }
                )
            out["segments"] = segs
            out["total"] = {"meters": total_m, "kilometers": total_m / 1000.0}
        else:
            out = {"error": f"Unbekannter mode: {mode}. Erlaubt: 'pairwise'|'path'."}

        await self.geo._emit_debug_state(__metadata__, __user__, "post", __event_emitter__)
        await self.geo._emit_status("Abgeschlossen: distance", True, __event_emitter__)
        return out

    async def render_geodata(
        self,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__: EventEmitter = None,
    ) -> None:
        await self.geo._emit_status("Aufruf: render_geodata", False, __event_emitter__)
        await self.geo._emit_debug_state(__metadata__, __user__, "pre", __event_emitter__)

        gs = self.geo._ensure_geo_store(__metadata__)
        geo_json = json.dumps(gs, ensure_ascii=False)

        html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <title>Geo Viewer</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    #map {{ height: 520px; width: 100%; }}
    body {{ margin:0; padding:0; }}
    .inside-true {{ color: #0a7f2e; }}
    .inside-false {{ color: #b00020; }}
    .distance-label {{
      font: 12px/1.2 Arial, sans-serif;
      color: #111;
      text-shadow: 0 1px 2px #fff;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const data = {geo_json};
    const map = L.map('map', {{ preferCanvas: true }});
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap-Mitwirkende'
    }}).addTo(map);

    const group = L.featureGroup().addTo(map);

    function toLatLng(coord) {{ return [coord[1], coord[0]]; }}
    function coordsToLatLngs(ring) {{ return ring.map(c => toLatLng(c)); }}

    function addPolygon(geo, label) {{
      if (!geo) return;
      const style = {{ color: '#1368ce', weight: 2, fillOpacity: 0.12 }};
      if (geo.type === 'Polygon') {{
        const latlngs = geo.coordinates.map(r => coordsToLatLngs(r));
        L.polygon(latlngs, style).addTo(group).bindPopup(label || 'Polygon');
      }} else if (geo.type === 'MultiPolygon') {{
        const latlngs = geo.coordinates.map(poly => poly.map(r => coordsToLatLngs(r)));
        L.polygon(latlngs, style).addTo(group).bindPopup(label || 'MultiPolygon');
      }}
    }}

    (data.geojson && data.geojson.features ? data.geojson.features : []).forEach(f => {{
      const g = f.geometry || {{}};
      const p = f.properties || {{}};
      if (g.type === 'Point' && Array.isArray(g.coordinates)) {{
        const [lon, lat] = g.coordinates;
        if (lat != null && lon != null) {{
          L.marker([lat, lon]).addTo(group).bindPopup(p.address || p.label || 'Point');
        }}
      }} else if (g.type === 'Polygon' || g.type === 'MultiPolygon') {{
        addPolygon(g, p.label || 'Boundary');
      }}
    }});

    (data.tests || []).forEach(t => {{
      if (t && t.type === 'distance') {{
        const a = t.a && t.a.coordinates ? t.a.coordinates : null;
        const b = t.b && t.b.coordinates ? t.b.coordinates : null;
        if (!a || !b) return;
        const [lon1, lat1] = a; const [lon2, lat2] = b;
        const line = L.polyline([[lat1, lon1], [lat2, lon2]], {{ weight: 3, opacity: 0.75, color: '#b00020' }}).addTo(group);
        const km = (typeof t.kilometers === 'number') ? t.kilometers : ((t.meters || 0) / 1000.0);
        const labelText = t.label || (km ? (km.toFixed(3) + ' km') : 'Distanz');
        line.bindPopup(labelText);
        const midLat = (lat1 + lat2) / 2; const midLon = (lon1 + lon2) / 2;
        const icon = L.divIcon({{ className: 'distance-label', html: labelText, iconSize: [0, 0] }});
        L.marker([midLat, midLon], {{ icon }}).addTo(group);
        return;
      }}
      if (!t || !t.point || !t.point.coordinates) return;
      const [lon, lat] = t.point.coordinates;
      const ok = !!t.inside;
      const icon = L.divIcon({{
        className: ok ? 'inside-true' : 'inside-false',
        html: ok ? '●' : '■', iconSize: [12, 12]
      }});
      L.marker([lat, lon], {{ icon }}).addTo(group).bindPopup(
        (ok ? 'Inside' : 'Outside')
        + (t.address ? ' • ' + t.address : '')
        + (t.boundary_for ? ' (gegen ' + t.boundary_for + ')' : '')
      );
    }});

    if (group.getLayers().length) {{ map.fitBounds(group.getBounds().pad(0.12)); }}
    else {{ map.setView([51.0, 10.0], 5); }}
  </script>
</body>
</html>"""

        await self.geo._emit_html(html, __user__, __event_emitter__)
        await self.geo._emit_debug_state(__metadata__, __user__, "post", __event_emitter__)
        await self.geo._emit_status(
            "Abgeschlossen: render_geodata", True, __event_emitter__
        )


# --- Minimaler, LLM-freundlicher tool_spec ---
tool_spec = {
    "tools": [
        {
            "name": "set_debug",
            "description": "Schaltet Debugging pro Chat ein/aus. Bei aktivem Debugging wird der aktuelle GeoStore als Notification gesendet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "True = Debug an, False = Debug aus",
                    }
                },
                "required": ["enabled"],
            },
        },
        {
            "name": "add_points",
            "description": "Fügt 1..n Punkte zum GeoStore hinzu (Adresse, GeoJSON-Point, [lon,lat], Koordinaten-String oder GeoStore-Index '#-1').",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "description": "Einzelnes Item oder Liste von Items: Adresse | GeoJSON-Point | [lon,lat] | Koordinaten-String | GeoStore-Index (#-1, 0, -1)."
                    }
                },
                "required": ["items"],
            },
        },
        {
            "name": "set_boundary",
            "description": "Setzt/holt die Boundary (Polygon/MultiPolygon). Ohne boundary_for wird die zuletzt gespeicherte Boundary verwendet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "boundary_for": {
                        "type": "string",
                        "description": "Name/Entität (z. B. Stadt), deren Boundary geladen wird. Optional.",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "within",
            "description": "Prüft 1..n Punkt(e) gegen eine Boundary. Ohne Argumente werden alle gespeicherten Punkte gegen die zuletzt gespeicherte Boundary geprüft.",
            "parameters": {
                "type": "object",
                "properties": {
                    "points": {
                        "description": "Optional: Ein Punkt oder Liste von Punkten (Adresse | GeoJSON-Point | [lon,lat] | String | GeoStore-Index)."
                    },
                    "boundary_for": {
                        "type": "string",
                        "description": "Optional: Boundary-Name; sonst letzte Boundary.",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "distance",
            "description": "Berechnet Distanzen. Ohne Punkte werden alle gespeicherten Punkte genutzt (>=2).",
            "parameters": {
                "type": "object",
                "properties": {
                    "points": {
                        "description": "Optional: Liste/Einzelpunkt (Adresse | GeoJSON-Point | [lon,lat] | String | GeoStore-Index)."
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["pairwise", "path"],
                        "description": "pairwise = alle Paare; path = Summe entlang der Reihenfolge.",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "render_geodata",
            "description": "Rendern der Karte mit allen gespeicherten Features und Tests.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    ]
}
