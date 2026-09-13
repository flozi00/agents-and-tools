"""
title: GitLab CI Pipeline Results Tool
author: OpenAI
version: 0.1.0
required_open_webui_version: 0.4.0
description: Liest GitLab-CI/CD-Ergebnisse: Pipelines, Jobs, Testberichte und Job-Logs — rein lesend, für die Fehlersuche an fehlgeschlagenen Pipelines.
requirements: requests
license: MIT No Attribution (MIT-0)
original_author: KommI – Kommunale Intelligenz (Boris van Benthem)
source_url: https://gitlab.opencode.de/kommi/adapter/gitlab-adapter

OpenWebUI Tools Function specialized in reading GitLab CI/CD pipeline results,
jobs, test reports, and selected job traces to support debugging workflows.

This adapter is read-only. It never creates, retries, cancels, or modifies
pipelines, jobs, repository content, issues, or merge requests.
"""

# --------------------------------------------------------------------------
# Herkunft / Provenance
#
# Übernommen aus dem KommI-Adapter-Katalog (openCode). Ergänzt wurden dieser
# Herkunftshinweis und Katalog-Metadaten im Kopf; der Code selbst ist
# unverändert.
#
#   Projekt : GitLab-Adapter
#   Quelle  : https://gitlab.opencode.de/kommi/adapter/gitlab-adapter
#   Datei   : gitlab_ci_pipeline_adapter.py
#   Autor   : KommI – Kommunale Intelligenz (Boris van Benthem)
#   Lizenz  : MIT No Attribution (MIT-0)
#
# LICENSE-Datei des Quellprojekts, wortgleich übernommen.
# --------------------------------------------------------------------------
# MIT No Attribution
#
# Copyright 2026 Boris van Benthem
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import quote

import requests
from pydantic import BaseModel, Field, ValidationError


