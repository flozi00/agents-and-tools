"""
title: Recht NRW Adapter
description: Durchsucht das geltende und historische NRW-Landesrecht (Gesetze, Rechtsverordnungen, Verwaltungsvorschriften) ueber recht.nrw.de und ruft Normen als Inhaltsverzeichnis, einzelne Paragraphen oder Volltext ab.
author: Florian Schade - Hochsauerlandkreis
version: 1.0
license: keine Lizenzangabe im Quellprojekt
original_author: Florian Schade – Hochsauerlandkreis
source_url: https://gitlab.opencode.de/kommi/adapter/recht-nrw-adapter

KommI-Adapter: gitlab.opencode.de/kommi/adapter/recht-nrw-adapter

Zugriff auf das NRW-Landesrecht ueber den OpenSearch-Endpunkt und die
Download-Fassungen von recht.nrw.de. Keine externen Abhaengigkeiten ausser
pydantic (von OpenWebUI bereitgestellt).

Dieses Modul stellt zwei vom LLM aufrufbare Tools bereit:
- searchLandesrechtNRW: Suche im geltenden/historischen NRW-Landesrecht ueber den
  OpenSearch-Endpunkt von recht.nrw.de. Wendet die Portal-Filter an
  (Status, Dokumenttyp, Titel) und liefert uuid + url je Treffer.
- getLandesrechtNRW: Abruf einer Norm (uuid oder url aus searchLandesrechtNRW). Modi: Inhalts-
  verzeichnis der Paragraphen (toc), ausgewaehlte Paragraphen (paragraphs)
  oder Volltext (fulltext). Quelle ist die saubere Download-Fassung
  /system/files/.../<id>.htm bzw. als Fallback die Detailseite.

Datenzugang (Stand 06/2026, nach Drupal-10-Relaunch):
- Suche:  POST {base}/search-middleware/opensearch_internet/_search (Query-DSL)
- Volltext: GET der Detailseite recht.nrw.de{url} -> Link auf saubere .htm
- Der OpenSearch-Index enthaelt nur Metadaten, KEINEN Normtext.

Hinweise:
- Konsolidierte Fassungen (SGV./SMBl. NRW) sind laut Portal NICHT amtlich
  (Serviceleistung); amtlich sind nur die GV.NRW-/MBl.NRW-PDFs.
- Normtexte selbst sind amtliche Werke (§ 5 UrhG, gemeinfrei).
- Defensiv: Mindestabstand zwischen Requests + Session-Cookie + Referer.

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
#   Projekt : Recht-NRW-Adapter
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/recht-nrw-adapter
#   Datei   : recht-nrw-adapter.py
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
from http.cookiejar import CookieJar
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.request import Request, build_opener, HTTPCookieProcessor

from pydantic import BaseModel, Field

# OpenSearch type-Werte (Sammlungen)
TYPE_SGV = 'state_law_and_regulations'  # SGV: Gesetze & Rechtsverordnungen (/lrgv)
TYPE_SMBL = 'state_law_ministerial_gazette'  # SMBl: Verwaltungsvorschriften (/lrmb)

# Nutzer-Eingabe -> exakter field_document_type_name-Wert (Filter "Dokumententyp").
DOKTYP_MAP = {
    'gesetz': 'Gesetz',
    'gesetze': 'Gesetz',
    'rechtsverordnung': 'Rechtsverordnung',
    'verordnung': 'Rechtsverordnung',
    'rvo': 'Rechtsverordnung',
    'vo': 'Rechtsverordnung',
    'verwaltungsvorschrift': 'Verwaltungsvorschrift',
    'verwaltungsvorschriften': 'Verwaltungsvorschrift',
    'vv': 'Verwaltungsvorschrift',
    'erlass': 'Verwaltungsvorschrift',
    'runderlass': 'Verwaltungsvorschrift',
    'richtlinie': 'Verwaltungsvorschrift',
    'bekanntmachung': 'Bekanntmachung',
}

NICHT_AMTLICH_HINWEIS = 'Konsolidierte Fassung aus recht.nrw.de (SGV./SMBl. NRW). Diese Fassung ist eine Serviceleistung und NICHT amtlich. Amtlich sind allein die Verkuendungsblatt-PDFs (GV.NRW / MBl.NRW).'


def _inforce_filters(now_ts: int) -> List[dict]:
    """Bool-Filter, die nur aktuell geltende Normen durchlassen."""
    return [
        {
            'bool': {
                'should': [
                    {'range': {'field_inforce_date': {'lte': now_ts}}},
                    {'bool': {'must_not': {'exists': {'field': 'field_inforce_date'}}}},
                ]
            }
        },
        {
            'bool': {
                'should': [
                    {'range': {'field_outforce_date': {'gt': now_ts}}},
                    {'bool': {'must_not': {'exists': {'field': 'field_outforce_date'}}}},
                ]
            }
        },
        {
            'bool': {
                'should': [
                    {'term': {'field_historically': {'value': False}}},
                    {'bool': {'must_not': {'exists': {'field': 'field_historically'}}}},
                ]
            }
        },
        {'bool': {'must_not': {'range': {'field_effective_from': {'gt': now_ts}}}}},
    ]


class _HtmlToText(HTMLParser):
    """Minimaler HTML->Text-Parser (block-bewusst) ohne externe Dependencies."""

    _BLOCK = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
    _SKIP = {'script', 'style'}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        if t in self._SKIP:
            self._skip += 1
        elif t in self._BLOCK:
            self._parts.append('\n')
        elif t == 'td':
            self._parts.append(' | ')

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self._SKIP and self._skip:
            self._skip -= 1
        elif t in self._BLOCK:
            self._parts.append('\n')

    def handle_data(self, data: str) -> None:
        if not self._skip and data:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = ''.join(self._parts)
        raw = re.sub(r'[ \t]+', ' ', raw)
        raw = re.sub(r' *\n *', '\n', raw)
        raw = re.sub(r'\n{3,}', '\n\n', raw)
        return raw.strip()


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default='https://recht.nrw.de',
            description='Basis-URL von recht.nrw.de ohne abschliessenden Slash.',
        )
        search_path: str = Field(
            default='/search-middleware/opensearch_internet/_search',
            description='Pfad des OpenSearch-Suchendpunkts.',
        )
        include_smbl: bool = Field(
            default=True,
            description='Wenn true, werden neben SGV (Gesetze/RVO) auch SMBl (Verwaltungsvorschriften) durchsucht.',
        )
        timeout_seconds: int = Field(
            default=20,
            ge=1,
            le=120,
            description='Timeout fuer externe HTTP-Aufrufe in Sekunden.',
        )
        min_request_interval: float = Field(
            default=1.0,
            ge=0.0,
            le=10.0,
            description='Mindestabstand zwischen externen Requests in Sekunden (Rate-Limit).',
        )
        max_search_results: int = Field(
            default=20,
            ge=1,
            le=100,
            description='Globale Obergrenze fuer Suchtreffer.',
        )
        max_response_bytes: int = Field(
            default=15_000_000,
            ge=100_000,
            le=200_000_000,
            description='Maximale Groesse einer einzelnen HTTP-Antwort in Bytes.',
        )
        max_output_chars: int = Field(
            default=0,
            ge=0,
            description='Optionale Ausgabelaengenbegrenzung. 0 = unbegrenzt.',
        )
        debug: bool = Field(
            default=False,
            description='Wenn true, werden Debug-Informationen ueber den event_emitter ausgegeben.',
        )

    class UserValves(BaseModel):
        preferred_output_language: str = Field(
            default='de',
            description='Bevorzugte Sprache fuer Hinweis- und Fehlermeldungen. Normtexte bleiben unveraendert.',
        )
        default_search_limit: int = Field(
            default=10,
            ge=1,
            le=50,
            description='Nutzerspezifisches Standardlimit fuer searchLandesrechtNRW.',
        )
        pretty_json: bool = Field(
            default=True,
            description='Wenn true, werden Tool-Ergebnisse als eingeruecktes JSON ausgegeben.',
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.user_valves = self.UserValves()
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._session_ready = False

    # ------------------------------------------------------------------ #
    #  Oeffentliche, vom LLM aufrufbare Tools                             #
    # ------------------------------------------------------------------ #

    async def searchLandesrechtNRW(
        self,
        query: str,
        dokumenttyp: str = '',
        status: str = 'in_kraft',
        nur_titel: bool = False,
        limit: Optional[int] = None,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Sucht NRW-Landesrecht und wendet die Portal-Filter an. Liefert je Treffer
        uuid und url; damit kann anschliessend getLandesrechtNRW aufgerufen werden.

        WICHTIG: Werte die Nutzerfrage aus und setze die Filter passend:
          - dokumenttyp: "Gesetz", "Rechtsverordnung", "Verwaltungsvorschrift"
            oder "Bekanntmachung" (mehrere mit Komma; leer = alle Typen). Setzen,
            wenn der Nutzer gezielt nach einer Art Vorschrift fragt.
          - status: "in_kraft" (Standard, nur geltendes Recht), "ausser_kraft"
            (aufgehobene/historische) oder "alle".
          - nur_titel: true, wenn nur in Titeln gesucht werden soll (praeziser bei
            bekanntem Gesetzesnamen/Abkuerzung).

        :param query: Thema, Stichwort, Titel oder Abkuerzung, z. B. "Arbeitszeit".
        :param dokumenttyp: optionaler Dokumenttyp-Filter (siehe oben).
        :param status: "in_kraft" | "ausser_kraft" | "alle".
        :param nur_titel: true = nur im Titel suchen.
        :param limit: optionales Trefferlimit (durch max_search_results begrenzt).
        :return: JSON mit Fundstellen (title, abbreviation, document_type, collection, uuid, url).
        """
        safe_query = (query or '').strip()
        status = (status or 'in_kraft').strip().lower()
        await self._emit_status(
            __event_emitter__,
            f'searchLandesrechtNRW gestartet: {safe_query}',
            done=False,
        )
        try:
            if not safe_query:
                raise ValueError('query darf nicht leer sein.')
            if len(safe_query) > 200:
                raise ValueError('query ist zu lang; maximal 200 Zeichen sind erlaubt.')

            effective_limit = limit if limit is not None else self.user_valves.default_search_limit
            effective_limit = max(1, min(int(effective_limit), self.valves.max_search_results))
            doktyp_list = self._norm_doktyp(dokumenttyp)

            body = self._build_search_body(safe_query, effective_limit, doktyp_list, status, nur_titel)
            data = await asyncio.to_thread(self._post_search_sync, body)

            hits = data.get('hits', {}).get('hits', [])
            results = [self._format_hit(h) for h in hits]
            total = data.get('hits', {}).get('total', {}).get('value', len(results))
            buckets = data.get('aggregations', {}).get('aggregates', {}).get('buckets', [])
            type_counts = {b.get('key'): b.get('doc_count') for b in buckets}

            payload = {
                'query': safe_query,
                'source_url': self._human_search_url(safe_query, doktyp_list, status, nur_titel),
                'total': total,
                'count': len(results),
                'limit': effective_limit,
                'filters': {
                    'status': status,
                    'dokumenttyp': doktyp_list or 'alle',
                    'nur_titel': nur_titel,
                    'collections': self._types(),
                },
                'type_counts': type_counts,
                'results': results,
                'hinweis': NICHT_AMTLICH_HINWEIS,
            }
            await self._emit_debug(
                __event_emitter__,
                {
                    'tool': 'searchLandesrechtNRW',
                    'query': safe_query,
                    'raw_hits': len(hits),
                    'result_count': len(results),
                    'total': total,
                },
            )
            await self._emit_status(
                __event_emitter__,
                f'searchLandesrechtNRW abgeschlossen: {len(results)} Treffer',
                done=True,
            )
            return self._to_json(payload)
        except Exception as exc:  # bewusst defensiv im Tool-Kontext
            await self._emit_status(
                __event_emitter__,
                f'searchLandesrechtNRW fehlgeschlagen: {exc}',
                done=True,
            )
            return self._to_json({'error': str(exc), 'tool': 'searchLandesrechtNRW', 'query': query})

    async def getLandesrechtNRW(
        self,
        law: str,
        paragraphs: Optional[List[str]] = None,
        fulltext: bool = False,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Ruft eine NRW-Landesrechtsnorm ab (Quelle: recht.nrw.de).

        :param law: uuid ODER url-Pfad/Link der Norm aus searchLandesrechtNRW
                    (z. B. "0760eb41-..." oder "/lrgv/gesetz/...").
        :param paragraphs: Optionale Liste gewuenschter Paragraphen, z. B. ["§ 1", "§ 8a"] oder ["1","8a"].
        :param fulltext: Wenn true, kompletter Normtext. Wenn false und keine
                         Paragraphen angegeben sind, wird nur das Inhaltsverzeichnis (toc) ausgegeben.
        :return: JSON mit Inhaltsverzeichnis, ausgewaehlten Paragraphen oder Volltext.
        """
        requested_refs = self._normalize_requested_refs(paragraphs or [])
        mode = 'fulltext' if fulltext else ('paragraphs' if requested_refs else 'toc')
        await self._emit_status(
            __event_emitter__,
            f'getLandesrechtNRW gestartet: {law} ({mode})',
            done=False,
        )
        try:
            titel, detail_url, raw_text = await asyncio.to_thread(self._fetch_norm_text, law)
            if not raw_text:
                raise ValueError('Konnte den Normtext nicht laden/extrahieren.')

            norms = self._split_norms(raw_text)
            source_url = self._abs_url(detail_url)
            base = {
                'law': law,
                'title': titel or None,
                'source_url': source_url,
                'hinweis': NICHT_AMTLICH_HINWEIS,
            }

            if fulltext:
                payload: Dict[str, Any] = {
                    **base,
                    'mode': 'fulltext',
                    'count': len(norms),
                    'norms': norms,
                }
            elif requested_refs:
                selected = [n for n in norms if self._norm_matches(n, requested_refs)]
                payload = {
                    **base,
                    'mode': 'paragraphs',
                    'requested': sorted(requested_refs),
                    'count': len(selected),
                    'norms': selected,
                }
                if not selected:
                    payload['warning'] = 'Keine passenden Paragraphen im Normtext gefunden.'
            else:
                toc = [
                    {
                        'enbez': n.get('enbez'),
                        'title': n.get('title'),
                        'reference_key': n.get('reference_key'),
                    }
                    for n in norms
                ]
                payload = {
                    **base,
                    'mode': 'toc',
                    'count': len(toc),
                    'table_of_contents': toc,
                }

            await self._emit_debug(
                __event_emitter__,
                {
                    'tool': 'getLandesrechtNRW',
                    'law': law,
                    'mode': mode,
                    'result_count': payload.get('count'),
                },
            )
            await self._emit_status(__event_emitter__, f'getLandesrechtNRW abgeschlossen: {law}', done=True)
            return self._to_json(payload)
        except Exception as exc:
            await self._emit_status(__event_emitter__, f'getLandesrechtNRW fehlgeschlagen: {exc}', done=True)
            return self._to_json({'error': str(exc), 'tool': 'getLandesrechtNRW', 'law': law})

    # ------------------------------------------------------------------ #
    #  Suche: Query-Aufbau und Trefferaufbereitung                       #
    # ------------------------------------------------------------------ #

    def _types(self) -> List[str]:
        return [TYPE_SGV, TYPE_SMBL] if self.valves.include_smbl else [TYPE_SGV]

    def _norm_doktyp(self, dokumenttyp: str) -> List[str]:
        out: List[str] = []
        for part in (dokumenttyp or '').replace(';', ',').split(','):
            key = part.strip().lower()
            if key:
                out.append(DOKTYP_MAP.get(key, part.strip()))
        return out

    def _status_filters(self, status: str, now: int) -> List[dict]:
        if status == 'alle':
            return []
        if status == 'ausser_kraft':
            # Naeherung: bereits ausser Kraft ODER als historisch markiert.
            return [
                {
                    'bool': {
                        'should': [
                            {'range': {'field_outforce_date': {'lte': now}}},
                            {'term': {'field_historically': {'value': True}}},
                        ],
                        'minimum_should_match': 1,
                    }
                }
            ]
        return _inforce_filters(now)

    def _build_search_body(
        self,
        query: str,
        limit: int,
        doktyp_list: List[str],
        status: str,
        nur_titel: bool,
    ) -> dict:
        now = int(time.time())
        must: List[dict] = [{'terms': {'type': self._types()}}]
        if query:
            fields = (
                ['title^3', 'field_short_title^3', 'field_long_title^2']
                if nur_titel
                else [
                    'field_short_title^3',
                    'field_abbreviation^3',
                    'title^2',
                    'field_long_title',
                ]
            )
            must.append({'multi_match': {'query': query, 'fields': fields, 'fuzziness': 'AUTO'}})
        filt: List[dict] = list(self._status_filters(status, now))
        if doktyp_list:
            filt.append({'terms': {'field_document_type_name': doktyp_list}})
        return {
            'query': {'bool': {'must': must, 'filter': filt}},
            '_source': [
                'uuid',
                'title',
                'url',
                'field_long_title',
                'field_short_title',
                'field_abbreviation',
                'field_document_type_name',
            ],
            'size': limit,
            'from': 0,
            'aggregations': {'aggregates': {'terms': {'field': 'field_document_type_name', 'size': 10}}},
        }

    def _format_hit(self, hit: dict) -> dict:
        src = hit.get('_source', {})
        url = self._first(src.get('url'))
        title = self._first(src.get('field_short_title')) or self._first(src.get('field_long_title')) or self._strip_date_prefix(self._first(src.get('title')))
        collection = 'SGV' if url.startswith('/lrgv') else ('SMBl' if url.startswith('/lrmb') else None)
        return {
            'title': title or None,
            'abbreviation': (self._first(src.get('field_abbreviation')).strip() or None),
            'document_type': self._first(src.get('field_document_type_name')) or None,
            'collection': collection,
            'uuid': self._first(src.get('uuid')) or hit.get('_id'),
            'url': self._abs_url(url),
        }

    def _human_search_url(self, query: str, doktyp_list: List[str], status: str, nur_titel: bool) -> str:
        from urllib.parse import urlencode, quote

        parts = [('s', query)]
        st = []
        if status in ('in_kraft', 'alle'):
            st.append('inkraft')
        if status in ('ausser_kraft', 'alle'):
            st.append('ausserkraft')
        ui_typ = {
            'Gesetz': 'gesetz',
            'Rechtsverordnung': 'verordnung',
            'Verwaltungsvorschrift': 'verwaltungsvorschrift',
            'Bekanntmachung': 'bekanntmachung',
        }
        pairs = [('s', query)]
        for i, s in enumerate(st):
            pairs.append((f'status[{i}]', s))
        for i, d in enumerate(doktyp_list):
            pairs.append((f'dokumentTyp[{i}]', ui_typ.get(d, d.lower())))
        if nur_titel:
            pairs.append(('titleSearch', 'true'))
        qs = urlencode(pairs, quote_via=quote)
        return f'{self.valves.base_url}/suche/lra/?{qs}'

    # ------------------------------------------------------------------ #
    #  Volltext: Detailseite -> saubere .htm -> Text -> Paragraphen      #
    # ------------------------------------------------------------------ #

    def _fetch_norm_text(self, law: str) -> Tuple[str, str, str]:
        """Liefert (titel, detail_url_pfad, normtext). Laeuft im Thread."""
        titel, detail_url = self._resolve_detail_url(law)
        if not detail_url:
            return '', '', ''
        page_html = self._get_text_sync(self._abs_url(detail_url))
        htm_path = self._find_download_link(page_html)
        if htm_path:
            htm = self._get_text_sync(self._abs_url(htm_path))
            text = _html_to_text(htm)
            if text:
                if not titel:
                    titel = text.splitlines()[0].strip() if text else ''
                return titel, detail_url, text
        # Fallback: Hauptinhalt der Detailseite
        text = self._extract_main_content(page_html)
        if not titel:
            titel = self._page_title(page_html)
        return titel, detail_url, text

    def _resolve_detail_url(self, law: str) -> Tuple[str, str]:
        k = (law or '').strip()
        if k.startswith('http'):
            path = k.split('recht.nrw.de', 1)[-1] if 'recht.nrw.de' in k else k
            return '', path.split('?', 1)[0]
        if k.startswith('/lr') or k.startswith('/taxonomy'):
            return '', k.split('?', 1)[0]
        # uuid / node-id -> OpenSearch-Lookup
        if k.startswith('entity:node'):
            query: dict = {'ids': {'values': [k]}}
        else:
            query = {
                'bool': {
                    'should': [
                        {'term': {'uuid': k}},
                        {'match': {'uuid': k}},
                    ],
                    'minimum_should_match': 1,
                }
            }
        data = self._post_search_sync(
            {
                'query': query,
                '_source': [
                    'uuid',
                    'url',
                    'title',
                    'field_short_title',
                    'field_long_title',
                ],
                'size': 1,
            }
        )
        hits = data.get('hits', {}).get('hits', [])
        if not hits:
            return '', ''
        src = hits[0].get('_source', {})
        titel = self._first(src.get('field_short_title')) or self._first(src.get('field_long_title')) or self._strip_date_prefix(self._first(src.get('title')))
        return titel, self._first(src.get('url'))

    @staticmethod
    def _find_download_link(page_html: str) -> str:
        m = re.search(r'href="(/system/files/[^"]+?\.htm)"', page_html or '')
        return m.group(1) if m else ''

    def _extract_main_content(self, page_html: str) -> str:
        text = _html_to_text(page_html or '')
        noise = {
            'Mehr',
            'Link kopiert',
            'Der Link zum Pragraph wurde kopiert',
            'Paragraph ausdrucken',
            'Paragraph Link kopieren',
            'Fußnoten',
            'Dokument ausdrucken',
            'Dokument herunterladen',
            'Inhaltsverzeichnis',
            'Weitere Funktionen',
            'Text durchsuchen',
            'Zum Textanfang',
            'Zum Seitenanfang',
            'Direkt zum Inhalt',
        }
        lines = [ln for ln in text.splitlines() if ln.strip() not in noise]
        return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()

    @staticmethod
    def _page_title(page_html: str) -> str:
        m = re.search(r'<h1[^>]*>(.*?)</h1>', page_html or '', re.IGNORECASE | re.DOTALL)
        if m:
            return _html_to_text(m.group(1)).strip()
        m = re.search(r'<title[^>]*>(.*?)</title>', page_html or '', re.IGNORECASE | re.DOTALL)
        return html.unescape(m.group(1)).split('|')[0].strip() if m else ''

    _PARA_RE = re.compile(r'^(§+\s*\d+\s*[a-z]?|Art(?:ikel)?\.?\s*\d+\s*[a-z]?)\b', re.IGNORECASE)

    def _split_norms(self, text: str) -> List[Dict[str, Any]]:
        """Zerlegt den Normtext anhand der Paragraphen-/Artikel-Ueberschriften."""
        norms: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        preamble: List[str] = []

        def close(cur: Optional[Dict[str, Any]]) -> None:
            if cur is None:
                return
            body = '\n'.join(cur['_lines']).strip()
            cur['text'] = f'{cur["title"]}\n{body}'.strip() if cur.get('title') else body
            cur.pop('_lines', None)
            norms.append(cur)

        for line in text.split('\n'):
            stripped = line.strip()
            if self._PARA_RE.match(stripped):
                close(current)
                enbez = re.sub(r'\s*\(Fn[^)]*\)\s*', ' ', stripped).strip()
                current = {
                    'index': len(norms) + 1,
                    'enbez': enbez,
                    'title': None,
                    'reference_key': self._normalize_paragraph_ref(enbez),
                    '_lines': [],
                }
            elif current is not None:
                if current['title'] is None and stripped:
                    current['title'] = stripped
                else:
                    current['_lines'].append(line)
            elif stripped:
                preamble.append(line)
        close(current)

        if preamble:
            pre_text = '\n'.join(preamble).strip()
            if pre_text:
                norms.insert(
                    0,
                    {
                        'index': 0,
                        'enbez': 'Eingangsformel/Praeambel',
                        'title': None,
                        'reference_key': '',
                        'text': pre_text,
                    },
                )
        return norms

    # ------------------------------------------------------------------ #
    #  Paragraphen-Referenzen (analog Bundesadapter)                     #
    # ------------------------------------------------------------------ #

    def _normalize_requested_refs(self, paragraphs: Sequence[str]) -> Set[str]:
        refs: Set[str] = set()
        for p in paragraphs:
            norm = self._normalize_paragraph_ref(p)
            if norm:
                refs.add(norm)
        return refs

    def _normalize_paragraph_ref(self, value: Any) -> str:
        text = html.unescape(str(value or '')).strip().lower()
        if not text:
            return ''
        text = text.replace('§§', '§')
        text = re.sub(r'\b(paragraph|paragraf|para\.?|nr\.)\b', '', text)
        text = re.sub(r'\bartikel\b', 'art', text)
        text = text.replace('§', '')
        text = re.sub(r'[^a-z0-9]+', '', text)
        if text.startswith('art'):
            return text
        number = re.search(r'([0-9]+[a-z]?)', text)
        return number.group(1) if number else text

    def _norm_matches(self, norm: Dict[str, Any], requested_refs: Set[str]) -> bool:
        candidates = {
            norm.get('reference_key') or '',
            self._normalize_paragraph_ref(norm.get('enbez') or ''),
        }
        return bool(candidates.intersection(requested_refs))

    # ------------------------------------------------------------------ #
    #  HTTP (urllib, dependency-frei) mit Rate-Limit + Session-Cookie    #
    # ------------------------------------------------------------------ #

    def _post_search_sync(self, body: dict) -> dict:
        url = self.valves.base_url + self.valves.search_path
        data = json.dumps(body).encode('utf-8')
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'OpenWebUI-RechtNRW-Tools/1.0',
            'Referer': f'{self.valves.base_url}/suche/lra/',
        }
        raw = self._open(Request(url, data=data, headers=headers, method='POST'))
        return json.loads(raw.decode('utf-8'))

    def _get_text_sync(self, url: str) -> str:
        headers = {
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
            'User-Agent': 'OpenWebUI-RechtNRW-Tools/1.0',
            'Referer': f'{self.valves.base_url}/suche/lra/',
        }
        raw = self._open(Request(url, headers=headers, method='GET'))
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            return raw.decode('latin-1', errors='replace')

    def _open(self, request: Request) -> bytes:
        self._ensure_session()
        with self._lock:
            wait = self.valves.min_request_interval - (time.time() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                with self._opener.open(request, timeout=self.valves.timeout_seconds) as resp:
                    return resp.read(self.valves.max_response_bytes + 1)
            finally:
                self._last_request = time.time()

    def _ensure_session(self) -> None:
        """Einmaliger GET aufs Portal fuer evtl. noetige Session-Cookies."""
        if self._session_ready:
            return
        self._session_ready = True
        try:
            req = Request(
                f'{self.valves.base_url}/suche/lra/',
                headers={'User-Agent': 'OpenWebUI-RechtNRW-Tools/1.0'},
                method='GET',
            )
            with self._opener.open(req, timeout=self.valves.timeout_seconds) as resp:
                resp.read(1)
        except Exception:
            pass  # falls kein Cookie noetig ist, schadet das Fehlen nicht

    # ------------------------------------------------------------------ #
    #  Kleinhelfer                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _first(value: Any) -> str:
        if isinstance(value, list):
            return str(value[0]) if value else ''
        return str(value) if value not in (None, '') else ''

    @staticmethod
    def _strip_date_prefix(s: str) -> str:
        return re.sub(r'^\d{2}\.\d{2}\.\d{4}\s+', '', s or '').strip()

    def _abs_url(self, url: str) -> str:
        if not url:
            return ''
        if url.startswith('http'):
            return url
        return self.valves.base_url + ('' if url.startswith('/') else '/') + url

    def _to_json(self, payload: Dict[str, Any]) -> str:
        indent = 2 if self.user_valves.pretty_json else None
        result = json.dumps(payload, ensure_ascii=False, indent=indent)
        max_chars = int(self.valves.max_output_chars or 0)
        if max_chars > 0 and len(result) > max_chars:
            return result[:max_chars] + '\n... Ausgabe durch max_output_chars gekuerzt ...'
        return result

    async def _emit_status(self, __event_emitter__, description: str, done: bool) -> None:
        if __event_emitter__ is None:
            return
        try:
            await __event_emitter__({'type': 'status', 'data': {'description': description, 'done': done}})
        except Exception:
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


def _html_to_text(html_str: str) -> str:
    parser = _HtmlToText()
    parser.feed(html_str or '')
    return parser.get_text()
