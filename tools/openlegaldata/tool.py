"""
title: OpenLegalData Adapter
description: Durchsucht Rechtsprechung und Gesetze ueber die offene OpenLegalData.io-API (Gerichtsentscheidungen im Volltext, Aktenzeichen-Lookup, Gesetzbuecher/Paragraphen) und liefert die Inhalte samt Quellen an das Sprachmodell.
author: Florian Schade - Hochsauerlandkreis
version: 1.0
license: keine Lizenzangabe im Quellprojekt
original_author: Florian Schade – Hochsauerlandkreis
source_url: https://gitlab.opencode.de/kommi/adapter/openlegaldata

KommI-Adapter: gitlab.opencode.de/kommi/adapter/openlegaldata

Nutzt ausschliesslich die oeffentliche, dokumentierte REST-API von
de.openlegaldata.io (Rechtsprechung + Gesetze). Das Zielsystem ist ueber
die Valve base_url konfigurierbar (Default: die oeffentliche OpenLegalData-
Instanz). Keine externen Abhaengigkeiten ausser pydantic (von OpenWebUI
bereitgestellt).

Dieses Modul stellt vier vom LLM aufrufbare Tools bereit:
- searchRechtsprechung: Suche in Gerichtsentscheidungen ueber die
  OpenLegalData-API (de.openlegaldata.io/api/cases/). Liefert je Treffer
  id/slug/Gericht/Aktenzeichen/Datum/Typ; damit kann anschliessend
  getRechtsprechung aufgerufen werden.
- getRechtsprechung: Abruf einer Gerichtsentscheidung (id oder slug aus
  searchRechtsprechung). Liefert Volltext oder erkannte Abschnitte
  (Tenor/Tatbestand/Gruende).
- searchOpenLegalDataGesetz: Client-seitige Titel-/Paragraphensuche
  innerhalb eines Gesetzbuchs (gesetzbuch ist Pflichtfeld). Keine
  uebergreifende Suche ueber alle Gesetze, keine Volltextsuche im
  Normtext (siehe API-Einschraenkung unten).
- getOpenLegalDataGesetz: Abruf eines Gesetzbuchs (Kuerzel/ID). Modi:
  Inhaltsverzeichnis (toc), ausgewaehlte Paragraphen (paragraphs) oder
  Volltext (fulltext).

Datenzugang (Stand 2026-07-03):
- Rechtsprechung-Volltextsuche: GET {base}/cases/search/?text=... (echte
  Elasticsearch-Suche mit snippets; page/page_size)
- Aktenzeichen exakt:            GET {base}/cases/?file_number=<AZ>
- Entscheidung im Detail:        GET {base}/cases/<id>/ (mit content-HTML)
- Courts: GET {base}/courts/?search=... (Namensaufloesung, funktioniert;
  liefert u. a. "code", z. B. "LAGBW")
- Laws:  GET {base}/laws/?book_id=<id> (Buch-Normen), GET {base}/laws/<id>/
- Law Books: GET {base}/law_books/?code=<kuerzel> (exakte Kuerzelaufloesung)

WICHTIGE API-EINSCHRAENKUNGEN (live verifiziert, Stand 2026-07-03) - das
sind Bugs/Eigenheiten der oeffentlichen API, keine Fehler dieses Moduls:
- "search=" auf /cases/, /laws/ und /law_books/ wird IGNORIERT (liefert
  immer die volle, ungefilterte Liste). Fuer Rechtsprechung ist deshalb der
  separate Endpunkt /cases/search/?text=... noetig; fuer Gesetze "code="
  (exakt) auf /law_books/ und "book_id=" auf /laws/.
- Auf /cases/search/ ist der Gericht-Filter "court=" ein Gerichts-CODE
  (z. B. "LAGBW"), keine numerische ID. Funktionierende Filter dort:
  court=<code>, court_jurisdiction=<wert>, decision_type=<wert>.
- Datums-Filter auf /cases/search/ (date_after/date_from/...) werden
  ignoriert -> Datum wird in diesem Modul client-seitig gefiltert.
- /cases/ nutzt page/page_size, /laws/ nutzt limit/offset (uneinheitlich).

Hinweis: OpenLegalData ist ein Community-Projekt ohne amtliche
Qualitaetssicherung. Fuer rechtsverbindliche Zwecke sind die amtlichen
Verkuendungsblaetter bzw. Gerichtsveroeffentlichungen massgeblich (siehe
hinweis-Feld in jeder Tool-Antwort).

Installation in OpenWebUI:
1. Adminbereich -> Tools -> Neues Tool
2. Inhalt dieser Datei einfuegen
3. Valves konfigurieren (i. d. R. Defaults ausreichend)
"""

# --------------------------------------------------------------------------
# Herkunft / Provenance
#
# Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
# Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
# unverändert.
#
#   Projekt : OpenLegalData-Adapter
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/openlegaldata
#   Datei   : openlegaldata-adapter.py
#   Autor   : Florian Schade – Hochsauerlandkreis
#   Lizenz  : keine Lizenzangabe im Quellprojekt
#
# Das Quellprojekt erklärt keine Lizenz: es enthält weder eine LICENSE-Datei
# noch eine license-Angabe im Dateikopf. Damit liegen alle Rechte beim
# Urheber. Die Übernahme in diesen Katalog erfolgt auf Grundlage der
# Veröffentlichung auf openCode, der Open-Source-Plattform der öffentlichen
# Verwaltung, und ist ausdrücklich keine Lizenzeinräumung. Wer diesen Code
# weiterverwendet, sollte die Rechtelage mit dem oben genannten Urheber
# klären. Auf Wunsch des Urhebers wird das Werkzeug aus dem Katalog
# entfernt.
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import html
import json
import re
import threading
import time
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

