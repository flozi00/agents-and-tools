"""
title: e-Vergabe Tenders
description: Search, read, and download public procurement tenders from the federal evergabe-online.de marketplace (e-Vergabe). Login-free.
author: primeLine Solutions GmbH
version: 1.0.0
requirements: requests
"""

import html
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import requests
from pydantic import BaseModel, Field

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

# The structured tender announcement XML exposes these all-ASCII element tags.
XML_FIELD_MAP = {
    'THEMA': 'title',
    'GESCHAEFTSZEICHEN': 'geschaeftszeichen',
    'VERGABESTELLE': 'vergabestelle',
    'ERFUELLUNGSORT': 'ort',
    'EINGANG_ANGEBOTE': 'frist',
    'VERFAHRENSART': 'verfahrensart',
    'VERGABERECHTSRAHMEN': 'rahmen',
    'AUFTRAGSART': 'auftragsart',
    'BEMERKUNGEN': 'bemerkungen',
}


def _clean(text: str) -> str:
    """Collapse whitespace and unescape HTML entities in a matched fragment."""
    return re.sub(r'\s+', ' ', html.unescape(text or '')).strip()


def _strip_ns(tag: str) -> str:
    return tag.split('}', 1)[-1] if '}' in tag else tag


def _parse_listing(html_text: str) -> list[dict]:
    """Parse a listing page into rows.

    Each result row links to `tenderdetails.html?id=<id>` and carries the
    columns Bezeichnung / Geschaeftszeichen / Vergabestelle / Ort /
    Verfahrensart / Frist / veraeffentlicht.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for block in re.split(r'</tr>', html_text):
        link = re.search(r'tenderdetails\.html\?id=(\d+)', block)
        if not link:
            continue
        tid = link.group(1)
        if tid in seen:
            continue
        seen.add(tid)
        cells = [
            _clean(re.sub(r'<[^>]+>', ' ', c))
            for c in re.findall(r'<td[^>]*>(.*?)</td>', block, re.S)
        ]
        title_link = re.search(r'tenderdetails\.html\?id=\d+"[^>]*>(.*?)</a>', block, re.S)
        title = _clean(title_link.group(1)) if title_link else ''
        rows.append({
            'id': tid,
            'title': title or (cells[0] if cells else ''),
            'geschaeftszeichen': cells[1] if len(cells) > 1 else '',
            'vergabestelle': cells[2] if len(cells) > 2 else '',
            'ort': cells[3] if len(cells) > 3 else '',
            'verfahrensart': cells[4] if len(cells) > 4 else '',
            'frist': cells[5] if len(cells) > 5 else '',
            'veroefflicht': cells[6] if len(cells) > 6 else '',
            'url': f'https://www.evergabe-online.de/tenderdetails.html?id={tid}',
        })
    return rows


def _parse_xml_detail(xml_text: str) -> dict:
    """Map the structured announcement XML into clean fields."""
    fields: dict = {}
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, TypeError):
        return fields
    for tag in root.iter():
        key = XML_FIELD_MAP.get(_strip_ns(tag.tag))
        if key and tag.text and tag.text.strip():
            fields[key] = _clean(tag.text)
    return fields


def _parse_html_detail(html_text: str) -> dict:
    """Fallback: pull the title and body text from the HTML detail page."""
    out: dict = {}
    title = re.search(r'<title>(.*?)</title>', html_text, re.S)
    if title:
        out['title'] = _clean(title.group(1))
    stripped = re.sub(r'<script.*?</script>', ' ', html_text, flags=re.S | re.I)
    stripped = re.sub(r'<style.*?</style>', ' ', stripped, flags=re.S | re.I)
    out['text'] = _clean(re.sub(r'<[^>]+>', ' ', stripped))
    return out


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default='https://www.evergabe-online.de',
            description='e-Vergabe marketplace base URL.',
        )
        user_agent: str = Field(
            default=DEFAULT_USER_AGENT,
            description='User agent used for marketplace requests.',
        )
        max_results: int = Field(
            default=50,
            description='Maximum tenders returned by a single search call (1-200).',
        )
        page_size: int = Field(
            default=100,
            description='Results per listing page fetched from the site (10-100).',
        )
        downloads_dir: str = Field(
            default='',
            description=(
                'Directory to save downloaded announcement files into. '
                'Leave empty to save into a ./tenders folder next to the agent.'
            ),
        )

    def __init__(self):
        self.valves = self.Valves()
        self._session = None

    # --- HTTP -------------------------------------------------------------

    def _get_session(self) -> requests.Session:
        if self._session is None:
            session = requests.Session()
            session.headers['User-Agent'] = self.valves.user_agent
            session.headers['Accept-Language'] = 'de-DE,de;q=0.9'
            session.headers['Accept'] = 'text/html,application/xhtml+xml'
            # Warm the cookie (F5 bot gate expects a prior page visit).
            try:
                session.get(f'{self.valves.base_url}/', timeout=30)
            except Exception:
                pass
            self._session = session
        return self._session

    def _fetch_text(self, path: str) -> str:
        response = self._get_session().get(f'{self.valves.base_url}{path}', timeout=45)
        response.raise_for_status()
        return response.text

    def _fetch_bytes(self, path: str) -> bytes:
        response = self._get_session().get(f'{self.valves.base_url}{path}', timeout=45)
        response.raise_for_status()
        return response.content

    # --- helpers --------------------------------------------------------

    def _emit(self, emitter, description: str, done: bool = True) -> None:
        if not emitter:
            return
        try:
            emitter(
                {
                    'type': 'status',
                    'data': {
                        'action': 'evergabe',
                        'description': description,
                        'done': done,
                    },
                }
            )
        except Exception:
            pass

    def _resolve_tender_url(self, tender_id: str) -> str:
        return f'{self.valves.base_url}/tenderdetails.html?id={tender_id}'

    # --- public tools (schema derived from these) -----------------------

    async def search(
        self,
        query: str = '',
        limit: int = 10,
        page: int = 1,
        __event_emitter__=None,
    ) -> dict[str, Any]:
        """
        Search public procurement tenders on the e-Vergabe marketplace.

        Args:
            query: Optional keyword; results are filtered client-side.
            limit: Maximum tenders to return (1 to max_results).
            page: Listing page to start from (1-based).

        Keyword search is best-effort: the site's own keyword form is
        stateful and often resets, so we list the public results and filter
        them by the query locally. Empty query lists all tenders.
        """
        limit = max(1, min(limit, self.valves.max_results))
        self._emit(__event_emitter__, f'e-Vergabe search: {query or "all tenders"}', done=False)
        rows = _parse_listing(self._fetch_text(f'/search.html?{page}'))
        if query:
            needle = query.lower()
            rows = [
                r for r in rows
                if needle in r['title'].lower() or needle in r['geschaeftszeichen'].lower()
            ]
        result = {
            'query': query,
            'page': page,
            'matches': len(rows),
            'tenders': rows[:limit],
        }
        self._emit(__event_emitter__, f'e-Vergabe: {len(rows)} matching tenders')
        return result

    async def read_tender(
        self,
        tender_id: str,
        __event_emitter__=None,
    ) -> dict[str, Any]:
        """
        Read a single tender's structured details from its announcement XML.

        Args:
            tender_id: The tender id (the digits in a tenderdetails.html link).
        """
        if not tender_id or not str(tender_id).strip():
            return {'error': 'tender_id is required.'}
        tender_id = str(tender_id).strip()
        self._emit(__event_emitter__, f'e-Vergabe reading tender {tender_id}', done=False)

        # Prefer the structured announcement XML; fall back to the HTML page.
        fields: dict = {}
        try:
            fields = _parse_xml_detail(self._fetch_text(f'/download/Bekanntmachung.xml?id={tender_id}'))
        except Exception:
            fields = {}

        if not fields:
            fields = _parse_html_detail(self._fetch_text(f'/tenderdetails.html?id={tender_id}'))

        result = {
            'id': tender_id,
            **fields,
            'url': self._resolve_tender_url(tender_id),
        }
        self._emit(__event_emitter__, f'e-Vergabe read tender {tender_id}')
        return result

    async def download(
        self,
        tender_id: str,
        kind: str = 'xml',
        __request__=None,
        __user__=None,
        __event_emitter__=None,
    ) -> dict[str, Any]:
        """
        Download a tender's announcement file (XML or PDF) and save it.

        Args:
            tender_id: The tender id (the digits in a tenderdetails.html link).
            kind: 'xml' or 'pdf'. Defaults to 'xml'.

        The file is saved into the configured downloads_dir (or a ./tenders
        folder next to the agent). Returns the saved path and size.
        """
        kind = (kind or 'xml').lower()
        if kind not in {'xml', 'pdf'}:
            return {'error': "kind must be 'xml' or 'pdf'."}
        tender_id = str(tender_id).strip()
        if not tender_id:
            return {'error': 'tender_id is required.'}

        self._emit(__event_emitter__, f'e-Vergabe downloading {kind} of tender {tender_id}', done=False)

        path = (
            f'/download/Bekanntmachung.xml?id={tender_id}'
            if kind == 'xml'
            else f'/Bekanntmachung.pdf?id={tender_id}'
        )
        data = self._fetch_bytes(path)
        target_dir = self.valves.downloads_dir.strip() or os.path.join(os.getcwd(), 'tenders')
        os.makedirs(target_dir, exist_ok=True)
        filename = f'tender-{tender_id}.{kind}'
        full_path = os.path.join(target_dir, filename)
        with open(full_path, 'wb') as handle:
            handle.write(data)

        self._emit(__event_emitter__, f'e-Vergabe saved {filename}')
        return {
            'status': 'completed',
            'kind': kind,
            'filename': filename,
            'path': full_path,
            'size_bytes': len(data),
            'source': path,
        }
