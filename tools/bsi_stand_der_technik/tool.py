"""
title: BSI Stand-der-Technik Adapter
description: Findet passende Anforderungen (Controls) aus der maschinenlesbaren BSI Stand-der-Technik-Bibliothek (OSCAL, GitHub) und liefert zitierfaehige Referenzen. Immer aktuell via ETag/Conditional-GET, ohne lokalen Voll-Spiegel.
author: Florian Schade - Hochsauerlandkreis
version: 1.0
license: keine Lizenzangabe im Quellprojekt
original_author: Florian Schade – Hochsauerlandkreis
source_url: https://gitlab.opencode.de/kommi/adapter/bsi_stand_der_technik_tools

KommI-Adapter: gitlab.opencode.de/kommi/adapter/bsi-stand-der-technik-adapter

Findet passende Anforderungen (Controls) aus der maschinenlesbaren BSI
Stand-der-Technik-Bibliothek (OSCAL) und liefert zitierfaehige Referenzen.
Immer aktuell via Conditional-GET (ETag) gegen raw.githubusercontent.com,
ohne lokalen Voll-Spiegel. Keine externen Abhaengigkeiten ausser pydantic
(von OpenWebUI bereitgestellt).

Quelle: https://github.com/BSI-Bund/Stand-der-Technik-Bibliothek
Viewer: https://bsi-community.github.io/Stand-der-Technik-Viewer/

Vier vom LLM aufrufbare Tools:
- suche_stand_der_technik: kataloguebergreifende Stichwortsuche ueber alle
  Controls; liefert bewertete Treffer mit Anforderungstext und zitierfaehiger
  Referenz (referenz_text + klickbare referenz_url). Entwuerfe/Previews
  (Grundschutz++, TLS) werden nur mit preview=True durchsucht.
- hole_control: Volltext eines konkreten Controls (Anforderung, Guidance,
  Metadaten) zum woertlichen Zitieren, z. B. in einer Ausschreibung.
- pruefe_anforderungen: gleicht eine Liste von Anforderungen (z. B. aus einer
  Ausschreibung, vom Chat-LLM extrahiert) deterministisch gegen die Bibliothek
  ab und liefert je Anforderung Control-Kandidaten + heuristisches Verdikt.
- liste_kataloge: verfuegbare Kataloge mit Kurzbeschreibung und Entwurf-Status.

Freshness-Strategie: Kataloge werden on-demand von raw.githubusercontent.com
geladen und modul-intern per ETag/If-None-Match gecacht. Unveraenderte Dateien
liefern HTTP 304 (kein Re-Download). Nur tatsaechlich abgefragte Kataloge landen
im Speicher - kein lokaler Voll-Spiegel.

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
#   Projekt : BSI Stand-der-Technik Tools
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/bsi_stand_der_technik_tools
#   Datei   : bsi-stand-der-technik-adapter.py
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
import json
import re
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

RAW_BASE = 'https://raw.githubusercontent.com/BSI-Bund/Stand-der-Technik-Bibliothek'
GITHUB_BLOB_BASE = 'https://github.com/BSI-Bund/Stand-der-Technik-Bibliothek/blob'
# Der Viewer laedt einen Katalog per Deep-Link ?url=<raw-URL> (verifiziert am
# Viewer-Quellcode: loadOscalDeepLink() -> params.getAll('url'); Typ wird via
# detectOscalKind automatisch erkannt, 'kind' ist optional). Bewusst NUR EIN
# Parameter, damit kein '&' im Link steht - ein '&' wird beim Markdown->HTML-
# Rendern zu '&amp;' und zerlegt den Parameter (url -> amp;url), der Link bricht.
# Ein Control-Anker wird nicht unterstuetzt -> die control_id steht in referenz_text.
VIEWER_BASE = 'https://bsi-community.github.io/Stand-der-Technik-Viewer/'


def _viewer_deep_link(viewer_base: str, raw_url: str) -> str:
    """Baut einen Viewer-Deep-Link (Ein-Parameter), der den Katalog aus raw_url laedt."""
    return f'{viewer_base}?url={quote(raw_url, safe="")}'


HINWEIS = 'Daten aus der BSI Stand-der-Technik-Bibliothek (GitHub, maschinenlesbar, OSCAL). Teile sind Entwuerfe/Previews. Fuer verbindliche Zwecke sind die amtlichen BSI-Veroeffentlichungen massgeblich.'

# key: stabiler Kurzname; path: Repo-Pfad; entwurf: aus Suche default ausgeblendet.
CATALOGS = [
    {'key': 'kernel', 'path': 'Quellkataloge/Kernel/BSI-Stand-der-Technik-Kernel-catalog.json', 'beschreibung': 'BSI Stand der Technik - Kernkatalog', 'entwurf': False},
    {'key': 'kernel-g0', 'path': 'Quellkataloge/Kernel/BSI-Stand-der-Technik-Kernel-G0-catalog.json', 'beschreibung': 'BSI Stand der Technik - Kernel G0', 'entwurf': False},
    {'key': 'risikomanagement', 'path': 'Quellkataloge/Risikomanagement/BSI-Anforderungen-zum-Risikomanagement-catalog.json', 'beschreibung': 'BSI Anforderungen zum Risikomanagement', 'entwurf': False},
    {'key': 'methodik', 'path': 'Quellkataloge/Methodik-Grundschutz++/BSI-Methodik-Grundschutz++-catalog.json', 'beschreibung': 'BSI Methodik Grundschutz++', 'entwurf': False},
    {'key': 'grundschutz++', 'path': 'Anwenderkataloge/Grundschutz++/Grundschutz++-catalog.json', 'beschreibung': 'Grundschutz++ (Kompendium-Preview, Entwurf)', 'entwurf': True},
    {'key': 'tls', 'path': 'Anwenderkataloge/Mindeststandard-TLS/Entwurf-Mindeststandard-TLS-catalog.json', 'beschreibung': 'Mindeststandard TLS (Entwurf)', 'entwurf': True},
]
CATALOGS_BY_KEY = {c['key']: c for c in CATALOGS}

_PARAM_RE = re.compile(r'\{\{\s*insert:\s*param,\s*([^}\s]+)\s*\}\}')
_UMLAUT = {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'}


def _fold(text: str) -> str:
    """Normalisiert Text fuer Matching: lowercase + Umlaut-Faltung."""
    text = (text or '').lower()
    for a, b in _UMLAUT.items():
        text = text.replace(a, b)
    return text


def _iter_controls(catalog_json: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], List[str]]]:
    """Yield (control, group_title_path) rekursiv ueber groups/controls/nested controls."""
    root = catalog_json.get('catalog', catalog_json)

    def walk_control(ctrl: Dict[str, Any], path: List[str]) -> Iterator[Tuple[Dict[str, Any], List[str]]]:
        yield ctrl, path
        for sub in ctrl.get('controls', []) or []:
            yield from walk_control(sub, path)

    def walk_group(group: Dict[str, Any], path: List[str]) -> Iterator[Tuple[Dict[str, Any], List[str]]]:
        new_path = path + [group.get('title') or group.get('id') or '']
        for ctrl in group.get('controls', []) or []:
            yield from walk_control(ctrl, new_path)
        for sub in group.get('groups', []) or []:
            yield from walk_group(sub, new_path)

    for group in root.get('groups', []) or []:
        yield from walk_group(group, [])
    for ctrl in root.get('controls', []) or []:
        yield from walk_control(ctrl, [])


def _iter_parts(parts: List[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    """Yield alle parts rekursiv (inkl. subparts)."""
    for part in parts or []:
        yield part
        yield from _iter_parts(part.get('parts', []) or [])


def _resolve_param_placeholders(prose: str, params: List[Dict[str, Any]]) -> str:
    """Ersetzt {{ insert: param, <id> }} durch params[].label (Fallback: id)."""
    labels = {p.get('id'): (p.get('label') or p.get('id')) for p in (params or [])}
    return _PARAM_RE.sub(lambda mtch: str(labels.get(mtch.group(1), mtch.group(1))), prose or '')


def _prop(props: List[Dict[str, Any]], name: str) -> Optional[str]:
    for p in props or []:
        if p.get('name') == name:
            return p.get('value')
    return None


def _control_to_record(
    ctrl: Dict[str, Any],
    group_path: List[str],
    catalog_key: str,
    beschreibung: str,
    referenz_url: str,
) -> Dict[str, Any]:
    """Wandelt ein OSCAL-Control in einen flachen, durchsuchbaren Record."""
    params = ctrl.get('params', []) or []
    if isinstance(params, dict):  # Einzel-Param defensiv als Liste behandeln
        params = [params]
    statement_parts: List[str] = []
    guidance_parts: List[str] = []
    for part in _iter_parts(ctrl.get('parts', []) or []):
        prose = _resolve_param_placeholders(part.get('prose') or '', params)
        if not prose:
            continue
        if part.get('name') == 'guidance':
            guidance_parts.append(prose)
        else:
            statement_parts.append(prose)
    control_id = ctrl.get('id') or ''
    titel = ctrl.get('title') or ''
    anforderung = '\n'.join(statement_parts).strip()
    guidance = '\n'.join(guidance_parts).strip()
    props = ctrl.get('props', []) or []
    such_text = _fold(' '.join([control_id, titel, anforderung, guidance]))
    return {
        'control_id': control_id,
        'katalog': catalog_key,
        'katalog_beschreibung': beschreibung,
        'gruppe': ' > '.join([g for g in group_path if g]),
        'titel': titel,
        'anforderung': anforderung,
        'guidance': guidance,
        'sec_level': _prop(props, 'sec_level'),
        'effort_level': _prop(props, 'effort_level'),
        'referenz_text': f'BSI {beschreibung} · {control_id}',
        'referenz_url': referenz_url,
        '_such_text': such_text,
        '_titel_fold': _fold(control_id + ' ' + titel),
    }


# Haeufige deutsche Fuell-/Funktionswoerter + Modalverben (MUSS/SOLL etc.), die in
# nahezu jedem Control vorkommen und beim Keyword-Matching nur Rauschen erzeugen.
# In gefalteter Form (Umlaute -> ae/oe/ue), da _query_terms erst faltet.
_STOPWORDS = {
    'der',
    'die',
    'das',
    'dass',
    'des',
    'dem',
    'den',
    'ein',
    'eine',
    'einer',
    'eines',
    'einem',
    'einen',
    'und',
    'oder',
    'aber',
    'sowie',
    'ist',
    'sind',
    'war',
    'waren',
    'sein',
    'wird',
    'werden',
    'wurde',
    'worden',
    'zu',
    'zur',
    'zum',
    'im',
    'in',
    'an',
    'auf',
    'aus',
    'bei',
    'mit',
    'nach',
    'vor',
    'ueber',
    'unter',
    'durch',
    'fuer',
    'gegen',
    'ohne',
    'um',
    'muss',
    'muessen',
    'soll',
    'sollen',
    'kann',
    'koennen',
    'darf',
    'duerfen',
    'sollte',
    'sollten',
    'es',
    'er',
    'sie',
    'wir',
    'man',
    'auch',
    'nur',
    'noch',
    'schon',
    'alle',
    'aller',
    'allen',
    'jede',
    'jeder',
    'jedes',
    'nicht',
    'kein',
    'keine',
    'als',
    'wie',
    'wenn',
    'dann',
    'sowohl',
    'bzw',
}


def _query_terms(query: str) -> List[str]:
    terms = []
    for tok in re.split(r'\s+', _fold(query)):
        tok = re.sub(r'^\W+|\W+$', '', tok)  # Rand-Satzzeichen weg, interne Punkte (z. B. "net.1") behalten
        if len(tok) >= 2 and tok not in _STOPWORDS:
            terms.append(tok)
    return terms


def _score_record(record: Dict[str, Any], terms: List[str]) -> int:
    """+3 pro Term im Titel/Control-ID, sonst +1 im gesamten Suchtext."""
    score = 0
    title = record.get('_titel_fold', '')
    body = record.get('_such_text', '')
    for term in terms:
        if term in title:
            score += 3
        elif term in body:
            score += 1
    return score


class Tools:
    class Valves(BaseModel):
        branch: str = Field(default='main', description='Git-Branch/Ref der BSI-Bibliothek.')
        referenz_ziel: str = Field(default='viewer', description="Ziel der referenz_url: 'viewer' (Stand-der-Technik-Viewer, Katalog per Deep-Link geladen) oder 'github' (Roh-JSON auf GitHub).")
        viewer_base_url: str = Field(default=VIEWER_BASE, description='Basis-URL des Stand-der-Technik-Viewers (mit abschliessendem Slash).')
        etag_check_interval_seconds: int = Field(
            default=600,
            ge=0,
            le=86400,
            description='Mindestabstand, bevor ein gecachter Katalog erneut per ETag geprueft wird. 0 = immer pruefen.',
        )
        timeout_seconds: int = Field(default=30, ge=1, le=120, description='HTTP-Timeout in Sekunden.')
        min_request_interval: float = Field(default=0.5, ge=0.0, le=10.0, description='Mindestabstand zwischen Requests.')
        max_response_bytes: int = Field(default=30_000_000, ge=100_000, le=200_000_000, description='Max. Groesse einer HTTP-Antwort (Grundschutz++ ~5,4 MB).')
        max_output_chars: int = Field(default=0, ge=0, description='Ausgabelaengenbegrenzung. 0 = unbegrenzt.')
        max_search_results: int = Field(default=25, ge=1, le=100, description='Globale Obergrenze fuer Suchtreffer.')
        include_entwurf_default: bool = Field(default=False, description='Ob Entwuerfe/Previews standardmaessig durchsucht werden.')
        starke_treffer_score: int = Field(default=3, ge=1, le=50, description="Ab diesem Score gilt eine Anforderung in pruefe_anforderungen als 'wahrscheinlich_abgedeckt'.")
        max_anforderungen: int = Field(default=100, ge=1, le=1000, description='Obergrenze der Anforderungen pro pruefe_anforderungen-Aufruf.')
        debug: bool = Field(default=False, description='Debug-Ausgaben ueber event_emitter.')

    class UserValves(BaseModel):
        pretty_json: bool = Field(default=True, description='JSON eingerueckt ausgeben.')
        default_search_limit: int = Field(default=8, ge=1, le=50, description='Standard-Trefferlimit fuer die Suche.')
        include_entwurf: Optional[bool] = Field(default=None, description='Entwuerfe/Previews mitdurchsuchen (ueberschreibt include_entwurf_default). None = Valve-Default.')

    def __init__(self) -> None:
        self.valves = self.Valves()
        self.user_valves = self.UserValves()
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    #  HTTP (urllib) mit Rate-Limit + Conditional-GET                    #
    # ------------------------------------------------------------------ #

    def _open(self, request: Request) -> Tuple[int, Optional[bytes], Optional[str]]:
        with self._lock:
            wait = self.valves.min_request_interval - (time.time() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                try:
                    with urlopen(request, timeout=self.valves.timeout_seconds) as resp:
                        body = resp.read(self.valves.max_response_bytes + 1)
                        return resp.status, body, resp.headers.get('ETag')
                except HTTPError as exc:
                    if exc.code == 304:
                        return 304, None, request.headers.get('If-none-match')
                    raise ValueError(f'HTTP {exc.code} bei {request.full_url}: {exc.reason}') from exc
            finally:
                self._last_request = time.time()

    def _referenz_url(self, path: str) -> str:
        """Zitier-URL fuer einen Katalog-Pfad: Viewer-Deep-Link (Default) oder GitHub-Roh-JSON."""
        raw_url = f'{RAW_BASE}/{self.valves.branch}/{quote(path)}'
        if (self.valves.referenz_ziel or 'viewer').strip().lower() == 'github':
            return f'{GITHUB_BLOB_BASE}/{self.valves.branch}/{quote(path)}'
        return _viewer_deep_link(self.valves.viewer_base_url or VIEWER_BASE, raw_url)

    def _fetch_catalog(self, path: str, prior_etag: Optional[str]) -> Tuple[int, Optional[bytes], Optional[str]]:
        url = f'{RAW_BASE}/{self.valves.branch}/{quote(path)}'
        headers = {'User-Agent': 'OpenWebUI-BSI-SdT-Tools/1.0', 'Accept': 'application/json'}
        if prior_etag:
            headers['If-None-Match'] = prior_etag
        return self._open(Request(url, headers=headers, method='GET'))

    def _get_catalog_records(self, key: str) -> List[Dict[str, Any]]:
        """Cache-aware: liefert die geparsten Control-Records eines Katalogs."""
        cat = CATALOGS_BY_KEY[key]
        entry = self._cache.get(key)
        now = time.time()
        if entry and entry.get('records') is not None:
            if now - entry['checked_at'] < self.valves.etag_check_interval_seconds:
                return entry['records']
        prior_etag = entry.get('etag') if entry else None
        try:
            status, body, etag = self._fetch_catalog(cat['path'], prior_etag)
        except ValueError:
            if entry and entry.get('records') is not None:
                entry['warning'] = 'Netzwerkfehler – letzter Cache-Stand verwendet.'
                return entry['records']
            raise
        if status == 304 and entry is not None:
            entry['checked_at'] = now
            return entry['records']
        catalog_json = json.loads(body.decode('utf-8'))
        referenz_url = self._referenz_url(cat['path'])
        records = [_control_to_record(ctrl, group_path, key, cat['beschreibung'], referenz_url) for ctrl, group_path in _iter_controls(catalog_json)]
        self._cache[key] = {'etag': etag, 'records': records, 'checked_at': now}
        return records

    # ------------------------------------------------------------------ #
    #  Ausgabe- / Emit-Hilfsfunktionen                                   #
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    #  liste_kataloge                                                    #
    # ------------------------------------------------------------------ #

    async def liste_kataloge(self, __event_emitter__=None, __user__: Optional[dict] = None) -> str:
        """
        Listet die verfuegbaren BSI-Stand-der-Technik-Kataloge mit Kurzbeschreibung und Entwurf-Status.
        :return: JSON mit allen Katalogen (key, beschreibung, entwurf, pfad).
        """
        await self._emit_status(__event_emitter__, 'liste_kataloge', done=False)
        kataloge = [{'key': c['key'], 'beschreibung': c['beschreibung'], 'entwurf': c['entwurf'], 'pfad': c['path']} for c in CATALOGS]
        await self._emit_status(__event_emitter__, 'liste_kataloge abgeschlossen', done=True)
        return self._to_json({'count': len(kataloge), 'kataloge': kataloge, 'hinweis': HINWEIS})

    # ------------------------------------------------------------------ #
    #  suche_stand_der_technik                                           #
    # ------------------------------------------------------------------ #

    def _select_catalog_keys(self, katalog_filter: str, preview: bool) -> List[str]:
        if katalog_filter.strip():
            key = katalog_filter.strip().lower()
            if key not in CATALOGS_BY_KEY:
                raise ValueError(f"Unbekannter Katalog '{katalog_filter}'. Verfuegbar: " + ', '.join(CATALOGS_BY_KEY))
            return [key]
        include_entwurf = preview
        if not preview:
            uv = self.user_valves.include_entwurf
            include_entwurf = uv if uv is not None else self.valves.include_entwurf_default
        return [c['key'] for c in CATALOGS if include_entwurf or not c['entwurf']]

    async def suche_stand_der_technik(
        self,
        stichworte: str,
        katalog_filter: str = '',
        preview: bool = False,
        limit: Optional[int] = None,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Durchsucht die BSI Stand-der-Technik-Bibliothek nach passenden Anforderungen (Controls) und liefert zitierfaehige Referenzen.
        :param stichworte: Suchbegriffe/Thema (z. B. "Passwortlaenge", "TLS Verschluesselung") oder eine konkrete Control-ID.
        :param katalog_filter: Optionaler Katalog-key (siehe liste_kataloge); leer = alle finalen Kataloge.
        :param preview: Wenn true, werden auch Entwuerfe/Previews (Grundschutz++, TLS) durchsucht.
        :param limit: Optionales Trefferlimit (durch max_search_results begrenzt).
        :return: JSON mit bewerteten Treffern inkl. Anforderungstext und Referenz (referenz_text, referenz_url).
        """
        query = (str(stichworte) if stichworte is not None else '').strip()
        await self._emit_status(__event_emitter__, f'Suche: {query or "(leer)"}', done=False)
        try:
            if not query:
                raise ValueError('stichworte darf nicht leer sein.')
            terms = _query_terms(query)
            if not terms:
                raise ValueError('Bitte mindestens einen Suchbegriff mit >= 2 Zeichen angeben.')
            eff_limit = limit if limit is not None else self.user_valves.default_search_limit
            eff_limit = max(1, min(int(eff_limit), self.valves.max_search_results))
            keys = self._select_catalog_keys(katalog_filter, preview)

            scored: List[Tuple[int, Dict[str, Any]]] = []
            warnings: List[str] = []
            for key in keys:
                try:
                    records = await asyncio.to_thread(self._get_catalog_records, key)
                except ValueError as exc:
                    warnings.append(f"Katalog '{key}' nicht ladbar: {exc}")
                    continue
                for rec in records:
                    s = _score_record(rec, terms)
                    if s > 0:
                        scored.append((s, rec))
            scored.sort(key=lambda t: (-t[0], t[1]['control_id']))

            results = []
            for score, rec in scored[:eff_limit]:
                guidance = rec['guidance']
                if len(guidance) > 500:
                    guidance = guidance[:500].rstrip() + ' …'
                results.append(
                    {
                        'control_id': rec['control_id'],
                        'katalog': rec['katalog'],
                        'katalog_beschreibung': rec['katalog_beschreibung'],
                        'gruppe': rec['gruppe'],
                        'titel': rec['titel'],
                        'anforderung': rec['anforderung'],
                        'guidance': guidance or None,
                        'sec_level': rec['sec_level'],
                        'effort_level': rec['effort_level'],
                        'referenz_text': rec['referenz_text'],
                        'referenz_url': rec['referenz_url'],
                        'score': score,
                    }
                )
            payload = {
                'stichworte': query,
                'durchsuchte_kataloge': keys,
                'preview': bool(preview),
                'total': len(scored),
                'count': len(results),
                'limit': eff_limit,
                'results': results,
                'hinweis': HINWEIS,
            }
            if warnings:
                payload['warnings'] = warnings
            await self._emit_debug(__event_emitter__, {'tool': 'suche_stand_der_technik', 'count': len(results), 'total': len(scored)})
            await self._emit_status(__event_emitter__, f'Suche abgeschlossen: {len(results)} Treffer', done=True)
            return self._to_json(payload)
        except Exception as exc:
            await self._emit_status(__event_emitter__, f'Suche fehlgeschlagen: {exc}', done=True)
            return self._to_json({'error': str(exc), 'tool': 'suche_stand_der_technik', 'stichworte': stichworte})

    # ------------------------------------------------------------------ #
    #  hole_control                                                      #
    # ------------------------------------------------------------------ #

    async def hole_control(
        self,
        control_id: str,
        katalog: str = '',
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Liefert den Volltext eines konkreten Controls (Anforderung, Guidance, Metadaten) zum woertlichen Zitieren.
        :param control_id: Die Control-ID, z. B. "RISK.1.1" (aus suche_stand_der_technik).
        :param katalog: Optionaler Katalog-key zur Eingrenzung; leer = ueber alle Kataloge suchen.
        :return: JSON mit dem vollstaendigen Control-Record inkl. Referenz.
        """
        cid = (str(control_id) if control_id is not None else '').strip()
        await self._emit_status(__event_emitter__, f'hole_control: {cid}', done=False)
        try:
            if not cid:
                raise ValueError('control_id darf nicht leer sein.')
            if katalog.strip():
                key = katalog.strip().lower()
                if key not in CATALOGS_BY_KEY:
                    raise ValueError(f"Unbekannter Katalog '{katalog}'.")
                keys = [key]
            else:
                keys = [c['key'] for c in CATALOGS]  # gezielte ID -> auch Entwuerfe
            target = _fold(cid)
            for key in keys:
                try:
                    records = await asyncio.to_thread(self._get_catalog_records, key)
                except ValueError:
                    continue
                for rec in records:
                    if _fold(rec['control_id']) == target:
                        payload = {k: v for k, v in rec.items() if not k.startswith('_')}
                        payload['hinweis'] = HINWEIS
                        await self._emit_status(__event_emitter__, f'hole_control abgeschlossen: {cid}', done=True)
                        return self._to_json(payload)
            raise ValueError(f"Control '{control_id}' nicht gefunden.")
        except Exception as exc:
            await self._emit_status(__event_emitter__, f'hole_control fehlgeschlagen: {exc}', done=True)
            return self._to_json({'error': str(exc), 'tool': 'hole_control', 'control_id': control_id})

    # ------------------------------------------------------------------ #
    #  pruefe_anforderungen (Phase 2: Dokument-/Ausschreibungsabgleich)   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_anforderungen(anforderungen: Any) -> List[str]:
        """Nimmt eine Liste ODER einen zeilengetrennten String und liefert bereinigte Anforderungen."""
        if anforderungen is None:
            return []
        if isinstance(anforderungen, str):
            roh = re.split(r'[\r\n]+', anforderungen)
        elif isinstance(anforderungen, (list, tuple)):
            roh = [str(a) for a in anforderungen]
        else:
            roh = [str(anforderungen)]
        return [a.strip() for a in roh if a and a.strip()]

    async def pruefe_anforderungen(
        self,
        anforderungen: Any,
        preview: bool = False,
        treffer_pro_anforderung: int = 3,
        __event_emitter__=None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        Gleicht vom LLM aus einem Dokument/einer Ausschreibung extrahierte Anforderungen gegen die BSI Stand-der-Technik-Bibliothek ab und liefert je Anforderung passende Controls plus ein heuristisches Abdeckungs-Verdikt.
        Vorgehen fuer den LLM: Extrahiere zuerst die einzelnen Anforderungen/Themen aus dem Dokument und uebergib sie als Liste an dieses Tool. Baue aus dem Ergebnis eine Abdeckungs-/Luecken-Tabelle mit Zitaten (referenz_text, referenz_url). Das Verdikt ist eine grobe Keyword-Vorsortierung, keine verbindliche Abdeckungsaussage.
        :param anforderungen: Liste der Anforderungen/Themen (oder ein zeilengetrennter String).
        :param preview: Wenn true, werden auch Entwuerfe/Previews (Grundschutz++, TLS) einbezogen.
        :param treffer_pro_anforderung: Anzahl der Control-Kandidaten je Anforderung (1-10).
        :return: JSON mit je Anforderung {verdikt, treffer[]} und einer Zusammenfassung.
        """
        await self._emit_status(__event_emitter__, 'pruefe_anforderungen gestartet', done=False)
        try:
            items = self._normalize_anforderungen(anforderungen)
            if not items:
                raise ValueError('anforderungen darf nicht leer sein.')
            if len(items) > self.valves.max_anforderungen:
                raise ValueError(f'Zu viele Anforderungen ({len(items)}); Maximum ist {self.valves.max_anforderungen}.')
            pro = max(1, min(int(treffer_pro_anforderung), 10))
            keys = self._select_catalog_keys('', preview)

            # Kataloge einmalig laden/cachen; nicht-ladbare mit Warnung ueberspringen.
            catalog_records: List[Dict[str, Any]] = []
            warnings: List[str] = []
            for key in keys:
                try:
                    catalog_records.extend(await asyncio.to_thread(self._get_catalog_records, key))
                except ValueError as exc:
                    warnings.append(f"Katalog '{key}' nicht ladbar: {exc}")

            starke = int(self.valves.starke_treffer_score)
            ergebnisse = []
            summary = {'wahrscheinlich_abgedeckt': 0, 'pruefen': 0, 'keine_entsprechung': 0}
            for anf in items:
                terms = _query_terms(anf)
                scored = (
                    sorted(
                        ((_score_record(r, terms), r) for r in catalog_records),
                        key=lambda t: (-t[0], t[1]['control_id']),
                    )
                    if terms
                    else []
                )
                treffer = [
                    {
                        'control_id': r['control_id'],
                        'katalog': r['katalog'],
                        'titel': r['titel'],
                        'sec_level': r['sec_level'],
                        'referenz_text': r['referenz_text'],
                        'referenz_url': r['referenz_url'],
                        'score': s,
                    }
                    for s, r in scored[:pro]
                    if s > 0
                ]
                best = treffer[0]['score'] if treffer else 0
                if best == 0:
                    verdikt = 'keine_entsprechung'
                elif best >= starke:
                    verdikt = 'wahrscheinlich_abgedeckt'
                else:
                    verdikt = 'pruefen'
                summary[verdikt] += 1
                ergebnisse.append({'anforderung': anf, 'verdikt': verdikt, 'treffer': treffer})

            payload = {
                'anzahl_anforderungen': len(items),
                'durchsuchte_kataloge': keys,
                'preview': bool(preview),
                'anforderungen': ergebnisse,
                'zusammenfassung': summary,
                'hinweis': ('Das Verdikt ist eine grobe Keyword-Vorsortierung (Score-basiert), keine verbindliche Abdeckungsaussage. Finale Bewertung durch LLM/Mensch anhand der verlinkten Controls. ' + HINWEIS),
            }
            if warnings:
                payload['warnings'] = warnings
            await self._emit_debug(__event_emitter__, {'tool': 'pruefe_anforderungen', 'anzahl': len(items), 'zusammenfassung': summary})
            await self._emit_status(__event_emitter__, f'pruefe_anforderungen abgeschlossen: {len(items)} Anforderungen', done=True)
            return self._to_json(payload)
        except Exception as exc:
            await self._emit_status(__event_emitter__, f'pruefe_anforderungen fehlgeschlagen: {exc}', done=True)
            return self._to_json({'error': str(exc), 'tool': 'pruefe_anforderungen'})