# Nutzer-Eingabe -> court_type-Wert (Filter "Instanz").
INSTANZ_MAP: Dict[str, str] = {
    "bgh": "BGH",
    "olg": "OLG",
    "lg": "LG",
    "ag": "AG",
    "arbg": "ArbG",
    "lag": "LAG",
    "bag": "BAG",
    "sg": "SG",
    "lsg": "LSG",
    "bsg": "BSG",
    "fg": "FG",
    "bfh": "BFH",
    "vg": "VG",
    "ovg": "OVG",
    "bverwg": "BVerwG",
    "verfg": "VerfG",
}

# Nutzer-Eingabe -> court__jurisdiction-Wert (Filter "Gerichtsbarkeit").
GERICHTSBARKEIT_MAP: Dict[str, str] = {
    "ordentlich": "Ordentliche Gerichtsbarkeit",
    "arbeit": "Arbeitsgerichtsbarkeit",
    "verwaltung": "Verwaltungsgerichtsbarkeit",
    "finanzen": "Finanzgerichtsbarkeit",
    "sozial": "Sozialgerichtsbarkeit",
    "verfassung": "Verfassungsgerichtsbarkeit",
}

# Nutzer-Eingabe -> type-Wert (Filter "Entscheidungstyp").
ENTSCHEIDUNGSTYP_MAP: Dict[str, str] = {
    "urteil": "Urteil",
    "endurteil": "Endurteil",
    "beschluss": "Beschluss",
    "gerichtsbescheid": "Gerichtsbescheid",
}

# Ueberschriften, anhand derer Entscheidungstexte grob gegliedert werden.
CASE_SECTION_HEADINGS: Dict[str, Tuple[str, ...]] = {
    "tenor": ("tenor",),
    "tatbestand": ("tatbestand",),
    "gruende": ("entscheidungsgruende", "gruende", "gründe", "aus den gründen"),
}

HINWEIS = (
    "Daten von de.openlegaldata.io (Community-Projekt, Rohdaten ohne "
    "amtliche Qualitaetssicherung). Fuer rechtsverbindliche Zwecke sind "
    "die amtlichen Verkuendungsblaetter bzw. Gerichtsveroeffentlichungen "
    "massgeblich."
)