# Target: OpenWebUI Tools Function
class Tools:
    class Valves(BaseModel):
        gitlab_url: str = Field(
            default='https://gitlab.example.com',
            description='Base URL of the GitLab instance, without trailing slash.',
        )
        api_path: str = Field(
            default='/api/v4',
            description='GitLab API path.',
        )
        admin_access_token: str = Field(
            default='',
            description=('Optional admin/service token fallback. Prefer short-lived OAuth tokens via __oauth_token__ where available.'),
        )
        verify_ssl: bool = Field(
            default=True,
            description='Verify SSL/TLS certificates for GitLab requests.',
        )
        request_timeout_seconds: int = Field(
            default=60,
            description='HTTP timeout for GitLab API calls.',
        )
        allowed_project_ids_csv: str = Field(
            default='',
            description=('Optional admin-controlled comma-separated allowlist of GitLab project IDs. Empty means no additional project restriction.'),
        )
        max_per_page: int = Field(
            default=100,
            description='Maximum allowed GitLab per_page value for list endpoints.',
        )
        default_pipeline_limit: int = Field(
            default=20,
            description='Default maximum number of pipelines returned by list calls.',
        )
        max_trace_bytes: int = Field(
            default=262_144,
            description='Maximum bytes to read from a single GitLab job trace.',
        )
        default_trace_tail_bytes: int = Field(
            default=40_000,
            description='Default number of trailing trace bytes returned for debugging.',
        )
        redact_trace_secrets: bool = Field(
            default=True,
            description='Redact common secret-looking values from returned job traces.',
        )
        trace_redaction_regex: str = Field(
            default=(
                r'(?i)(token|password|passwd|secret|api[_-]?key|private[_-]?token)'
                r"(\s*[:=]\s*)([^\s'\"`]+)"
            ),
            description='Regex used to redact secret-like key/value pairs in traces.',
        )
        emit_debug_notifications: bool = Field(
            default=False,
            description='Emit extra debug notifications to the UI.',
        )

    class UserValves(BaseModel):
        default_ref: str = Field(
            default='main',
            description='Preferred default Git ref for latest-pipeline lookups.',
        )
        default_pipeline_limit: int = Field(
            default=10,
            description='User preference for how many pipelines to list by default.',
        )
        default_trace_tail_bytes: int = Field(
            default=20_000,
            description='User preference for how much trace tail to return.',
        )
        preferred_status_filter: str = Field(
            default='',
            description='Optional preferred pipeline status filter, e.g. failed or success.',
        )
        include_traces_in_debug: bool = Field(
            default=True,
            description='Whether debug summaries should include failed job trace tails by default.',
        )

    def __init__(self):
        self.valves = self.Valves()

    @dataclass
    class _Context:
        eventer: 'EventEmitterHelper'
        helper: 'GitLabCIHelper'
        user_valves: 'Tools.UserValves'

    def _build_context(
        self,
        __event_emitter__: Optional[Callable[..., Awaitable[Any]]],
        __user__: Optional[dict],
        __oauth_token__: Optional[str] = None,
    ) -> 'Tools._Context':
        eventer = EventEmitterHelper(__event_emitter__, self.valves.emit_debug_notifications)
        user_valves = self._extract_user_valves(__user__)
        helper = GitLabCIHelper(self.valves, user_valves, eventer, __oauth_token__)
        return self._Context(eventer=eventer, helper=helper, user_valves=user_valves)

    def _extract_user_valves(self, __user__: Optional[dict]) -> 'Tools.UserValves':
        if not __user__:
            return self.UserValves()
        raw = __user__.get('valves', {}) or {}
        if isinstance(raw, self.UserValves):
            return raw
        if isinstance(raw, dict):
            try:
                return self.UserValves(**raw)
            except ValidationError:
                return self.UserValves()
        return self.UserValves()

    # -------------------------- Tool methods --------------------------

    async def list_pipelines(
        self,
        project_id: str,
        ref: str = '',
        status: str = '',
        source: str = '',
        updated_after: str = '',
        updated_before: str = '',
        per_page: Optional[int] = None,
        page: int = 1,
        __event_emitter__=None,
        __user__=None,
        __oauth_token__=None,
    ) -> dict:
        """List GitLab CI/CD pipelines for a project.

        Optional filters mirror common GitLab API filters: ref, status, source,
        updated_after, and updated_before. This is read-only.
        """
        ctx = self._build_context(__event_emitter__, __user__, __oauth_token__)
        ctx.helper.enforce_project_access(project_id)

        safe_page = max(1, int(page or 1))
        safe_per_page = ctx.helper.resolve_per_page(per_page)
        effective_status = (status or ctx.user_valves.preferred_status_filter).strip()

        params: Dict[str, Any] = {'page': safe_page, 'per_page': safe_per_page}
        if ref.strip():
            params['ref'] = ref.strip()
        if effective_status:
            params['status'] = ctx.helper.normalize_pipeline_status(effective_status)
        if source.strip():
            params['source'] = source.strip()
        if updated_after.strip():
            params['updated_after'] = updated_after.strip()
        if updated_before.strip():
            params['updated_before'] = updated_before.strip()

        await ctx.eventer.status('info', f'Lade CI/CD-Pipelines für Projekt {project_id} …', False)
        pipelines = ctx.helper.get_json(
            f'/projects/{quote(str(project_id), safe="")}/pipelines',
            params=params,
        )
        summaries = [ctx.helper.pipeline_summary(item) for item in pipelines]
        await ctx.eventer.status('success', f'{len(summaries)} Pipeline(s) geladen.', True)
        return {
            'ok': True,
            'project_id': project_id,
            'page': safe_page,
            'per_page': safe_per_page,
            'count': len(summaries),
            'pipelines': summaries,
        }

    async def get_latest_pipeline_for_ref(
        self,
        project_id: str,
        ref: str = '',
        status: str = '',
        include_jobs: bool = True,
        include_test_report_summary: bool = True,
        __event_emitter__=None,
        __user__=None,
        __oauth_token__=None,
    ) -> dict:
        """Load the newest pipeline for a ref and optionally include jobs/test summary."""
        ctx = self._build_context(__event_emitter__, __user__, __oauth_token__)
        ctx.helper.enforce_project_access(project_id)
        effective_ref = (ref or ctx.user_valves.default_ref or 'main').strip()
        effective_status = (status or ctx.user_valves.preferred_status_filter).strip()

        params: Dict[str, Any] = {'ref': effective_ref, 'page': 1, 'per_page': 1}
        if effective_status:
            params['status'] = ctx.helper.normalize_pipeline_status(effective_status)

        await ctx.eventer.status('info', f'Lade neueste Pipeline für {project_id}@{effective_ref} …', False)
        pipelines = ctx.helper.get_json(
            f'/projects/{quote(str(project_id), safe="")}/pipelines',
            params=params,
        )
        if not pipelines:
            await ctx.eventer.status('info', 'Keine passende Pipeline gefunden.', True)
            return {
                'ok': False,
                'project_id': project_id,
                'ref': effective_ref,
                'message': 'No matching pipeline found',
            }

        pipeline_id = int(pipelines[0]['id'])
        result = await self.get_pipeline(
            project_id=project_id,
            pipeline_id=pipeline_id,
            include_jobs=include_jobs,
            include_test_report_summary=include_test_report_summary,
            __event_emitter__=__event_emitter__,
            __user__=__user__,
            __oauth_token__=__oauth_token__,
        )
        result['lookup'] = {'ref': effective_ref, 'status': effective_status or None}
        return result

    async def get_pipeline(
        self,
        project_id: str,
        pipeline_id: int,
        include_jobs: bool = True,
        include_test_report_summary: bool = True,
        __event_emitter__=None,
        __user__=None,
        __oauth_token__=None,
    ) -> dict:
        """Read one GitLab CI/CD pipeline with optional jobs and test summary."""
        ctx = self._build_context(__event_emitter__, __user__, __oauth_token__)
        ctx.helper.enforce_project_access(project_id)
        safe_pipeline_id = ctx.helper.normalize_positive_int(pipeline_id, 'pipeline_id')

        await ctx.eventer.status('info', f'Lade Pipeline {safe_pipeline_id} für Projekt {project_id} …', False)
        pipeline = ctx.helper.get_json(f'/projects/{quote(str(project_id), safe="")}/pipelines/{safe_pipeline_id}')
        result: Dict[str, Any] = {
            'ok': True,
            'project_id': project_id,
            'pipeline': ctx.helper.pipeline_summary(pipeline, detailed=True),
        }

        if include_jobs:
            jobs = ctx.helper.get_all_pages(
                f'/projects/{quote(str(project_id), safe="")}/pipelines/{safe_pipeline_id}/jobs',
                params={'include_retried': True},
                limit=ctx.helper.resolve_per_page(None),
            )
            result['jobs'] = [ctx.helper.job_summary(job) for job in jobs]
            result['job_status_counts'] = ctx.helper.count_by_status(result['jobs'])

        if include_test_report_summary:
            result['test_report_summary'] = ctx.helper.get_optional_json(f'/projects/{quote(str(project_id), safe="")}/pipelines/{safe_pipeline_id}/test_report_summary')

        await ctx.eventer.status('success', 'Pipeline geladen.', True)
        return result

    async def list_pipeline_jobs(
        self,
        project_id: str,
        pipeline_id: int,
        scope: Optional[List[str]] = None,
        include_retried: bool = True,
        per_page: Optional[int] = None,
        page: int = 1,
        __event_emitter__=None,
        __user__=None,
        __oauth_token__=None,
    ) -> dict:
        """List jobs for a GitLab CI/CD pipeline."""
        ctx = self._build_context(__event_emitter__, __user__, __oauth_token__)
        ctx.helper.enforce_project_access(project_id)
        safe_pipeline_id = ctx.helper.normalize_positive_int(pipeline_id, 'pipeline_id')
        safe_page = max(1, int(page or 1))
        safe_per_page = ctx.helper.resolve_per_page(per_page)

        params: Dict[str, Any] = {
            'page': safe_page,
            'per_page': safe_per_page,
            'include_retried': include_retried,
        }
        normalized_scope = ctx.helper.normalize_job_scope(scope or [])
        if normalized_scope:
            params['scope[]'] = normalized_scope

        await ctx.eventer.status('info', f'Lade Jobs für Pipeline {safe_pipeline_id} …', False)
        jobs = ctx.helper.get_json(
            f'/projects/{quote(str(project_id), safe="")}/pipelines/{safe_pipeline_id}/jobs',
            params=params,
        )
        summaries = [ctx.helper.job_summary(job) for job in jobs]
        await ctx.eventer.status('success', f'{len(summaries)} Job(s) geladen.', True)
        return {
            'ok': True,
            'project_id': project_id,
            'pipeline_id': safe_pipeline_id,
            'page': safe_page,
            'per_page': safe_per_page,
            'count': len(summaries),
            'status_counts': ctx.helper.count_by_status(summaries),
            'jobs': summaries,
        }

    async def get_job_trace(
        self,
        project_id: str,
        job_id: int,
        max_bytes: Optional[int] = None,
        tail_bytes: Optional[int] = None,
        redact: bool = True,
        __event_emitter__=None,
        __user__=None,
        __oauth_token__=None,
    ) -> dict:
        """Read a GitLab job trace, optionally returning only the tail.

        Traces can contain sensitive data. By default, the adapter applies a
        best-effort redaction for common secret-like key/value patterns.
        """
        ctx = self._build_context(__event_emitter__, __user__, __oauth_token__)
        ctx.helper.enforce_project_access(project_id)
        safe_job_id = ctx.helper.normalize_positive_int(job_id, 'job_id')
        safe_max_bytes = ctx.helper.resolve_trace_max_bytes(max_bytes)
        safe_tail_bytes = ctx.helper.resolve_trace_tail_bytes(tail_bytes)

        await ctx.eventer.status('info', f'Lese Trace für Job {safe_job_id} …', False)
        trace_info = ctx.helper.get_trace_text(
            project_id=project_id,
            job_id=safe_job_id,
            max_bytes=safe_max_bytes,
            tail_bytes=safe_tail_bytes,
            redact=redact,
        )
        await ctx.eventer.status('success', 'Job-Trace geladen.', True)
        return {
            'ok': True,
            'project_id': project_id,
            'job_id': safe_job_id,
            **trace_info,
        }

    async def get_pipeline_test_report(
        self,
        project_id: str,
        pipeline_id: int,
        include_raw: bool = False,
        __event_emitter__=None,
        __user__=None,
        __oauth_token__=None,
    ) -> dict:
        """Read the GitLab test report for a pipeline, if available."""
        ctx = self._build_context(__event_emitter__, __user__, __oauth_token__)
        ctx.helper.enforce_project_access(project_id)
        safe_pipeline_id = ctx.helper.normalize_positive_int(pipeline_id, 'pipeline_id')

        await ctx.eventer.status('info', f'Lade Testbericht für Pipeline {safe_pipeline_id} …', False)
        report = ctx.helper.get_optional_json(f'/projects/{quote(str(project_id), safe="")}/pipelines/{safe_pipeline_id}/test_report')
        summary = ctx.helper.test_report_summary(report or {}) if report else None
        await ctx.eventer.status('success', 'Testbericht geladen.', True)
        result = {
            'ok': report is not None,
            'project_id': project_id,
            'pipeline_id': safe_pipeline_id,
            'summary': summary,
        }
        if include_raw:
            result['raw'] = report
        return result

    async def debug_pipeline(
        self,
        project_id: str,
        pipeline_id: int,
        include_failed_traces: Optional[bool] = None,
        trace_tail_bytes: Optional[int] = None,
        __event_emitter__=None,
        __user__=None,
        __oauth_token__=None,
    ) -> dict:
        """Create a read-only debugging summary for a pipeline.

        The summary includes pipeline metadata, job status counts, failed jobs,
        optional failed-job trace tails, and lightweight troubleshooting hints.
        """
        ctx = self._build_context(__event_emitter__, __user__, __oauth_token__)
        ctx.helper.enforce_project_access(project_id)
        safe_pipeline_id = ctx.helper.normalize_positive_int(pipeline_id, 'pipeline_id')
        should_include_traces = ctx.user_valves.include_traces_in_debug if include_failed_traces is None else bool(include_failed_traces)
        safe_tail_bytes = ctx.helper.resolve_trace_tail_bytes(trace_tail_bytes)

        await ctx.eventer.status('info', f'Erstelle Debug-Zusammenfassung für Pipeline {safe_pipeline_id} …', False)
        pipeline = ctx.helper.get_json(f'/projects/{quote(str(project_id), safe="")}/pipelines/{safe_pipeline_id}')
        jobs = ctx.helper.get_all_pages(
            f'/projects/{quote(str(project_id), safe="")}/pipelines/{safe_pipeline_id}/jobs',
            params={'include_retried': True},
            limit=ctx.helper.resolve_per_page(None),
        )
        job_summaries = [ctx.helper.job_summary(job) for job in jobs]
        failed_jobs = [job for job in job_summaries if job.get('status') in {'failed', 'canceled'}]

        failed_traces: List[dict] = []
        if should_include_traces:
            for job in failed_jobs[:10]:
                try:
                    failed_traces.append(
                        {
                            'job_id': job.get('id'),
                            'name': job.get('name'),
                            'stage': job.get('stage'),
                            'status': job.get('status'),
                            'failure_reason': job.get('failure_reason'),
                            'trace': ctx.helper.get_trace_text(
                                project_id=project_id,
                                job_id=int(job['id']),
                                max_bytes=ctx.helper.resolve_trace_max_bytes(None),
                                tail_bytes=safe_tail_bytes,
                                redact=True,
                            ),
                        }
                    )
                except Exception as exc:
                    failed_traces.append(
                        {
                            'job_id': job.get('id'),
                            'name': job.get('name'),
                            'error': str(exc),
                        }
                    )

        result = {
            'ok': True,
            'project_id': project_id,
            'pipeline': ctx.helper.pipeline_summary(pipeline, detailed=True),
            'job_status_counts': ctx.helper.count_by_status(job_summaries),
            'failed_jobs': failed_jobs,
            'failed_traces': failed_traces,
            'hints': ctx.helper.build_debug_hints(pipeline, failed_jobs),
            'test_report_summary': ctx.helper.get_optional_json(f'/projects/{quote(str(project_id), safe="")}/pipelines/{safe_pipeline_id}/test_report_summary'),
        }
        await ctx.eventer.status('success', 'Debug-Zusammenfassung erstellt.', True)
        return result


