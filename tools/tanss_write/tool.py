"""
title: TANSS Write API
description: Write tool for TANSS — create and update tickets, add comments, book time tracking entries (supports), and send ticket mails.
author: flozi00
version: 0.1.0
requirements: requests
"""

import base64
import re
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from pydantic import BaseModel, Field


def get_env_value(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value.strip()
    return ''


class Tools:
    class Valves(BaseModel):
        base_url: str = Field(
            default_factory=lambda: get_env_value(
                'TANSS_URL',
                'TANSS_BASE_URL',
                'TANSS_API_URL',
            ),
            description='TANSS base URL, e.g. https://your-tanss.example.com',
        )
        username: str = Field(
            default_factory=lambda: get_env_value(
                'TANSS_USERNAME',
                'TANSS_USER',
                'TANSS_LOGIN',
            ),
            description='TANSS username / login name',
        )
        password: str = Field(
            default_factory=lambda: get_env_value(
                'TANSS_PASSWORD',
                'TANSS_PASSWORT',
                'TANSS_PASS',
            ),
            description='TANSS password',
        )
        request_timeout_seconds: int = Field(
            default=int(os.getenv('TANSS_REQUEST_TIMEOUT_SECONDS', '30')),
            description='HTTP timeout in seconds',
        )
        auth_mode: str = Field(
            default=(os.getenv('TANSS_AUTH_MODE', 'auto') or 'auto').strip().lower(),
            description='Auth mode: auto, api_token, or web_session',
        )
        mail_recipient_domains: str = Field(
            default_factory=lambda: get_env_value('TANSS_MAIL_RECIPIENT_DOMAINS'),
            description=("Optional comma-separated allowlist of recipient email domains for send_ticket_mail (e.g. 'example.com,partner.de'). Empty means any recipient is allowed."),
        )

    def __init__(self):
        self.valves = self.Valves()
        self._api_token: str = ''
        self._api_token_expires_at: float = 0
        self._login_context: Dict[str, Any] = {}
        self._http_session = requests.Session()

    def _user_agent(self) -> str:
        return 'OpenWebUI-TANSS-Write-Tool/0.1.0'

    def _normalized_auth_mode(self) -> str:
        auth_mode = (self.valves.auth_mode or 'auto').strip().lower()
        if auth_mode not in {'auto', 'api_token', 'web_session'}:
            raise ValueError('Invalid TANSS auth_mode. Allowed values: auto, api_token, web_session')
        return auth_mode

    def _assert_config(self) -> None:
        missing = []
        if not self.valves.base_url.strip():
            missing.append('TANSS_URL')
        if not self.valves.username.strip():
            missing.append('TANSS_USERNAME')
        if not self.valves.password:
            missing.append('TANSS_PASSWORD')

        if missing:
            raise Exception('TANSS is not fully configured. Missing values: ' + ', '.join(missing) + f' ({self._debug_context()})')

    def _normalize_base_url(self) -> str:
        base_url = self.valves.base_url.strip().rstrip('/')
        if base_url.endswith('/api/v1'):
            base_url = base_url[: -len('/api/v1')]
        return base_url

    def _normalize_api_base_url(self, value: str) -> str:
        base_url = (value or '').strip().rstrip('/')
        return base_url

    def _decode_base64_value(self, value: str) -> str:
        normalized = (value or '').strip()
        if not normalized:
            return ''
        padding = (-len(normalized)) % 4
        normalized += '=' * padding
        try:
            return base64.b64decode(normalized).decode('utf-8').strip()
        except Exception:
            return ''

    def _extract_frontend_api_context(self, html: str) -> Dict[str, str]:
        match = re.search(
            r"api:\s*\{\s*key:\s*'(?P<key>[^']+)'\s*,\s*url:\s*'(?P<url>[^']+)'",
            html or '',
            re.DOTALL,
        )
        if not match:
            return {}

        api_token = (match.group('key') or '').strip()
        encoded_url = (match.group('url') or '').strip()
        api_base_url = self._normalize_api_base_url(self._decode_base64_value(encoded_url))
        if not api_token or not api_base_url:
            return {}

        return {
            'api_token': api_token,
            'api_base_url': api_base_url,
        }

    def _fetch_frontend_api_context(self, base_url: str) -> Dict[str, str]:
        page_candidates = [
            f'{base_url}/index.php?section=internFirma',
            f'{base_url}/index.php?section=bug&initFirma=1&page=1',
            f'{base_url}/',
        ]

        for page_url in page_candidates:
            try:
                response = self._http_session.get(
                    page_url,
                    headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Referer': f'{base_url}/index.php?section=login',
                        'User-Agent': self._user_agent(),
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

    def _resolve_request_target(self, path: str, login_context: Dict[str, Any]) -> Tuple[str, str]:
        normalized_path = path if path.startswith('/') else f'/{path}'
        api_base_url = self._normalize_api_base_url(str(login_context.get('api_base_url') or ''))
        if api_base_url:
            if api_base_url.endswith('/api/v1') and normalized_path.startswith('/api/v1/'):
                normalized_path = normalized_path[len('/api/v1') :]
            elif api_base_url.endswith('/api/v1') and normalized_path == '/api/v1':
                normalized_path = '/'
            return api_base_url, normalized_path
        return self._normalize_base_url(), normalized_path

    def _debug_context(self) -> str:
        base_url = self._normalize_base_url() or '<empty>'
        username = self.valves.username.strip() or '<empty>'
        auth_mode = self._normalized_auth_mode()
        actual_auth_mode = self._login_context.get('auth_mode') or '<none>'
        login_source = self._login_context.get('login_source') or '<none>'
        api_base_url = self._login_context.get('api_base_url') or '<none>'
        return f'base_url={base_url}, username={username}, auth_mode={auth_mode}, actual_auth_mode={actual_auth_mode}, login_source={login_source}, api_base_url={api_base_url}'

    def _reset_auth_cache(self) -> None:
        self._api_token = ''
        self._api_token_expires_at = 0
        self._login_context = {}
        self._http_session = requests.Session()

    def _extract_error(self, response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip() or 'Unknown TANSS error'

        meta = payload.get('meta') or {}
        content = payload.get('content') or {}
        detail = content.get('detailMessage')
        text = meta.get('text')
        return ' | '.join(part for part in [text, detail] if part) or str(payload)

    def _login_via_api_token(self, force_refresh: bool = False) -> Dict[str, Any]:
        self._assert_config()

        now = time.time()
        if not force_refresh and self._login_context.get('auth_mode') == 'api_token' and self._api_token and now < self._api_token_expires_at:
            return self._login_context

        try:
            response = requests.post(
                f'{self._normalize_base_url()}/api/v1/login',
                json={
                    'username': self.valves.username.strip(),
                    'password': self.valves.password,
                    'token': '',
                },
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'User-Agent': self._user_agent(),
                },
                timeout=self.valves.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise Exception(f'TANSS api_token login request failed: {exc} ({self._debug_context()})') from exc

        if not response.ok:
            raise Exception(f'TANSS api_token login failed ({response.status_code}): {self._extract_error(response)} ({self._debug_context()})')

        try:
            payload = response.json()
        except ValueError as exc:
            raise Exception(f'TANSS api_token login returned invalid JSON. ({self._debug_context()})') from exc

        content = payload.get('content') or {}
        api_token = (content.get('apiKey') or '').strip()
        expire = content.get('expire')
        employee_id = content.get('employeeId')
        employee_type = content.get('employeeType')

        if not api_token:
            raise Exception(f'TANSS api_token login succeeded but did not return an apiKey. ({self._debug_context()})')

        self._api_token = api_token
        self._api_token_expires_at = float(expire) - 60 if isinstance(expire, (int, float)) else now + 4 * 3600
        self._login_context = {
            'auth_mode': 'api_token',
            'login_source': 'api_token',
            'api_token': self._api_token,
            'token_expires_at': self._api_token_expires_at,
            'employee_id': employee_id,
            'employee_type': employee_type,
            'base_url': self._normalize_base_url(),
            'username': self.valves.username.strip(),
        }
        return self._login_context

    def _login_via_web_session(self, force_refresh: bool = False) -> Dict[str, Any]:
        self._assert_config()

        if not force_refresh and self._login_context.get('login_source') in {'web_session', 'web_session_page_config'} and self._http_session.cookies.get_dict():
            return self._login_context

        self._http_session = requests.Session()
        base_url = self._normalize_base_url()
        login_url = f'{base_url}/index.php?section=login'

        try:
            self._http_session.get(
                login_url,
                headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'User-Agent': self._user_agent(),
                },
                timeout=self.valves.request_timeout_seconds,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise Exception(f'TANSS web_session bootstrap failed: {exc} ({self._debug_context()})') from exc

        try:
            response = self._http_session.post(
                login_url,
                json={
                    'username': self.valves.username.strip(),
                    'password': self.valves.password,
                    'token': '',
                },
                headers={
                    'Accept': 'application/json, text/plain, */*',
                    'Content-Type': 'application/json',
                    'Origin': base_url,
                    'Referer': login_url,
                    'User-Agent': self._user_agent(),
                },
                timeout=self.valves.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise Exception(f'TANSS web_session login request failed: {exc} ({self._debug_context()})') from exc

        if not response.ok:
            raise Exception(f'TANSS web_session login failed ({response.status_code}): {self._extract_error(response)} ({self._debug_context()})')

        payload: Dict[str, Any] = {}
        try:
            candidate_payload = response.json()
            if isinstance(candidate_payload, dict):
                payload = candidate_payload
        except ValueError:
            payload = {}

        content = payload.get('content') or {}
        api_token = (content.get('apiKey') or '').strip()
        employee_id = content.get('employeeId')
        employee_type = content.get('employeeType')

        if api_token:
            now = time.time()
            expire = content.get('expire')
            self._api_token = api_token
            self._api_token_expires_at = float(expire) - 60 if isinstance(expire, (int, float)) else now + 4 * 3600
            self._login_context = {
                'auth_mode': 'api_token',
                'login_source': 'web_session',
                'api_token': self._api_token,
                'token_expires_at': self._api_token_expires_at,
                'employee_id': employee_id,
                'employee_type': employee_type,
                'base_url': base_url,
                'api_base_url': f'{base_url}/api/v1',
                'username': self.valves.username.strip(),
            }
            return self._login_context

        cookie_names = sorted(self._http_session.cookies.get_dict().keys())
        if not cookie_names:
            raise Exception(f'TANSS web_session login succeeded without usable session cookies. ({self._debug_context()})')

        frontend_api_context = self._fetch_frontend_api_context(base_url)
        frontend_api_token = frontend_api_context.get('api_token', '').strip()
        frontend_api_base_url = frontend_api_context.get('api_base_url', '').strip()
        if frontend_api_token and frontend_api_base_url:
            self._api_token = frontend_api_token
            self._api_token_expires_at = time.time() + 4 * 3600
            self._login_context = {
                'auth_mode': 'api_token',
                'login_source': 'web_session_page_config',
                'api_token': self._api_token,
                'token_expires_at': self._api_token_expires_at,
                'employee_id': employee_id,
                'employee_type': employee_type,
                'base_url': base_url,
                'api_base_url': frontend_api_base_url,
                'username': self.valves.username.strip(),
                'session_cookie_names': cookie_names,
            }
            return self._login_context

        self._login_context = {
            'auth_mode': 'web_session',
            'login_source': 'web_session',
            'api_token': '',
            'token_expires_at': None,
            'employee_id': employee_id,
            'employee_type': employee_type,
            'base_url': base_url,
            'api_base_url': '',
            'username': self.valves.username.strip(),
            'session_cookie_names': cookie_names,
        }
        return self._login_context

    def _perform_login(self, force_refresh: bool = False) -> Dict[str, Any]:
        requested_auth_mode = self._normalized_auth_mode()
        strategies = ['api_token', 'web_session'] if requested_auth_mode == 'auto' else [requested_auth_mode]

        errors: List[str] = []
        for strategy in strategies:
            try:
                if strategy == 'api_token':
                    return self._login_via_api_token(force_refresh=force_refresh)
                return self._login_via_web_session(force_refresh=force_refresh)
            except Exception as exc:
                errors.append(f'{strategy}: {exc}')

        raise Exception('TANSS login failed. ' + ' | '.join(errors))

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        retry_on_auth_failure: bool = True,
    ) -> Dict[str, Any]:
        allowed_methods = {'POST', 'PUT'}
        normalized_method = method.upper()
        if normalized_method not in allowed_methods:
            raise ValueError(f'Method {normalized_method} is not allowed. This tool only performs create/update operations; use the TANSS read tool for reads.')

        login_context = self._perform_login()
        request_base_url, request_path = self._resolve_request_target(path, login_context)
        uses_web_session = str(login_context.get('login_source') or '').startswith('web_session')
        normalized_base_url = self._normalize_base_url()

        headers = {
            'Accept': 'application/json, text/plain, */*',
            'User-Agent': self._user_agent(),
        }
        if json_body is not None:
            headers['Content-Type'] = 'application/json'
        if login_context.get('auth_mode') == 'api_token':
            headers['apiToken'] = str(login_context.get('api_token') or '')
        if uses_web_session:
            headers['Origin'] = normalized_base_url
            headers['Referer'] = f'{normalized_base_url}/'

        client = self._http_session if uses_web_session or login_context.get('auth_mode') != 'api_token' else requests

        try:
            response = client.request(
                method=normalized_method,
                url=f'{request_base_url}{request_path}',
                headers=headers,
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json_body,
                timeout=self.valves.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise Exception(f'TANSS request failed for {path}: {exc}') from exc

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
            raise Exception(f'TANSS request failed ({response.status_code}) for {path}: {self._extract_error(response)} ({self._debug_context()})')

        try:
            return response.json()
        except ValueError as exc:
            raise Exception(f'TANSS returned non-JSON data for {path}.') from exc

    def _build_payload(
        self,
        base: Dict[str, Any],
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {key: value for key, value in base.items() if value is not None}
        payload.update(extra_fields or {})
        return payload

    @staticmethod
    def _int_id(value: Any, name: str) -> int:
        # Path-parameter ids are interpolated into the request URL, so they must
        # be real integers — a string could inject a different endpoint (e.g.
        # "../supports/clear#") since POST/PUT are both allowed here.
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f'{name} must be an integer id, got {value!r}.')

    def _check_mail_recipients(self, *address_fields: str) -> None:
        allowed = {domain.strip().lower().lstrip('@') for domain in (self.valves.mail_recipient_domains or '').replace(';', ',').split(',') if domain.strip()}
        if not allowed:
            return
        for field in address_fields:
            for address in re.split(r'[,;]', field or ''):
                address = address.strip()
                if not address:
                    continue
                domain = address.rsplit('@', 1)[-1].lower() if '@' in address else ''
                if domain not in allowed:
                    raise ValueError(f'Recipient {address!r} is not in the allowed mail domains ({", ".join(sorted(allowed))}).')

    def test_login(self, force_refresh: bool = True) -> Dict[str, Any]:
        """
        Verify TANSS login against the configured instance without writing
        anything.
        """
        login_context = self._perform_login(force_refresh=force_refresh)
        return {
            'ok': True,
            'base_url': login_context.get('base_url'),
            'api_base_url': login_context.get('api_base_url'),
            'username': login_context.get('username'),
            'auth_mode': login_context.get('auth_mode'),
            'login_source': login_context.get('login_source'),
            'employee_id': login_context.get('employee_id'),
            'employee_type': login_context.get('employee_type'),
        }

    def create_ticket(
        self,
        company_id: int,
        title: str,
        content: str = '',
        remitter_id: Optional[int] = None,
        status_id: Optional[int] = None,
        type_id: Optional[int] = None,
        assigned_to_employee_id: Optional[int] = None,
        assigned_to_department_id: Optional[int] = None,
        due_date: Optional[int] = None,
        deadline_date: Optional[int] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new TANSS ticket for a company.

        Dates are Unix timestamps in seconds. remitter_id is the employee who
        reported/ordered the ticket; TANSS requires it unless the caller opts
        out, so when it is omitted the ticket is created with the remitter
        check disabled (remitterCheck=false). extra_fields is merged into the
        request body for less common Ticket-Save fields, e.g. orderById,
        projectId, project (bool), repair (bool), attention, linkTypeId/linkId,
        extTicketId, separateBilling, billingToCompanyId, serviceCapAmount.
        """
        if not (title or '').strip():
            raise ValueError('title must not be empty.')
        payload = self._build_payload(
            {
                'companyId': company_id,
                'title': title.strip(),
                'content': content or None,
                'remitterId': remitter_id,
                'statusId': status_id,
                'typeId': type_id,
                'assignedToEmployeeId': assigned_to_employee_id,
                'assignedToDepartmentId': assigned_to_department_id,
                'dueDate': due_date,
                'deadlineDate': deadline_date,
            },
            extra_fields,
        )
        params = None if remitter_id is not None else {'remitterCheck': 'false'}
        return self._request('POST', '/api/v1/tickets', params=params, json_body=payload)

    def update_ticket(self, ticket_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing TANSS ticket. fields contains the Ticket-Save
        attributes to change, e.g. title, content, statusId, typeId,
        assignedToEmployeeId, assignedToDepartmentId, companyId, remitterId,
        orderById, dueDate, deadlineDate (Unix seconds), projectId, attention.

        Typical status change: fields={"statusId": 3}. Reassignment:
        fields={"assignedToEmployeeId": 12}. To add an internal note use
        create_ticket_comment(internal=True), not a ticket field.
        """
        if not fields:
            raise ValueError('fields must contain at least one attribute to change.')
        return self._request(
            'PUT',
            f'/api/v1/tickets/{self._int_id(ticket_id, "ticket_id")}',
            json_body=dict(fields),
        )

    def create_ticket_comment(
        self,
        ticket_id: int,
        content: str,
        title: str = '',
        internal: bool = True,
    ) -> Dict[str, Any]:
        """
        Add a comment to a TANSS ticket. internal=True (default) keeps the
        comment invisible to the customer; set internal=False explicitly for
        customer-visible comments.
        """
        if not (content or '').strip():
            raise ValueError('content must not be empty.')
        payload = self._build_payload(
            {
                'content': content,
                'title': title or None,
                'internal': internal,
            }
        )
        return self._request(
            'POST',
            f'/api/v1/tickets/{self._int_id(ticket_id, "ticket_id")}/comments',
            json_body=payload,
        )

    def send_ticket_mail(
        self,
        ticket_id: int,
        to: str,
        subject: str,
        text: str,
        cc: str = '',
        bcc: str = '',
        internal: bool = False,
        html: bool = False,
        mail_type: str = 'NORMAL',
        status_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Compose and send an outbound mail from a TANSS ticket. Multiple
        recipient addresses can be given in one string separated by commas.
        mail_type is one of NORMAL, REPLY, SEND_AGAIN, FORWARD, SEMI_AUTOMATE.
        status_id optionally sets the ticket status when sending. If the
        mail_recipient_domains valve is configured, every recipient domain must
        be on that allowlist.
        """
        normalized_type = (mail_type or 'NORMAL').strip().upper()
        if normalized_type not in {
            'NORMAL',
            'REPLY',
            'SEND_AGAIN',
            'FORWARD',
            'SEMI_AUTOMATE',
        }:
            raise ValueError('Invalid mail_type. Allowed: NORMAL, REPLY, SEND_AGAIN, FORWARD, SEMI_AUTOMATE')
        if not (to or '').strip():
            raise ValueError('to must not be empty.')
        self._check_mail_recipients(to, cc, bcc)
        payload = self._build_payload(
            {
                'to': to,
                'cc': cc or None,
                'bcc': bcc or None,
                'title': subject,
                'text': text,
                'internal': internal,
                'html': html,
                'type': normalized_type,
                'statusId': status_id,
            }
        )
        return self._request(
            'POST',
            f'/api/v1/tickets/{self._int_id(ticket_id, "ticket_id")}/mails',
            json_body=payload,
        )

    def create_support(
        self,
        date: int,
        duration_minutes: int,
        text: str,
        ticket_id: Optional[int] = None,
        company_id: Optional[int] = None,
        employee_id: Optional[int] = None,
        remitter_id: Optional[int] = None,
        type_id: Optional[int] = None,
        internal: bool = False,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Book a TANSS support (time tracking entry / appointment).

        date is the start as a Unix timestamp in seconds, duration_minutes the
        worked time in minutes, text the visible work description. Usually
        ticket_id is given; employee_id defaults to the logged-in technician.
        extra_fields is merged into the request body for less common
        TnsSupport fields, e.g. location (OFFICE/CUSTOMER/REMOTE), planningType,
        durationNotCharged, reasonNotChargedId, durationApproach, kmApproach,
        durationDeparture, kmDeparture, contractId, costCenterId,
        accountingTypeId, textIntern, linkTypeId/linkId.
        """
        if not (text or '').strip():
            raise ValueError('text must not be empty.')
        if ticket_id is None and not (extra_fields or {}).get('linkId'):
            raise ValueError('Either ticket_id or extra_fields with linkTypeId/linkId is required.')
        payload = self._build_payload(
            {
                'date': date,
                'duration': duration_minutes,
                'text': text,
                'ticketId': ticket_id,
                'companyId': company_id,
                'employeeId': employee_id,
                'remitterId': remitter_id,
                'typeId': type_id,
                'internal': internal,
            },
            extra_fields,
        )
        return self._request('POST', '/api/v1/supports', json_body=payload)

    def update_support(self, support_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Edit an existing TANSS support (time tracking entry). fields contains
        the TnsSupport attributes to change, e.g. date (Unix seconds),
        duration (minutes), text, typeId, employeeId, internal,
        durationNotCharged, contractId.
        """
        if not fields:
            raise ValueError('fields must contain at least one attribute to change.')
        return self._request(
            'PUT',
            f'/api/v1/supports/{self._int_id(support_id, "support_id")}',
            json_body=dict(fields),
        )
