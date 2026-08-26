"""
title: e-Vergabe Tenders
description: Search, read, and download public procurement tenders from the e-Vergabe marketplace (evergabe-online.de) — listing, tender announcements, and all attached tender documents. Login-free.
author: primeLine Solutions GmbH
version: 1.2.0
requirements: requests
"""

import html
import io
import os
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Any
from urllib.parse import urljoin

import requests
from pydantic import BaseModel, Field

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

# The e-Vergabe site is a stateful JSF/PrimeFaces application. Its public
# listing/search is a POST to the search panel's action URL; the keyword is
# carried in the `searchString` field and the submit button triggers it. A plain
# GET on /search.html?N always returns the first page (the ?N is a JSF view id,
# not a page number), so it can never reach older tenders. These constants
# identify the working search form and the JSF pagination command.
JSF_SEARCH_ACTION = '/search.html?1-1.-searchPanel-searchForm'
JSF_KEYWORD_FIELD = 'simpleSearchParametersPanel:keywordStringGroup:searchString'
JSF_SUBMIT_FIELD = 'submitButton'
JSF_SUBMIT_VALUE = 'suchen'
JSF_PAGELINK = r'href="(\./search\.html\?[^"]*pageLink)"[^>]*title="Gehe zu Seite %d"'

# Upper bound on listing pages scanned in a single search() call. The site
# shows 10 results per page and the public index holds ~1000 tenders, so this
# caps worst-case work (e.g. a broad keyword whose matches are filtered out) at
# a few hundred rows while never blocking an explicitly requested deep page.
MAX_SEARCH_PAGES = 30

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


