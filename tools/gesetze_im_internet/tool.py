"""
title: Gesetze im Internet
description: Findet und liest Bundesrecht über gesetze-im-internet.de — Gesetze nach Titel oder Kürzel suchen, Volltext einzelner Normen abrufen und die öffentliche Volltextsuche nutzen.
version: 0.1.0
license: keine Lizenzangabe im Quellprojekt
original_author: Boris van Benthem (KommI)
source_url: https://gitlab.opencode.de/kommi/adapter/bundesgesetzadapter

gesetze-im-internet.de Basis-Tools für OpenWebUI.

Dieses Modul stellt drei vom LLM aufrufbare Tools bereit:
- findLaw: Findet Gesetze nach Titel/Kürzel im Gesamtinhaltsverzeichnis (gii-toc.xml) und liefert den law_code (Slug)
- getLaw: Abruf eines Gesetzestextes aus https://www.gesetze-im-internet.de/{kuerzel}/xml.zip
- searchLaw: Suche über die öffentliche gesetze-im-internet.de Volltextsuche

Installation in OpenWebUI:
1. Adminbereich -> Tools -> Neues Tool
2. Inhalt dieser Datei einfügen
3. Valves konfigurieren, insbesondere allowed_law_codes
"""

# --------------------------------------------------------------------------
# Herkunft / Provenance
#
# Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
# Herkunftshinweis und Katalog-Metadaten im Kopf; weitere Änderungen sind
# unten aufgeführt.
#
#   Projekt : Bundesgesetz-Adapter
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/bundesgesetzadapter
#   Datei   : gesetze_im_internet_tools.py
#   Autor   : Boris van Benthem (KommI)
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
#
# Änderungen gegenüber dem Original:
#   - Die Kommentarzeile "# Target: OpenWebUI Tools Function" vor dem
#   Docstring wurde entfernt. Der Frontmatter-Parser der Installation
#   erkennt den Kopf nur, wenn die Datei mit dem Docstring beginnt.
#   - Titel, Beschreibung und Version wurden im Kopf ergänzt; das Original
#   enthält keine Katalog-Metadaten.
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import html
import json
import re
import time
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field


@dataclass
class _SearchAnchor:
    href: str
    text: str


