"""
title: MediaWiki Suche
description: Sucht im MediaWiki-Volltext, lädt Inhalte, lädt diese als Dateien hoch, gibt die Quellen an, liefert je Seite die internen Verlinkungen und extrahiert Datei-Anhänge (z. B. PDF) als Text.
author: Boris van Benthem - Stadt Oberhausen
version: 0.4
requirements: requests, pypdf
license: keine Lizenzangabe im Quellprojekt
original_author: Boris van Benthem (Stadt Oberhausen)
source_url: https://gitlab.opencode.de/kommi/adapter/mediawiki-adapter
"""

# --------------------------------------------------------------------------
# Herkunft / Provenance
#
# Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
# Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
# unverändert.
#
#   Projekt : MediaWiki-Adapter
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/mediawiki-adapter
#   Datei   : mediawiki-adapter.py
#   Autor   : Boris van Benthem (Stadt Oberhausen)
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

# Basis: offizieller KommI-Adapter von Boris van Benthem - Stadt Oberhausen
# (gitlab.opencode.de/kommi/adapter/mediawiki-adapter, v0.1).
# Erweiterung (v0.2-0.4): Florian Schade - Hochsauerlandkreis.
# Erweiterung (v0.2): zusaetzliche Funktion get_wiki_page, die eine Seite
# abruft und deren interne Seitenlinks (prop=links), Kategorien und
# Abschnitts-Gliederung liefert - fuer die gezielte Weiterrecherche von
# einer Uebersichtsseite zu ihren Unterseiten.
#
# Zielsystem wird ausschliesslich ueber die Valve mediawiki_base_url
# konfiguriert (kein fest verdrahtetes Wiki im Code).

import json
import re
import unicodedata
import requests
from itertools import islice
from datetime import datetime
from typing import Optional, Any, Dict
from urllib.parse import quote
from pydantic import BaseModel, Field