def _listing_bytes(data: bytes) -> list[str]:
    """Best-effort listing of a ZIP archive's member names.

    Returns an empty list when the payload is not a well-formed archive, so a
    caller can report an archive's presence without depending on its contents.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return [entry.filename for entry in archive.infolist()]
    except Exception:
        return []


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

    def _post_text(self, path: str, data: dict, *, headers: dict | None = None) -> str:
        """POST to a JSF action and return the response body (follows redirects)."""
        request_headers = {'Origin': self.valves.base_url, 'Referer': f'{self.valves.base_url}/search.html'}
        if headers:
            request_headers.update(headers)
        response = self._get_session().post(
            f'{self.valves.base_url}{path}', data=data, headers=request_headers, timeout=45
        )
        response.raise_for_status()
        return response.text

    def _search_first_page(self, query: str) -> str:
        """Return the HTML of the first listing page for `query`.

        An empty query lists all tenders (newest first) via a plain GET. A
        non-empty query runs the site's real keyword search, which is a JSF
        POST to the search panel's action URL. The view id in that URL and a
        prior GET of /search.html (to initialise the panel in the session) are
        both required; without them the keyword is silently ignored.
        """
        if not query:
            return self._fetch_text('/search.html')
        self._fetch_text('/search.html')  # warm the JSF search panel state
        return self._post_text(
            JSF_SEARCH_ACTION,
            {JSF_KEYWORD_FIELD: query, JSF_SUBMIT_FIELD: JSF_SUBMIT_VALUE},
        )

    def _next_page(self, html_text: str, from_page: int) -> str | None:
        """Follow the JSF 'next page' link to page `from_page + 1`.

        Returns the next page's HTML, or None when the current page is the
        last one. Each pageLink encodes its exact target page, so the link for
        K+1 must be read fresh out of page K's HTML.
        """
        match = re.search(JSF_PAGELINK % (from_page + 1), html_text)
        if not match:
            return None
        link = match.group(1)
        path = link[2:] if link.startswith('./') else link  # drop the leading ./
        return self._post_text(path, {'javax.faces.partial.ajax': 'true'})

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

    def _resolve_tender_documents_url(self, tender_id: str) -> str:
        return f'{self.valves.base_url}/tenderdocuments.html?id={tender_id}'

    def _new_session(self) -> requests.Session:
        """A fresh gated HTTP session for one stateful (JSF) operation.

        Distinct from ``_get_session`` on purpose: JSF view-state-scoped,
        single-use commands (the tender ZIP archive command, per-file download
        commands) bind only to the session that rendered the page carrying the
        command's state token. Sharing the pooled session across such
        operations would consume the state token of one download before the
        next, so each stateful retrieval runs in its own session.
        """
        session = requests.Session()
        session.headers['User-Agent'] = self.valves.user_agent
        session.headers['Accept-Language'] = 'de-DE,de;q=0.9'
        session.headers['Accept'] = 'text/html,application/xhtml+xml'
        return session

    def _emitted_links(self, html_text: str, tender_id: str) -> list[str]:
        """Extract the tender's command links (ZIP + per-file) from its documents page.

        Returns the distinct hrefs (HTML-unescaped) matching the tender id, in
        document order. These are JSF view-state-scoped, single-use commands
        that bind only to the session that rendered them, so they must be
        triggered by that very session rather than by a copied link.
        """
        pat = r'href="([^"]*tenderdocuments\.html\?[^"]*id=' + re.escape(tender_id) + r'[^"]*)"'
        out: list[str] = []
        seen: set[str] = set()
        for href in re.findall(pat, html_text):
            candidate = html.unescape(href)
            if candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
        return out

    def _fetch_zip_bytes(self, tender_id: str, __event_emitter__=None) -> dict | None:
        """Return the tender's ZIP archive bytes via its documents page's ZIP command.

        The archive command is a JSF view-state-scoped, single-use command: it
        only resolves inside the session that rendered the tender's
        tenderdocuments page. This opens a fresh gated session, visits that
        page in-session (which binds the command's state token), then
        immediately triggers the ZIP command with the correct Referer. Returns
        ``{'data': bytes, 'listing': [...]}`` on success, or ``None`` after
        retries.
        """
        documents_url = self._resolve_tender_documents_url(tender_id)
        zip_pat = r'href="([^"]*tenderdocuments\.html\?[^"]*zipDownloadButton[^"]*id=' + re.escape(tender_id) + r'[^"]*)"'
        last_error: str | None = None
        for attempt in range(1, 4):
            self._emit(__event_emitter__, f'e-Vergabe requesting tender documents (attempt {attempt})', done=False)
            session = self._new_session()
            try:
                session.get(f'{self.valves.base_url}/', timeout=30)
                documents = session.get(documents_url, timeout=60)
                if documents.status_code != 200:
                    last_error = f'tender documents page HTTP {documents.status_code}'
                    time.sleep(2)
                    continue
                match = re.search(zip_pat, documents.text)
                if not match:
                    last_error = 'no ZIP-download command found on the tender documents page'
                    break
                archive_url = urljoin(documents_url, html.unescape(match.group(1)))
                archive = session.get(
                    archive_url,
                    timeout=180,
                    allow_redirects=True,
                    headers={
                        'Referer': documents_url,
                        'Accept': 'application/zip, application/octet-stream, multipart/*; q=0.9, */*; q=0.8',
                    },
                )
                if archive.status_code == 200 and archive.content:
                    return {
                        'data': archive.content,
                        'listing': _listing_bytes(archive.content),
                    }
                last_error = f'ZIP command HTTP {archive.status_code}'
            except Exception as exc:
                last_error = f'{exc.__class__.__name__}: {exc}'
            time.sleep(2)
        self._emit(__event_emitter__, f'e-Vergabe ZIP command unavailable: {last_error}')
        return None

    # --- public tools (schema derived from these) -----------------------

    async def search_on_evergabe_online(
        self,
        query: str = '',
        limit: int = 10,
        page: int = 1,
        __event_emitter__=None,
    ) -> dict[str, Any]:
        """
        Search public procurement tenders on the evergabe-online.de e-Vergabe marketplace.

        Queries the live evergabe-online.de search and returns matching tender
        listings (Bezeichnung, Geschaeftszeichen, Vergabestelle, Ort,
        Verfahrensart, Frist). Each result carries the tender id and a
        tenderdetails.html link for follow-up calls.

        Args:
            query: Optional keyword to filter tenders on evergabe-online.de.
            limit: Maximum tenders to return (1 to max_results).
            page: Listing page to start from (1-based).

        An empty query lists all currently-published tenders (newest first).
        """
        limit = max(1, min(limit, self.valves.max_results))
        page = max(1, page)
        self._emit(__event_emitter__, f'e-Vergabe search: {query or "all tenders"}', done=False)

        # The site is a stateful JSF app: a GET on /search.html?N always returns
        # the same first page (N is a view id, not a page number). The real
        # keyword search is a POST (see _search_first_page) and paging forward
        # is done by POSTing the JSF pageLink. Keep the client-side filter as a
        # safety net, but the candidate set now comes from the server search.
        needle = query.lower() if query else None
        collected: list[dict] = []
        current_page = 1
        html = self._search_first_page(query)

        # Advance to the requested starting page.
        while current_page < page:
            nxt = self._next_page(html, current_page)
            if nxt is None:
                break
            current_page += 1
            html = nxt

        # Collect across pages until we have enough (or run out of pages). The
        # page cap bounds worst-case work when a broad keyword's matches are
        # filtered out client-side across many pages.
        scanned = 0
        page_cap = max(MAX_SEARCH_PAGES, page + limit // 5)
        while len(collected) < limit and scanned < page_cap:
            rows = _parse_listing(html)
            if needle:
                rows = [
                    r for r in rows
                    if needle in r['title'].lower() or needle in r['geschaeftszeichen'].lower()
                ]
            collected.extend(rows)
            if len(collected) >= limit:
                break
            nxt = self._next_page(html, current_page)
            if nxt is None:
                break
            current_page += 1
            scanned += 1
            html = nxt

        result = {
            'query': query,
            'page': page,
            'matches': len(collected),
            'tenders': collected[:limit],
        }
        self._emit(__event_emitter__, f'e-Vergabe: {len(collected)} matching tenders')
        return result

    async def read_tender_on_evergabe_online(
        self,
        tender_id: str,
        __event_emitter__=None,
    ) -> dict[str, Any]:
        """
        Read a single tender's structured announcement from evergabe-online.de.

        Fetches the structured Bekanntmachung.xml announcement for the given
        tender id from evergabe-online.de and returns its fields (Titel,
        Geschaeftszeichen, Vergabestelle, Erfuellungsort, Angebotsfrist,
        Verfahrensart, etc.). Falls back to the HTML detail page if the XML
        is unavailable.

        Args:
            tender_id: The tender id from a tenderdetails.html link on evergabe-online.de.
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

    async def download_announcement_from_evergabe_online(
        self,
        tender_id: str,
        kind: str = 'xml',
        __request__=None,
        __user__=None,
        __event_emitter__=None,
    ) -> dict[str, Any]:
        """
        Download a tender's official announcement (Bekanntmachung) as XML or PDF from evergabe-online.de.

        Fetches the structured Bekanntmachung.xml or Bekanntmachung.pdf
        announcement file for the given tender id from evergabe-online.de and
        saves it locally. This is the formal published announcement only —
        for the attached tender documents (Vergabeunterlagen: PDFs, Word
        files, etc.) use download_documents_from_evergabe_online instead.

        Args:
            tender_id: The tender id from a tenderdetails.html link on evergabe-online.de.
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

    async def download_documents_from_evergabe_online(
        self,
        tender_id: str,
        __request__=None,
        __user__=None,
        __event_emitter__=None,
    ) -> dict[str, Any]:
        """
        Download ALL attached tender documents (Vergabeunterlagen) of an evergabe-online.de tender as a single ZIP archive.

        evergabe-online.de publishes each tender's attached documents (PDF,
        Word, Excel, drawings, etc.) on a separate tenderdocuments.html page
        behind JSF view-state-scoped, single-use download commands. This
        method opens a fresh session, visits the tender's documents page,
        and triggers the site's built-in "download all as ZIP" command
        (zipDownloadButton), so every attached file is retrieved in one call
        rather than one command per file.

        The resulting ZIP is validated (PK header + member listing) and
        saved into the configured downloads_dir (or a ./tenders folder next
        to the agent). Returns the saved path, size, and the list of file
        names contained in the archive. If the tender has no attachments or
        the ZIP command is unavailable, returns an error explaining why.

        Args:
            tender_id: The tender id from a tenderdetails.html link on evergabe-online.de.
        """
        tender_id = str(tender_id).strip()
        if not tender_id:
            return {'error': 'tender_id is required.'}

        self._emit(__event_emitter__, f'e-Vergabe downloading all documents of tender {tender_id}', done=False)

        result = self._fetch_zip_bytes(tender_id, __event_emitter__)
        if result is None:
            return {
                'error': (
                    'No ZIP archive could be downloaded for this tender. The '
                    'tender may have no attached documents, or the evergabe-online.de '
                    'ZIP command was temporarily unavailable. Use '
                    'read_tender_on_evergabe_online to inspect the tender, then retry.'
                ),
            }

        data: bytes = result['data']
        listing: list[str] = result['listing']
        if not listing:
            self._emit(__event_emitter__, f'e-Vergabe tender {tender_id}: archive was empty or not a valid ZIP')
            return {
                'error': (
                    'A file was returned but it is not a valid ZIP archive. '
                    'The tender may have no attached documents.'
                ),
            }

        target_dir = self.valves.downloads_dir.strip() or os.path.join(os.getcwd(), 'tenders')
        os.makedirs(target_dir, exist_ok=True)
        filename = f'tender-{tender_id}-documents.zip'
        full_path = os.path.join(target_dir, filename)
        with open(full_path, 'wb') as handle:
            handle.write(data)

        self._emit(
            __event_emitter__,
            f'e-Vergabe saved {filename} ({len(listing)} files)',
        )
        return {
            'status': 'completed',
            'filename': filename,
            'path': full_path,
            'size_bytes': len(data),
            'file_count': len(listing),
            'files': listing,
        }