class EventEmitterHelper:
    def __init__(
        self,
        emitter: Optional[Callable[..., Awaitable[Any]]],
        debug_enabled: bool = False,
    ):
        self.emitter = emitter
        self.debug_enabled = debug_enabled

    async def _emit(self, payload: dict):
        if self.emitter is None:
            return
        result = self.emitter(payload)
        if asyncio.iscoroutine(result):
            await result

    async def status(self, level: str, description: str, done: bool):
        await self._emit(
            {
                'type': 'status',
                'data': {
                    'status': 'complete' if done else 'in_progress',
                    'level': level,
                    'description': description,
                    'done': done,
                },
            }
        )

    async def notification(self, level: str, content: str):
        await self._emit({'type': 'notification', 'data': {'type': level, 'content': content}})

    async def debug(self, content: str):
        if not self.debug_enabled:
            return
        await self.notification('info', f'DEBUG: {content}')


class GitLabCIHelper:
    PIPELINE_STATUSES = {
        'created',
        'waiting_for_resource',
        'preparing',
        'pending',
        'running',
        'success',
        'failed',
        'canceled',
        'cancelled',
        'skipped',
        'manual',
        'scheduled',
    }
    JOB_SCOPES = {
        'created',
        'pending',
        'running',
        'failed',
        'success',
        'canceled',
        'cancelled',
        'skipped',
        'waiting_for_resource',
        'manual',
    }

    def __init__(
        self,
        valves: Tools.Valves,
        user_valves: Tools.UserValves,
        eventer: EventEmitterHelper,
        oauth_token: Optional[str] = None,
    ):
        self.valves = valves
        self.user_valves = user_valves
        self.eventer = eventer
        self.base_url = f'{self.valves.gitlab_url.rstrip("/")}{self.valves.api_path}'
        self.session = requests.Session()

        token = (oauth_token or '').strip() or self.valves.admin_access_token
        if not token:
            raise ValueError('No GitLab access token configured. Provide an OAuth token or set admin_access_token in Valves.')
        self.session.headers.update(
            {
                'PRIVATE-TOKEN': token,
                'Accept': 'application/json',
            }
        )

        if not self.valves.verify_ssl:
            requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        url = endpoint if endpoint.startswith('http') else f'{self.base_url}{endpoint}'
        response = self.session.request(
            method=method,
            url=url,
            verify=self.valves.verify_ssl,
            timeout=self.valves.request_timeout_seconds,
            **kwargs,
        )
        if not response.ok:
            detail = self._safe_error_text(response)
            raise ValueError(f'GitLab API error {response.status_code}: {detail}')
        return response

    def get_json(self, endpoint: str, params: Optional[dict] = None) -> Any:
        response = self._request('GET', endpoint, params=params)
        return response.json()

    def get_optional_json(self, endpoint: str, params: Optional[dict] = None) -> Optional[Any]:
        try:
            return self.get_json(endpoint, params=params)
        except ValueError as exc:
            # GitLab returns 404 for test-report endpoints when no report exists.
            if 'GitLab API error 404' in str(exc):
                return None
            raise

    def get_all_pages(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        limit: int = 100,
    ) -> List[Any]:
        safe_limit = max(1, min(int(limit or 100), self.valves.max_per_page, 1000))
        collected: List[Any] = []
        page = 1
        while len(collected) < safe_limit:
            page_params = dict(params or {})
            page_params['page'] = page
            page_params['per_page'] = min(self.valves.max_per_page, 100, safe_limit - len(collected))
            batch = self.get_json(endpoint, params=page_params)
            if not batch:
                break
            collected.extend(batch)
            if len(batch) < page_params['per_page']:
                break
            page += 1
        return collected[:safe_limit]

    def _safe_error_text(self, response: requests.Response) -> str:
        try:
            payload = response.json()
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            text = response.text.strip()
            return text[:1000] if text else 'Unknown error'

    def enforce_project_access(self, project_id: str):
        if not str(project_id).strip():
            raise ValueError('project_id must not be empty')
        allowed = [item.strip() for item in self.valves.allowed_project_ids_csv.split(',') if item.strip()]
        if allowed and str(project_id) not in allowed:
            raise ValueError(f'Project {project_id} is not allowed by admin policy')

    def normalize_positive_int(self, value: Any, name: str) -> int:
        parsed = int(value)
        if parsed <= 0:
            raise ValueError(f'{name} must be a positive integer')
        return parsed

    def resolve_per_page(self, per_page: Optional[int]) -> int:
        if per_page is None:
            requested = min(
                self.user_valves.default_pipeline_limit,
                self.valves.default_pipeline_limit,
            )
        else:
            requested = int(per_page)
        return max(1, min(requested, self.valves.max_per_page, 100))

    def resolve_trace_max_bytes(self, max_bytes: Optional[int]) -> int:
        requested = self.valves.max_trace_bytes if max_bytes is None else int(max_bytes)
        return max(1, min(requested, self.valves.max_trace_bytes))

    def resolve_trace_tail_bytes(self, tail_bytes: Optional[int]) -> int:
        requested = min(self.user_valves.default_trace_tail_bytes, self.valves.default_trace_tail_bytes) if tail_bytes is None else int(tail_bytes)
        return max(1, min(requested, self.valves.max_trace_bytes))

    def normalize_pipeline_status(self, status: str) -> str:
        normalized = status.strip().lower()
        if normalized == 'cancelled':
            normalized = 'canceled'
        if normalized not in self.PIPELINE_STATUSES:
            raise ValueError(f"Invalid pipeline status '{status}'. Expected one of: {sorted(self.PIPELINE_STATUSES)}")
        return normalized

    def normalize_job_scope(self, scope: List[str]) -> List[str]:
        result = []
        for item in scope:
            normalized = str(item).strip().lower()
            if normalized == 'cancelled':
                normalized = 'canceled'
            if not normalized:
                continue
            if normalized not in self.JOB_SCOPES:
                raise ValueError(f"Invalid job scope '{item}'. Expected one of: {sorted(self.JOB_SCOPES)}")
            if normalized not in result:
                result.append(normalized)
        return result

    def pipeline_summary(self, item: dict, detailed: bool = False) -> dict:
        user = item.get('user') or {}
        result = {
            'id': item.get('id'),
            'iid': item.get('iid'),
            'project_id': item.get('project_id'),
            'status': item.get('status'),
            'source': item.get('source'),
            'ref': item.get('ref'),
            'sha': item.get('sha'),
            'web_url': item.get('web_url'),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at'),
        }
        if detailed:
            result.update(
                {
                    'name': item.get('name'),
                    'duration': item.get('duration'),
                    'queued_duration': item.get('queued_duration'),
                    'started_at': item.get('started_at'),
                    'finished_at': item.get('finished_at'),
                    'coverage': item.get('coverage'),
                    'detailed_status': item.get('detailed_status'),
                    'user': {
                        'id': user.get('id'),
                        'name': user.get('name'),
                        'username': user.get('username'),
                        'web_url': user.get('web_url'),
                    }
                    if user
                    else None,
                }
            )
        return result

    def job_summary(self, item: dict) -> dict:
        runner = item.get('runner') or {}
        user = item.get('user') or {}
        commit = item.get('commit') or {}
        artifacts_file = item.get('artifacts_file') or {}
        return {
            'id': item.get('id'),
            'name': item.get('name'),
            'stage': item.get('stage'),
            'status': item.get('status'),
            'failure_reason': item.get('failure_reason'),
            'allow_failure': item.get('allow_failure'),
            'ref': item.get('ref'),
            'tag': item.get('tag'),
            'web_url': item.get('web_url'),
            'duration': item.get('duration'),
            'queued_duration': item.get('queued_duration'),
            'created_at': item.get('created_at'),
            'started_at': item.get('started_at'),
            'finished_at': item.get('finished_at'),
            'erased_at': item.get('erased_at'),
            'artifacts_expire_at': item.get('artifacts_expire_at'),
            'artifacts_file': {
                'filename': artifacts_file.get('filename'),
                'size': artifacts_file.get('size'),
            }
            if artifacts_file
            else None,
            'runner': {
                'id': runner.get('id'),
                'description': runner.get('description'),
                'runner_type': runner.get('runner_type'),
                'status': runner.get('status'),
            }
            if runner
            else None,
            'user': {
                'id': user.get('id'),
                'name': user.get('name'),
                'username': user.get('username'),
            }
            if user
            else None,
            'commit': {
                'id': commit.get('id'),
                'short_id': commit.get('short_id'),
                'title': commit.get('title'),
                'web_url': commit.get('web_url'),
            }
            if commit
            else None,
        }

    def count_by_status(self, items: List[dict]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in items:
            status = str(item.get('status') or 'unknown')
            counts[status] = counts.get(status, 0) + 1
        return counts

    def get_trace_text(
        self,
        project_id: str,
        job_id: int,
        max_bytes: int,
        tail_bytes: int,
        redact: bool = True,
    ) -> dict:
        endpoint = f'/projects/{quote(str(project_id), safe="")}/jobs/{job_id}/trace'
        url = f'{self.base_url}{endpoint}'
        headers = {
            'PRIVATE-TOKEN': self.session.headers['PRIVATE-TOKEN'],
            'Accept': 'text/plain',
        }
        response = self.session.get(
            url,
            headers=headers,
            verify=self.valves.verify_ssl,
            timeout=self.valves.request_timeout_seconds,
            stream=True,
        )
        if not response.ok:
            detail = self._safe_error_text(response)
            raise ValueError(f'GitLab API error {response.status_code}: {detail}')

        chunks: List[bytes] = []
        total = 0
        truncated = False
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                remaining = max(0, max_bytes - sum(len(item) for item in chunks))
                if remaining:
                    chunks.append(chunk[:remaining])
                truncated = True
                break
            chunks.append(chunk)

        content = b''.join(chunks)
        original_read_bytes = len(content)
        if tail_bytes and len(content) > tail_bytes:
            content = content[-tail_bytes:]
            tail_applied = True
        else:
            tail_applied = False

        text = content.decode('utf-8', errors='replace')
        redacted = False
        if redact and self.valves.redact_trace_secrets:
            text, redacted = self.redact_trace(text)

        return {
            'trace': text,
            'read_bytes': original_read_bytes,
            'returned_bytes': len(text.encode('utf-8')),
            'max_bytes': max_bytes,
            'tail_bytes': tail_bytes,
            'truncated_at_max_bytes': truncated,
            'tail_applied': tail_applied,
            'redacted': redacted,
        }

    def redact_trace(self, text: str) -> tuple[str, bool]:
        redacted = False
        try:
            pattern = re.compile(self.valves.trace_redaction_regex)
            text, count = pattern.subn(r'\1\2[REDACTED]', text)
            redacted = redacted or count > 0
        except re.error:
            # If admin configured an invalid regex, fall back to token-like redaction only.
            pass

        token_patterns = [
            r'glpat-[A-Za-z0-9_\-]{10,}',
            r'glrt-[A-Za-z0-9_\-]{10,}',
            r'gloas-[A-Za-z0-9_\-]{10,}',
            r'eyJ[A-Za-z0-9_\-.]{20,}',
        ]
        for token_pattern in token_patterns:
            text, count = re.subn(token_pattern, '[REDACTED]', text)
            redacted = redacted or count > 0
        return text, redacted

    def test_report_summary(self, report: dict) -> dict:
        suites = report.get('test_suites') or []
        failed_cases: List[dict] = []
        for suite in suites:
            for case in suite.get('test_cases') or []:
                if case.get('status') in {'failed', 'error'}:
                    failed_cases.append(
                        {
                            'suite_name': suite.get('name'),
                            'name': case.get('name'),
                            'classname': case.get('classname'),
                            'status': case.get('status'),
                            'execution_time': case.get('execution_time'),
                            'file': case.get('file'),
                            'system_output': case.get('system_output'),
                            'stack_trace': case.get('stack_trace'),
                        }
                    )
        return {
            'total_time': report.get('total_time'),
            'total_count': report.get('total_count'),
            'success_count': report.get('success_count'),
            'failed_count': report.get('failed_count'),
            'skipped_count': report.get('skipped_count'),
            'error_count': report.get('error_count'),
            'failed_cases_count': len(failed_cases),
            'failed_cases': failed_cases[:50],
        }

    def build_debug_hints(self, pipeline: dict, failed_jobs: List[dict]) -> List[str]:
        hints: List[str] = []
        status = pipeline.get('status')
        if status == 'success':
            hints.append('Pipeline ist erfolgreich; prüfe bei Bedarf Testberichte und Job-Dauer für Flakiness oder Performance.')
        elif status == 'failed':
            hints.append('Pipeline ist fehlgeschlagen; beginne mit den fehlgeschlagenen Jobs und deren Trace-Ende.')
        elif status in {'running', 'pending'}:
            hints.append('Pipeline läuft noch oder wartet; prüfe pending Jobs, Runner-Verfügbarkeit und queued_duration.')
        elif status == 'canceled':
            hints.append('Pipeline wurde abgebrochen; prüfe Autor, Zeitpunkt und abhängige Downstream-Jobs.')

        reasons = {job.get('failure_reason') for job in failed_jobs if job.get('failure_reason')}
        if 'script_failure' in reasons:
            hints.append('Mindestens ein Job hat script_failure; meist liegt die Ursache im Trace nahe dem Ende.')
        if 'stuck_or_timeout_failure' in reasons:
            hints.append('Mindestens ein Job ist stuck oder in Timeout gelaufen; Runner-Zuordnung, Tags und Timeout prüfen.')
        if 'runner_system_failure' in reasons:
            hints.append('Runner-Systemfehler erkannt; Runner-Logs/Infrastruktur und Ressourcen prüfen.')
        if 'missing_dependency_failure' in reasons:
            hints.append('Fehlende Dependency erkannt; Artefakt- und needs/dependencies-Konfiguration prüfen.')
        if not failed_jobs and status not in {'success', 'running', 'pending'}:
            hints.append('Keine fehlgeschlagenen Jobs gefunden; prüfe Bridges/Downstream-Pipelines oder gelöschte Jobs.')
        return hints
