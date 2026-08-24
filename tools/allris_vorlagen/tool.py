"""
title: ALLRIS Vorlagen Tools
description: Sucht Vorlagen im Ratsinformationssystem ALLRIS, gibt Beschlussvorschlag, Beratungsfolge und Beschlusstexte im Volltext aus und listet die Anlagen samt PDF-Text auf.
author: Stadt Oberhausen (Boris van Benthem)
version: 0.2.0
required_open_webui_version: 0.9.5
requirements: httpx, beautifulsoup4, pydantic, pypdf
license: keine Lizenzangabe im Quellprojekt
original_author: Stadt Oberhausen (Boris van Benthem)
source_url: https://gitlab.opencode.de/kommi/adapter/allris-adapter
"""

# --------------------------------------------------------------------------
# Herkunft / Provenance
#
# Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
# Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
# unverändert.
#
#   Projekt : ALLRIS-Adapter
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/allris-adapter
#   Datei   : allris-vorlagen-tools.py
#   Autor   : Stadt Oberhausen (Boris van Benthem)
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

# Target: OpenWebUI Tools Function

import base64
import json
import re
import time
from io import BytesIO
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import Request
from pydantic import BaseModel, Field

try:
    from open_webui.models.users import Users
    from open_webui.utils.chat import generate_chat_completion
except Exception:  # pragma: no cover - OpenWebUI imports are only available at runtime.
    Users = None
    generate_chat_completion = None


@dataclass
class TemplateDocument:
    """Parsed representation of a single ALLRIS Vorlage."""

    title: str = ""
    subject: str = ""
    url: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)
    parts: Dict[str, str] = field(default_factory=dict)
    agenda_items: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[str] = field(default_factory=list)


class EventEmitter:
    """Small helper around OpenWebUI's event emitter."""

    def __init__(self, emitter=None):
        self.emitter = emitter

    async def status(self, description: str, done: bool = False, hidden: bool = False) -> None:
        if not self.emitter:
            return
        await self.emitter(
            {
                "type": "status",
                "data": {"description": description, "done": done, "hidden": hidden},
            }
        )

    async def citation(self, title: str, url: str, text: str) -> None:
        if not self.emitter:
            return
        await self.emitter(
            {
                "type": "citation",
                "data": {
                    "document": [text[:2000]],
                    "metadata": [{"source": title, "url": url}],
                    "source": {"name": title or "ALLRIS Vorlage", "url": url},
                },
            }
        )

    async def files(self, files: List[Dict[str, str]]) -> None:
        if not self.emitter or not files:
            return
        await self.emitter({"type": "files", "data": {"files": files}})

    async def debug(self, title: str, data: Any, enabled: bool) -> None:
        if not enabled or not self.emitter:
            return
        try:
            content = f"{title}:\n" + json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            content = f"{title}:\n{data}"
        await self.emitter(
            {"type": "notification", "data": {"type": "info", "content": content}}
        )