class Tools:
    """
    OpenWebUI Tool:
    - Volltextsuche (srwhat=text) im konfigurierten MediaWiki
    - Inhalte je Treffer holen (HTML->Plaintext via action=parse)
    - Inhalt je Seite als Datei HOCHLADEN
    - Pro Seite ein 'citation'-Event emittieren (UI)
    - Return enthält Metadaten + Upload-Resultat
    - Einzelseite abrufen inkl. interner Verlinkungen (get_wiki_page)
    """

    def __init__(self):
        self.valves = self.Valves()
        # Eigene Citations -> OWUI-Auto-Citations aus
        self.citation = False

        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": "OpenWebUI-MediaWikiTool/1.7 (+tools@openwebui.local)"}
        )
        if self.valves.basic_auth_user:
            self._session.auth = (
                self.valves.basic_auth_user,
                self.valves.basic_auth_password,
            )
        if not self.valves.verify_tls:
            self._session.verify = False

    # ======================
    # Valves (Admin-Config)
    # ======================
    class Valves(BaseModel):
        mediawiki_base_url: str = Field(
            default="https://de.wikipedia.org/w",
            description="Basis-URL des MediaWiki (ohne /api.php), z. B. https://de.wikipedia.org/w oder die URL des eigenen Wikis.",
        )
        search_max_results: int = Field(
            default=5,
            ge=1,
            le=500,
            description="Maximale Anzahl Treffer pro Suche. Jeder Treffer wird als Datei hochgeladen und als Quelle angezeigt - niedrig halten (z. B. 3-5), sonst kann OpenWebUI bei zu vielen Quellen abbrechen.",
        )
        citation_length: int = Field(
            default=500,
            ge=0,
            description="Maximale Länge des Zitat-Textes im Citation-Event; 0 = voller Inhalt.",
        )
        search_sort_order: str = Field(
            default="relevance",
            description="Sortierung der Suchergebnisse (z. B. relevance, last_edit_desc, create_timestamp_desc).",
        )
        smart_query_fallback: bool = Field(
            default=True,
            description="Wenn true, wird ein zu langer Suchbegriff bei 0 Treffern automatisch schrittweise gekürzt und erneut gesucht.",
        )
        max_links: int = Field(
            default=200,
            ge=0,
            le=2000,
            description="Obergrenze der je Seite von get_wiki_page zurückgegebenen internen Links.",
        )
        file_max_chars: int = Field(
            default=20000,
            ge=0,
            description="Maximale Zeichenzahl des aus einer Datei (PDF/Text) extrahierten Inhalts; 0 = unbegrenzt.",
        )
        max_file_bytes: int = Field(
            default=25_000_000,
            ge=100_000,
            le=200_000_000,
            description="Maximale Größe einer herunterzuladenden Datei in Bytes (Schutz vor Riesen-Downloads).",
        )
        basic_auth_user: str = Field(
            default="",
            description="Optionaler Benutzername für HTTP-Basic-Auth, falls das interne Wiki eine Anmeldung verlangt.",
        )
        basic_auth_password: str = Field(
            default="",
            description="Optionales Passwort für HTTP-Basic-Auth (nur zusammen mit basic_auth_user).",
        )
        verify_tls: bool = Field(
            default=True,
            description="TLS-Zertifikat prüfen. Nur im vertrauenswürdigen Intranet auf false setzen (selbstsignierte Zertifikate).",
        )

    # ======================
    # Helpers
    # ======================
    @staticmethod
    def _strip_html(html: str) -> str:
        if not html:
            return ""
        txt = re.sub(r"<[^>]+>", " ", html)  # Tags weg
        txt = re.sub(r"\s+", " ", txt).strip()
        return (
            txt.replace("&quot;", '"')
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
        )

    @staticmethod
    def _slugify(text: str, max_len: int = 60) -> str:
        text = (
            unicodedata.normalize("NFKD", text)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
        return (text[:max_len] or "seite").strip("_")

    # Fuellwoerter, die bei der Suchbegriff-Vereinfachung entfernt werden.
    _STOPWORDS = {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einer",
        "und", "oder", "für", "fuer", "mit", "von", "vom", "im", "in", "am", "an",
        "auf", "zu", "zur", "zum", "bei", "aus", "über", "ueber", "wie", "was",
        "wann", "wo", "wer", "welche", "welcher", "welches", "ist", "sind", "wird",
        "werden", "kann", "soll", "muss", "gibt", "es", "sich", "auch", "noch",
        "nicht", "man", "einem", "einige", "the", "and", "or", "of", "to", "for",
        "with", "how", "what", "wiki", "thema", "bitte", "steht", "sit",
    }

    @classmethod
    def _content_words(cls, text: str) -> list:
        """Signifikante Woerter (ohne Stoppwoerter/Kurztokens), Reihenfolge erhalten, dedupliziert."""
        words = []
        seen = set()
        for tok in re.findall(r"\w+", text or "", flags=re.UNICODE):
            low = tok.lower()
            if len(tok) > 2 and low not in cls._STOPWORDS and low not in seen:
                seen.add(low)
                words.append(tok)
        return words

    @classmethod
    def _query_variants(cls, query: str) -> list:
        """Erzeugt vom Original ausgehend progressiv kuerzere Suchbegriffe."""
        q = (query or "").strip()
        variants = [q] if q else []
        words = cls._content_words(q)

        def add(candidate: str) -> None:
            candidate = candidate.strip()
            if candidate and candidate.lower() not in [v.lower() for v in variants]:
                variants.append(candidate)

        if words:
            add(" ".join(words))          # ohne Stoppwoerter
        if len(words) > 4:
            add(" ".join(words[:4]))      # 4 wichtigste
        if len(words) > 2:
            add(" ".join(words[:2]))      # 2 wichtigste
        if len(words) >= 1:
            add(words[0])                 # einzelnes Leitwort
        return variants or [q]

    def _do_search(self, api_url: str, search_term: str, sort_order: str, effective_limit: int) -> list:
        """Fuehrt eine einzelne Volltextsuche (mit Pagination bis effective_limit) aus."""
        params = {
            "action": "query",
            "list": "search",
            "srsearch": search_term,
            "srwhat": "text",
            "srsort": sort_order,
            "srlimit": 50,
            "format": "json",
        }
        all_results = []
        cont = {}
        while True:
            resp = self._session.get(api_url, params={**params, **cont}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            all_results.extend(data.get("query", {}).get("search", []))
            if len(all_results) >= effective_limit:
                return list(islice(all_results, 0, effective_limit))
            cont = data.get("continue") or {}
            if not cont:
                return all_results

    def _api_url(self) -> str:
        return f"{self.valves.mediawiki_base_url.rstrip('/')}/api.php"

    def _page_url(self, pageid: int) -> str:
        return f"{self.valves.mediawiki_base_url.rstrip('/')}/index.php?curid={pageid}"

    def _page_url_by_title(self, title: str) -> str:
        # index.php?title= funktioniert unabhaengig von Short-URL-Konfiguration.
        enc = quote((title or "").replace(" ", "_"), safe="/:()")
        return f"{self.valves.mediawiki_base_url.rstrip('/')}/index.php?title={enc}"

    async def _upload_file(
        self, __file_upload__, content: str, filename: str, mime: str = "text/plain"
    ) -> Dict[str, Any]:
        """
        Robuster Wrapper um __file_upload__:
        - versucht Dict-Signatur
        - fällt zurück auf positional (content, filename, mime)
        - gibt Upload-Result (beliebige Struktur) oder Minimal-Metadaten zurück
        """
        if not __file_upload__:
            return {
                "warning": "file_upload_helper_missing",
                "filename": filename,
                "size": len(content),
            }
        # bevorzugt Dict-Signatur
        try:
            res = await __file_upload__(
                {"file_name": filename, "content": content, "mime_type": mime}
            )
            return {"ok": True, "result": res, "filename": filename}
        except TypeError:
            # positional fallback
            try:
                res = await __file_upload__(content, filename, mime)
                return {"ok": True, "result": res, "filename": filename}
            except Exception as e:
                return {"ok": False, "error": str(e), "filename": filename}
        except Exception as e:
            return {"ok": False, "error": str(e), "filename": filename}

    # ======================
    # Main
    # ======================
    async def search_mediawiki(
        self,
        search_term: str,
        max_results: Optional[int] = None,
        __event_emitter__=None,
        __file_upload__=None,
        __metadata__=None,
    ) -> str:
        """
        Durchsucht das Wiki im Volltext und liefert die passendsten Seiten
        (Inhalt wird als Datei hochgeladen und als Quelle zitiert). Fuehre
        pro Nutzerfrage in der Regel nur EINE Suche aus. Verwende 2-4
        praegnante Schlagworte, KEINE ganzen Saetze oder langen Wortketten -
        viele Begriffe werden UND-verknuepft und fuehren zu 0 Treffern.
        Treffer im Namensraum "Datei:"/"File:" sind Datei-Anhaenge (z. B.
        PDF); deren Inhalt mit get_wiki_file abrufen, nicht mit get_wiki_page.

        :param search_term: Suchbegriff / Stichworte zur Nutzerfrage.
        :param max_results: optionales Trefferlimit (durch search_max_results begrenzt).
        :return: JSON-Liste mit Seitenmetadaten + Upload-Infos.
        """
        hard_cap = max(1, min(500, self.valves.search_max_results))
        effective_limit = min(max_results or hard_cap, hard_cap)
        cite_len = max(0, self.valves.citation_length)
        sort_order = self.valves.search_sort_order or "relevance"

        api_url = self._api_url()

        # Status
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"Suche '{search_term}' (max. {effective_limit}, sortiert nach {sort_order}) …",
                        "done": False,
                    },
                }
            )

        try:
            # --- 1) Suche mit automatischer Vereinfachung langer Suchbegriffe ---
            variants = (
                self._query_variants(search_term)
                if self.valves.smart_query_fallback
                else [search_term]
            )
            all_results = []
            used_query = search_term
            for idx, variant in enumerate(variants):
                all_results = self._do_search(api_url, variant, sort_order, effective_limit)
                used_query = variant
                if all_results:
                    if idx > 0 and __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": f"Suchbegriff vereinfacht zu '{variant}' – {len(all_results)} Treffer.",
                                    "done": False,
                                },
                            }
                        )
                    break

            if not all_results:
                if __event_emitter__:
                    await __event_emitter__(
                        {
                            "type": "status",
                            "data": {
                                "description": f"Keine Treffer für '{search_term}' (auch nach Vereinfachung des Suchbegriffs).",
                                "done": True,
                            },
                        }
                    )
                return json.dumps([], ensure_ascii=False)

            # Map Grunddaten
            by_id = {
                r["pageid"]: {
                    "title": r.get("title"),
                    "snippet": self._strip_html(r.get("snippet", "")),
                }
                for r in all_results
                if "pageid" in r
            }
            pageids = list(by_id.keys())

            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": f"{len(pageids)} Seiten zu '{used_query}' gefunden – lade Inhalte & uploade Dateien …",
                            "done": False,
                        },
                    }
                )

            results = []
            # --- 2) Inhalte + 3) Upload + 4) Citation ---
            for pid in pageids:
                # Inhalte via parse (HTML -> Plaintext)
                pr = self._session.get(
                    api_url,
                    params={
                        "action": "parse",
                        "pageid": pid,
                        "prop": "text",
                        "format": "json",
                        "formatversion": "2",
                    },
                    timeout=60,
                )
                pr.raise_for_status()
                pd = pr.json()
                html = pd.get("parse", {}).get("text", "") or ""
                content_text = self._strip_html(html)

                title = by_id[pid]["title"] or f"Seite_{pid}"
                snippet = by_id[pid]["snippet"]
                page_url = self._page_url(pid)

                # Dateiname bauen
                filename = f"{pid}_{self._slugify(title)}.txt"

                # Datei-Upload (IMMER)
                upload_info = await self._upload_file(
                    __file_upload__, content_text, filename, mime="text/plain"
                )

                # Citation-Preview gemäß Valve
                citation_text = (
                    content_text if cite_len == 0 else content_text[:cite_len]
                )

                # Citation-Event (zeigt Quelle + kurzen Auszug im UI)
                if __event_emitter__:
                    await __event_emitter__(
                        {
                            "type": "citation",
                            "data": {
                                "document": [citation_text],
                                "metadata": [
                                    {
                                        "date_accessed": datetime.utcnow().isoformat()
                                        + "Z",
                                        "source": title,
                                        "url": page_url,
                                        # Optional: Upload-Info für UI/Debug
                                        "uploaded_file": upload_info.get("filename"),
                                    }
                                ],
                                "source": {"name": title, "url": page_url},
                            },
                        }
                    )

                results.append(
                    {
                        "pageid": pid,
                        "title": title,
                        "url": page_url,
                        "snippet": snippet,
                        "uploaded_file": upload_info,  # enthält ok/result/filename/… je nach Helper
                        "size_chars": len(content_text),
                    }
                )

            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": f"Fertig: {len(results)} Seiten verarbeitet & hochgeladen.",
                            "done": True,
                        },
                    }
                )

            return json.dumps(results, ensure_ascii=False)

        except requests.exceptions.RequestException as e:
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "notification",
                        "data": {
                            "type": "error",
                            "content": f"MediaWiki-Verbindungsfehler: {e}",
                        },
                    }
                )
            return json.dumps(
                [{"error": f"Error connecting to MediaWiki: {e}"}], ensure_ascii=False
            )
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "notification",
                        "data": {
                            "type": "error",
                            "content": f"Unerwarteter Fehler: {e}",
                        },
                    }
                )
            return json.dumps(
                [{"error": f"An unexpected error occurred: {e}"}], ensure_ascii=False
            )

    # ======================
    # Einzelseite + interne Verlinkungen
    # ======================
    async def get_wiki_page(
        self,
        title: str,
        include_links: bool = True,
        include_content: bool = True,
        __event_emitter__=None,
        __file_upload__=None,
        __metadata__=None,
    ) -> str:
        """
        Ruft eine einzelne Wiki-Seite ab und liefert deren interne
        Verlinkungen, Kategorien und Abschnitts-Gliederung; damit kann von
        einer Übersichtsseite gezielt zu ihren Unterseiten weiterrecherchiert
        werden.

        :param title: Seitentitel der abzurufenden Wiki-Seite (Weiterleitungen werden verfolgt).
        :param include_links: Wenn true, werden die internen Seitenlinks (Namensraum 0, existierend) mitgeliefert.
        :param include_content: Wenn true, wird der Seitentext als Klartext geliefert, als Datei hochgeladen und als Citation angezeigt.
        :return: JSON-Objekt mit title, url, categories, sections und ggf. links/content.
        """
        api_url = self._api_url()
        safe_title = (str(title) if title is not None else "").strip()

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": f"Lade Seite '{safe_title}' …", "done": False},
                }
            )

        try:
            if not safe_title:
                return json.dumps(
                    {"error": "title darf nicht leer sein."}, ensure_ascii=False
                )

            props = ["sections", "categories", "displaytitle"]
            if include_content:
                props.append("text")
            if include_links:
                props.append("links")

            pr = self._session.get(
                api_url,
                params={
                    "action": "parse",
                    "page": safe_title,
                    "prop": "|".join(props),
                    "redirects": "1",
                    "format": "json",
                    "formatversion": "2",
                },
                timeout=60,
            )
            pr.raise_for_status()
            pd = pr.json()

            # MediaWiki meldet fehlende/ungueltige Seiten mit HTTP 200 + error-Feld.
            if pd.get("error"):
                err = pd["error"]
                if __event_emitter__:
                    await __event_emitter__(
                        {
                            "type": "status",
                            "data": {
                                "description": f"Seite '{safe_title}' nicht gefunden.",
                                "done": True,
                            },
                        }
                    )
                return json.dumps(
                    {
                        "error": f"Seite '{safe_title}' nicht gefunden ({err.get('code')}).",
                        "hinweis": "Bitte zuerst search_mediawiki verwenden, um den korrekten Seitentitel zu finden.",
                    },
                    ensure_ascii=False,
                )

            parse = pd.get("parse", {}) or {}
            resolved_title = parse.get("title") or safe_title
            page_url = self._page_url_by_title(resolved_title)

            categories = [
                c.get("category")
                for c in (parse.get("categories") or [])
                if c.get("category") and not c.get("hidden")
            ]
            sections = [
                {
                    "level": s.get("level"),
                    "line": s.get("line"),
                    "anchor": s.get("anchor"),
                }
                for s in (parse.get("sections") or [])
            ]

            result: Dict[str, Any] = {
                "title": resolved_title,
                "url": page_url,
                "categories": categories,
                "sections": sections,
            }

            if include_links:
                max_links = max(0, int(self.valves.max_links or 0))
                links = [
                    {
                        "title": lnk.get("title"),
                        "url": self._page_url_by_title(lnk.get("title") or ""),
                    }
                    for lnk in (parse.get("links") or [])
                    if lnk.get("ns") == 0 and lnk.get("exists")
                ]
                if max_links and len(links) > max_links:
                    result["links_truncated"] = True
                    links = links[:max_links]
                result["links"] = links
                result["link_count"] = len(links)

            if include_content:
                content_text = self._strip_html(parse.get("text", "") or "")
                result["size_chars"] = len(content_text)

                filename = f"{self._slugify(resolved_title)}.txt"
                upload_info = await self._upload_file(
                    __file_upload__, content_text, filename, mime="text/plain"
                )
                result["uploaded_file"] = upload_info

                cite_len = max(0, self.valves.citation_length)
                citation_text = (
                    content_text if cite_len == 0 else content_text[:cite_len]
                )
                if __event_emitter__:
                    await __event_emitter__(
                        {
                            "type": "citation",
                            "data": {
                                "document": [citation_text],
                                "metadata": [
                                    {
                                        "date_accessed": datetime.utcnow().isoformat()
                                        + "Z",
                                        "source": resolved_title,
                                        "url": page_url,
                                        "uploaded_file": upload_info.get("filename"),
                                    }
                                ],
                                "source": {"name": resolved_title, "url": page_url},
                            },
                        }
                    )

            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "status",
                        "data": {
                            "description": f"Fertig: '{resolved_title}' ({result.get('link_count', 0)} Links).",
                            "done": True,
                        },
                    }
                )
            return json.dumps(result, ensure_ascii=False)

        except requests.exceptions.RequestException as e:
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "notification",
                        "data": {
                            "type": "error",
                            "content": f"MediaWiki-Verbindungsfehler: {e}",
                        },
                    }
                )
            return json.dumps(
                {"error": f"Error connecting to MediaWiki: {e}"}, ensure_ascii=False
            )
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "notification",
                        "data": {"type": "error", "content": f"Unerwarteter Fehler: {e}"},
                    }
                )
            return json.dumps(
                {"error": f"An unexpected error occurred: {e}"}, ensure_ascii=False
            )

    # ======================
    # Datei-Anhang (PDF/Text) extrahieren
    # ======================
    @staticmethod
    def _extract_pdf_text(blob: bytes) -> str:
        """Extrahiert Text aus PDF-Bytes. Nutzt pypdf, faellt auf PyPDF2 zurueck."""
        try:
            from pypdf import PdfReader  # bevorzugt
        except Exception:
            from PyPDF2 import PdfReader  # Fallback (aeltere Umgebungen)
        import io

        reader = PdfReader(io.BytesIO(blob))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(parts).strip()

    async def get_wiki_file(
        self,
        title: str,
        max_chars: Optional[int] = None,
        __event_emitter__=None,
        __file_upload__=None,
        __metadata__=None,
    ) -> str:
        """
        Ruft einen Datei-Anhang aus dem Wiki ab (z. B. PDF) und extrahiert
        dessen Textinhalt, damit er zusammengefasst werden kann. Fuer Treffer
        im Namensraum "Datei:"/"File:" verwenden - NICHT get_wiki_page, das
        nur die Beschreibungsseite liefert.

        :param title: Dateiname bzw. Datei-Seitentitel, z. B. "Datei:Bericht.pdf" oder "Bericht.pdf".
        :param max_chars: optionale Obergrenze der extrahierten Zeichen (Default aus file_max_chars).
        :return: JSON mit url, mime, size und extrahiertem Text (zusaetzlich als Datei hochgeladen + Citation).
        """
        api_url = self._api_url()
        name = (str(title) if title is not None else "").strip()
        if ":" not in name:
            name = f"File:{name}"

        if __event_emitter__:
            await __event_emitter__(
                {"type": "status", "data": {"description": f"Lade Datei '{name}' …", "done": False}}
            )

        try:
            if not name or name.endswith(":"):
                return json.dumps({"error": "title darf nicht leer sein."}, ensure_ascii=False)

            # 1) Echte Datei-URL ueber imageinfo aufloesen
            ir = self._session.get(
                api_url,
                params={
                    "action": "query",
                    "titles": name,
                    "prop": "imageinfo",
                    "iiprop": "url|mime|size",
                    "redirects": "1",
                    "format": "json",
                    "formatversion": "2",
                },
                timeout=30,
            )
            ir.raise_for_status()
            ij = ir.json()
            pages = (ij.get("query", {}) or {}).get("pages", []) or []
            page = pages[0] if pages else {}
            info_list = page.get("imageinfo") or []
            if page.get("missing") or not info_list:
                if __event_emitter__:
                    await __event_emitter__(
                        {"type": "status", "data": {"description": f"Datei '{name}' nicht gefunden.", "done": True}}
                    )
                return json.dumps(
                    {
                        "error": f"Keine Datei '{name}' gefunden.",
                        "hinweis": "Titel muss der Datei-Seite entsprechen (z. B. 'Datei:Bericht.pdf'); zuerst search_mediawiki nutzen.",
                    },
                    ensure_ascii=False,
                )
            info = info_list[0]
            file_url = info.get("url") or ""
            mime = (info.get("mime") or "").lower()
            size = int(info.get("size") or 0)

            max_bytes = int(self.valves.max_file_bytes or 0)
            if max_bytes and size and size > max_bytes:
                return json.dumps(
                    {
                        "error": f"Datei zu groß ({size} Bytes > max_file_bytes {max_bytes}).",
                        "url": file_url,
                        "mime": mime,
                        "size_bytes": size,
                    },
                    ensure_ascii=False,
                )

            # 2) Binaerdatei herunterladen (gleiche Session/Auth/TLS)
            fr = self._session.get(file_url, timeout=120)
            fr.raise_for_status()
            blob = fr.content

            # 3) Text extrahieren
            note = None
            lower_url = file_url.lower()
            if "pdf" in mime or lower_url.endswith(".pdf"):
                try:
                    text = self._extract_pdf_text(blob)
                except Exception as e:
                    return json.dumps(
                        {
                            "error": f"PDF-Textextraktion fehlgeschlagen: {e}",
                            "hinweis": "Bibliothek 'pypdf' muss installiert sein (im Tool-Header 'requirements: pypdf').",
                            "url": file_url,
                        },
                        ensure_ascii=False,
                    )
                if not text:
                    note = "Kein extrahierbarer Text gefunden (evtl. gescanntes PDF ohne Textebene; hierfür wäre OCR nötig)."
            elif mime.startswith("text/") or lower_url.endswith((".txt", ".csv", ".md", ".json")):
                text = blob.decode("utf-8", errors="replace").strip()
            else:
                return json.dumps(
                    {
                        "error": f"Dateityp '{mime or 'unbekannt'}' wird nicht unterstützt (nur PDF und Textdateien).",
                        "url": file_url,
                        "mime": mime,
                        "size_bytes": size,
                    },
                    ensure_ascii=False,
                )

            # 4) Kuerzen gemaess Valve/Parameter
            limit = self.valves.file_max_chars if max_chars is None else max(0, int(max_chars))
            truncated = False
            if limit and len(text) > limit:
                text = text[:limit]
                truncated = True

            # 5) Upload + Citation
            filename = f"{self._slugify(name)}.txt"
            upload_info = await self._upload_file(__file_upload__, text, filename, mime="text/plain")

            result: Dict[str, Any] = {
                "title": name,
                "url": file_url,
                "mime": mime,
                "size_bytes": size,
                "size_chars": len(text),
                "text": text,
                "uploaded_file": upload_info,
            }
            if truncated:
                result["truncated"] = True
            if note:
                result["hinweis"] = note

            cite_len = max(0, self.valves.citation_length)
            citation_text = text if cite_len == 0 else text[:cite_len]
            if __event_emitter__ and text:
                await __event_emitter__(
                    {
                        "type": "citation",
                        "data": {
                            "document": [citation_text],
                            "metadata": [
                                {
                                    "date_accessed": datetime.utcnow().isoformat() + "Z",
                                    "source": name,
                                    "url": file_url,
                                    "uploaded_file": upload_info.get("filename"),
                                }
                            ],
                            "source": {"name": name, "url": file_url},
                        },
                    }
                )

            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": f"Fertig: '{name}' ({len(text)} Zeichen).", "done": True}}
                )
            return json.dumps(result, ensure_ascii=False)

        except requests.exceptions.RequestException as e:
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "notification", "data": {"type": "error", "content": f"MediaWiki-Verbindungsfehler: {e}"}}
                )
            return json.dumps({"error": f"Error connecting to MediaWiki: {e}"}, ensure_ascii=False)
        except Exception as e:
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "notification", "data": {"type": "error", "content": f"Unerwarteter Fehler: {e}"}}
                )
            return json.dumps({"error": f"An unexpected error occurred: {e}"}, ensure_ascii=False)
