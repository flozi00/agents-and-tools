"""
title: TANSS Read-Only API
description: Read-only OpenWebUI tool for TANSS ticket, company, employee, and search endpoints.
author: flozi00
version: 0.1.8
requirements: requests
"""

import base64
import html
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from pydantic import BaseModel, Field


def get_env_value(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value.strip()
    return ""


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default_factory=lambda: get_env_value(
                "TANSS_URL",
                "TANSS_BASE_URL",
                "TANSS_API_URL",
            ),
            description="TANSS base URL, e.g. https://your-tanss.example.com",
        )
        username: str = Field(
            default_factory=lambda: get_env_value(
                "TANSS_USERNAME",
                "TANSS_USER",
                "TANSS_LOGIN",
            ),
            description="TANSS username / login name",
        )
        password: str = Field(
            default_factory=lambda: get_env_value(
                "TANSS_PASSWORD",
                "TANSS_PASSWORT",
                "TANSS_PASS",
            ),
            description="TANSS password",
        )
        request_timeout_seconds: int = Field(
            default=int(os.getenv("TANSS_REQUEST_TIMEOUT_SECONDS", "30")),
            description="HTTP timeout in seconds",
        )
        auth_mode: str = Field(
            default=(os.getenv("TANSS_AUTH_MODE", "auto") or "auto").strip().lower(),
            description="Auth mode: auto, api_token, or web_session",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._api_token: str = ""
        self._api_token_expires_at: float = 0
        self._login_context: Dict[str, Any] = {}
        self._http_session = requests.Session()

    def _user_agent(self) -> str:
        return "OpenWebUI-TANSS-Tool/0.1.5"

    def _normalized_auth_mode(self) -> str:
        auth_mode = (self.valves.auth_mode or "auto").strip().lower()
        if auth_mode not in {"auto", "api_token", "web_session"}:
            raise ValueError(
                "Invalid TANSS auth_mode. Allowed values: auto, api_token, web_session"
            )
        return auth_mode

    def _assert_config(self) -> None:
        missing = []
        if not self.valves.base_url.strip():
            missing.append("TANSS_URL")
        if not self.valves.username.strip():
            missing.append("TANSS_USERNAME")
        if not self.valves.password:
            missing.append("TANSS_PASSWORD")

        if missing:
            raise Exception(
                "TANSS is not fully configured. Missing values: "
                + ", ".join(missing)
                + f" ({self._debug_context()})"
            )

    def _normalize_base_url(self) -> str:
        base_url = self.valves.base_url.strip().rstrip("/")
        if base_url.endswith("/api/v1"):
            base_url = base_url[: -len("/api/v1")]
        return base_url

    def _normalize_api_base_url(self, value: str) -> str:
        base_url = (value or "").strip().rstrip("/")
        if not base_url:
            return ""
        if base_url.endswith("/api/v1"):
            return base_url
        if base_url.endswith("/backend"):
            return base_url
        return base_url

    def _decode_base64_value(self, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            return ""
        padding = (-len(normalized)) % 4
        normalized += "=" * padding
        try:
            return base64.b64decode(normalized).decode("utf-8").strip()
        except Exception:
            return ""

    def _extract_frontend_api_context(self, html: str) -> Dict[str, str]:
        match = re.search(
            r"api:\s*\{\s*key:\s*'(?P<key>[^']+)'\s*,\s*url:\s*'(?P<url>[^']+)'",
            html or "",
            re.DOTALL,
        )
        if not match:
            return {}

        api_token = (match.group("key") or "").strip()
        encoded_url = (match.group("url") or "").strip()
        api_base_url = self._normalize_api_base_url(
            self._decode_base64_value(encoded_url)
        )
        if not api_token or not api_base_url:
            return {}

        return {
            "api_token": api_token,
            "api_base_url": api_base_url,
        }

    def _fetch_frontend_api_context(self, base_url: str) -> Dict[str, str]:
        page_candidates = [
            f"{base_url}/index.php?section=internFirma",
            f"{base_url}/index.php?section=bug&initFirma=1&page=1",
            f"{base_url}/",
        ]

        for page_url in page_candidates:
            try:
                response = self._http_session.get(
                    page_url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Referer": f"{base_url}/index.php?section=login",
                        "User-Agent": self._user_agent(),
                    },
                    timeout=self.valves.request_timeout_seconds,
                    allow_redirects=True,
                )
            except requests.RequestException:
                continue

            if not response.ok:
                continue

            api_context = self._extract_frontend_api_context(response.text)
            if api_context:
                return api_context

        return {}

    def _resolve_request_target(
        self, path: str, login_context: Dict[str, Any]
    ) -> Tuple[str, str]:
        normalized_path = path if path.startswith("/") else f"/{path}"
        api_base_url = self._normalize_api_base_url(
            str(login_context.get("api_base_url") or "")
        )
        if api_base_url:
            if api_base_url.endswith("/api/v1") and normalized_path.startswith(
                "/api/v1/"
            ):
                normalized_path = normalized_path[len("/api/v1") :]
            elif api_base_url.endswith("/api/v1") and normalized_path == "/api/v1":
                normalized_path = "/"
            return api_base_url, normalized_path
        return self._normalize_base_url(), normalized_path

    def _debug_context(self) -> str:
        base_url = self._normalize_base_url() or "<empty>"
        username = self.valves.username.strip() or "<empty>"
        auth_mode = self._normalized_auth_mode()
        actual_auth_mode = self._login_context.get("auth_mode") or "<none>"
        login_source = self._login_context.get("login_source") or "<none>"
        api_base_url = self._login_context.get("api_base_url") or "<none>"
        return (
            f"base_url={base_url}, username={username}, auth_mode={auth_mode}, "
            f"actual_auth_mode={actual_auth_mode}, login_source={login_source}, "
            f"api_base_url={api_base_url}"
        )

    def _reset_auth_cache(self) -> None:
        self._api_token = ""
        self._api_token_expires_at = 0
        self._login_context = {}
        self._http_session = requests.Session()

    def _extract_error(self, response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip() or "Unknown TANSS error"

        meta = payload.get("meta") or {}
        content = payload.get("content") or {}
        detail = content.get("detailMessage")
        text = meta.get("text")
        return " | ".join(part for part in [text, detail] if part) or str(payload)

    def _login_via_api_token(self, force_refresh: bool = False) -> Dict[str, Any]:
        self._assert_config()

        now = time.time()
        if (
            not force_refresh
            and self._login_context.get("auth_mode") == "api_token"
            and self._api_token
            and now < self._api_token_expires_at
        ):
            return self._login_context

        try:
            response = requests.post(
                f"{self._normalize_base_url()}/api/v1/login",
                json={
                    "username": self.valves.username.strip(),
                    "password": self.valves.password,
                    "token": "",
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": self._user_agent(),
                },
                timeout=self.valves.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise Exception(
                f"TANSS api_token login request failed: {exc} ({self._debug_context()})"
            ) from exc

        if not response.ok:
            raise Exception(
                f"TANSS api_token login failed ({response.status_code}): "
                f"{self._extract_error(response)} ({self._debug_context()})"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise Exception(
                f"TANSS api_token login returned invalid JSON. ({self._debug_context()})"
            ) from exc

        content = payload.get("content") or {}
        api_token = (content.get("apiKey") or "").strip()
        expire = content.get("expire")
        employee_id = content.get("employeeId")
        employee_type = content.get("employeeType")

        if not api_token:
            raise Exception(
                "TANSS api_token login succeeded but did not return an apiKey. "
                f"({self._debug_context()})"
            )

        self._api_token = api_token
        self._api_token_expires_at = (
            float(expire) - 60 if isinstance(expire, (int, float)) else now + 4 * 3600
        )
        self._login_context = {
            "auth_mode": "api_token",
            "login_source": "api_token",
            "api_token": self._api_token,
            "token_expires_at": self._api_token_expires_at,
            "employee_id": employee_id,
            "employee_type": employee_type,
            "base_url": self._normalize_base_url(),
            "username": self.valves.username.strip(),
        }
        return self._login_context

    def _login_via_web_session(self, force_refresh: bool = False) -> Dict[str, Any]:
        self._assert_config()

        if (
            not force_refresh
            and self._login_context.get("login_source")
            in {"web_session", "web_session_page_config"}
            and self._http_session.cookies.get_dict()
        ):
            return self._login_context

        self._http_session = requests.Session()
        base_url = self._normalize_base_url()
        login_url = f"{base_url}/index.php?section=login"

        try:
            self._http_session.get(
                login_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "User-Agent": self._user_agent(),
                },
                timeout=self.valves.request_timeout_seconds,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise Exception(
                f"TANSS web_session bootstrap failed: {exc} ({self._debug_context()})"
            ) from exc

        try:
            response = self._http_session.post(
                login_url,
                json={
                    "username": self.valves.username.strip(),
                    "password": self.valves.password,
                    "token": "",
                },
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "Origin": base_url,
                    "Referer": login_url,
                    "User-Agent": self._user_agent(),
                },
                timeout=self.valves.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise Exception(
                f"TANSS web_session login request failed: {exc} ({self._debug_context()})"
            ) from exc

        if not response.ok:
            raise Exception(
                f"TANSS web_session login failed ({response.status_code}): "
                f"{self._extract_error(response)} ({self._debug_context()})"
            )

        payload: Dict[str, Any] = {}
        try:
            candidate_payload = response.json()
            if isinstance(candidate_payload, dict):
                payload = candidate_payload
        except ValueError:
            payload = {}

        content = payload.get("content") or {}
        api_token = (content.get("apiKey") or "").strip()
        employee_id = content.get("employeeId")
        employee_type = content.get("employeeType")

        if api_token:
            now = time.time()
            expire = content.get("expire")
            self._api_token = api_token
            self._api_token_expires_at = (
                float(expire) - 60
                if isinstance(expire, (int, float))
                else now + 4 * 3600
            )
            self._login_context = {
                "auth_mode": "api_token",
                "login_source": "web_session",
                "api_token": self._api_token,
                "token_expires_at": self._api_token_expires_at,
                "employee_id": employee_id,
                "employee_type": employee_type,
                "base_url": base_url,
                "api_base_url": f"{base_url}/api/v1",
                "username": self.valves.username.strip(),
            }
            return self._login_context

        cookie_names = sorted(self._http_session.cookies.get_dict().keys())
        if not cookie_names:
            raise Exception(
                "TANSS web_session login succeeded without usable session cookies. "
                f"({self._debug_context()})"
            )

        frontend_api_context = self._fetch_frontend_api_context(base_url)
        frontend_api_token = frontend_api_context.get("api_token", "").strip()
        frontend_api_base_url = frontend_api_context.get("api_base_url", "").strip()
        if frontend_api_token and frontend_api_base_url:
            self._api_token = frontend_api_token
            self._api_token_expires_at = time.time() + 4 * 3600
            self._login_context = {
                "auth_mode": "api_token",
                "login_source": "web_session_page_config",
                "api_token": self._api_token,
                "token_expires_at": self._api_token_expires_at,
                "employee_id": employee_id,
                "employee_type": employee_type,
                "base_url": base_url,
                "api_base_url": frontend_api_base_url,
                "username": self.valves.username.strip(),
                "session_cookie_names": cookie_names,
            }
            return self._login_context

        self._login_context = {
            "auth_mode": "web_session",
            "login_source": "web_session",
            "api_token": "",
            "token_expires_at": None,
            "employee_id": employee_id,
            "employee_type": employee_type,
            "base_url": base_url,
            "api_base_url": "",
            "username": self.valves.username.strip(),
            "session_cookie_names": cookie_names,
        }
        return self._login_context

    def _perform_login(self, force_refresh: bool = False) -> Dict[str, Any]:
        requested_auth_mode = self._normalized_auth_mode()
        strategies = (
            ["api_token", "web_session"]
            if requested_auth_mode == "auto"
            else [requested_auth_mode]
        )

        errors: List[str] = []
        for strategy in strategies:
            try:
                if strategy == "api_token":
                    return self._login_via_api_token(force_refresh=force_refresh)
                return self._login_via_web_session(force_refresh=force_refresh)
            except Exception as exc:
                errors.append(f"{strategy}: {exc}")

        raise Exception("TANSS login failed. " + " | ".join(errors))

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        retry_on_auth_failure: bool = True,
    ) -> Dict[str, Any]:
        allowed_methods = {"GET", "PUT"}
        normalized_method = method.upper()
        if normalized_method not in allowed_methods:
            raise ValueError(
                f"Method {normalized_method} is not allowed. This tool is read-only."
            )

        login_context = self._perform_login()
        request_base_url, request_path = self._resolve_request_target(
            path, login_context
        )
        uses_web_session = str(login_context.get("login_source") or "").startswith(
            "web_session"
        )
        normalized_base_url = self._normalize_base_url()

        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": self._user_agent(),
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if login_context.get("auth_mode") == "api_token":
            headers["apiToken"] = str(login_context.get("api_token") or "")
        if uses_web_session:
            headers["Origin"] = normalized_base_url
            headers["Referer"] = f"{normalized_base_url}/"

        client = (
            self._http_session
            if uses_web_session or login_context.get("auth_mode") != "api_token"
            else requests
        )

        try:
            response = client.request(
                method=normalized_method,
                url=f"{request_base_url}{request_path}",
                headers=headers,
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json_body,
                timeout=self.valves.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise Exception(f"TANSS request failed for {path}: {exc}") from exc

        if retry_on_auth_failure and response.status_code in {401, 403}:
            self._reset_auth_cache()
            self._perform_login(force_refresh=True)
            return self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                retry_on_auth_failure=False,
            )

        if not response.ok:
            raise Exception(
                f"TANSS request failed ({response.status_code}) for {path}: "
                f"{self._extract_error(response)} ({self._debug_context()})"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise Exception(f"TANSS returned non-JSON data for {path}.") from exc

    def _parse_search_areas(self, areas: str) -> List[str]:
        valid_areas = {"COMPANY", "EMPLOYEE", "TICKET"}
        parsed_areas = [
            area.strip().upper() for area in (areas or "").split(",") if area.strip()
        ]

        if not parsed_areas:
            parsed_areas = ["COMPANY", "EMPLOYEE", "TICKET"]

        invalid_areas = [area for area in parsed_areas if area not in valid_areas]
        if invalid_areas:
            raise ValueError(
                "Invalid search areas: "
                + ", ".join(invalid_areas)
                + ". Allowed values: COMPANY, EMPLOYEE, TICKET"
            )

        return parsed_areas

    def _stringify_history_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value.strip()
        return str(value)

    def _normalize_history_text(self, value: Any) -> str:
        text = self._stringify_history_value(value)
        if not text:
            return ""

        text = html.unescape(text)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(
            r"</?(?:p|div|li|tr|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return "\n".join(line.strip() for line in text.split("\n") if line.strip())

    def _format_history_timestamp(self, *candidates: Any) -> str:
        for candidate in candidates:
            if candidate in (None, ""):
                continue
            if isinstance(candidate, (int, float)):
                if candidate > 1_000_000_000:
                    try:
                        return time.strftime(
                            "%Y-%m-%d %H:%M:%S UTC", time.gmtime(float(candidate))
                        )
                    except (OverflowError, ValueError):
                        return str(candidate)
                return str(candidate)

            text = self._stringify_history_value(candidate)
            if text:
                return text

        return "unknown"

    def _format_history_people(self, values: List[Dict[str, Any]]) -> str:
        entries = []
        for value in values or []:
            address = self._stringify_history_value(
                value.get("emailAddress") or value.get("email")
            )
            name = self._stringify_history_value(value.get("name"))
            method = self._stringify_history_value(value.get("method")).upper()
            status = self._stringify_history_value(value.get("status"))

            label = name or address or "unknown"
            if address and address.lower() != label.lower():
                label = f"{label} <{address}>"
            if method:
                label = f"{method}: {label}"
            if status:
                label = f"{label} [{status}]"
            entries.append(label)

        return ", ".join(entry for entry in entries if entry) or "none"

    def _format_history_attachments(self, values: List[Dict[str, Any]]) -> str:
        items = []
        for value in values or []:
            name = self._stringify_history_value(
                value.get("name")
                or value.get("fileName")
                or value.get("filename")
                or value.get("originalFileName")
            )
            if not name:
                continue
            size = value.get("size")
            if isinstance(size, (int, float)) and size > 0:
                items.append(f"{name} ({int(size)} bytes)")
            else:
                items.append(name)
        return ", ".join(items) or "none"

    def _collect_history_generic_fields(
        self, item: Dict[str, Any], excluded_keys: set[str]
    ) -> List[str]:
        lines = []
        for key, value in item.items():
            if key in excluded_keys or value in (None, "", [], {}):
                continue

            if isinstance(value, list):
                serialized_items = [
                    self._normalize_history_text(entry) for entry in value
                ]
                serialized_items = [entry for entry in serialized_items if entry]
                if serialized_items:
                    lines.append(f"- {key}: {'; '.join(serialized_items)}")
                continue

            if isinstance(value, dict):
                serialized = ", ".join(
                    f"{sub_key}={self._normalize_history_text(sub_value)}"
                    for sub_key, sub_value in value.items()
                    if sub_value not in (None, "", [], {})
                )
                if serialized:
                    lines.append(f"- {key}: {serialized}")
                continue

            serialized = self._normalize_history_text(value)
            if serialized:
                lines.append(f"- {key}: {serialized}")

        return lines

    def _format_history_mail(self, mail: Dict[str, Any], index: int) -> str:
        title = self._normalize_history_text(mail.get("subject")) or "No subject"
        sender = self._normalize_history_text(
            mail.get("senderName") or mail.get("senderEMail") or mail.get("senderId")
        )
        sent_at = self._format_history_timestamp(
            mail.get("sentDate"),
            mail.get("date"),
            next(
                (
                    header.get("headerValue")
                    for header in (mail.get("headers") or [])
                    if self._stringify_history_value(header.get("headerName")).lower()
                    == "date"
                ),
                None,
            ),
        )
        direction = "inbound" if mail.get("inbound") else "outbound"
        internal = "internal" if mail.get("internal") else "external"
        body = self._normalize_history_text(
            mail.get("bodyPlain") or mail.get("bodyHtml")
        )
        if not body:
            body = "No body content available."

        lines = [
            f"### Mail {index}: {title}",
            f"- id: {mail.get('id', 'unknown')}",
            f"- when: {sent_at}",
            f"- from: {sender or 'unknown'}",
            f"- direction: {direction}",
            f"- visibility: {internal}",
            f"- to: {self._format_history_people(mail.get('receivers') or [])}",
            f"- attachments: {self._format_history_attachments(mail.get('attachments') or [])}",
            "- body:",
            "```text",
            body,
            "```",
        ]

        generic_lines = self._collect_history_generic_fields(
            mail,
            {
                "id",
                "subject",
                "senderName",
                "senderEMail",
                "senderId",
                "sentDate",
                "date",
                "inbound",
                "internal",
                "receivers",
                "attachments",
                "bodyPlain",
                "bodyHtml",
                "headers",
            },
        )
        if generic_lines:
            lines.append("- additional fields:")
            lines.extend(generic_lines)

        return "\n".join(lines)

    def _format_history_generic_item(
        self,
        section_label: str,
        item: Dict[str, Any],
        index: int,
    ) -> str:
        item_id = item.get("id") or item.get("historyId") or item.get("supportId")
        title = self._normalize_history_text(
            item.get("subject")
            or item.get("title")
            or item.get("name")
            or item.get("type")
            or item.get("comment")
            or item.get("text")
        )
        if not title:
            title = f"Entry {index}"

        author = self._normalize_history_text(
            item.get("employeeName")
            or item.get("employee")
            or item.get("author")
            or item.get("createdBy")
            or item.get("senderName")
        )
        timestamp = self._format_history_timestamp(
            item.get("date"),
            item.get("createDate"),
            item.get("createdAt"),
            item.get("time"),
            item.get("timestamp"),
        )
        body = self._normalize_history_text(
            item.get("bodyPlain")
            or item.get("text")
            or item.get("comment")
            or item.get("description")
            or item.get("note")
            or item.get("message")
        )

        lines = [f"### {section_label} {index}: {title}"]
        if item_id not in (None, ""):
            lines.append(f"- id: {item_id}")
        if timestamp != "unknown":
            lines.append(f"- when: {timestamp}")
        if author:
            lines.append(f"- author: {author}")
        if body:
            lines.extend(
                [
                    "- body:",
                    "```text",
                    body,
                    "```",
                ]
            )

        generic_lines = self._collect_history_generic_fields(
            item,
            {
                "id",
                "historyId",
                "supportId",
                "subject",
                "title",
                "name",
                "type",
                "comment",
                "text",
                "description",
                "note",
                "message",
                "bodyPlain",
                "employeeName",
                "employee",
                "author",
                "createdBy",
                "senderName",
                "date",
                "createDate",
                "createdAt",
                "time",
                "timestamp",
            },
        )
        if generic_lines:
            lines.append("- additional fields:")
            lines.extend(generic_lines)

        return "\n".join(lines)

    def _format_ticket_history_markdown(
        self, ticket_id: int, response: Dict[str, Any]
    ) -> str:
        meta = response.get("meta") or {}
        content = response.get("content") or {}
        mails = content.get("mails") or []
        comments = content.get("comments") or []
        supports = content.get("supports") or []

        lines = [
            f"# TANSS Ticket History {ticket_id}",
            "",
            f"- status: {self._stringify_history_value(meta.get('text')) or 'unknown'}",
            f"- mails: {len(mails)}",
            f"- comments: {len(comments)}",
            f"- supports: {len(supports)}",
        ]

        if mails:
            lines.extend(["", "## Mails", ""])
            for index, mail in enumerate(mails, start=1):
                lines.append(self._format_history_mail(mail, index))
                lines.append("")

        if comments:
            lines.extend(["", "## Comments", ""])
            for index, comment in enumerate(comments, start=1):
                lines.append(
                    self._format_history_generic_item("Comment", comment, index)
                )
                lines.append("")

        if supports:
            lines.extend(["", "## Supports", ""])
            for index, support in enumerate(supports, start=1):
                lines.append(
                    self._format_history_generic_item("Support", support, index)
                )
                lines.append("")

        extra_sections = []
        for key, value in content.items():
            if key in {"mails", "comments", "supports"} or value in (None, "", [], {}):
                continue
            extra_sections.append((key, value))

        if extra_sections:
            lines.extend(["", "## Other History Data", ""])
            for key, value in extra_sections:
                lines.append(f"### {key}")
                if isinstance(value, list):
                    if all(isinstance(entry, dict) for entry in value):
                        for index, entry in enumerate(value, start=1):
                            lines.append(
                                self._format_history_generic_item(
                                    key[:-1].capitalize() or key.capitalize(),
                                    entry,
                                    index,
                                )
                            )
                            lines.append("")
                    else:
                        normalized_items = [
                            self._normalize_history_text(entry)
                            for entry in value
                            if entry not in (None, "")
                        ]
                        for item in normalized_items:
                            lines.append(f"- {item}")
                        lines.append("")
                elif isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        normalized = self._normalize_history_text(sub_value)
                        if normalized:
                            lines.append(f"- {sub_key}: {normalized}")
                    lines.append("")
                else:
                    normalized = self._normalize_history_text(value)
                    if normalized:
                        lines.extend(["```text", normalized, "```", ""])

        cleaned_lines = []
        previous_blank = False
        for line in lines:
            is_blank = line == ""
            if is_blank and previous_blank:
                continue
            cleaned_lines.append(line)
            previous_blank = is_blank

        return "\n".join(cleaned_lines).strip()

    def _resolve_ticket_linked_entity_name(
        self,
        linked_entities: Dict[str, Any],
        entity_group: str,
        entity_id: Any,
    ) -> str:
        if entity_id in (None, ""):
            return ""

        group = linked_entities.get(entity_group) or {}
        entity = group.get(str(entity_id)) or group.get(entity_id)
        if isinstance(entity, dict):
            for key in ("name", "title", "label", "fullName"):
                value = self._normalize_history_text(entity.get(key))
                if value:
                    return value
        elif entity not in (None, "", [], {}):
            return self._normalize_history_text(entity)

        return ""

    def _format_ticket_reference(
        self,
        linked_entities: Dict[str, Any],
        entity_group: str,
        entity_id: Any,
    ) -> str:
        resolved = self._resolve_ticket_linked_entity_name(
            linked_entities, entity_group, entity_id
        )
        if resolved:
            return resolved
        if entity_id in (None, "", 0, "0"):
            return ""
        return str(entity_id)

    def _normalize_ticket_content_text(self, value: Any) -> str:
        text = self._normalize_history_text(value)
        if not text:
            return ""

        lines = [line.strip() for line in text.split("\n")]
        cleaned_lines = []
        index = 0

        while index < len(lines):
            line = re.sub(r"\[cid:[^\]]+\]", "", lines[index]).strip()
            if not line:
                index += 1
                continue

            lowered = line.lower()
            if lowered.startswith(
                "achtung: diese e-mail stammt von einem externen absender"
            ):
                index += 1
                continue
            if lowered.startswith("hinweis auf vertraulichkeit:") or lowered.startswith(
                "confidentiality-note:"
            ):
                break
            if re.fullmatch(
                r"(?:https?://\S+|www\.\S+)(?:\s+(?:https?://\S+|www\.\S+))*", line
            ):
                index += 1
                continue

            if line in {"*", "-", "•"} and index + 1 < len(lines):
                next_line = re.sub(r"\[cid:[^\]]+\]", "", lines[index + 1]).strip()
                if next_line:
                    cleaned_lines.append(f"- {next_line}")
                    index += 2
                    continue

            cleaned_lines.append(line)
            index += 1

        return "\n".join(cleaned_lines).strip()

    def _collect_ticket_additional_fields(
        self, ticket: Dict[str, Any], excluded_keys: set[str]
    ) -> List[str]:
        lines = []
        for key, value in ticket.items():
            if key in excluded_keys or value in (None, "", [], {}):
                continue
            if value is False or value == 0:
                continue
            if isinstance(value, str) and value.strip().upper() in {"NO", "NONE"}:
                continue

            if isinstance(value, list):
                if all(isinstance(entry, dict) for entry in value):
                    lines.append(f"- {key}: {len(value)} item(s)")
                else:
                    serialized_items = [
                        self._normalize_history_text(entry)
                        for entry in value
                        if entry not in (None, "")
                    ]
                    serialized_items = [entry for entry in serialized_items if entry]
                    if serialized_items:
                        lines.append(f"- {key}: {'; '.join(serialized_items)}")
                continue

            if isinstance(value, dict):
                serialized_parts = []
                for sub_key, sub_value in value.items():
                    if sub_value in (None, "", [], {}, 0, False):
                        continue
                    normalized = self._normalize_history_text(sub_value)
                    if normalized:
                        serialized_parts.append(f"{sub_key}={normalized}")
                if serialized_parts:
                    lines.append(f"- {key}: {', '.join(serialized_parts)}")
                continue

            normalized = self._normalize_history_text(value)
            if normalized:
                lines.append(f"- {key}: {normalized}")

        return lines

    def _format_ticket_markdown(self, ticket_id: int, response: Dict[str, Any]) -> str:
        meta = response.get("meta") or {}
        properties = meta.get("properties") or {}
        linked_entities = meta.get("linkedEntities") or {}
        ticket = response.get("content") or {}

        resolved_ticket_id = ticket.get("id") or ticket_id
        title = (
            self._normalize_history_text(ticket.get("title"))
            or f"Ticket {resolved_ticket_id}"
        )
        status = self._format_ticket_reference(
            linked_entities, "ticketStates", ticket.get("statusId")
        )
        ticket_type = self._format_ticket_reference(
            linked_entities, "ticketTypes", ticket.get("typeId")
        )
        order_by = self._format_ticket_reference(
            linked_entities, "orderBys", ticket.get("orderById")
        )
        company = self._format_ticket_reference(
            linked_entities, "companies", ticket.get("companyId")
        )
        assignee = self._format_ticket_reference(
            linked_entities, "employees", ticket.get("assignedToEmployeeId")
        )
        department = self._format_ticket_reference(
            linked_entities, "departments", ticket.get("assignedToDepartmentId")
        )
        contract = self._format_ticket_reference(
            linked_entities, "contracts", ticket.get("contractId")
        )
        phase = self._format_ticket_reference(
            linked_entities, "phases", ticket.get("phaseId")
        )
        cost_center = self._format_ticket_reference(
            linked_entities, "costCenters", ticket.get("costCenterId")
        )
        linked_ticket = self._format_ticket_reference(
            linked_entities, "tickets", ticket.get("linkId")
        )

        body = self._normalize_ticket_content_text(ticket.get("content"))
        internal_content = self._normalize_ticket_content_text(
            ticket.get("internalContent")
        )

        lines = [f"# TANSS Ticket {resolved_ticket_id}: {title}", ""]
        summary_fields = [
            ("status", status),
            ("type", ticket_type),
            ("created", self._format_history_timestamp(ticket.get("creationDate"))),
            (
                "due",
                (
                    self._format_history_timestamp(ticket.get("dueDate"))
                    if ticket.get("dueDate")
                    else ""
                ),
            ),
            (
                "deadline",
                (
                    self._format_history_timestamp(ticket.get("deadlineDate"))
                    if ticket.get("deadlineDate")
                    else ""
                ),
            ),
            ("priority", self._stringify_history_value(ticket.get("priority"))),
            ("attention", self._normalize_history_text(ticket.get("attention"))),
            ("order by", order_by),
            ("company", company),
            ("assigned employee", assignee),
            ("assigned department", department),
            ("contract", contract),
            ("phase", phase),
            ("cost center", cost_center),
            ("linked ticket", linked_ticket),
            (
                "editable",
                (
                    self._stringify_history_value(properties.get("editable"))
                    if properties.get("editable") is True
                    else ""
                ),
            ),
        ]
        for label, value in summary_fields:
            if value not in (None, ""):
                lines.append(f"- {label}: {value}")

        if (
            isinstance(ticket.get("numberOfDocuments"), (int, float))
            and ticket.get("numberOfDocuments") > 0
        ):
            lines.append(f"- documents: {int(ticket['numberOfDocuments'])}")

        if body:
            lines.extend(["", "## Request", "", "```text", body, "```"])

        if internal_content:
            lines.extend(
                ["", "## Internal Content", "", "```text", internal_content, "```"]
            )

        chats = ticket.get("chats") or []
        if chats:
            lines.extend(["", "## Chats", ""])
            for index, chat in enumerate(chats, start=1):
                if isinstance(chat, dict):
                    lines.append(self._format_history_generic_item("Chat", chat, index))
                else:
                    lines.append(f"- {self._normalize_history_text(chat)}")
                lines.append("")

        additional_fields = self._collect_ticket_additional_fields(
            ticket,
            {
                "id",
                "title",
                "content",
                "creationDate",
                "dueDate",
                "deadlineDate",
                "priority",
                "attention",
                "statusId",
                "typeId",
                "orderById",
                "companyId",
                "assignedToEmployeeId",
                "assignedToDepartmentId",
                "contractId",
                "phaseId",
                "costCenterId",
                "linkId",
                "numberOfDocuments",
                "internalContent",
                "chats",
            },
        )
        if additional_fields:
            lines.extend(["", "## Additional Fields", ""])
            lines.extend(additional_fields)

        cleaned_lines = []
        previous_blank = False
        for line in lines:
            is_blank = line == ""
            if is_blank and previous_blank:
                continue
            cleaned_lines.append(line)
            previous_blank = is_blank

        return "\n".join(cleaned_lines).strip()

    def test_login(
        self,
        force_refresh: bool = True,
        probe_endpoint: str = "",
        probe_method: str = "GET",
    ) -> Dict[str, Any]:
        """
        Verify TANSS login against the configured instance.

        By default this forces a fresh login request so the model can confirm
        access to the real configured TANSS instance instead of only reusing a
        cached token.

        This validates authentication only by default. To additionally verify a
        specific read endpoint, provide probe_endpoint, e.g.
        /api/v1/tickets/own.
        """
        login_context = self._perform_login(force_refresh=force_refresh)
        result = {
            "ok": True,
            "base_url": login_context.get("base_url"),
            "api_base_url": login_context.get("api_base_url"),
            "username": login_context.get("username"),
            "auth_mode": login_context.get("auth_mode"),
            "login_source": login_context.get("login_source"),
            "employee_id": login_context.get("employee_id"),
            "employee_type": login_context.get("employee_type"),
            "token_expires_at": login_context.get("token_expires_at"),
            "session_cookie_names": login_context.get("session_cookie_names", []),
            "force_refresh": force_refresh,
            "probe_endpoint": probe_endpoint or None,
            "probe_method": probe_method.upper(),
            "probe_ok": None,
        }

        normalized_probe_endpoint = (probe_endpoint or "").strip()
        if not normalized_probe_endpoint:
            result["probe_skipped"] = True
            return result

        probe_response = self._request(
            probe_method,
            normalized_probe_endpoint,
            retry_on_auth_failure=False,
        )
        content = probe_response.get("content")
        result["probe_skipped"] = False
        result["probe_ok"] = True
        if isinstance(content, list):
            result["probe_item_count"] = len(content)
        result["probe_result"] = probe_response

        return result

    def list_tickets(
        self, scope: str = "own", company_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Read-only ticket list access for TANSS.

        Allowed scopes:
        - own
        - general
        - company (requires company_id)
        - technician
        - repair
        - not_identified
        - projects
        - local_admin_overview
        - with_role
        """
        scope_map = {
            "own": "/api/v1/tickets/own",
            "general": "/api/v1/tickets/general",
            "company": f"/api/v1/tickets/company/{company_id}",
            "technician": "/api/v1/tickets/technician",
            "repair": "/api/v1/tickets/repair",
            "not_identified": "/api/v1/tickets/notIdentified",
            "projects": "/api/v1/tickets/projects",
            "local_admin_overview": "/api/v1/tickets/localAdminOverview",
            "with_role": "/api/v1/tickets/withRole",
        }

        normalized_scope = (scope or "").strip().lower()
        if normalized_scope == "company" and company_id is None:
            raise ValueError("company_id is required when scope='company'.")
        if normalized_scope not in scope_map:
            raise ValueError(
                "Invalid scope. Allowed values: " + ", ".join(scope_map.keys())
            )

        return self._request("GET", scope_map[normalized_scope])

    def get_ticket(self, ticket_id: int) -> str:
        """
        Get one TANSS ticket as a compact Markdown summary that is easier
        for LLMs to process.
        """
        response = self._request("GET", f"/api/v1/tickets/{ticket_id}")
        return self._format_ticket_markdown(ticket_id, response)

    def get_ticket_history(self, ticket_id: int) -> str:
        """
        Get TANSS ticket history including comments, supports, and mails
        as a compact Markdown summary that is easier for LLMs to process.
        """
        response = self._request("GET", f"/api/v1/tickets/history/{ticket_id}")
        return self._format_ticket_history_markdown(ticket_id, response)

    def list_ticket_documents(self, ticket_id: int) -> Dict[str, Any]:
        """
        List documents attached to a TANSS ticket.
        """
        return self._request("GET", f"/api/v1/tickets/{ticket_id}/documents")

    def get_ticket_document_link(
        self, ticket_id: int, document_id: int
    ) -> Dict[str, Any]:
        """
        Generate a temporary one-time download link for a TANSS ticket document.
        """
        return self._request(
            "GET", f"/api/v1/tickets/{ticket_id}/documents/{document_id}"
        )

    def list_company_employees(self, company_id: int) -> Dict[str, Any]:
        """
        List all employees assigned to a TANSS company.
        """
        return self._request("GET", f"/api/v1/companies/{company_id}/employees")

    def list_technicians(
        self, freelancer_company_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        List TANSS technicians. Optionally include freelancers for one company.
        """
        return self._request(
            "GET",
            "/api/v1/employees/technicians",
            params={"freelancerCompanyId": freelancer_company_id},
        )

    def global_search(
        self,
        query: str,
        areas: str = "COMPANY,EMPLOYEE,TICKET",
        company_max_results: int = 20,
        employee_max_results: int = 20,
        employee_company_id: Optional[int] = None,
        include_inactive_employees: bool = True,
        include_employee_categories: bool = False,
        include_employee_callbacks: bool = False,
        ticket_max_results: int = 20,
        ticket_preview_content_max_chars: int = 200,
        ticket_company_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run TANSS global search across companies, employees, and/or tickets.

        Note: TANSS implements this read-only search endpoint as HTTP PUT.
        """
        normalized_query = (query or "").strip()
        if not normalized_query:
            raise ValueError("query must not be empty.")

        payload = {
            "areas": self._parse_search_areas(areas),
            "query": normalized_query,
            "configs": {
                "company": {
                    "maxResults": company_max_results,
                },
                "employee": {
                    "maxResults": employee_max_results,
                    "companyId": employee_company_id,
                    "inactive": include_inactive_employees,
                    "categories": include_employee_categories,
                    "callbacks": include_employee_callbacks,
                },
                "ticket": {
                    "maxResults": ticket_max_results,
                    "previewContentMaxChars": ticket_preview_content_max_chars,
                    "companyId": ticket_company_id,
                },
            },
        }

        return self._request("PUT", "/api/v1/search", json_body=payload)