class _HtmlToText(HTMLParser):
    """Minimaler HTML->Text-Parser (block-bewusst) ohne externe Dependencies."""

    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
    _SKIP = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        if t in self._SKIP:
            self._skip += 1
        elif t in self._BLOCK:
            self._parts.append("\n")
        elif t == "td":
            self._parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self._SKIP and self._skip:
            self._skip -= 1
        elif t in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _html_to_text(html_str: str) -> str:
    parser = _HtmlToText()
    parser.feed(html_str or "")
    return parser.get_text()


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default="https://de.openlegaldata.io/api",
            description="Basis-URL der OpenLegalData-API ohne abschliessenden Slash.",
        )
        api_token: str = Field(
            default="",
            description=(
                "Optionaler API-Token. Wenn gesetzt, wird "
                "'Authorization: Token <token>' gesendet. Lesezugriffe "
                "funktionieren auch ohne Token; ein Token kann hoehere "
                "Rate-Limits ermoeglichen."
            ),
        )
        timeout_seconds: int = Field(
            default=20,
            ge=1,
            le=120,
            description="Timeout fuer externe HTTP-Aufrufe in Sekunden.",
        )
        min_request_interval: float = Field(
            default=1.0,
            ge=0.0,
            le=10.0,
            description="Mindestabstand zwischen externen Requests in Sekunden (Rate-Limit).",
        )
        max_search_results: int = Field(
            default=20,
            ge=1,
            le=100,
            description="Globale Obergrenze fuer Suchtreffer.",
        )
        max_response_bytes: int = Field(
            default=15_000_000,
            ge=100_000,
            le=200_000_000,
            description="Maximale Groesse einer einzelnen HTTP-Antwort in Bytes.",
        )
        max_output_chars: int = Field(
            default=0,
            ge=0,
            description="Optionale Ausgabelaengenbegrenzung. 0 = unbegrenzt.",
        )
        max_law_pages: int = Field(
            default=20,
            ge=1,
            le=200,
            description=(
                "Obergrenze der Seiten (a page_size Eintraege), die "
                "getOpenLegalDataGesetz beim Laden eines Gesetzbuchs "
                "abruft. Schuetzt vor zu vielen sequentiellen API-Calls "
                "bei sehr grossen Gesetzbuechern."
            ),
        )
        debug: bool = Field(
            default=False,
            description="Wenn true, werden Debug-Informationen ueber den event_emitter ausgegeben.",
        )

    class UserValves(BaseModel):
        preferred_output_language: str = Field(
            default="de",
            description="Bevorzugte Sprache fuer Hinweis- und Fehlermeldungen. Rechtstexte bleiben unveraendert.",
        )
        default_case_search_limit: int = Field(
            default=10,
            ge=1,
            le=50,
            description="Nutzerspezifisches Standardlimit fuer searchRechtsprechung.",
        )
        default_law_search_limit: int = Field(
            default=10,
            ge=1,
            le=50,
            description="Nutzerspezifisches Standardlimit fuer searchOpenLegalDataGesetz.",
        )
        pretty_json: bool = Field(
            default=True,
            description="Wenn true, werden Tool-Ergebnisse als eingerueckes JSON ausgegeben.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.user_valves = self.UserValves()
        self._lock = threading.Lock()
        self._last_request = 0.0

    # ------------------------------------------------------------------ #
    #  HTTP (urllib, dependency-frei) mit Rate-Limit                     #
    # ------------------------------------------------------------------ #

    def _get_json_sync(self, path: str, params: Optional[Dict[str, Any]] = None) -> dict:
        query = "?" + urlencode(params, doseq=True) if params else ""
        url = self.valves.base_url.rstrip("/") + path + query
        headers = {
            "Accept": "application/json",
            "User-Agent": "OpenWebUI-OpenLegalData-Tools/1.0",
        }
        if self.valves.api_token:
            headers["Authorization"] = f"Token {self.valves.api_token}"
        raw = self._open(Request(url, headers=headers, method="GET"))
        return json.loads(raw.decode("utf-8"))

    def _open(self, request: Request) -> bytes:
        with self._lock:
            wait = self.valves.min_request_interval - (time.time() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                try:
                    with urlopen(request, timeout=self.valves.timeout_seconds) as resp:
                        return resp.read(self.valves.max_response_bytes + 1)
                except HTTPError as exc:
                    raise ValueError(
                        f"HTTP {exc.code} bei {request.full_url}: {exc.reason}"
                    ) from exc
            finally:
                self._last_request = time.time()

    # ------------------------------------------------------------------ #
    #  Ausgabe- / Emit-Hilfsfunktionen                                   #
    # ------------------------------------------------------------------ #

    def _to_json(self, payload: Dict[str, Any]) -> str:
        indent = 2 if self.user_valves.pretty_json else None
        result = json.dumps(payload, ensure_ascii=False, indent=indent)
        max_chars = int(self.valves.max_output_chars or 0)
        if max_chars > 0 and len(result) > max_chars:
            return (
                result[:max_chars]
                + "\n... Ausgabe durch max_output_chars gekuerzt ..."
            )
        return result

    async def _emit_status(self, __event_emitter__, description: str, done: bool) -> None:
        if __event_emitter__ is None:
            return
        try:
            await __event_emitter__(
                {"type": "status", "data": {"description": description, "done": done}}
            )
        except Exception:
            return

    async def _emit_debug(self, __event_emitter__, payload: Dict[str, Any]) -> None:
        if __event_emitter__ is None or not self.valves.debug:
            return
        try:
            await __event_emitter__(
                {
                    "type": "message",
                    "data": {
                        "content": "\n```json\n"
                        + json.dumps(payload, ensure_ascii=False, indent=2)
                        + "\n```\n"
                    },
                }
            )
        except Exception:
            return

    # ------------------------------------------------------------------ #
    #  Paragraphen-Normalisierung / generische Namensaufloesung          #
    # ------------------------------------------------------------------ #

    def _normalize_requested_refs(self, paragraphs: Sequence[str]) -> Set[str]:
        refs: Set[str] = set()
        for p in paragraphs:
            norm = self._normalize_paragraph_ref(p)
            if norm:
                refs.add(norm)
        return refs

    def _normalize_paragraph_ref(self, value: Any) -> str:
        text = html.unescape(str(value or "")).strip().lower()
        if not text:
            return ""
        text = text.replace("§§", "§")
        text = re.sub(r"\b(paragraph|paragraf|para\.?|nr\.)\b", "", text)
        text = re.sub(r"\bartikel\b", "art", text)
        text = text.replace("§", "")
        text = re.sub(r"[^a-z0-9]+", "", text)
        if text.startswith("art"):
            return text
        number = re.search(r"([0-9]+[a-z]?)", text)
        return number.group(1) if number else text

    def _norm_matches(self, norm: Dict[str, Any], requested_refs: Set[str]) -> bool:
        candidates = {
            self._normalize_paragraph_ref(norm.get("section") or ""),
            self._normalize_paragraph_ref(norm.get("title") or ""),
        }
        return bool(candidates.intersection(requested_refs))

    def _resolve_entity(self, list_path: str, query: str) -> Tuple[Optional[dict], int]:
        """Sucht list_path?search=query und liefert (bestes_Ergebnis, Gesamtzahl_Treffer)."""
        data = self._get_json_sync(list_path, {"search": query, "limit": 5})
        results = data.get("results", [])
        if not results:
            return None, 0
        return results[0], data.get("count", len(results))

    # ------------------------------------------------------------------ #
    #  searchRechtsprechung                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _umlaut_variant(text: str) -> str:
        """ue/ae/oe -> ü/ä/ö (Fallback fuer Umlaut-Umschreibungen in Eingaben)."""
        for a, b in (("ue", "ü"), ("ae", "ä"), ("oe", "ö"),
                     ("Ue", "Ü"), ("Ae", "Ä"), ("Oe", "Ö")):
            text = text.replace(a, b)
        return text

    def _resolve_court(self, gericht: str) -> Tuple[Optional[dict], Optional[Dict[str, Any]]]:
        """Loest einen Gerichtsnamen auf ein Gerichts-Objekt auf (mit 'code' fuer
        /cases/search/ und 'id' fuer /cases/). Wirft ValueError bei Nichtauflösung."""
        if not gericht:
            return None, None
        best, total = self._resolve_entity("/courts/", gericht)
        if best is None:
            alt = self._umlaut_variant(gericht)
            if alt != gericht:
                best, total = self._resolve_entity("/courts/", alt)
        if best is None:
            raise ValueError(f"Gericht '{gericht}' nicht gefunden. Bitte Name/Ort/Slug pruefen.")
        resolution = {
            "query": gericht,
            "resolved_name": best.get("name"),
            "resolved_code": best.get("code"),
            "resolved_id": best.get("id"),
            "total_matches": total,
        }
        return best, resolution

    def _resolve_court_graceful(
        self, gericht: str
    ) -> Tuple[Optional[dict], Optional[Dict[str, Any]], Optional[str]]:
        """Wie _resolve_court, aber ohne Abbruch: bei Nichtauflösung
        (best, resolution)=None und eine Warnung als drittes Element."""
        if not (gericht or "").strip():
            return None, None, None
        try:
            best, resolution = self._resolve_court(gericht.strip())
            return best, resolution, None
        except ValueError as exc:
            return None, None, f"{exc} Suche wurde ohne Gerichtsfilter durchgefuehrt."

    @staticmethod
    def _validate_date(value: str, field_name: str) -> str:
        if not value:
            return ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            raise ValueError(f"{field_name} muss im Format YYYY-MM-DD angegeben werden.")
        return value.strip()

    @staticmethod
    def _looks_like_aktenzeichen(query: str) -> bool:
        """Grobe Heuristik: Aktenzeichen enthalten Schraegstrich + Ziffern
        (z. B. "12 SLa 775/25", "I ZR 78/25", "8 O 4860/25")."""
        return "/" in query and any(c.isdigit() for c in query)

    @staticmethod
    def _clean_snippets(snippets: Optional[List[Dict[str, Any]]]) -> str:
        """Fasst die <em>-markierten Trefferausschnitte zu einem Klartext zusammen."""
        parts: List[str] = []
        seen: Set[str] = set()
        for sn in snippets or []:
            txt = html.unescape(re.sub(r"</?em>", "", sn.get("text") or "")).strip()
            if txt and txt not in seen:
                seen.add(txt)
                parts.append(txt)
        return " … ".join(parts)

    async def searchRechtsprechung(
        self,
        query: str,
        gericht: str = "",
        instanz: str = "",
        gerichtsbarkeit: str = "",
        entscheidungstyp: str = "",
        datum_von: str = "",
        datum_bis: str = "",
        sortierung: str = "relevanz",
        limit: Optional[int] = None,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Sucht Gerichtsentscheidungen (Urteile, Beschluesse) und liefert je
        Treffer u. a. id/slug; mit id oder slug kann anschliessend
        getRechtsprechung fuer den Volltext aufgerufen werden.

        Drei Suchmodi (automatisch gewaehlt):
          - Enthaelt query ein Aktenzeichen (Schraegstrich + Ziffern, z. B.
            "12 SLa 775/25"), wird exakt danach gesucht (mode "aktenzeichen").
          - Ist query LEER, werden Entscheidungen nach Datum aufgelistet
            (mode "liste") - z. B. fuer "das aktuellste Urteil" (sortierung
            "neueste") oder Entscheidungen in einem Zeitraum (datum_von/bis).
          - Sonst Volltextsuche ueber den Entscheidungstext (mode "volltext");
            je Treffer werden passende Textausschnitte (snippet) mitgeliefert.

        Filter (im Volltext- und Liste-Modus wirksam):
          - gericht: Name/Ort eines Gerichts, z. B. "LAG Baden-Wuerttemberg".
          - instanz: "AG", "LG", "OLG", "BGH", "ArbG", "LAG", "BAG", "SG",
            "LSG", "BSG", "FG", "BFH", "VG", "OVG", "BVerwG", "VerfG".
          - gerichtsbarkeit: "ordentlich", "arbeit", "verwaltung",
            "finanzen", "sozial", "verfassung".
          - entscheidungstyp: "Urteil", "Beschluss", "Endurteil",
            "Gerichtsbescheid" o. ae.
          - datum_von/datum_bis: YYYY-MM-DD (client-seitig gefiltert).
          - sortierung: "relevanz" (Standard), "neueste", "aelteste".

        :param query: Thema/Stichwort, ein konkretes Aktenzeichen ODER leer (= Liste nach Datum).
        :param gericht: optionaler Gerichtsname/-ort.
        :param instanz: optionaler Instanz-Filter (siehe oben).
        :param gerichtsbarkeit: optionaler Gerichtsbarkeits-Filter (siehe oben).
        :param entscheidungstyp: optionaler Entscheidungstyp-Filter.
        :param datum_von: optionales Startdatum (YYYY-MM-DD).
        :param datum_bis: optionales Enddatum (YYYY-MM-DD).
        :param sortierung: "relevanz" | "neueste" | "aelteste".
        :param limit: optionales Trefferlimit (durch max_search_results begrenzt).
        :return: JSON mit Fundstellen (id, slug, ... plus snippet bzw. file_number).
        """
        safe_query = (str(query) if query is not None else "").strip()
        await self._emit_status(__event_emitter__, f"searchRechtsprechung gestartet: {safe_query or '(Liste nach Datum)'}", done=False)
        try:
            if len(safe_query) > 200:
                raise ValueError("query ist zu lang; maximal 200 Zeichen sind erlaubt.")

            effective_limit = limit if limit is not None else self.user_valves.default_case_search_limit
            effective_limit = max(1, min(int(effective_limit), self.valves.max_search_results))
            datum_von = self._validate_date(datum_von, "datum_von")
            datum_bis = self._validate_date(datum_bis, "datum_bis")
            sort = (sortierung or "relevanz").strip().lower()

            base_url = self.valves.base_url.rstrip("/")

            # 0) Liste-Pfad: leere query -> Entscheidungen nach Datum ueber
            #    den DB-Endpunkt /cases/ (ordering + date_after/date_before
            #    funktionieren hier serverseitig).
            if not safe_query:
                ordering = "date" if sort == "aelteste" else "-date"
                court_obj, court_resolution, court_warning = self._resolve_court_graceful(gericht)
                need_client_filter = bool(instanz or gerichtsbarkeit or entscheidungstyp)
                fetch_size = min(100, max(effective_limit, 50)) if need_client_filter else effective_limit
                params = {"ordering": ordering, "page_size": fetch_size}
                if court_obj is not None and court_obj.get("id") is not None:
                    params["court"] = court_obj.get("id")
                if datum_von:
                    params["date_after"] = datum_von
                if datum_bis:
                    params["date_before"] = datum_bis
                data = await asyncio.to_thread(self._get_json_sync, "/cases/", params)
                raw = data.get("results", [])
                if gerichtsbarkeit:
                    jur = GERICHTSBARKEIT_MAP.get(gerichtsbarkeit.strip().lower(), gerichtsbarkeit.strip())
                    raw = [r for r in raw if (r.get("court") or {}).get("jurisdiction") == jur]
                if entscheidungstyp:
                    typ = ENTSCHEIDUNGSTYP_MAP.get(entscheidungstyp.strip().lower(), entscheidungstyp.strip())
                    raw = [r for r in raw if (r.get("type") or "") == typ]
                if instanz:
                    prefix = INSTANZ_MAP.get(instanz.strip().lower(), instanz.strip()).lower()
                    raw = [r for r in raw if prefix in ((r.get("court") or {}).get("level_of_appeal") or "").lower()]
                raw = raw[:effective_limit]
                results = []
                for hit in raw:
                    court = hit.get("court") or {}
                    results.append({
                        "id": hit.get("id"),
                        "slug": hit.get("slug"),
                        "court_name": court.get("name"),
                        "court_jurisdiction": court.get("jurisdiction"),
                        "file_number": hit.get("file_number"),
                        "date": hit.get("date"),
                        "type": hit.get("type"),
                        "ecli": hit.get("ecli") or None,
                        "url": hit.get("source_url") or f"https://de.openlegaldata.io/case/{hit.get('slug')}",
                    })
                payload = {
                    "query": "",
                    "mode": "liste",
                    "source_url": base_url + "/cases/?" + urlencode(params, doseq=True),
                    "total": data.get("count", len(results)),
                    "count": len(results),
                    "limit": effective_limit,
                    "filters": {
                        "gericht": gericht or None,
                        "instanz": instanz or None,
                        "gerichtsbarkeit": gerichtsbarkeit or None,
                        "entscheidungstyp": entscheidungstyp or None,
                        "datum_von": datum_von or None,
                        "datum_bis": datum_bis or None,
                        "sortierung": "aelteste" if ordering == "date" else "neueste",
                    },
                    "results": results,
                    "hinweis": HINWEIS,
                }
                if court_resolution is not None:
                    payload["court_resolution"] = court_resolution
                if court_warning is not None:
                    payload["warning"] = court_warning
                await self._emit_status(__event_emitter__, f"searchRechtsprechung abgeschlossen: {len(results)} Treffer (Liste)", done=True)
                return self._to_json(payload)

            # 1) Aktenzeichen-Pfad: exakte Suche ueber /cases/?file_number=
            if self._looks_like_aktenzeichen(safe_query):
                az_params = {"file_number": safe_query, "page_size": effective_limit}
                az_data = await asyncio.to_thread(self._get_json_sync, "/cases/", az_params)
                az_hits = az_data.get("results", [])
                if az_hits:
                    results = []
                    for hit in az_hits[:effective_limit]:
                        court = hit.get("court") or {}
                        results.append({
                            "id": hit.get("id"),
                            "slug": hit.get("slug"),
                            "court_name": court.get("name"),
                            "file_number": hit.get("file_number"),
                            "date": hit.get("date"),
                            "type": hit.get("type"),
                            "ecli": hit.get("ecli") or None,
                            "url": hit.get("source_url") or f"https://de.openlegaldata.io/case/{hit.get('slug')}",
                        })
                    payload: Dict[str, Any] = {
                        "query": safe_query,
                        "mode": "aktenzeichen",
                        "source_url": base_url + "/cases/?" + urlencode(az_params, doseq=True),
                        "total": az_data.get("count", len(results)),
                        "count": len(results),
                        "limit": effective_limit,
                        "results": results,
                        "hinweis": HINWEIS,
                    }
                    await self._emit_status(__event_emitter__, f"searchRechtsprechung abgeschlossen: {len(results)} Treffer (Aktenzeichen)", done=True)
                    return self._to_json(payload)
                # kein exakter AZ-Treffer -> weiter mit Volltextsuche

            # 2) Volltext-Pfad ueber /cases/search/?text=
            # Gericht auflösen; bei Misserfolg nicht die ganze Suche abbrechen,
            # sondern ohne Gerichtsfilter weitersuchen und warnen.
            court_obj, court_resolution, court_warning = self._resolve_court_graceful(gericht)
            court_code = court_obj.get("code") if court_obj else None
            need_client_filter = bool(
                instanz or datum_von or datum_bis or sort in ("neueste", "aelteste")
            )
            fetch_size = min(100, max(effective_limit, 50)) if need_client_filter else effective_limit
            params: Dict[str, Any] = {"text": safe_query, "page_size": fetch_size}
            if court_code:
                params["court"] = court_code
            if gerichtsbarkeit:
                params["court_jurisdiction"] = GERICHTSBARKEIT_MAP.get(
                    gerichtsbarkeit.strip().lower(), gerichtsbarkeit.strip()
                )
            if entscheidungstyp:
                params["decision_type"] = ENTSCHEIDUNGSTYP_MAP.get(
                    entscheidungstyp.strip().lower(), entscheidungstyp.strip()
                )

            data = await asyncio.to_thread(self._get_json_sync, "/cases/search/", params)
            raw = data.get("results", [])

            # Client-seitige Filter (serverseitig nicht verfuegbar/zuverlaessig)
            if instanz:
                prefix = INSTANZ_MAP.get(instanz.strip().lower(), instanz.strip()).upper()
                raw = [r for r in raw if str(r.get("court") or "").upper().startswith(prefix)]
            if datum_von:
                raw = [r for r in raw if (r.get("date") or "") >= datum_von]
            if datum_bis:
                raw = [r for r in raw if (r.get("date") or "") <= datum_bis]
            if sort == "neueste":
                raw = sorted(raw, key=lambda r: r.get("date") or "", reverse=True)
            elif sort == "aelteste":
                raw = sorted(raw, key=lambda r: r.get("date") or "")
            raw = raw[:effective_limit]

            results = [{
                "id": r.get("id"),
                "slug": r.get("slug"),
                "court": r.get("court"),
                "court_jurisdiction": r.get("court_jurisdiction"),
                "type": r.get("decision_type"),
                "date": r.get("date"),
                "snippet": self._clean_snippets(r.get("snippets")) or None,
                "url": f"https://de.openlegaldata.io/case/{r.get('slug')}",
            } for r in raw]

            payload = {
                "query": safe_query,
                "mode": "volltext",
                "source_url": base_url + "/cases/search/?" + urlencode(params, doseq=True),
                "total": data.get("count", len(results)),
                "count": len(results),
                "limit": effective_limit,
                "filters": {
                    "gericht": gericht or None,
                    "instanz": instanz or None,
                    "gerichtsbarkeit": gerichtsbarkeit or None,
                    "entscheidungstyp": entscheidungstyp or None,
                    "datum_von": datum_von or None,
                    "datum_bis": datum_bis or None,
                    "sortierung": sort,
                },
                "results": results,
                "hinweis": HINWEIS,
            }
            if court_resolution is not None:
                payload["court_resolution"] = court_resolution
            if court_warning is not None:
                payload["warning"] = court_warning

            await self._emit_debug(__event_emitter__, {
                "tool": "searchRechtsprechung", "query": safe_query,
                "result_count": len(results), "total": payload["total"],
            })
            await self._emit_status(__event_emitter__, f"searchRechtsprechung abgeschlossen: {len(results)} Treffer", done=True)
            return self._to_json(payload)
        except Exception as exc:
            await self._emit_status(__event_emitter__, f"searchRechtsprechung fehlgeschlagen: {exc}", done=True)
            return self._to_json({"error": str(exc), "tool": "searchRechtsprechung", "query": query})

    # ------------------------------------------------------------------ #
    #  getRechtsprechung                                                  #
    # ------------------------------------------------------------------ #

    def _split_case_sections(self, text: str) -> Dict[str, str]:
        """Grobe Gliederung anhand ueblicher Urteils-Ueberschriften. Best effort."""
        lines = text.split("\n")
        sections: Dict[str, List[str]] = {}
        current_key: Optional[str] = None
        for line in lines:
            stripped_lower = line.strip().strip(":").lower()
            matched_key = None
            for key, headings in CASE_SECTION_HEADINGS.items():
                if stripped_lower in headings:
                    matched_key = key
                    break
            if matched_key:
                current_key = matched_key
                sections.setdefault(current_key, [])
                continue
            if current_key is not None:
                sections[current_key].append(line)
        return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}

    async def getRechtsprechung(
        self,
        case: str,
        abschnitte: Optional[List[str]] = None,
        fulltext: bool = True,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Ruft eine Gerichtsentscheidung ab (id oder slug aus
        searchRechtsprechung).

        :param case: id, slug ODER Aktenzeichen (z. B. "12 SLa 775/25") der Entscheidung.
        :param abschnitte: Optionale Liste gewuenschter Abschnitte, z. B. ["tenor", "gruende"]. Erkannte Schluessel: "tenor", "tatbestand", "gruende".
        :param fulltext: Wenn true (Standard), wird der komplette Text zurueckgegeben (unabhaengig von abschnitte). Wenn false und abschnitte gesetzt ist, werden nur die erkannten Abschnitte geliefert; werden keine Abschnitte erkannt, faellt das Tool auf Volltext zurueck.
        :return: JSON mit Metadaten und Text (voll oder als sections-Liste).
        """
        # str() macht robust, falls das Modell die numerische id als Zahl uebergibt.
        key = (str(case) if case is not None else "").strip()
        await self._emit_status(__event_emitter__, f"getRechtsprechung gestartet: {key}", done=False)
        try:
            if not key:
                raise ValueError("case darf nicht leer sein.")

            # Aktenzeichen -> exakt auf eine Fall-id aufloesen.
            if self._looks_like_aktenzeichen(key):
                lookup = await asyncio.to_thread(
                    self._get_json_sync, "/cases/", {"file_number": key, "page_size": 1}
                )
                az_hits = lookup.get("results", [])
                if not az_hits:
                    raise ValueError(f"Kein Fall mit Aktenzeichen '{key}' gefunden.")
                key = str(az_hits[0].get("id"))

            data = await asyncio.to_thread(self._get_json_sync, f"/cases/{key}/")
            court = data.get("court") or {}
            content_html = data.get("content") or ""
            text = _html_to_text(content_html)
            if not text:
                raise ValueError("Konnte den Entscheidungstext nicht laden/extrahieren.")

            base = {
                "case": key,
                "id": data.get("id"),
                "slug": data.get("slug"),
                "court_name": court.get("name"),
                "file_number": data.get("file_number"),
                "date": data.get("date"),
                "type": data.get("type"),
                "ecli": data.get("ecli") or None,
                "source_url": data.get("source_url")
                or f"https://de.openlegaldata.io/case/{data.get('slug')}",
                "hinweis": HINWEIS,
            }

            requested_sections = [s.strip().lower() for s in (abschnitte or []) if s.strip()]
            if not fulltext and requested_sections:
                found = self._split_case_sections(text)
                selected = {k: v for k, v in found.items() if k in requested_sections}
                if selected:
                    payload = {
                        **base,
                        "mode": "sections",
                        "requested": requested_sections,
                        "sections": [{"name": k, "text": v} for k, v in selected.items()],
                    }
                else:
                    payload = {
                        **base,
                        "mode": "fulltext",
                        "text": text,
                        "warning": "Abschnittsgliederung nicht erkannt, Volltext zurueckgegeben.",
                    }
            else:
                payload = {**base, "mode": "fulltext", "text": text}

            max_chars = int(self.valves.max_output_chars or 0)
            if payload.get("mode") == "fulltext" and max_chars > 0 and len(payload.get("text", "")) > max_chars:
                payload["truncated"] = True

            await self._emit_debug(__event_emitter__, {
                "tool": "getRechtsprechung", "case": key, "mode": payload.get("mode"),
            })
            await self._emit_status(__event_emitter__, f"getRechtsprechung abgeschlossen: {key}", done=True)
            return self._to_json(payload)
        except Exception as exc:
            await self._emit_status(__event_emitter__, f"getRechtsprechung fehlgeschlagen: {exc}", done=True)
            return self._to_json({"error": str(exc), "tool": "getRechtsprechung", "case": case})

    # ------------------------------------------------------------------ #
    #  searchOpenLegalDataGesetz                                          #
    # ------------------------------------------------------------------ #

    def _resolve_law_book(self, gesetzbuch: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        if gesetzbuch is None:
            return None, None
        key = str(gesetzbuch).strip()
        if not key:
            return None, None
        if key.isdigit():
            return int(key), None
        # API-Einschraenkung (live verifiziert, Stand 2026-07-02):
        # /law_books/?search= ist wirkungslos (liefert immer die volle,
        # ungefilterte Liste). Der einzige verlaessliche Filter ist der
        # exakte Kuerzel-Match ueber ?code=. Deshalb: nur Kuerzel wie
        # "BGB"/"StGB"/"GG" werden unterstuetzt, keine Titelsuche.
        results = self._get_json_sync("/law_books/", {"code": key}).get("results", [])
        if not results:
            results = self._get_json_sync("/law_books/", {"code": key.upper()}).get("results", [])
        if not results:
            raise ValueError(
                f"Gesetzbuch '{gesetzbuch}' nicht gefunden. Aufgrund einer "
                "API-Einschraenkung wird nur der exakte Kuerzel-Code "
                "unterstuetzt (z. B. 'BGB', 'StGB', 'GG'), keine Titelsuche."
            )
        # Mehrere Revisionen moeglich (z. B. BGB 2017 + 2026): aktuellste waehlen.
        best = max(
            results,
            key=lambda r: (r.get("latest") is True, r.get("revision_date") or ""),
        )
        resolution = {
            "query": gesetzbuch,
            "resolved_title": best.get("title"),
            "resolved_code": best.get("code"),
            "resolved_id": best.get("id"),
            "total_matches": len(results),
        }
        return best.get("id"), resolution

    async def searchOpenLegalDataGesetz(
        self,
        query: str,
        gesetzbuch: str,
        limit: Optional[int] = None,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Durchsucht die Paragraphen-Titel eines Gesetzbuchs. Liefert je
        Treffer id/book_code/section/title; damit kann anschliessend
        getOpenLegalDataGesetz aufgerufen werden.

        WICHTIG: gesetzbuch ist ein Pflichtfeld (z. B. "BGB"). Die
        OpenLegalData-API unterstuetzt keine serverseitige Volltextsuche
        ueber Gesetzesnormen; dieses Tool laedt daher alle Normen des
        angegebenen Gesetzbuchs und filtert client-seitig nach Titel/
        Paragraphenbezeichnung. Es gibt KEINE Suche ueber alle Gesetze
        hinweg und KEINE Suche im vollen Normtext (nur Titel/Bezeichnung).

        :param query: Suchbegriff, der im Paragraphentitel/-bezeichnung vorkommen soll, z. B. "Schadensersatz".
        :param gesetzbuch: Gesetzbuch-Kuerzel (z. B. "BGB") oder numerische book-ID.
        :param limit: optionales Trefferlimit (durch max_search_results begrenzt).
        :return: JSON mit Fundstellen (id, book_code, title, section, slug, book_slug).
        """
        safe_query = (query or "").strip()
        await self._emit_status(__event_emitter__, f"searchOpenLegalDataGesetz gestartet: {safe_query}", done=False)
        try:
            if not safe_query:
                raise ValueError("query darf nicht leer sein.")
            if len(safe_query) > 200:
                raise ValueError("query ist zu lang; maximal 200 Zeichen sind erlaubt.")
            gesetzbuch_str = (str(gesetzbuch) if gesetzbuch is not None else "").strip()
            if not gesetzbuch_str:
                raise ValueError(
                    "gesetzbuch darf nicht leer sein (die OpenLegalData-API "
                    "unterstuetzt keine Volltextsuche ueber alle Gesetze hinweg)."
                )

            effective_limit = limit if limit is not None else self.user_valves.default_law_search_limit
            effective_limit = max(1, min(int(effective_limit), self.valves.max_search_results))

            book_id, book_resolution = self._resolve_law_book(gesetzbuch_str)
            if book_id is None:
                raise ValueError(f"Gesetzbuch '{gesetzbuch}' konnte nicht aufgeloest werden.")

            norms_raw, truncated = await self._load_law_book_norms(book_id)
            query_lower = safe_query.lower()
            matches = [
                n for n in norms_raw
                if query_lower in (n.get("title") or "").lower()
                or query_lower in (n.get("section") or "").lower()
            ]
            results = [{
                "id": hit.get("id"),
                "book_code": hit.get("book_code"),
                "title": hit.get("title"),
                "section": hit.get("section"),
                "slug": hit.get("slug"),
                "book_slug": hit.get("book_slug"),
            } for hit in matches[:effective_limit]]

            payload: Dict[str, Any] = {
                "query": safe_query,
                "gesetzbuch": gesetzbuch,
                "total": len(matches),
                "count": len(results),
                "limit": effective_limit,
                "results": results,
                "hinweis": HINWEIS,
            }
            if book_resolution is not None:
                payload["book_resolution"] = book_resolution
            if truncated:
                payload["warning"] = "Gesetzbuch zu gross, nur Teilmenge durchsucht (max_law_pages erreicht)."

            await self._emit_debug(__event_emitter__, {
                "tool": "searchOpenLegalDataGesetz", "query": safe_query,
                "result_count": len(results), "total": payload["total"],
            })
            await self._emit_status(__event_emitter__, f"searchOpenLegalDataGesetz abgeschlossen: {len(results)} Treffer", done=True)
            return self._to_json(payload)
        except Exception as exc:
            await self._emit_status(__event_emitter__, f"searchOpenLegalDataGesetz fehlgeschlagen: {exc}", done=True)
            return self._to_json({"error": str(exc), "tool": "searchOpenLegalDataGesetz", "query": query})

    # ------------------------------------------------------------------ #
    #  getOpenLegalDataGesetz                                             #
    # ------------------------------------------------------------------ #

    async def _load_law_book_norms(self, book_id: int) -> Tuple[List[Dict[str, Any]], bool]:
        """Laedt alle Normen eines Gesetzbuchs seitenweise. Liefert (normen, wurde_gekuerzt)."""
        # API-Einschraenkung (live verifiziert, Stand 2026-07-02): der
        # Parameter "book=" wird von /laws/ ignoriert (liefert ungefiltert
        # alle 176k Normen). Der korrekte, tatsaechlich filternde Parameter
        # ist "book_id=".
        page_size = 100
        norms: List[Dict[str, Any]] = []
        truncated = False
        for page in range(self.valves.max_law_pages):
            data = await asyncio.to_thread(
                self._get_json_sync, "/laws/",
                {"book_id": book_id, "limit": page_size, "offset": page * page_size},
            )
            batch = data.get("results", [])
            norms.extend(batch)
            if data.get("next") is None or not batch:
                break
        else:
            truncated = True
        return norms, truncated

    async def getOpenLegalDataGesetz(
        self,
        gesetzbuch: str,
        paragraphs: Optional[List[str]] = None,
        fulltext: bool = False,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Ruft ein Gesetzbuch von OpenLegalData ab (Kuerzel, Titel oder
        numerische book-ID aus searchOpenLegalDataGesetz).

        :param gesetzbuch: Kuerzel/Titel (z. B. "BGB") oder numerische book-ID.
        :param paragraphs: Optionale Liste gewuenschter Paragraphen, z. B. ["§ 823", "823"].
        :param fulltext: Wenn true, kompletter Text aller Normen. Wenn false und keine Paragraphen angegeben sind, wird nur das Inhaltsverzeichnis (toc) ausgegeben.
        :return: JSON mit Inhaltsverzeichnis, ausgewaehlten Paragraphen oder Volltext.
        """
        key = (str(gesetzbuch) if gesetzbuch is not None else "").strip()
        requested_refs = self._normalize_requested_refs(paragraphs or [])
        mode = "fulltext" if fulltext else ("paragraphs" if requested_refs else "toc")
        await self._emit_status(__event_emitter__, f"getOpenLegalDataGesetz gestartet: {key} ({mode})", done=False)
        try:
            if not key:
                raise ValueError("gesetzbuch darf nicht leer sein.")

            book_id, book_resolution = self._resolve_law_book(key)
            if book_id is None:
                raise ValueError(f"Gesetzbuch '{gesetzbuch}' konnte nicht aufgeloest werden.")

            norms_raw, truncated = await self._load_law_book_norms(book_id)
            if not norms_raw:
                raise ValueError(f"Keine Normen fuer Gesetzbuch-ID {book_id} gefunden.")

            book_code = norms_raw[0].get("book_code")
            source_url = f"{self.valves.base_url.rstrip('/')}/laws/?book_id={book_id}"
            base = {
                "gesetzbuch": gesetzbuch,
                "book_id": book_id,
                "book_code": book_code,
                "source_url": source_url,
                "mode": mode,
                "hinweis": HINWEIS,
            }
            if book_resolution is not None:
                base["book_resolution"] = book_resolution

            if fulltext:
                norms = []
                for n in norms_raw:
                    detail = await asyncio.to_thread(self._get_json_sync, f"/laws/{n.get('id')}/")
                    norms.append({
                        "id": n.get("id"),
                        "section": n.get("section"),
                        "title": n.get("title"),
                        "text": _html_to_text(detail.get("content") or ""),
                    })
                payload = {**base, "count": len(norms), "norms": norms}
            elif requested_refs:
                selected_meta = [n for n in norms_raw if self._norm_matches(n, requested_refs)]
                norms = []
                for n in selected_meta:
                    detail = await asyncio.to_thread(self._get_json_sync, f"/laws/{n.get('id')}/")
                    norms.append({
                        "id": n.get("id"),
                        "section": n.get("section"),
                        "title": n.get("title"),
                        "text": _html_to_text(detail.get("content") or ""),
                    })
                payload = {
                    **base,
                    "requested": sorted(requested_refs),
                    "count": len(norms),
                    "norms": norms,
                }
                if not norms:
                    payload["warning"] = "Keine passenden Paragraphen im Gesetzbuch gefunden."
            else:
                toc = [{
                    "id": n.get("id"),
                    "section": n.get("section"),
                    "title": n.get("title"),
                } for n in norms_raw]
                payload = {**base, "count": len(toc), "table_of_contents": toc}

            if truncated:
                payload["warning"] = "Gesetzbuch zu gross, nur Teilmenge geladen (max_law_pages erreicht)."

            await self._emit_debug(__event_emitter__, {
                "tool": "getOpenLegalDataGesetz", "gesetzbuch": key, "mode": mode,
                "result_count": payload.get("count"),
            })
            await self._emit_status(__event_emitter__, f"getOpenLegalDataGesetz abgeschlossen: {key}", done=True)
            return self._to_json(payload)
        except Exception as exc:
            await self._emit_status(__event_emitter__, f"getOpenLegalDataGesetz fehlgeschlagen: {exc}", done=True)
            return self._to_json({"error": str(exc), "tool": "getOpenLegalDataGesetz", "gesetzbuch": gesetzbuch})