class _AnchorParser(HTMLParser):
    """Minimaler HTML-Parser für Suchergebnis-Links ohne externe Dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._current_href: Optional[str] = None
        self._current_text: List[str] = []
        self.anchors: List[_SearchAnchor] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != 'a':
            return
        attrs_dict = {k.lower(): v for k, v in attrs}
        href = attrs_dict.get('href')
        if href:
            self._current_href = href
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == 'a' and self._current_href is not None:
            text = ' '.join(part.strip() for part in self._current_text if part.strip())
            self.anchors.append(_SearchAnchor(href=self._current_href, text=text))
            self._current_href = None
            self._current_text = []


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default='https://www.gesetze-im-internet.de',
            description='Basis-URL von gesetze-im-internet.de ohne abschließenden Slash.',
        )
        search_url: str = Field(
            default='https://www.gesetze-im-internet.de/cgi-bin/htsearch',
            description='URL der öffentlichen Volltextsuche von gesetze-im-internet.de.',
        )
        allowed_law_codes: str = Field(
            default='bgb,gg,stgb,sgb_12',
            description=("Kommaseparierte Liste zulässiger Gesetzeskürzel, z. B. 'bgb,gg,sgb_12'. Nur diese Kürzel werden abgerufen bzw. aus Suchtreffern zurückgegeben."),
        )
        allow_all_laws: bool = Field(
            default=False,
            description='Wenn true, werden alle syntaktisch gültigen Gesetzeskürzel zugelassen. Standard: false.',
        )
        timeout_seconds: int = Field(
            default=20,
            ge=1,
            le=120,
            description='Timeout für externe HTTP-Aufrufe in Sekunden.',
        )
        max_search_results: int = Field(
            default=20,
            ge=1,
            le=100,
            description='Globale Obergrenze für Suchtreffer.',
        )
        max_zip_bytes: int = Field(
            default=25_000_000,
            ge=1_000_000,
            le=200_000_000,
            description='Maximale Größe eines heruntergeladenen XML-ZIP in Bytes.',
        )
        max_output_chars: int = Field(
            default=0,
            ge=0,
            description=('Optionale Ausgabelängenbegrenzung. 0 bedeutet unbegrenzt. Wenn begrenzt, wird JSON am Ende mit einem Hinweis gekürzt.'),
        )
        toc_url: str = Field(
            default='https://www.gesetze-im-internet.de/gii-toc.xml',
            description='URL des Gesamtinhaltsverzeichnisses zur Slug-Auflösung.',
        )
        toc_cache_seconds: int = Field(
            default=86400,
            ge=0,
            description='Cache-Dauer für gii-toc.xml in Sekunden.',
        )
        debug: bool = Field(
            default=False,
            description='Wenn true, werden Debug-Informationen über den event_emitter ausgegeben.',
        )

    class UserValves(BaseModel):
        preferred_output_language: str = Field(
            default='de',
            description='Bevorzugte Sprache für Hinweis- und Fehlermeldungen. Gesetzestexte bleiben unverändert.',
        )
        default_search_limit: int = Field(
            default=10,
            ge=1,
            le=50,
            description='Nutzerspezifisches Standardlimit für searchLaw.',
        )
        pretty_json: bool = Field(
            default=True,
            description='Wenn true, werden Tool-Ergebnisse als eingerücktes JSON ausgegeben.',
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.user_valves = self.UserValves()
        self._toc_cache: Optional[Dict[str, str]] = None
        self._toc_cache_ts: float = 0.0

    async def getLaw(
        self,
        law_code: str,
        paragraphs: Optional[List[str]] = None,
        fulltext: bool = False,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Ruft ein Gesetz von gesetze-im-internet.de ab.

        :param law_code: Gesetzeskürzel, z. B. "bgb" oder "sgb_12".
        :param paragraphs: Optionale Liste gewünschter Paragraphen/Artikel, z. B. ["§ 823", "§ 242"] oder ["823"].
        :param fulltext: Wenn true, wird der komplette Gesetzestext ausgegeben. Wenn false und keine Paragraphen angegeben sind, wird nur das Inhaltsverzeichnis ausgegeben.
        :return: JSON mit Inhaltsverzeichnis, ausgewählten Normen oder Volltext.
        """
        await self._emit_status(__event_emitter__, f'getLaw gestartet: {law_code}', done=False)
        try:
            normalized_law = self._validate_law_code(law_code)
            requested_refs = self._normalize_requested_refs(paragraphs or [])
            mode = 'fulltext' if fulltext else ('paragraphs' if requested_refs else 'toc')

            await self._emit_debug(
                __event_emitter__,
                {
                    'tool': 'getLaw',
                    'law_code': normalized_law,
                    'mode': mode,
                    'requested_refs': sorted(requested_refs),
                },
            )

            try:
                zip_bytes = await self._download_law_zip(normalized_law)
            except Exception as download_exc:
                if '404' in str(download_exc):
                    # Slug != Kürzel (z. B. stvo -> stvo_2013): über gii-toc.xml auflösen.
                    normalized_law = await self._resolve_slug(normalized_law)
                    zip_bytes = await self._download_law_zip(normalized_law)
                else:
                    raise
            xml_bytes, xml_filename = await asyncio.to_thread(self._extract_xml_from_zip, zip_bytes)
            root = await asyncio.to_thread(ET.fromstring, xml_bytes)
            norms = await asyncio.to_thread(self._extract_norms, root)

            if fulltext:
                payload: Dict[str, Any] = {
                    'law_code': normalized_law,
                    'source_url': self._law_zip_url(normalized_law),
                    'xml_filename': xml_filename,
                    'mode': 'fulltext',
                    'count': len(norms),
                    'norms': norms,
                }
            elif requested_refs:
                selected = [norm for norm in norms if self._norm_matches(norm, requested_refs)]
                payload = {
                    'law_code': normalized_law,
                    'source_url': self._law_zip_url(normalized_law),
                    'xml_filename': xml_filename,
                    'mode': 'paragraphs',
                    'requested': sorted(requested_refs),
                    'count': len(selected),
                    'norms': selected,
                }
                if not selected:
                    payload['warning'] = 'Keine passenden Paragraphen/Artikel im Gesetzestext gefunden.'
            else:
                toc = [
                    {
                        'id': norm.get('id'),
                        'enbez': norm.get('enbez'),
                        'title': norm.get('title'),
                        'reference_key': norm.get('reference_key'),
                    }
                    for norm in norms
                ]
                payload = {
                    'law_code': normalized_law,
                    'source_url': self._law_zip_url(normalized_law),
                    'xml_filename': xml_filename,
                    'mode': 'toc',
                    'count': len(toc),
                    'table_of_contents': toc,
                }

            await self._emit_debug(
                __event_emitter__,
                {
                    'tool': 'getLaw',
                    'law_code': normalized_law,
                    'mode': mode,
                    'result_count': payload.get('count'),
                },
            )
            result = self._to_json(payload)
            await self._emit_status(__event_emitter__, f'getLaw abgeschlossen: {normalized_law}', done=True)
            return result
        except Exception as exc:  # bewusst defensiv für Tool-Aufruf-Kontext
            await self._emit_status(__event_emitter__, f'getLaw fehlgeschlagen: {exc}', done=True)
            return self._to_json({'error': str(exc), 'tool': 'getLaw', 'law_code': law_code})

    async def searchLaw(
        self,
        query: str,
        limit: Optional[int] = None,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Sucht in der Volltextsuche von gesetze-im-internet.de und gibt strukturierte Fundstellen zurück.

        :param query: Suchbegriff, z. B. "Sozialhilfe".
        :param limit: Optionales Trefferlimit. Wird durch max_search_results begrenzt.
        :return: JSON mit Fundstellen aus zugelassenen Gesetzen, inklusive law_code, paragraph und URL.
        """
        safe_query = (query or '').strip()
        await self._emit_status(__event_emitter__, f'searchLaw gestartet: {safe_query}', done=False)
        try:
            if not safe_query:
                raise ValueError('query darf nicht leer sein.')
            if len(safe_query) > 200:
                raise ValueError('query ist zu lang; maximal 200 Zeichen sind erlaubt.')

            effective_limit = limit if limit is not None else self.user_valves.default_search_limit
            effective_limit = max(1, min(int(effective_limit), self.valves.max_search_results))

            search_url = self._build_search_url(safe_query)
            html_text = await self._download_text(search_url)
            anchors = await asyncio.to_thread(self._parse_anchors, html_text)
            results = self._extract_search_results(anchors, effective_limit)

            payload = {
                'query': safe_query,
                'source_url': search_url,
                'count': len(results),
                'limit': effective_limit,
                'allowed_law_codes': ('*' if self.valves.allow_all_laws else sorted(self._allowed_law_codes())),
                'results': results,
            }
            await self._emit_debug(
                __event_emitter__,
                {
                    'tool': 'searchLaw',
                    'query': safe_query,
                    'raw_links': len(anchors),
                    'result_count': len(results),
                },
            )
            await self._emit_status(
                __event_emitter__,
                f'searchLaw abgeschlossen: {len(results)} Treffer',
                done=True,
            )
            return self._to_json(payload)
        except Exception as exc:
            await self._emit_status(__event_emitter__, f'searchLaw fehlgeschlagen: {exc}', done=True)
            return self._to_json({'error': str(exc), 'tool': 'searchLaw', 'query': query})

    async def findLaw(
        self,
        query: str,
        limit: Optional[int] = None,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Sucht Gesetze nach Titel oder Kürzel im Gesamtinhaltsverzeichnis (gii-toc.xml).

        :param query: Suchbegriff, z. B. "Straßenverkehr" oder "stvo".
        :param limit: Optionales Trefferlimit.
        :return: JSON mit passenden Gesetzen inkl. aufgelöstem law_code (Slug) und xml_url.
        """
        safe_query = (query or '').strip()
        await self._emit_status(__event_emitter__, f'findLaw gestartet: {safe_query}', done=False)
        try:
            if not safe_query:
                raise ValueError('query darf nicht leer sein.')
            effective_limit = limit if limit is not None else self.user_valves.default_search_limit
            effective_limit = max(1, min(int(effective_limit), self.valves.max_search_results))
            toc = await self._load_toc()
            normalized_query = self._normalize_code(safe_query)
            seen: Set[str] = set()
            results: List[Dict[str, Any]] = []
            for key_norm, slug in toc.items():
                if slug in seen:
                    continue
                if normalized_query and normalized_query in key_norm:
                    seen.add(slug)
                    results.append({'law_code': slug, 'xml_url': self._law_zip_url(slug)})
                if len(results) >= effective_limit:
                    break
            payload = {
                'query': safe_query,
                'count': len(results),
                'limit': effective_limit,
                'results': results,
            }
            await self._emit_status(
                __event_emitter__,
                f'findLaw abgeschlossen: {len(results)} Treffer',
                done=True,
            )
            return self._to_json(payload)
        except Exception as exc:
            await self._emit_status(__event_emitter__, f'findLaw fehlgeschlagen: {exc}', done=True)
            return self._to_json({'error': str(exc), 'tool': 'findLaw', 'query': query})

    @staticmethod
    def _normalize_code(value: Any) -> str:
        return re.sub(r'[^a-z0-9]', '', str(value or '').strip().lower())

    @staticmethod
    def _strip_version_suffix(slug: str) -> str:
        return re.sub(r'_(\d{4})$', '', slug or '')

    async def _load_toc(self) -> Dict[str, str]:
        now = time.time()
        if self._toc_cache is not None and (now - self._toc_cache_ts) < self.valves.toc_cache_seconds:
            return self._toc_cache
        xml_text = await self._download_text(self.valves.toc_url)
        mapping = await asyncio.to_thread(self._parse_toc, xml_text)
        self._toc_cache = mapping
        self._toc_cache_ts = now
        return mapping

    def _parse_toc(self, xml_text: str) -> Dict[str, str]:
        data = xml_text.encode('utf-8') if isinstance(xml_text, str) else xml_text
        root = ET.fromstring(data)
        mapping: Dict[str, str] = {}
        for item in root.iter():
            if self._local_name(item.tag) != 'item':
                continue
            title = self._first_text(item, 'title') or ''
            link = self._first_text(item, 'link') or ''
            match = re.search(r'/([a-z0-9_.\-]+)/xml\.zip', link, re.IGNORECASE)
            if not match:
                continue
            slug = match.group(1).lower()
            mapping.setdefault(self._normalize_code(slug), slug)
            mapping.setdefault(self._normalize_code(self._strip_version_suffix(slug)), slug)
            if title:
                mapping.setdefault(self._normalize_code(title), slug)
        return mapping

    async def _resolve_slug(self, law_code: str) -> str:
        toc = await self._load_toc()
        key = self._normalize_code(law_code)
        if key in toc:
            return toc[key]
        stripped = self._normalize_code(self._strip_version_suffix((law_code or '').strip().lower()))
        if stripped in toc:
            return toc[stripped]
        raise ValueError(f"Gesetzeskürzel '{law_code}' nicht im Inhaltsverzeichnis (gii-toc.xml) gefunden. Bitte Kürzel oder vollständigen Titel prüfen.")

    def _validate_law_code(self, law_code: str) -> str:
        normalized = (law_code or '').strip().lower()
        if not re.fullmatch(r'[a-z0-9_-]{1,64}', normalized):
            raise ValueError("Ungültiges Gesetzeskürzel. Erlaubt sind a-z, 0-9, '_' und '-'.")
        if not self.valves.allow_all_laws and normalized not in self._allowed_law_codes():
            raise ValueError(f"Gesetzeskürzel '{normalized}' ist nicht in allowed_law_codes konfiguriert.")
        return normalized

    def _allowed_law_codes(self) -> Set[str]:
        return {part.strip().lower() for part in (self.valves.allowed_law_codes or '').split(',') if part.strip()}

    def _law_zip_url(self, law_code: str) -> str:
        base = (self.valves.base_url or 'https://www.gesetze-im-internet.de').rstrip('/')
        return f'{base}/{quote(law_code, safe="")}/xml.zip'

    async def _download_law_zip(self, law_code: str) -> bytes:
        url = self._law_zip_url(law_code)
        data = await self._download_bytes(url)
        if len(data) > self.valves.max_zip_bytes:
            raise ValueError(f'ZIP-Datei ist zu groß ({len(data)} Bytes > {self.valves.max_zip_bytes} Bytes).')
        return data

    async def _download_bytes(self, url: str) -> bytes:
        return await asyncio.to_thread(self._download_bytes_sync, url)

    async def _download_text(self, url: str) -> str:
        data = await self._download_bytes(url)
        # Die Webseite liefert meist UTF-8 oder ISO-8859-1; erst UTF-8, dann Fallback.
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return data.decode('latin-1', errors='replace')

    def _download_bytes_sync(self, url: str) -> bytes:
        request = Request(
            url,
            headers={
                'User-Agent': 'OpenWebUI-GesetzeImInternet-Tools/1.0',
                'Accept': 'application/xml,application/zip,text/html,*/*',
            },
            method='GET',
        )
        with urlopen(request, timeout=self.valves.timeout_seconds) as response:  # nosec: URL ist Valve/validiert
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > self.valves.max_zip_bytes:
                raise ValueError(f'Antwort ist zu groß ({content_length} Bytes > {self.valves.max_zip_bytes} Bytes).')
            return response.read(self.valves.max_zip_bytes + 1)

    def _extract_xml_from_zip(self, zip_bytes: bytes) -> Tuple[bytes, str]:
        with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
            xml_names = [name for name in archive.namelist() if name.lower().endswith('.xml')]
            if not xml_names:
                raise ValueError('ZIP-Datei enthält keine XML-Datei.')
            # Falls mehrere XMLs enthalten sind, ist die größte typischerweise der Gesetzestext.
            xml_name = max(xml_names, key=lambda name: archive.getinfo(name).file_size)
            with archive.open(xml_name) as xml_file:
                return xml_file.read(), xml_name

    def _extract_norms(self, root: ET.Element) -> List[Dict[str, Any]]:
        norms: List[Dict[str, Any]] = []
        for index, norm_el in enumerate(self._iter_by_local_name(root, 'norm'), start=1):
            enbez = self._first_text(norm_el, 'enbez')
            title = self._first_text(norm_el, 'titel')
            textdaten = self._first_child(norm_el, 'textdaten')
            text = self._flatten_text(textdaten if textdaten is not None else norm_el)
            norm_id = norm_el.attrib.get('builddate') or norm_el.attrib.get('doknr') or str(index)
            reference_key = self._normalize_paragraph_ref(enbez or title or str(index))
            norms.append(
                {
                    'id': norm_id,
                    'index': index,
                    'enbez': enbez,
                    'title': title,
                    'reference_key': reference_key,
                    'text': text,
                }
            )
        return norms

    def _norm_matches(self, norm: Dict[str, Any], requested_refs: Set[str]) -> bool:
        candidates = {
            norm.get('reference_key') or '',
            self._normalize_paragraph_ref(norm.get('enbez') or ''),
            self._normalize_paragraph_ref(norm.get('title') or ''),
        }
        return bool(candidates.intersection(requested_refs))

    def _normalize_requested_refs(self, paragraphs: Sequence[str]) -> Set[str]:
        refs: Set[str] = set()
        for paragraph in paragraphs:
            normalized = self._normalize_paragraph_ref(paragraph)
            if normalized:
                refs.add(normalized)
        return refs

    def _normalize_paragraph_ref(self, value: Any) -> str:
        text = html.unescape(str(value or '')).strip().lower()
        if not text:
            return ''
        url_marker = re.search(r'__([0-9]+[a-z]?)', text)
        if url_marker:
            return url_marker.group(1)
        text = text.replace('§§', '§')
        text = re.sub(r'\b(paragraph|paragraf|para\.?|nr\.)\b', '', text)
        text = re.sub(r'\bartikel\b', 'art', text)
        text = text.replace('§', '')
        text = re.sub(r'[^a-z0-9]+', '', text)
        if text.startswith('art'):
            return text
        number = re.search(r'([0-9]+[a-z]?)', text)
        return number.group(1) if number else text

    def _build_search_url(self, query: str) -> str:
        params = urlencode(
            {
                'config': 'Gesamt_bmjhome2005',
                'method': 'and',
                'words': query,
                'suche': 'Suchen',
            }
        )
        return f'{self.valves.search_url}?{params}'

    def _parse_anchors(self, html_text: str) -> List[_SearchAnchor]:
        parser = _AnchorParser()
        parser.feed(html_text or '')
        return parser.anchors

    def _extract_search_results(self, anchors: Iterable[_SearchAnchor], limit: int) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str]] = set()
        base = (self.valves.base_url or 'https://www.gesetze-im-internet.de').rstrip('/') + '/'

        for anchor in anchors:
            absolute_url = urljoin(base, anchor.href)
            parsed = urlparse(absolute_url)
            if 'gesetze-im-internet.de' not in parsed.netloc:
                continue
            match = re.search(
                r'/([a-z0-9_-]{1,64})/__([0-9]+[a-z]?)\.html$',
                parsed.path,
                re.IGNORECASE,
            )
            if not match:
                continue
            law_code = match.group(1).lower()
            paragraph = match.group(2)
            if not self.valves.allow_all_laws and law_code not in self._allowed_law_codes():
                continue
            key = (law_code, paragraph)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    'law_code': law_code,
                    'paragraph': paragraph,
                    'paragraph_marker': f'__{paragraph}',
                    'url': absolute_url,
                    'title': anchor.text or None,
                }
            )
            if len(results) >= limit:
                break
        return results

    def _first_child(self, element: ET.Element, local_name: str) -> Optional[ET.Element]:
        for child in list(element):
            if self._local_name(child.tag) == local_name:
                return child
        return None

    def _first_text(self, element: ET.Element, local_name: str) -> Optional[str]:
        for found in self._iter_by_local_name(element, local_name):
            text = self._flatten_text(found)
            if text:
                return text
        return None

    def _iter_by_local_name(self, element: ET.Element, local_name: str) -> Iterable[ET.Element]:
        for candidate in element.iter():
            if self._local_name(candidate.tag) == local_name:
                yield candidate

    @staticmethod
    def _local_name(tag: str) -> str:
        if '}' in tag:
            return tag.rsplit('}', 1)[1]
        return tag

    @staticmethod
    def _flatten_text(element: Optional[ET.Element]) -> str:
        if element is None:
            return ''
        chunks = [part.strip() for part in element.itertext() if part and part.strip()]
        text = '\n'.join(chunks)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _to_json(self, payload: Dict[str, Any]) -> str:
        indent = 2 if self.user_valves.pretty_json else None
        result = json.dumps(payload, ensure_ascii=False, indent=indent)
        max_chars = int(self.valves.max_output_chars or 0)
        if max_chars > 0 and len(result) > max_chars:
            truncated = result[:max_chars]
            suffix = '\n... Ausgabe durch max_output_chars gekürzt ...'
            return truncated + suffix
        return result

    async def _emit_status(self, __event_emitter__, description: str, done: bool) -> None:
        if __event_emitter__ is None:
            return
        try:
            await __event_emitter__(
                {
                    'type': 'status',
                    'data': {
                        'description': description,
                        'done': done,
                    },
                }
            )
        except Exception:
            # Event-Fehler dürfen Tool-Ergebnisse nicht verhindern.
            return

    async def _emit_debug(self, __event_emitter__, payload: Dict[str, Any]) -> None:
        if __event_emitter__ is None or not self.valves.debug:
            return
        try:
            await __event_emitter__(
                {
                    'type': 'message',
                    'data': {'content': '\n```json\n' + json.dumps(payload, ensure_ascii=False, indent=2) + '\n```\n'},
                }
            )
        except Exception:
            return
