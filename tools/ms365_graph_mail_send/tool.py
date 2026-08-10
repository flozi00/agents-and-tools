"""
title: Microsoft 365 Mail (Graph)
description: Sendet Ergebnisse per Microsoft Graph an die eigene E-Mail-Adresse der angemeldeten Person — optional mit Dateianhängen aus der Agent-VM.
author: primeline
version: 1.0.0
"""

import datetime as dt
import json
import os
import re
from html import escape
from urllib.parse import quote

import aiohttp
from pydantic import BaseModel, Field

SSL_VERIFY = os.environ.get('AIOHTTP_CLIENT_SESSION_SSL', 'True').lower() == 'true'
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
GUID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def get_env_value(*keys: str, default: str = '') -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value.strip()
    return default


def get_env_int(key: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(key, str(default))))
    except ValueError:
        return default


def get_app_config_value(request, *keys: str) -> str:
    """Read a value from the host app config (admin UI settings win over env)."""
    config = getattr(getattr(getattr(request, 'app', None), 'state', None), 'config', None)
    for key in keys:
        value = getattr(config, key, None) if config is not None else None
        value = getattr(value, 'value', value)
        if value:
            return str(value)
    return ''


class Tools:
    class Valves(BaseModel):
        tenant_id: str = Field(
            default='',
            description='Entra/Azure Tenant ID. Leer = Microsoft-Einstellungen der App bzw. GRAPH_TENANT_ID/MS_ENTRA_DIRECTORY.',
        )
        client_id: str = Field(
            default='',
            description='App-Registrierung (Client ID). Leer = Microsoft-Einstellungen der App bzw. GRAPH_CLIENT_ID/MS_ENTRA_APP_ID.',
        )
        client_secret: str = Field(
            default='',
            description='Client Secret der App-Registrierung. Leer = Microsoft-Einstellungen der App bzw. GRAPH_CLIENT_SECRET/MS_ENTRA_VALUE.',
        )
        sender_user_id: str = Field(
            default='',
            description='Absender-Postfach: UPN/E-Mail oder Object ID. Leer = MS_ENTRA_MAILBOX/GRAPH_USER_ID.',
        )
        login_base_url: str = Field(
            default='',
            description='Login-Endpunkt. Leer = https://login.microsoftonline.com',
        )
        app_name: str = Field(
            default='',
            description='Absendername im Mail-Layout. Leer = MAIL_APP_NAME bzw. der Name der Anwendung.',
        )
        allowed_recipient_domains: str = Field(
            default_factory=lambda: get_env_value('SELF_MAIL_ALLOWED_DOMAINS'),
            description='Optionale Komma-Liste erlaubter Empfängerdomains. Leer = alle Domains erlaubt.',
        )
        max_subject_length: int = Field(
            default_factory=lambda: get_env_int('SELF_MAIL_MAX_SUBJECT_LENGTH', 180),
            description='Maximale Betrefflänge in Zeichen.',
        )
        max_body_length: int = Field(
            default_factory=lambda: get_env_int('SELF_MAIL_MAX_BODY_LENGTH', 50000),
            description='Maximale Textlänge in Zeichen.',
        )
        max_attachment_size_mb: int = Field(
            default_factory=lambda: get_env_int('SELF_MAIL_MAX_ATTACHMENT_SIZE_MB', 3),
            description='Maximale Größe je Anhang in MB.',
        )
        request_timeout_seconds: int = Field(
            default_factory=lambda: get_env_int('GRAPH_REQUEST_TIMEOUT_SECONDS', 30),
            description='Timeout für Graph-Aufrufe in Sekunden.',
        )
        save_to_sent_items: bool = Field(
            default_factory=lambda: get_env_value('GRAPH_SAVE_TO_SENT_ITEMS', default='true').lower() == 'true',
            description='Gesendete Mails im Postfach des Absenders ablegen.',
        )

    def __init__(self):
        self.valves = self.Valves()

    def _config(self, request) -> dict:
        valves = self.valves
        app_name = valves.app_name or get_env_value('MAIL_APP_NAME') or getattr(getattr(getattr(request, 'app', None), 'state', None), 'WEBUI_NAME', '') or 'OpenWebUI'
        return {
            'tenant_id': valves.tenant_id or get_app_config_value(request, 'GRAPH_TENANT_ID', 'MICROSOFT_CLIENT_TENANT_ID') or get_env_value('GRAPH_TENANT_ID', 'ENTRA_TENANT_ID', 'AZURE_TENANT_ID', 'MS_ENTRA_DIRECTORY', 'MICROSOFT_CLIENT_TENANT_ID'),
            'client_id': valves.client_id or get_app_config_value(request, 'GRAPH_CLIENT_ID', 'MICROSOFT_CLIENT_ID') or get_env_value('GRAPH_CLIENT_ID', 'ENTRA_CLIENT_ID', 'AZURE_CLIENT_ID', 'MS_ENTRA_APP_ID', 'MICROSOFT_CLIENT_ID'),
            'client_secret': valves.client_secret
            or get_app_config_value(request, 'GRAPH_CLIENT_SECRET', 'MICROSOFT_CLIENT_SECRET')
            or get_env_value(
                'GRAPH_CLIENT_SECRET',
                'ENTRA_CLIENT_SECRET',
                'AZURE_CLIENT_SECRET',
                'MS_ENTRA_VALUE',
                'MS_ENTRA_SECRET',
                'MICROSOFT_CLIENT_SECRET',
            ),
            'sender_user_id': valves.sender_user_id
            or get_app_config_value(request, 'GRAPH_SENDER_USER_ID')
            or get_env_value(
                'MS_ENTRA_MAILBOX',
                'MS_ENTRA_SENDER',
                'GRAPH_USER_ID',
                'GRAPH_SENDER',
                'ENTRA_USER_ID',
                'AZURE_USER_ID',
                'MS_ENTRA_USERNAME',
                'MS_ENTRA_OBJECT_ID',
                'GRAPH_SENDER_USER_ID',
            ),
            'login_base_url': (valves.login_base_url or get_app_config_value(request, 'MICROSOFT_CLIENT_LOGIN_BASE_URL') or get_env_value('MICROSOFT_CLIENT_LOGIN_BASE_URL', default='https://login.microsoftonline.com')).rstrip('/'),
            'app_name': app_name,
            'save_to_sent_items': valves.save_to_sent_items,
            'request_timeout_seconds': max(1, valves.request_timeout_seconds),
            'allowed_recipient_domains': valves.allowed_recipient_domains,
            'max_subject_length': max(1, valves.max_subject_length),
            'max_body_length': max(1, valves.max_body_length),
            'max_attachment_size_mb': max(1, valves.max_attachment_size_mb),
        }

    def _assert_config(self, config: dict) -> None:
        missing = [
            label
            for key, label in (
                ('tenant_id', 'Tenant ID'),
                ('client_id', 'Client ID'),
                ('client_secret', 'Client Secret'),
                ('sender_user_id', 'Absender-Postfach'),
            )
            if not config.get(key)
        ]
        if missing:
            raise ValueError('Microsoft Graph ist nicht vollständig konfiguriert. Fehlende Werte: ' + ', '.join(missing))

        sender = str(config['sender_user_id']).strip()
        if not ('@' in sender or GUID_RE.match(sender)):
            raise ValueError('GRAPH sender muss eine Mailbox-UPN/E-Mail oder eine gültige User Object ID sein.')

    def _validate_inputs(self, config: dict, user: dict, subject: str, results: str) -> tuple[str, str, str, str]:
        user_email = str((user or {}).get('email') or '').strip().lower()
        user_name = str((user or {}).get('name') or '').strip()
        if not user_email:
            raise ValueError('Im aktuellen Benutzerkontext ist keine E-Mail-Adresse vorhanden.')
        if not EMAIL_RE.match(user_email):
            raise ValueError('Die E-Mail-Adresse im Benutzerkontext ist ungültig.')

        allowed_domains = {item.strip().lower() for item in str(config['allowed_recipient_domains'] or '').split(',') if item.strip()}
        if allowed_domains:
            user_domain = user_email.split('@', 1)[-1]
            if user_domain not in allowed_domains:
                raise ValueError(f"Die Empfängerdomain '{user_domain}' ist nicht erlaubt.")

        subject = (subject or '').replace('\r', ' ').replace('\n', ' ').strip()
        results = (results or '').strip()
        if not subject:
            raise ValueError('Betreff darf nicht leer sein.')
        if not results:
            raise ValueError('Ergebnisse/Text dürfen nicht leer sein.')
        if len(subject) > config['max_subject_length']:
            raise ValueError(f'Betreff ist zu lang. Maximal {config["max_subject_length"]} Zeichen erlaubt.')
        if len(results) > config['max_body_length']:
            raise ValueError(f'Nachricht ist zu lang. Maximal {config["max_body_length"]} Zeichen erlaubt.')

        return user_email, user_name, subject, results

    def _build_html(self, config: dict, user_name: str, subject: str, body: str) -> str:
        safe_user_name = escape(user_name or 'Nutzer')
        safe_subject = escape(subject)
        safe_body = escape(body).replace('\n', '<br>')
        timestamp = dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')
        app_name = escape(config.get('app_name') or 'OpenWebUI')

        return f"""
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{safe_subject}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:Arial,sans-serif;color:#18181b;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:32px 16px;background:#f4f4f5;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:720px;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">
          <tr>
            <td style="padding:24px 32px;background:#111827;color:#ffffff;">
              <h1 style="margin:0;font-size:20px;">{app_name}</h1>
              <p style="margin:8px 0 0 0;font-size:13px;color:#d1d5db;">Ihre Ergebnisse wurden per Microsoft Graph versendet.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px 0;font-size:15px;">Hallo {safe_user_name},</p>
              <p style="margin:0 0 16px 0;font-size:15px;">hier sind die Ergebnisse, die Sie sich selbst geschickt haben.</p>
              <div style="margin:24px 0;padding:16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;">
                <p style="margin:0 0 8px 0;font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em;">Betreff</p>
                <p style="margin:0;font-size:16px;font-weight:600;">{safe_subject}</p>
              </div>
              <div style="margin:24px 0;padding:16px;background:#fafafa;border:1px solid #e5e7eb;border-radius:8px;">
                <p style="margin:0 0 12px 0;font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em;">Inhalt</p>
                <div style="font-size:14px;line-height:1.6;white-space:normal;word-break:break-word;">{safe_body}</div>
              </div>
              <p style="margin:24px 0 0 0;font-size:12px;color:#6b7280;">Versandzeitpunkt: {timestamp}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px;background:#f9fafb;border-top:1px solid #e5e7eb;">
              <p style="margin:0;font-size:12px;color:#6b7280;">Diese E-Mail wurde automatisch von {app_name} erzeugt.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    async def _acquire_token(self, config: dict) -> str:
        token_url = f'{config["login_base_url"]}/{config["tenant_id"]}/oauth2/v2.0/token'
        data = {
            'client_id': config['client_id'],
            'client_secret': config['client_secret'],
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials',
        }
        timeout = aiohttp.ClientTimeout(total=config['request_timeout_seconds'], connect=10)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.post(token_url, data=data, ssl=SSL_VERIFY) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(f'Token-Abruf fehlgeschlagen ({response.status}): {text[:500]}')
                payload = await response.json()

        access_token = payload.get('access_token') if isinstance(payload, dict) else None
        if not access_token:
            raise RuntimeError('Kein access_token von Microsoft Graph erhalten.')
        return access_token

    async def _send_mail(self, config: dict, to_email: str, subject: str, html_body: str, attachments: list | None = None) -> None:
        access_token = await self._acquire_token(config)
        sender = quote(str(config['sender_user_id']).strip(), safe='')
        message = {
            'subject': subject,
            'body': {'contentType': 'HTML', 'content': html_body},
            'toRecipients': [{'emailAddress': {'address': to_email}}],
        }
        if attachments:
            message['attachments'] = attachments

        timeout = aiohttp.ClientTimeout(total=config['request_timeout_seconds'], connect=10)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.post(
                f'https://graph.microsoft.com/v1.0/users/{sender}/sendMail',
                headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
                json={'message': message, 'saveToSentItems': config['save_to_sent_items']},
                ssl=SSL_VERIFY,
            ) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(f'Microsoft Graph sendMail fehlgeschlagen ({response.status}): {text[:500]}')

    async def send_results_to_my_email(
        self,
        subject: str,
        results: str,
        file_paths: str = '',
        __request__=None,
        __user__: dict = None,
        __metadata__: dict = None,
    ) -> str:
        """
        Send results to the current user's own e-mail address with Microsoft Graph.
        The recipient is always taken from the authenticated user context and cannot be overridden.
        Optional attachments are loaded directly from the active Agent-VM.

        :param subject: E-mail subject.
        :param results: Message body text to send.
        :param file_paths: Optional comma-separated Agent-VM file paths to attach, for example "/home/user/report.pdf, /home/user/data.csv".
        """
        try:
            if not __user__:
                raise ValueError('User context not available')

            config = self._config(__request__)
            self._assert_config(config)
            user_email, user_name, subject, results = self._validate_inputs(config, __user__, subject, results)

            attachments = []
            if (file_paths or '').strip():
                # Agent-VM files are fetched by the host app, which owns the terminal auth.
                from open_webui.tools.builtin import build_agent_vm_attachments

                attachments = await build_agent_vm_attachments(
                    __request__,
                    __user__,
                    __metadata__,
                    file_paths,
                    config['max_attachment_size_mb'],
                    config['request_timeout_seconds'],
                )

            await self._send_mail(
                config,
                to_email=user_email,
                subject=subject,
                html_body=self._build_html(config, user_name, subject, results),
                attachments=attachments or None,
            )

            attachment_info = ''
            if attachments:
                names = [attachment['name'] for attachment in attachments]
                attachment_info = f' Mit {len(names)} Anhang/Anhängen: {", ".join(names)}'
            return f'E-Mail wurde erfolgreich an Ihre eigene Adresse gesendet: {user_email}{attachment_info}'
        except Exception as exc:
            return json.dumps({'error': str(exc)}, ensure_ascii=False)