class Tools:
    class Valves(BaseModel):
        public_base_url: str = Field(
            default="https://ratsinfo.deine-stadt.de",
            description="Öffentliche Basis-URL des ALLRIS/Ratsinfo-Systems ohne Login, z. B. https://ratsinfo.oberhausen.de",
        )
        private_base_url: str = Field(
            default="https://ratsinfo.deine-stadt.de/personal",
            description="Nicht öffentliche Basis-URL des ALLRIS/Ratsinfo-Systems mit Login, z. B. https://ratsinfo.oberhausen.de/personal",
        )
        template_url_pattern: str = Field(
            default="{base_url}/vo0050?VOLFDNR={id}",
            description="URL-Muster für eine numerische Vorlagen-ID. Platzhalter: {base_url}, {id}.",
        )
        login_enabled: bool = Field(
            default=False,
            description="Erlaubt bei privater Nutzung einen interaktiven ALLRIS/Form-Login über __event_call__.",
        )
        login_max_attempts: int = Field(
            default=3,
            ge=1,
            le=5,
            description="Maximale Anzahl interaktiver Login-Versuche, wenn keine gültige Session vorhanden ist.",
        )
        session_ttl_seconds: int = Field(
            default=3600,
            ge=60,
            le=86400,
            description="Gültigkeitsdauer der im Userkontext zwischengespeicherten ALLRIS-Session in Sekunden.",
        )
        search_max_results: int = Field(
            default=10,
            ge=1,
            le=50,
            description="Globales maximales Ergebnislimit für die Suche.",
        )
        agenda_max_items: int = Field(
            default=25,
            ge=0,
            le=100,
            description="Maximale Anzahl auszulesender Beratungsfolge-/Tagesordnungspunkt-Seiten pro Vorlage.",
        )
        request_timeout_seconds: int = Field(
            default=20,
            ge=5,
            le=120,
            description="HTTP-Timeout für ALLRIS/Ratsinfo-Aufrufe.",
        )
        user_agent: str = Field(
            default="OpenWebUI-ALLRIS-Vorlagen-Tools/0.2.0",
            description="User-Agent für HTTP-Anfragen an das Ratsinformationssystem.",
        )
        allow_redirects: bool = Field(
            default=False,
            description=(
                "Erlaubt HTTP-Redirects bei ALLRIS-Aufrufen. Aus Sicherheitsgründen standardmäßig deaktiviert, "
                "passend zur OpenWebUI-0.9.5-SSRF-Härtung gegen redirect-basierte Angriffe."
            ),
        )
        allowed_hosts: str = Field(
            default="",
            description=(
                "Optionale kommagetrennte Host-Allowlist für ALLRIS-URLs. Wenn leer, werden die Hosts aus "
                "public_base_url und private_base_url verwendet."
            ),
        )
        model_summary: str = Field(
            default="gpt-4o-mini",
            description="OpenWebUI-Modell für interne Zusammenfassungen.",
        )
        prompt_summary: str = Field(
            default=(
                "Fasse die folgende kommunale Vorlage präzise zusammen. "
                "Berücksichtige ausdrücklich Beschlussvorschlag, Beschlusstexte, Beratungsergebnisse, "
                "Betreff, Sachverhalt und relevante Dokumente. Gib die Antwort auf Deutsch als Markdown aus."
            ),
            description="System-Prompt für die Zusammenfassung einer Vorlage.",
        )
        max_text_chars_for_summary: int = Field(
            default=24000,
            ge=2000,
            le=100000,
            description="Maximale Zeichenanzahl des Vorlagentextes, die an das Zusammenfassungsmodell übergeben wird.",
        )
        max_return_chars: int = Field(
            default=50000,
            ge=5000,
            le=200000,
            description="Maximale Zeichenanzahl für Rückgaben aus Tool-Methoden.",
        )
        max_attachment_download_bytes: int = Field(
            default=15_000_000,
            ge=100_000,
            le=100_000_000,
            description="Maximale Downloadgröße je Anlage/PDF in Bytes.",
        )
        max_attachment_pdf_pages: int = Field(
            default=25,
            ge=1,
            le=300,
            description="Maximale Anzahl auszulesender PDF-Seiten je Anlage.",
        )
        max_attachment_text_chars: int = Field(
            default=20000,
            ge=1000,
            le=200000,
            description="Maximale Zeichenanzahl des extrahierten PDF-Textes je Anlage.",
        )
        debug_mode: bool = Field(
            default=False,
            description="Gibt zusätzliche Debug-Informationen als OpenWebUI-Notifications aus.",
        )

    class UserValves(BaseModel):
        preferred_language: str = Field(
            default="de",
            description="Bevorzugte Ausgabesprache für Zusammenfassungen.",
        )
        result_limit: int = Field(
            default=5,
            ge=1,
            le=20,
            description="Nutzerspezifisches Standardlimit für Suchergebnisse.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = False
        # Runtime cache only: stores authenticated cookie snapshots per OpenWebUI user.
        # Passwords are intentionally never stored here.
        self._session_store: Dict[str, Dict[str, Any]] = {}
        # Runtime cache: remembers public/private access selection per chat.
        self._access_choice_store: Dict[str, bool] = {}

    async def search_vorlagen(
        self,
        query: str,
        date_from: str = "",
        date_to: str = "",
        max_results: int = 5,
        __user__: Optional[dict] = None,
        __event_emitter__=None,
        __event_call__=None,
        __metadata__: Optional[dict] = None,
    ) -> str:
        """
        Sucht ALLRIS/Ratsinfo-Vorlagen und gibt Treffer inklusive Beschlussvorschlag und Beschlusstexten zurück.

        :param query: Suchbegriff oder Suchphrase für die ALLRIS-Suche.
        :param date_from: Optionales Startdatum im Format YYYY-MM-DD oder YYYYMMDD.
        :param date_to: Optionales Enddatum im Format YYYY-MM-DD oder YYYYMMDD.
        :param max_results: Maximale Anzahl der zurückzugebenden Treffer.
        :return: Markdown-Liste der Treffer mit URL, Betreff, Beschlussvorschlag und Beschlusstexten.
        """
        events = EventEmitter(__event_emitter__)
        if not query or not query.strip():
            return "Bitte gib einen Suchbegriff an."

        user_valves = self._get_user_valves(__user__)
        use_private_access = await self._select_private_access(events, __event_call__, __user__, __metadata__)
        base_url = self._base_url(use_private_access)
        limit = self._effective_limit(max_results, user_valves)

        await events.status(
            f"🔎 Suche ALLRIS-Vorlagen nach: {query} "
            f"({'nicht öffentlich' if use_private_access else 'öffentlich'})"
        )
        try:
            async with self._client() as client:
                login_ok = await self._login_if_enabled(
                    client, events, __event_call__, __user__, base_url, use_private_access
                )
                if use_private_access and not login_ok:
                    return "Login erforderlich. Es konnte keine gültige ALLRIS-Session aufgebaut werden."
                results = await self._execute_search(
                    client=client,
                    base_url=base_url,
                    query=query.strip(),
                    date_from=date_from,
                    date_to=date_to,
                    limit=limit,
                    events=events,
                )
        except httpx.TimeoutException:
            await events.status("Zeitüberschreitung bei der ALLRIS-Suche.", done=True)
            return "Die Suche im Ratsinformationssystem hat zu lange gedauert."
        except Exception as exc:
            await events.status("Fehler bei der ALLRIS-Suche.", done=True)
            return f"Fehler bei der Suche: {type(exc).__name__}: {exc}"

        if not results:
            await events.status("Keine Vorlagen gefunden.", done=True)
            return "Keine passenden Vorlagen gefunden."

        lines = [f"# Suchergebnisse für „{query}“", ""]
        for index, doc in enumerate(results, start=1):
            text = self._document_to_markdown(doc, include_full_parts=False)
            await events.citation(doc.title or f"Treffer {index}", doc.url, text)
            lines.append(f"## {index}. {doc.title or 'Ohne Titel'}")
            if doc.subject:
                lines.append(f"**Betreff:** {doc.subject}")
            lines.append(f"**URL:** {doc.url}")
            lines.append("")
            lines.append(self._decision_block(doc, max_chars=3500))
            lines.append("")

        await events.status("✅ Suche abgeschlossen.", done=True, hidden=False)
        return self._truncate("\n".join(lines).strip(), self.valves.max_return_chars)

    async def summarize_vorlage(
        self,
        vorlage: str,
        __request__: Optional[Request] = None,
        __user__: Optional[dict] = None,
        __event_emitter__=None,
        __event_call__=None,
        __metadata__: Optional[dict] = None,
    ) -> str:
        """
        Ruft eine ALLRIS/Ratsinfo-Vorlage ab und erstellt eine Zusammenfassung inklusive Beschlusstexten.

        :param vorlage: Vollständige URL, relativer Pfad oder numerische Vorlagen-ID.
        :return: Markdown-Zusammenfassung mit Quelle, Beschlussvorschlag und Beschlusstexten.
        """
        events = EventEmitter(__event_emitter__)
        if not vorlage or not vorlage.strip():
            return "Bitte gib eine Vorlagen-URL, einen Pfad oder eine Vorlagen-ID an."

        user_valves = self._get_user_valves(__user__)
        use_private_access = await self._select_private_access(events, __event_call__, __user__, __metadata__)
        base_url = self._base_url(use_private_access)
        try:
            await events.status(
                "📖 Lade Vorlage für Zusammenfassung "
                f"({'nicht öffentlich' if use_private_access else 'öffentlich'}) ..."
            )
            async with self._client() as client:
                login_ok = await self._login_if_enabled(
                    client, events, __event_call__, __user__, base_url, use_private_access
                )
                if use_private_access and not login_ok:
                    return "Login erforderlich. Es konnte keine gültige ALLRIS-Session aufgebaut werden."
                doc = await self._fetch_template_document(client, vorlage.strip(), events, base_url)
        except httpx.TimeoutException:
            await events.status("Zeitüberschreitung beim Laden der Vorlage.", done=True)
            return "Das Laden der Vorlage hat zu lange gedauert."
        except Exception as exc:
            await events.status("Fehler beim Laden der Vorlage.", done=True)
            return f"Fehler beim Laden der Vorlage: {type(exc).__name__}: {exc}"

        full_text = self._document_to_markdown(doc, include_full_parts=True)
        await events.citation(doc.title or "ALLRIS Vorlage", doc.url, full_text)

        summary = await self._summarize_with_llm(
            full_text=full_text,
            request=__request__,
            user=__user__,
            user_valves=user_valves,
            events=events,
        )

        decision_text = self._decision_block(doc, max_chars=8000)
        response = (
            f"# Zusammenfassung: {doc.title or 'ALLRIS Vorlage'}\n\n"
            f"**URL:** {doc.url}\n\n"
            f"{summary}\n\n"
            f"---\n\n"
            f"## Beschlusstexte\n\n"
            f"{decision_text}"
        )
        await events.status("✅ Zusammenfassung abgeschlossen.", done=True, hidden=False)
        return self._truncate(response.strip(), self.valves.max_return_chars)

    async def get_vorlage_text(
        self,
        vorlage: str,
        __user__: Optional[dict] = None,
        __event_emitter__=None,
        __event_call__=None,
        __metadata__: Optional[dict] = None,
    ) -> str:
        """
        Ruft den Gesamttext einer ALLRIS/Ratsinfo-Vorlage inklusive Beschlussvorschlag, Beratungsfolge und Beschlusstexten ab.

        :param vorlage: Vollständige URL, relativer Pfad oder numerische Vorlagen-ID.
        :return: Vollständiger extrahierter Vorlagentext als Markdown.
        """
        events = EventEmitter(__event_emitter__)
        if not vorlage or not vorlage.strip():
            return "Bitte gib eine Vorlagen-URL, einen Pfad oder eine Vorlagen-ID an."

        user_valves = self._get_user_valves(__user__)
        use_private_access = await self._select_private_access(events, __event_call__, __user__, __metadata__)
        base_url = self._base_url(use_private_access)
        try:
            await events.status(
                "📖 Lade Gesamttext der Vorlage "
                f"({'nicht öffentlich' if use_private_access else 'öffentlich'}) ..."
            )
            async with self._client() as client:
                login_ok = await self._login_if_enabled(
                    client, events, __event_call__, __user__, base_url, use_private_access
                )
                if use_private_access and not login_ok:
                    return "Login erforderlich. Es konnte keine gültige ALLRIS-Session aufgebaut werden."
                doc = await self._fetch_template_document(client, vorlage.strip(), events, base_url)
        except httpx.TimeoutException:
            await events.status("Zeitüberschreitung beim Laden der Vorlage.", done=True)
            return "Das Laden der Vorlage hat zu lange gedauert."
        except Exception as exc:
            await events.status("Fehler beim Laden der Vorlage.", done=True)
            return f"Fehler beim Laden der Vorlage: {type(exc).__name__}: {exc}"

        markdown = self._document_to_markdown(doc, include_full_parts=True)
        await events.citation(doc.title or "ALLRIS Vorlage", doc.url, markdown)
        await events.status("✅ Gesamttext geladen.", done=True, hidden=False)
        return self._truncate(markdown, self.valves.max_return_chars)

    async def get_vorlage_anlagen(
        self,
        vorlage: str,
        include_agenda_documents: bool = True,
        include_pdf_text: bool = True,
        __user__: Optional[dict] = None,
        __event_emitter__=None,
        __event_call__=None,
        __metadata__: Optional[dict] = None,
    ) -> str:
        """
        Ruft die Anlagen/Dokumentlinks einer ALLRIS/Ratsinfo-Vorlage ab und gibt sie als Markdown-Liste zurück.

        :param vorlage: Vollständige URL, relativer Pfad oder numerische Vorlagen-ID.
        :param include_agenda_documents: Wenn True, werden zusätzlich Dokumente aus Beratungsfolge/Tagesordnungspunkten einbezogen.
        :param include_pdf_text: Wenn True, werden PDF-Anlagen heruntergeladen und der Text extrahiert.
        :return: Markdown-Liste der gefundenen Anlagen inklusive Quelle, URL und optional extrahiertem PDF-Text.
        """
        events = EventEmitter(__event_emitter__)
        if not vorlage or not vorlage.strip():
            return "Bitte gib eine Vorlagen-URL, einen Pfad oder eine Vorlagen-ID an."

        user_valves = self._get_user_valves(__user__)
        use_private_access = await self._select_private_access(events, __event_call__, __user__, __metadata__)
        base_url = self._base_url(use_private_access)

        try:
            await events.status(
                "📎 Lade Anlagen der Vorlage "
                f"({'nicht öffentlich' if use_private_access else 'öffentlich'}) ..."
            )
            async with self._client() as client:
                login_ok = await self._login_if_enabled(
                    client, events, __event_call__, __user__, base_url, use_private_access
                )
                if use_private_access and not login_ok:
                    return "Login erforderlich. Es konnte keine gültige ALLRIS-Session aufgebaut werden."
                doc = await self._fetch_template_document(client, vorlage.strip(), events, base_url)
                attachments = self._collect_attachments(
                    doc, include_agenda_documents=include_agenda_documents
                )
                if include_pdf_text and attachments:
                    await self._load_attachment_texts(client, attachments, events)
        except httpx.TimeoutException:
            await events.status("Zeitüberschreitung beim Laden der Anlagen.", done=True)
            return "Das Laden der Anlagen hat zu lange gedauert."
        except Exception as exc:
            await events.status("Fehler beim Laden der Anlagen.", done=True)
            return f"Fehler beim Laden der Anlagen: {type(exc).__name__}: {exc}"

        if not attachments:
            await events.status("Keine Anlagen gefunden.", done=True, hidden=False)
            return f"Keine Anlagen zur Vorlage gefunden.\n\nQuelle: {doc.url}"

        file_events = [
            {"name": item["name"], "url": item["url"]}
            for item in attachments
            if item.get("url")
        ]
        await events.files(file_events)

        lines = [f"# Anlagen: {doc.title or 'ALLRIS Vorlage'}", ""]
        if doc.subject:
            lines.append(f"**Betreff:** {doc.subject}")
        lines.append(f"**Vorlage:** {doc.url}")
        lines.append("")
        if use_private_access:
            lines.append(
                "> Hinweis: Die Anlagen stammen aus dem nicht öffentlichen Bereich. "
                "Der direkte Aufruf der Links kann außerhalb der aktuellen ALLRIS-Session eine erneute Anmeldung erfordern."
            )
            lines.append("")

        for index, item in enumerate(attachments, start=1):
            lines.append(f"{index}. [{item['name']}]({item['url']})")
            lines.append(f"   - Quelle: {item['source']}")
            if item.get("text"):
                lines.append("   - Extrahierter PDF-Text:")
                lines.append("")
                lines.append("```text")
                lines.append(item["text"])
                lines.append("```")
            elif item.get("text_error"):
                lines.append(f"   - PDF-Text: {item['text_error']}")

        await events.status("✅ Anlagen geladen.", done=True, hidden=False)
        return self._truncate("\n".join(lines).strip(), self.valves.max_return_chars)

    def _client(self) -> httpx.AsyncClient:
        headers = {"User-Agent": self.valves.user_agent}
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.valves.request_timeout_seconds),
            headers=headers,
            follow_redirects=bool(self.valves.allow_redirects),
        )

    async def _login_if_enabled(
        self,
        client: httpx.AsyncClient,
        events: EventEmitter,
        event_call=None,
        user: Optional[dict] = None,
        base_url: str = "",
        use_private_access: bool = False,
    ) -> bool:
        if not use_private_access:
            return True
        if not self.valves.login_enabled:
            await events.status("⚠️ Private Nutzung ist ausgewählt, aber login_enabled ist nicht aktiviert.")
            return False

        if self._restore_user_session(client, user, base_url):
            await events.status("🔐 Verwende gespeicherte ALLRIS-Session aus dem Userkontext.")
            return True

        max_attempts = max(1, min(int(self.valves.login_max_attempts), 5))
        for attempt in range(1, max_attempts + 1):
            credentials = await self._prompt_for_credentials(event_call, events, attempt)
            if not credentials:
                await events.status("ℹ️ Login abgebrochen oder keine Zugangsdaten eingegeben.")
                return False

            username, password = credentials
            ok = await self._perform_login(client, username, password, events, base_url)
            if ok:
                self._save_user_session(client, user, username, base_url)
                await events.status("✅ ALLRIS-Login erfolgreich; Session im Userkontext gespeichert.")
                return True

            await events.status(
                f"❌ ALLRIS-Login fehlgeschlagen ({attempt}/{max_attempts})."
                + (" Bitte Zugangsdaten erneut eingeben." if attempt < max_attempts else "")
            )

        return False

    async def _prompt_for_credentials(
        self,
        event_call,
        events: EventEmitter,
        attempt: int,
    ) -> Optional[Tuple[str, str]]:
        if not event_call:
            await events.status("⚠️ Interaktive Login-Abfrage ist nicht verfügbar (__event_call__ fehlt).")
            return None

        suffix = "" if attempt <= 1 else f" (Versuch {attempt})"
        username_response = await event_call(
            {
                "type": "input",
                "data": {
                    "title": f"ALLRIS Login{suffix}",
                    "message": "Bitte Benutzernamen eingeben.",
                    "placeholder": "Benutzername",
                },
            }
        )
        username = self._event_call_value(username_response).strip()
        if not username:
            return None

        password_response = await event_call(
            {
                "type": "input",
                "data": {
                    "title": f"ALLRIS Passwort{suffix}",
                    "message": "Bitte Passwort eingeben. Das Passwort wird nicht gespeichert; gespeichert werden nur Session-Cookies.",
                    "placeholder": "Passwort",
                    "input_type": "password",
                },
            }
        )
        password = self._event_call_value(password_response)
        if not password:
            return None

        return username, password

    async def _perform_login(
        self,
        client: httpx.AsyncClient,
        username: str,
        password: str,
        events: EventEmitter,
        base_url: str,
    ) -> bool:
        base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        client.headers["Authorization"] = f"Basic {token}"

        try:
            response = await client.get(base_url)
            response.raise_for_status()
            if self._looks_logged_in(response.text):
                return True

            soup = BeautifulSoup(response.text, "html.parser")
            token_el = soup.find("input", {"name": "sectoken"})
            sectoken = token_el.get("value") if token_el else None
            if not sectoken:
                await events.status("⚠️ Kein sectoken im Loginformular gefunden; Login konnte nicht geprüft werden.")
                client.headers.pop("Authorization", None)
                return False

            login_response = await client.post(
                f"{base_url}/logon2",
                data={
                    "sectoken": sectoken,
                    "LOUID": username,
                    "LOPWD": password,
                    "LOGON": "1",
                    "js": "1",
                },
            )
            login_response.raise_for_status()
            ok = self._looks_logged_in(login_response.text)
            if not ok:
                client.headers.pop("Authorization", None)
            return ok
        except Exception as exc:
            client.headers.pop("Authorization", None)
            await events.status(f"⚠️ ALLRIS-Login-Fehler: {type(exc).__name__}: {exc}")
            return False

    def _restore_user_session(self, client: httpx.AsyncClient, user: Optional[dict], base_url: str) -> bool:
        session = self._get_user_session(user)
        if not session:
            return False
        expires_at = float(session.get("expires_at") or 0)
        cookies = session.get("cookies") or {}
        session_base_url = session.get("base_url") or ""
        if session_base_url and session_base_url != base_url.rstrip("/"):
            self._clear_user_session(user)
            return False
        if not cookies or expires_at <= time.time():
            self._clear_user_session(user)
            return False
        client.cookies.update(cookies)
        return True

    def _save_user_session(self, client: httpx.AsyncClient, user: Optional[dict], username: str, base_url: str) -> None:
        if not user:
            return
        session = {
            "username": username,
            "cookies": dict(client.cookies),
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + int(self.valves.session_ttl_seconds),
            "base_url": base_url.rstrip("/"),
        }
        user_key = self._user_key(user)
        if user_key:
            self._session_store[user_key] = session
        try:
            user["allris_session"] = session
        except Exception:
            pass

    def _get_user_session(self, user: Optional[dict]) -> Optional[Dict[str, Any]]:
        if not user:
            return None
        session = user.get("allris_session") if isinstance(user, dict) else None
        if session:
            return session
        user_key = self._user_key(user)
        return self._session_store.get(user_key) if user_key else None

    def _clear_user_session(self, user: Optional[dict]) -> None:
        if not user:
            return
        user_key = self._user_key(user)
        if user_key:
            self._session_store.pop(user_key, None)
        try:
            user.pop("allris_session", None)
        except Exception:
            pass

    def _user_key(self, user: Optional[dict]) -> str:
        if not isinstance(user, dict):
            return ""
        return str(user.get("id") or user.get("email") or user.get("name") or "")

    def _event_call_value(self, response: Any) -> str:
        if response is None:
            return ""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            for key in ("value", "text", "content", "input"):
                value = response.get(key)
                if isinstance(value, str):
                    return value
            data = response.get("data")
            if isinstance(data, dict):
                for key in ("value", "text", "content", "input"):
                    value = data.get(key)
                    if isinstance(value, str):
                        return value
        return str(response)

    def _looks_logged_in(self, html: str) -> bool:
        text = (html or "").lower()
        return "logoff" in text or "abmelden" in text or "logout" in text

    async def _execute_search(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        query: str,
        date_from: str,
        date_to: str,
        limit: int,
        events: EventEmitter,
    ) -> List[TemplateDocument]:
        params = {"SUCHWORT": query}
        normalized_from = self._normalize_date(date_from)
        normalized_to = self._normalize_date(date_to)
        if normalized_from:
            params["BEGINN"] = normalized_from
        if normalized_to:
            params["ENDE"] = normalized_to

        search_url = self._absolute_url("tr010", base_url)
        await events.debug("Suchparameter", {"url": search_url, "params": params}, self.valves.debug_mode)

        response = await client.post(search_url, params=params)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        urls: List[str] = []
        for row in soup.select("tbody tr"):
            link_tag = row.select_one("td:nth-child(1) > div > a") or row.select_one("a[href]")
            if not link_tag:
                continue
            href = link_tag.get("href")
            if not href:
                continue
            url = self._absolute_url(href, base_url)
            if url not in urls:
                urls.append(url)
            if len(urls) >= limit:
                break

        documents: List[TemplateDocument] = []
        for index, url in enumerate(urls, start=1):
            await events.status(f"📖 Lese Treffer {index}/{len(urls)} ...")
            try:
                documents.append(await self._fetch_template_document(client, url, events, base_url))
            except Exception as exc:
                documents.append(
                    TemplateDocument(
                        title=f"Fehler beim Abruf von Treffer {index}",
                        url=url,
                        parts={"Fehler": f"{type(exc).__name__}: {exc}"},
                    )
                )
        return documents

    async def _fetch_template_document(
        self,
        client: httpx.AsyncClient,
        vorlage: str,
        events: EventEmitter,
        base_url: str,
    ) -> TemplateDocument:
        url = self._resolve_template_reference(vorlage, base_url)
        await events.debug("Vorlagenabruf", {"input": vorlage, "url": url}, self.valves.debug_mode)

        response = await client.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        doc = TemplateDocument(url=self._response_url(response, url, base_url))
        doc.title = self._select_text(soup, "h1.title") or self._select_text(soup, "h1")
        doc.subject = self._select_text(soup, "#vobetreff")
        doc.metadata = self._extract_metadata(soup)
        doc.parts = self._extract_doc_parts(soup)
        doc.documents = self._extract_document_links(soup, base_url)

        agenda_links = self._extract_agenda_links(soup, base_url)
        for agenda_url in agenda_links[: self.valves.agenda_max_items]:
            doc.agenda_items.append(await self._parse_agenda_item(client, agenda_url, base_url))

        return doc

    async def _parse_agenda_item(self, client: httpx.AsyncClient, url: str, base_url: str) -> Dict[str, Any]:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except Exception as exc:
            return {"url": url, "title": "", "error": f"{type(exc).__name__}: {exc}"}

        soup = BeautifulSoup(response.text, "html.parser")
        return {
            "url": self._response_url(response, url, base_url),
            "title": self._select_text(soup, "h1.title") or self._select_text(soup, "h1"),
            "metadata": self._extract_metadata(soup),
            "beratung": self._find_section_text_by_heading(soup, "Beratung"),
            "beschluss": self._find_section_text_by_heading(soup, "Beschluss"),
            "documents": self._extract_document_links(soup, base_url),
        }

    async def _summarize_with_llm(
        self,
        full_text: str,
        request: Optional[Request],
        user: Optional[dict],
        user_valves: Optional["Tools.UserValves"],
        events: EventEmitter,
    ) -> str:
        if not request or not user or not generate_chat_completion or not Users:
            return self._fallback_summary(full_text)

        user_id = user.get("id") if isinstance(user, dict) else None
        if not user_id:
            return self._fallback_summary(full_text)

        language = user_valves.preferred_language if user_valves else "de"
        body = {
            "model": self.valves.model_summary,
            "stream": False,
            "messages": [
                {"role": "system", "content": self.valves.prompt_summary},
                {
                    "role": "user",
                    "content": (
                        f"Ausgabesprache: {language}\n\n"
                        f"Vorlagentext:\n{self._truncate(full_text, self.valves.max_text_chars_for_summary)}"
                    ),
                },
            ],
        }
        try:
            await events.status("🧠 Erstelle Zusammenfassung ...")
            await events.debug("Summary Prompt", body, self.valves.debug_mode)
            response = await generate_chat_completion(request, body, Users.get_user_by_id(user_id))
            return response.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or self._fallback_summary(full_text)
        except Exception as exc:
            await events.status(f"⚠️ LLM-Zusammenfassung fehlgeschlagen, nutze Kurzextrakt: {type(exc).__name__}")
            return self._fallback_summary(full_text)

    def _fallback_summary(self, full_text: str) -> str:
        text = re.sub(r"\s+", " ", full_text or "").strip()
        if not text:
            return "Keine Inhalte für eine Zusammenfassung gefunden."
        return "## Kurzextrakt\n\n" + self._truncate(text, 2500)

    def _document_to_markdown(self, doc: TemplateDocument, include_full_parts: bool) -> str:
        lines: List[str] = [f"# {doc.title or 'ALLRIS Vorlage'}"]
        if doc.subject:
            lines.extend(["", f"**Betreff:** {doc.subject}"])
        if doc.url:
            lines.append(f"**URL:** {doc.url}")

        if doc.metadata:
            lines.extend(["", "## Grunddaten"])
            for key, value in doc.metadata.items():
                lines.append(f"- **{key}:** {value}")

        lines.extend(["", "## Beschlusstexte", self._decision_block(doc, max_chars=0)])

        if include_full_parts:
            for title, content in doc.parts.items():
                if self._is_decision_heading(title):
                    continue
                if content:
                    lines.extend(["", f"## {title}", content])

        if doc.documents:
            lines.extend(["", "## Dokumente"])
            lines.extend([f"- {url}" for url in doc.documents])

        if doc.agenda_items:
            lines.extend(["", "## Beratungsfolge / Tagesordnungspunkte"])
            for item in doc.agenda_items:
                lines.extend(["", f"### {item.get('title') or 'Tagesordnungspunkt'}"])
                if item.get("url"):
                    lines.append(f"**URL:** {item['url']}")
                metadata = item.get("metadata") or {}
                for key, value in metadata.items():
                    lines.append(f"- **{key}:** {value}")
                if item.get("beratung"):
                    lines.extend(["", "**Beratung:**", item["beratung"]])
                if item.get("beschluss"):
                    lines.extend(["", "**Beschluss:**", item["beschluss"]])
                if item.get("error"):
                    lines.extend(["", f"**Fehler:** {item['error']}"])
                documents = item.get("documents") or []
                if documents:
                    lines.extend(["", "**Dokumente:**"])
                    lines.extend([f"- {url}" for url in documents])

        return "\n".join(lines).strip()

    def _decision_block(self, doc: TemplateDocument, max_chars: int = 0) -> str:
        lines: List[str] = []
        for title, content in doc.parts.items():
            if self._is_decision_heading(title) and content:
                lines.extend([f"### {title}", content, ""])

        for index, item in enumerate(doc.agenda_items, start=1):
            beschluss = item.get("beschluss") or ""
            beratung = item.get("beratung") or ""
            if not beschluss and not beratung:
                continue
            lines.append(f"### Beschluss/Beratung {index}: {item.get('title') or 'Tagesordnungspunkt'}")
            if item.get("url"):
                lines.append(f"URL: {item['url']}")
            if beratung:
                lines.extend(["Beratung:", beratung])
            if beschluss:
                lines.extend(["Beschluss:", beschluss])
            lines.append("")

        if not lines:
            lines.append("Keine Beschlusstexte gefunden.")

        text = "\n".join(lines).strip()
        return self._truncate(text, max_chars) if max_chars and max_chars > 0 else text

    def _extract_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        for dl in soup.select("#headLeft dl, #headRight dl, dl"):
            key_el = dl.select_one("dt .label") or dl.select_one("dt")
            val_el = dl.select_one("dd")
            if not key_el or not val_el:
                continue
            key = self._clean_text(key_el.get_text(" "))
            value = self._clean_text(val_el.get_text(" "))
            if key and value and key not in metadata:
                metadata[key] = value
        return metadata

    def _extract_doc_parts(self, soup: BeautifulSoup) -> Dict[str, str]:
        parts: Dict[str, str] = {}
        for section in soup.select("div.compFull"):
            title_el = section.select_one("h2.expandedTitle") or section.select_one("h2")
            if not title_el:
                continue
            title = self._clean_text(title_el.get_text(" "))
            content_el = section.select_one("div.docPart")
            content = self._clean_text(content_el.get_text(" ")) if content_el else ""
            if title and content:
                parts[title] = content

        # Fallback for pages where sections are not wrapped in div.compFull.
        for heading in soup.find_all(["h2", "h3"]):
            title = self._clean_text(heading.get_text(" "))
            if not title or title in parts:
                continue
            next_doc_part = heading.find_next("div", class_="docPart")
            if next_doc_part:
                content = self._clean_text(next_doc_part.get_text(" "))
                if content:
                    parts[title] = content
        return parts

    def _extract_agenda_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        links: List[str] = []
        selectors = ["a[href*='to020?TOLFDNR=']", "a[href*='to020.asp']", "a[href*='TOLFDNR=']"]
        for selector in selectors:
            for anchor in soup.select(selector):
                href = anchor.get("href")
                if not href:
                    continue
                url = self._absolute_url(href, base_url)
                if url not in links:
                    links.append(url)
        return links

    def _extract_document_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        links: List[str] = []
        for item in self._extract_document_items(soup, base_url):
            url = item.get("url") or ""
            if url and url not in links:
                links.append(url)
        return links

    def _extract_document_items(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        selectors = (
            "aside#dokumenteHeaderPanel a[href], "
            "a.pdf[href], "
            "a[href$='.pdf'], "
            "a[href*='getfile'], "
            "a[href*='doctoshow'], "
            "a[href*='document']"
        )
        for anchor in soup.select(selectors):
            href = anchor.get("href")
            if not href:
                continue
            url = self._absolute_url(href, base_url)
            name = self._clean_text(anchor.get_text(" ")) or self._filename_from_url(url)
            if not name:
                name = "Anlage"
            if not any(existing.get("url") == url for existing in items):
                items.append({"name": name, "url": url})
        return items

    def _collect_attachments(
        self, doc: TemplateDocument, include_agenda_documents: bool = True
    ) -> List[Dict[str, str]]:
        attachments: List[Dict[str, str]] = []
        seen: set = set()

        def add(url: str, source: str) -> None:
            if not url or url in seen:
                return
            seen.add(url)
            attachments.append(
                {
                    "name": self._filename_from_url(url) or "Anlage",
                    "url": url,
                    "source": source,
                }
            )

        for url in doc.documents:
            add(url, "Vorlage")

        if include_agenda_documents:
            for item in doc.agenda_items:
                source = item.get("title") or "Tagesordnungspunkt"
                for url in item.get("documents") or []:
                    add(url, source)

        return attachments

    async def _load_attachment_texts(
        self,
        client: httpx.AsyncClient,
        attachments: List[Dict[str, str]],
        events: EventEmitter,
    ) -> None:
        for index, item in enumerate(attachments, start=1):
            url = item.get("url") or ""
            name = item.get("name") or "Anlage"
            if not self._looks_like_pdf(url, name):
                continue

            await events.status(f"📄 Lade und verarbeite PDF-Anlage {index}/{len(attachments)}: {name}")
            try:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content or b""
                if len(content) > self.valves.max_attachment_download_bytes:
                    item["text_error"] = (
                        "PDF wurde nicht verarbeitet, weil die Datei größer als "
                        f"{self.valves.max_attachment_download_bytes} Bytes ist."
                    )
                    continue

                content_type = (response.headers.get("content-type") or "").lower()
                if "pdf" not in content_type and not content.startswith(b"%PDF"):
                    item["text_error"] = "Anlage sieht nicht wie eine PDF-Datei aus."
                    continue

                text = self._extract_pdf_text(content)
                item["text"] = self._truncate(text, self.valves.max_attachment_text_chars)
            except Exception as exc:
                item["text_error"] = f"PDF konnte nicht geladen/verarbeitet werden: {type(exc).__name__}: {exc}"

    def _extract_pdf_text(self, content: bytes) -> str:
        try:
            from pypdf import PdfReader
        except Exception as exc:
            return (
                "PDF-Text konnte nicht extrahiert werden, weil pypdf nicht verfügbar ist. "
                f"Installiere die Function-Anforderung 'pypdf'. ({type(exc).__name__}: {exc})"
            )

        try:
            reader = PdfReader(BytesIO(content))
            if getattr(reader, "is_encrypted", False):
                try:
                    reader.decrypt("")
                except Exception:
                    return "PDF ist verschlüsselt und konnte nicht ohne Passwort gelesen werden."

            texts: List[str] = []
            max_pages = min(len(reader.pages), self.valves.max_attachment_pdf_pages)
            for page_index in range(max_pages):
                page = reader.pages[page_index]
                try:
                    page_text = page.extract_text() or ""
                except Exception as exc:
                    page_text = f"[Seite {page_index + 1}: Textextraktion fehlgeschlagen: {type(exc).__name__}: {exc}]"
                page_text = self._clean_text(page_text)
                if page_text:
                    texts.append(f"--- Seite {page_index + 1} ---\n{page_text}")

            if not texts:
                return "Aus der PDF-Anlage konnte kein Text extrahiert werden. Möglicherweise ist sie gescannt oder bildbasiert."
            if len(reader.pages) > max_pages:
                texts.append(f"[Weitere Seiten ausgelassen: {len(reader.pages) - max_pages}]")
            return "\n\n".join(texts)
        except Exception as exc:
            return f"PDF-Text konnte nicht extrahiert werden: {type(exc).__name__}: {exc}"

    def _looks_like_pdf(self, url: str, name: str = "") -> bool:
        lowered = f"{url} {name}".lower()
        return ".pdf" in lowered or "format=pdf" in lowered or "pdf" in lowered

    def _filename_from_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            filename = unquote((parsed.path or "").rstrip("/").split("/")[-1])
            return filename or ""
        except Exception:
            return ""

    def _find_section_text_by_heading(self, soup: BeautifulSoup, needle: str) -> str:
        needle_lower = needle.lower()
        for heading in soup.find_all(["h2", "h3"]):
            heading_text = self._clean_text(heading.get_text(" ")).lower()
            if needle_lower not in heading_text:
                continue
            part = heading.find_next("div", class_="docPart")
            if part:
                return self._clean_text(part.get_text(" "))
        return ""

    def _select_text(self, soup: BeautifulSoup, selector: str) -> str:
        element = soup.select_one(selector)
        return self._clean_text(element.get_text(" ")) if element else ""

    def _resolve_template_reference(self, value: str, base_url: str) -> str:
        value = value.strip()
        if value.startswith("http://") or value.startswith("https://"):
            return self._validate_allris_url(value, base_url)
        if re.fullmatch(r"\d+", value):
            return self._validate_allris_url(
                self.valves.template_url_pattern.format(
                    base_url=base_url.rstrip("/"),
                    id=value,
                ),
                base_url,
            )
        return self._absolute_url(value, base_url)

    def _absolute_url(self, href: str, base_url: str) -> str:
        return self._validate_allris_url(urljoin(base_url.rstrip("/") + "/", href), base_url)

    def _response_url(self, response: httpx.Response, fallback_url: str, base_url: str) -> str:
        """Return and validate the effective response URL, especially when redirects are enabled."""
        effective_url = str(response.url) if getattr(response, "url", None) else fallback_url
        return self._validate_allris_url(effective_url, base_url)

    def _allowed_hostnames(self, base_url: str) -> set:
        hosts = set()
        for configured_url in (base_url, self.valves.public_base_url, self.valves.private_base_url):
            try:
                hostname = urlparse((configured_url or "").strip()).hostname
                if hostname:
                    hosts.add(hostname.lower())
            except Exception:
                pass
        for host in (self.valves.allowed_hosts or "").split(","):
            cleaned = host.strip().lower()
            if cleaned:
                hosts.add(cleaned)
        return hosts

    def _validate_allris_url(self, url: str, base_url: str) -> str:
        """Defensively restrict tool-controlled URLs to configured ALLRIS hosts."""
        if not url:
            raise ValueError("Leere URL ist nicht erlaubt.")
        if any(control in url for control in ("\\", "\t", "\r", "\n")):
            raise ValueError("URL enthält nicht erlaubte Steuerzeichen oder Backslashes.")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Nicht erlaubtes URL-Schema: {parsed.scheme or '(leer)'}")
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise ValueError("URL enthält keinen Hostnamen.")
        allowed_hosts = self._allowed_hostnames(base_url)
        if hostname not in allowed_hosts:
            raise ValueError(
                f"Host '{hostname}' ist nicht in der ALLRIS-Allowlist ({', '.join(sorted(allowed_hosts))}) enthalten."
            )
        return url

    def _normalize_date(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if re.fullmatch(r"\d{8}", value):
            return value
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
        if match:
            return "".join(match.groups())
        return value

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _truncate(self, text: str, max_chars: int) -> str:
        if not max_chars or max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[: max_chars - 20].rstrip() + "\n\n[… gekürzt]"

    def _is_decision_heading(self, heading: str) -> bool:
        lowered = (heading or "").lower()
        return "beschluss" in lowered or "entscheidung" in lowered

    def _base_url(self, use_private_access: bool) -> str:
        if use_private_access:
            return (self.valves.private_base_url or self.valves.public_base_url).rstrip("/")
        return self.valves.public_base_url.rstrip("/")

    async def _select_private_access(
        self,
        events: EventEmitter,
        event_call=None,
        user: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> bool:
        """Ask once per chat whether to use public or private ALLRIS access."""
        if not self.valves.login_enabled:
            return False

        cached = self._get_chat_access_choice(user, metadata)
        if cached is not None:
            await events.status(
                "🔐 Nutze für diesen Chat weiterhin den nicht öffentlichen ALLRIS-Bereich."
                if cached
                else "🌐 Nutze für diesen Chat weiterhin den öffentlichen ALLRIS-Bereich."
            )
            return cached

        if not event_call:
            await events.status(
                "ℹ️ Keine interaktive Bereichsauswahl verfügbar – nutze öffentlichen ALLRIS-Bereich."
            )
            self._save_chat_access_choice(user, metadata, False)
            return False

        has_private_session = False
        session = self._get_user_session(user)
        if session:
            expires_at = float(session.get("expires_at") or 0)
            session_base_url = session.get("base_url") or ""
            has_private_session = (
                expires_at > time.time()
                and session_base_url == self.valves.private_base_url.rstrip("/")
            )

        message = (
            "Soll der nicht öffentliche ALLRIS-Bereich durchsucht werden?\n\n"
            "Bestätigen: nicht öffentlicher Bereich mit Login/private_base_url.\n"
            "Abbrechen: öffentlicher Bereich ohne Login/public_base_url."
        )
        if has_private_session:
            message += "\n\nFür den nicht öffentlichen Bereich ist bereits eine gültige Session vorhanden."

        response = await event_call(
            {
                "type": "confirmation",
                "data": {
                    "title": "ALLRIS-Zugriffsbereich auswählen",
                    "message": message,
                },
            }
        )
        use_private = self._event_call_bool(response)
        self._save_chat_access_choice(user, metadata, use_private)
        await events.status(
            "🔐 Nicht öffentlicher ALLRIS-Bereich für diesen Chat gespeichert."
            if use_private
            else "🌐 Öffentlicher ALLRIS-Bereich für diesen Chat gespeichert."
        )
        return use_private

    def _get_chat_access_choice(
        self, user: Optional[dict], metadata: Optional[dict]
    ) -> Optional[bool]:
        chat_key = self._chat_key(user, metadata)
        if not chat_key:
            return None

        if isinstance(user, dict):
            user_choices = user.get("allris_access_choice_by_chat")
            if isinstance(user_choices, dict) and chat_key in user_choices:
                return bool(user_choices[chat_key])

        if chat_key in self._access_choice_store:
            return bool(self._access_choice_store[chat_key])
        return None

    def _save_chat_access_choice(
        self, user: Optional[dict], metadata: Optional[dict], use_private: bool
    ) -> None:
        chat_key = self._chat_key(user, metadata)
        if not chat_key:
            return
        self._access_choice_store[chat_key] = bool(use_private)
        if isinstance(user, dict):
            try:
                choices = user.setdefault("allris_access_choice_by_chat", {})
                if isinstance(choices, dict):
                    choices[chat_key] = bool(use_private)
            except Exception:
                pass

    def _chat_key(self, user: Optional[dict], metadata: Optional[dict]) -> str:
        chat_id = ""
        if isinstance(metadata, dict):
            chat_id = str(
                metadata.get("chat_id")
                or metadata.get("chatId")
                or metadata.get("conversation_id")
                or metadata.get("session_id")
                or ""
            )
            chat = metadata.get("chat")
            if not chat_id and isinstance(chat, dict):
                chat_id = str(chat.get("id") or "")
        if not chat_id:
            return ""
        user_key = self._user_key(user) or "anonymous"
        return f"{user_key}:{chat_id}"

    def _event_call_bool(self, response: Any) -> bool:
        if isinstance(response, bool):
            return response
        if isinstance(response, dict):
            for key in ("confirmed", "confirm", "value", "result", "ok"):
                value = response.get(key)
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    return value.strip().lower() in (
                        "true",
                        "yes",
                        "ja",
                        "1",
                        "ok",
                        "confirmed",
                    )
            data = response.get("data")
            if isinstance(data, dict):
                for key in ("confirmed", "confirm", "value", "result", "ok"):
                    value = data.get(key)
                    if isinstance(value, bool):
                        return value
                    if isinstance(value, str):
                        return value.strip().lower() in (
                            "true",
                            "yes",
                            "ja",
                            "1",
                            "ok",
                            "confirmed",
                        )
        if isinstance(response, str):
            return response.strip().lower() in (
                "true",
                "yes",
                "ja",
                "1",
                "ok",
                "confirmed",
            )
        return False

    def _get_user_valves(self, user: Optional[dict]) -> Optional["Tools.UserValves"]:
        if not user:
            return None
        raw = user.get("valves") if isinstance(user, dict) else None
        if isinstance(raw, self.UserValves):
            return raw
        if isinstance(raw, dict):
            try:
                return self.UserValves(**raw)
            except Exception:
                return None
        return None

    def _effective_limit(self, requested: int, user_valves: Optional["Tools.UserValves"]) -> int:
        try:
            requested_int = int(requested)
        except Exception:
            requested_int = user_valves.result_limit if user_valves else 5
        user_limit = user_valves.result_limit if user_valves else requested_int
        return max(1, min(requested_int, user_limit, self.valves.search_max_results))
