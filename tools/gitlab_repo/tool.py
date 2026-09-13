"""
title: GitLab Repository Coding Tool
author: OpenAI
version: 0.3.4
required_open_webui_version: 0.4.0
description: Liest und schreibt GitLab-Repositories über die REST-API — Dateien lesen, Branches und Forks anlegen, Änderungen committen, Merge Requests und Issues verwalten.
requirements: requests
license: MIT No Attribution (MIT-0)
original_author: KommI – Kommunale Intelligenz (Boris van Benthem)
source_url: https://gitlab.opencode.de/kommi/adapter/gitlab-adapter

OpenWebUI Tool for reading repository content from GitLab, writing file changes
back via GitLab's REST API using the commits endpoint, managing open
GitLab tasks/issues, listing branches, and creating project forks.
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
#   Datei   : gitlab_adapter.py
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
import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
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
            description='Optional admin/service token fallback if no user token is provided.',
        )
        verify_ssl: bool = Field(
            default=True,
            description='Verify SSL/TLS certificates for GitLab requests.',
        )
        request_timeout_seconds: int = Field(
            default=60,
            description='HTTP timeout for GitLab API calls.',
        )
        max_tree_items: int = Field(
            default=500,
            description='Maximum number of repository tree items to return.',
        )
        max_file_bytes: int = Field(
            default=512_000,
            description='Maximum file size to read through the tool.',
        )
        max_batch_files: int = Field(
            default=20,
            description='Maximum number of files allowed in a single commit operation.',
        )
        max_commit_payload_bytes: int = Field(
            default=2_000_000,
            description='Maximum aggregate content size allowed in a commit request.',
        )
        default_branch_name_prefix: str = Field(
            default='openwebui',
            description='Prefix used when suggesting work branch names.',
        )
        prohibit_direct_default_branch_commits: bool = Field(
            default=True,
            description='Block direct commits to protected/default-style branches.',
        )
        protected_branch_regex: str = Field(
            default=r'^(main|master|develop|dev|production|prod|release.*)$',
            description='Regex for branch names that must not be written to directly.',
        )
        blocked_path_regex: str = Field(
            default=r'(^|/)(\.gitlab-ci\.yml|\.gitlab/|terraform/|helm/|infra/|secrets/)',
            description='Regex for paths blocked from modification.',
        )
        allow_merge_request_creation: bool = Field(
            default=True,
            description='Whether the tool may create merge requests.',
        )
        enforce_ai_generated_commit_prefix: bool = Field(
            default=True,
            description=('Ensure every commit created through this tool is marked as AI-generated.'),
        )
        ai_generated_commit_prefix: str = Field(
            default='AI-generated:',
            description='Required prefix for commit messages created through this tool.',
        )
        enforce_ai_generated_merge_request_text: bool = Field(
            default=True,
            description=('Ensure every merge request created through this tool contains an AI-generated marker.'),
        )
        ai_generated_merge_request_text: str = Field(
            default=('AI-generated: This merge request was created by an AI assistant. The final merge must be performed manually by a human in GitLab.'),
            description='Required marker text for merge requests created through this tool.',
        )
        allow_issue_creation: bool = Field(
            default=True,
            description='Whether the tool may create GitLab issues/tasks.',
        )
        allow_issue_update: bool = Field(
            default=True,
            description='Whether the tool may update existing GitLab issues/tasks.',
        )
        allow_project_fork_creation: bool = Field(
            default=True,
            description='Whether the tool may create GitLab project forks.',
        )
        max_branch_items: int = Field(
            default=100,
            description='Maximum number of repository branches to return per request.',
        )
        max_issue_description_bytes: int = Field(
            default=64_000,
            description='Maximum UTF-8 byte size for a newly created GitLab issue/task description.',
        )
        normalize_issue_escape_sequences: bool = Field(
            default=True,
            description=('Convert literal backslash escape sequences to real whitespace before creating GitLab issues/tasks.'),
        )
        default_remove_source_branch: bool = Field(
            default=False,
            description='Default remove_source_branch value for created merge requests.',
        )
        emit_debug_notifications: bool = Field(
            default=False,
            description='Emit extra debug notifications to the UI.',
        )

    class UserValves(BaseModel):
        gitlab_access_token: str = Field(
            default='',
            description='User-specific GitLab personal access token or project/group token.',
        )
        allowed_project_ids_csv: str = Field(
            default='',
            description='Optional comma-separated allowlist of project IDs the user may access.',
        )
        allowed_path_regex: str = Field(
            default='',
            description='Optional regex limiting which repository paths may be read/written.',
        )
        author_name: str = Field(
            default='',
            description='Optional Git commit author name override.',
        )
        author_email: str = Field(
            default='',
            description='Optional Git commit author email override.',
        )
        require_merge_request_for_writes: bool = Field(
            default=False,
            description='If true, write flows should also open a merge request.',
        )
        dry_run_only: bool = Field(
            default=False,
            description='If true, write operations only validate and preview but do not commit.',
        )
        default_issue_labels_csv: str = Field(
            default='',
            description='Optional comma-separated default labels for newly created issues/tasks.',
        )

    def __init__(self):
        self.valves = self.Valves()

    # -------------------------- Data models --------------------------

    class FileChange(BaseModel):
        file_path: str = Field(..., description='Repository-relative file path.')
        content: Optional[str] = Field(
            default=None,
            description='New file content for create/update. Required except for delete.',
        )
        action: str = Field(
            default='update',
            description='GitLab commit action: create, update, delete, or move.',
        )
        previous_path: Optional[str] = Field(
            default=None,
            description='Previous path for move actions.',
        )
        encoding: str = Field(
            default='text',
            description="Content encoding. Use 'text' or 'base64'.",
        )
        execute_filemode: Optional[bool] = Field(
            default=None,
            description='Optional execute filemode for create/update actions.',
        )

    class TextEdit(BaseModel):
        file_path: str = Field(..., description='Repository-relative file path.')
        operation: str = Field(
            default='replace',
            description=('Edit operation: replace, regex_replace, insert_before, insert_after, prepend, append, create, delete, or move.'),
        )
        old_text: Optional[str] = Field(
            default=None,
            description='Exact text anchor for replace and insert operations.',
        )
        new_text: Optional[str] = Field(
            default=None,
            description='Replacement, inserted text, or full content for create/move.',
        )
        regex: Optional[str] = Field(
            default=None,
            description='Python regular expression for regex_replace.',
        )
        count: int = Field(
            default=1,
            description='Maximum replacements. Use 0 for all occurrences.',
        )
        expected_occurrences: Optional[int] = Field(
            default=1,
            description='Expected match count. Set null to skip the assertion.',
        )
        previous_path: Optional[str] = Field(
            default=None,
            description='Previous path for move operations.',
        )
        create_if_missing: bool = Field(
            default=False,
            description='Create missing target file for text-edit operations.',
        )

    @dataclass
    class _Context:
        eventer: 'EventEmitterHelper'
        helper: 'GitLabHelper'
        user_valves: 'Tools.UserValves'

    # -------------------------- Internal setup --------------------------

    def _build_context(
        self,
        __event_emitter__: Optional[Callable[..., Awaitable[Any]]],
        __user__: Optional[dict],
    ) -> 'Tools._Context':
        eventer = EventEmitterHelper(__event_emitter__, self.valves.emit_debug_notifications)
        user_valves = self._extract_user_valves(__user__)
        helper = GitLabHelper(self.valves, user_valves, eventer)
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

    async def list_projects(
        self,
        search: str = '',
        membership: bool = True,
        owned: bool = False,
        per_page: int = 20,
        simple: bool = True,
        archived: Optional[bool] = None,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """List GitLab projects visible to the current token."""
        ctx = self._build_context(__event_emitter__, __user__)
        await ctx.eventer.status('info', 'Lade GitLab-Projekte …', False)

        params: Dict[str, Any] = {
            'per_page': max(1, min(per_page, 100)),
            'membership': membership,
            'owned': owned,
            'simple': simple,
        }
        if search:
            params['search'] = search
        if archived is not None:
            params['archived'] = archived

        data = ctx.helper.get_json('/projects', params=params)
        projects = [ctx.helper.project_summary(p) for p in data]

        await ctx.eventer.status('success', f'{len(projects)} Projekte geladen.', True)
        return {'count': len(projects), 'projects': projects}

    async def get_repository_tree(
        self,
        project_id: str,
        ref: str = 'main',
        path: str = '',
        recursive: bool = False,
        per_page: int = 100,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """List repository files/directories for a project/ref/path."""
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)
        await ctx.eventer.status('info', f'Lade Repository-Baum für {project_id}@{ref} …', False)

        params = {
            'ref': ref,
            'path': path,
            'recursive': recursive,
            'per_page': min(per_page, self.valves.max_tree_items, 1000),
        }
        items = ctx.helper.get_json(
            f'/projects/{quote(str(project_id), safe="")}/repository/tree',
            params=params,
        )
        await ctx.eventer.status('success', f'{len(items)} Repository-Einträge geladen.', True)
        return {
            'project_id': project_id,
            'ref': ref,
            'path': path,
            'count': len(items),
            'items': items,
        }

    async def read_repository_file(
        self,
        project_id: str,
        file_path: str,
        ref: str = 'main',
        return_base64: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Read one repository file from GitLab."""
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)
        ctx.helper.enforce_path_access(file_path)

        await ctx.eventer.status('info', f'Lese Datei {file_path} aus {project_id}@{ref} …', False)
        result = ctx.helper.read_file(project_id, file_path, ref, return_base64=return_base64)
        await ctx.eventer.status('success', f'Datei {file_path} geladen.', True)
        return result

    async def read_repository_files(
        self,
        project_id: str,
        file_paths: List[str],
        ref: str = 'main',
        return_base64: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Read multiple repository files from GitLab."""
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)

        if not file_paths:
            raise ValueError('file_paths must not be empty')

        results = []
        await ctx.eventer.status('info', f'Lese {len(file_paths)} Dateien aus {project_id}@{ref} …', False)
        for file_path in file_paths:
            ctx.helper.enforce_path_access(file_path)
            results.append(ctx.helper.read_file(project_id, file_path, ref, return_base64=return_base64))

        await ctx.eventer.status('success', f'{len(results)} Dateien geladen.', True)
        return {
            'project_id': project_id,
            'ref': ref,
            'count': len(results),
            'files': results,
        }

    async def create_work_branch(
        self,
        project_id: str,
        branch_name: str,
        from_ref: str = 'main',
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Create a work branch from an existing ref."""
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)
        await ctx.eventer.status('info', f'Erzeuge Branch {branch_name} aus {from_ref} …', False)

        payload = {'branch': branch_name, 'ref': from_ref}
        data = ctx.helper.post_json(
            f'/projects/{quote(str(project_id), safe="")}/repository/branches',
            json_body=payload,
        )

        await ctx.eventer.status('success', f'Branch {branch_name} erzeugt.', True)
        return data

    async def list_repository_branches(
        self,
        project_id: str,
        search: str = '',
        regex: str = '',
        per_page: int = 100,
        page: int = 1,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """List existing branches of a GitLab project.

        Optional filters:
        - search: GitLab branch search term
        - regex: GitLab RE2 regular expression for branch names
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)

        safe_per_page = max(1, min(int(per_page or 100), self.valves.max_branch_items, 100))
        safe_page = max(1, int(page or 1))
        params: Dict[str, Any] = {'per_page': safe_per_page, 'page': safe_page}
        if search.strip():
            params['search'] = search.strip()
        if regex.strip():
            params['regex'] = regex.strip()

        await ctx.eventer.status('info', f'Lade Branches für Projekt {project_id} …', False)
        branches = ctx.helper.get_json(
            f'/projects/{quote(str(project_id), safe="")}/repository/branches',
            params=params,
        )
        summaries = [ctx.helper.branch_summary(branch) for branch in branches]

        await ctx.eventer.status('success', f'{len(summaries)} Branches geladen.', True)
        return {
            'project_id': project_id,
            'page': safe_page,
            'per_page': safe_per_page,
            'count': len(summaries),
            'branches': summaries,
        }

    async def list_branches(
        self,
        project_id: str,
        search: str = '',
        regex: str = '',
        per_page: int = 100,
        page: int = 1,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Alias for list_repository_branches: list existing project branches."""
        return await self.list_repository_branches(
            project_id=project_id,
            search=search,
            regex=regex,
            per_page=per_page,
            page=page,
            __event_emitter__=__event_emitter__,
            __user__=__user__,
        )

    async def fork_project(
        self,
        project_id: str,
        namespace_id: Optional[int] = None,
        namespace_path: str = '',
        path: str = '',
        name: str = '',
        description: str = '',
        visibility: str = '',
        branches: str = '',
        mr_default_target_self: bool = False,
        dry_run: bool = False,
        __event_emitter__=None,
        __event_call__=None,
        __user__=None,
    ) -> dict:
        """Create a fork of a GitLab project.

        The function validates the target project, supports dry runs, and asks
        for UI confirmation via __event_call__ before creating the fork when
        OpenWebUI provides the callback. Optional GitLab fork parameters include
        namespace_id or namespace_path, path, name, description, visibility,
        branches, and mr_default_target_self.
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)
        if not self.valves.allow_project_fork_creation:
            raise ValueError('GitLab project fork creation is disabled by admin valves')

        payload: Dict[str, Any] = {}
        if namespace_id is not None:
            payload['namespace_id'] = int(namespace_id)
        if namespace_path.strip():
            payload['namespace_path'] = namespace_path.strip()
        if path.strip():
            payload['path'] = path.strip()
        if name.strip():
            payload['name'] = name.strip()
        if description.strip():
            payload['description'] = description.strip()
        if visibility.strip():
            normalized_visibility = visibility.strip().lower()
            if normalized_visibility not in {'private', 'internal', 'public'}:
                raise ValueError('visibility must be one of: private, internal, public')
            payload['visibility'] = normalized_visibility
        if branches.strip():
            payload['branches'] = branches.strip()
        if mr_default_target_self:
            payload['mr_default_target_self'] = True

        preview = {
            'project_id': project_id,
            'namespace_id': payload.get('namespace_id'),
            'namespace_path': payload.get('namespace_path'),
            'path': payload.get('path'),
            'name': payload.get('name'),
            'description_set': bool(payload.get('description')),
            'visibility': payload.get('visibility'),
            'branches': payload.get('branches'),
            'mr_default_target_self': payload.get('mr_default_target_self', False),
        }

        await ctx.eventer.status('info', f'Validiere Fork-Anlage für Projekt {project_id} …', False)

        if dry_run or ctx.user_valves.dry_run_only:
            await ctx.eventer.notification('info', 'Dry run: Fork-Anlage validiert. Es wurde kein Fork erstellt.')
            await ctx.eventer.status('success', 'Dry run erfolgreich abgeschlossen.', True)
            return {'ok': True, 'dry_run': True, 'preview': preview}

        if __event_call__ is not None:
            target_hint = namespace_path.strip() or str(namespace_id or 'aktuellen Namespace')
            confirmed = await ctx.eventer.confirmation(
                __event_call__,
                title='GitLab-Projekt fork erstellen?',
                message=(f'Soll für Projekt {project_id} ein GitLab-Fork erstellt werden?\n\nZiel-Namespace: {target_hint}'),
            )
            if not confirmed:
                await ctx.eventer.status('info', 'Fork-Anlage abgebrochen.', True)
                return {'ok': False, 'cancelled': True, 'preview': preview}

        await ctx.eventer.status('info', f'Erstelle Fork für Projekt {project_id} …', False)
        fork = ctx.helper.post_json(
            f'/projects/{quote(str(project_id), safe="")}/fork',
            json_body=payload,
        )
        summary = ctx.helper.fork_summary(fork)
        await ctx.eventer.notification('success', 'GitLab-Fork erfolgreich erstellt.')
        await ctx.eventer.status('success', 'GitLab-Fork erfolgreich erstellt.', True)
        return {'ok': True, 'project_id': project_id, 'fork': summary}

    async def commit_file_changes(
        self,
        project_id: str,
        branch: str,
        commit_message: str,
        file_changes: List[dict],
        start_branch: Optional[str] = None,
        create_branch_if_missing: bool = False,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
        dry_run: bool = False,
        stats: bool = True,
        force: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Commit one or more file changes using GitLab's commits API.
        Needs complete files in file_changes, no code snippets allowed.
        file_changes accepts dict items like:
        [{"file_path": "src/app.py", "content": "...", "action": "update"}]
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)
        ctx.helper.enforce_branch_write_allowed(branch)

        commit_message = ctx.helper.ensure_ai_generated_commit_message(commit_message)
        if not file_changes:
            raise ValueError('file_changes must not be empty')
        if len(file_changes) > self.valves.max_batch_files:
            raise ValueError(f'Too many file changes. Max allowed: {self.valves.max_batch_files}')

        await ctx.eventer.status('info', f'Validiere {len(file_changes)} Dateiänderungen …', False)

        parsed_changes = ctx.helper.normalize_file_changes(file_changes)
        actions, preview = ctx.helper.build_commit_actions(parsed_changes)
        aggregate_size = sum(item.get('content_bytes', 0) for item in preview)
        if aggregate_size > self.valves.max_commit_payload_bytes:
            raise ValueError(f'Commit payload too large: {aggregate_size} bytes exceeds limit {self.valves.max_commit_payload_bytes}')

        if create_branch_if_missing:
            if not start_branch:
                raise ValueError('start_branch is required when create_branch_if_missing is true')
            if not ctx.helper.branch_exists(project_id, branch):
                await ctx.eventer.status(
                    'info',
                    f'Branch {branch} fehlt. Erzeuge ihn aus {start_branch} …',
                    False,
                )
                ctx.helper.create_branch(project_id, branch, start_branch)

        if dry_run or ctx.user_valves.dry_run_only:
            await ctx.eventer.notification(
                'info',
                f'Dry run: {len(actions)} Änderungen validiert. Es wurde kein Commit erzeugt.',
            )
            await ctx.eventer.status('success', 'Dry run erfolgreich abgeschlossen.', True)
            return {
                'ok': True,
                'dry_run': True,
                'project_id': project_id,
                'branch': branch,
                'commit_message': commit_message,
                'actions_preview': preview,
                'actions_count': len(actions),
                'aggregate_content_bytes': aggregate_size,
            }

        branch_preexists = ctx.helper.branch_exists(project_id, branch)

        payload: Dict[str, Any] = {
            'branch': branch,
            'commit_message': commit_message,
            'actions': actions,
            'stats': stats,
            'force': force,
        }
        # IMPORTANT:
        # `start_branch` in the GitLab Commits API is not just informational.
        # It is used to create/reset the target branch from a parent ref.
        # Therefore we must only pass it when the target branch does not yet
        # exist (or when force is explicitly requested for branch reset logic).
        if start_branch and (force or not branch_preexists):
            payload['start_branch'] = start_branch
        resolved_author_name = author_name or ctx.user_valves.author_name
        resolved_author_email = author_email or ctx.user_valves.author_email
        if resolved_author_name:
            payload['author_name'] = resolved_author_name
        if resolved_author_email:
            payload['author_email'] = resolved_author_email

        await ctx.eventer.status('info', f'Erzeuge Commit auf Branch {branch} …', False)
        commit = ctx.helper.post_json(
            f'/projects/{quote(str(project_id), safe="")}/repository/commits',
            json_body=payload,
        )

        result = {
            'ok': True,
            'project_id': project_id,
            'branch': branch,
            'commit_message': commit_message,
            'actions_count': len(actions),
            'actions_preview': preview,
            'aggregate_content_bytes': aggregate_size,
            'commit': {
                'id': commit.get('id'),
                'short_id': commit.get('short_id'),
                'title': commit.get('title'),
                'message': commit.get('message'),
                'web_url': commit.get('web_url'),
                'created_at': commit.get('created_at'),
            },
            'stats': commit.get('stats'),
        }

        await ctx.eventer.notification('success', f'Commit {commit.get("short_id", "")} erfolgreich erstellt.')
        await ctx.eventer.status('success', 'Commit erfolgreich erstellt.', True)
        return result

    async def open_merge_request(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = '',
        remove_source_branch: Optional[bool] = None,
        draft: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Open a merge request for a work branch.

        This tool only creates the merge request. It never performs the final
        merge; merging must remain a manual human action in GitLab.
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)
        if not self.valves.allow_merge_request_creation:
            raise ValueError('Merge request creation is disabled by admin valves')

        mr_title = title.strip()
        if draft and not mr_title.lower().startswith(('draft:', 'wip:')):
            mr_title = f'Draft: {mr_title}'

        await ctx.eventer.status(
            'info',
            f'Erzeuge Merge Request {source_branch} → {target_branch} …',
            False,
        )
        mr_description = ctx.helper.ensure_ai_generated_merge_request_description(description)
        payload = {
            'source_branch': source_branch,
            'target_branch': target_branch,
            'title': mr_title,
            'description': mr_description,
            'remove_source_branch': (self.valves.default_remove_source_branch if remove_source_branch is None else remove_source_branch),
        }
        mr = ctx.helper.post_json(
            f'/projects/{quote(str(project_id), safe="")}/merge_requests',
            json_body=payload,
        )
        await ctx.eventer.notification('success', 'Merge Request erfolgreich erstellt.')
        await ctx.eventer.status('success', 'Merge Request erfolgreich erstellt.', True)
        return mr

    async def list_merge_requests(
        self,
        project_id: str,
        state: str = 'opened',
        source_branch: str = '',
        target_branch: str = '',
        search: str = '',
        labels: str = '',
        author_id: Optional[int] = None,
        assignee_id: Optional[int] = None,
        reviewer_id: Optional[int] = None,
        milestone: str = '',
        created_after: str = '',
        updated_after: str = '',
        order_by: str = 'updated_at',
        sort: str = 'desc',
        per_page: int = 50,
        page: int = 1,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """List GitLab merge requests for a project.

        Supports common read filters such as state, source_branch,
        target_branch, search, labels, author_id, assignee_id, reviewer_id,
        milestone, created_after, and updated_after. The result contains
        compact merge request summaries without full descriptions.
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)

        safe_per_page = max(1, min(int(per_page or 50), 100))
        safe_page = max(1, int(page or 1))
        normalized_state = (state or 'opened').strip().lower()
        if normalized_state not in {'opened', 'closed', 'locked', 'merged', 'all'}:
            raise ValueError('state must be one of: opened, closed, locked, merged, all')

        params: Dict[str, Any] = {
            'state': normalized_state,
            'per_page': safe_per_page,
            'page': safe_page,
            'order_by': order_by if order_by in {'created_at', 'updated_at', 'title'} else 'updated_at',
            'sort': sort if sort in {'asc', 'desc'} else 'desc',
        }
        if source_branch.strip():
            params['source_branch'] = source_branch.strip()
        if target_branch.strip():
            params['target_branch'] = target_branch.strip()
        if search.strip():
            params['search'] = search.strip()
        if labels.strip():
            params['labels'] = labels.strip()
        if author_id is not None:
            params['author_id'] = int(author_id)
        if assignee_id is not None:
            params['assignee_id'] = int(assignee_id)
        if reviewer_id is not None:
            params['reviewer_id'] = int(reviewer_id)
        if milestone.strip():
            params['milestone'] = milestone.strip()
        if created_after.strip():
            params['created_after'] = created_after.strip()
        if updated_after.strip():
            params['updated_after'] = updated_after.strip()

        await ctx.eventer.status('info', f'Lade Merge Requests für Projekt {project_id} …', False)
        merge_requests = ctx.helper.get_json(
            f'/projects/{quote(str(project_id), safe="")}/merge_requests',
            params=params,
        )
        summaries = [ctx.helper.merge_request_summary(mr) for mr in merge_requests]

        await ctx.eventer.status('success', f'{len(summaries)} Merge Requests geladen.', True)
        return {
            'project_id': project_id,
            'state': normalized_state,
            'page': safe_page,
            'per_page': safe_per_page,
            'count': len(summaries),
            'merge_requests': summaries,
        }

    async def get_merge_request(
        self,
        project_id: str,
        merge_request_iid: int,
        include_raw: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Read one GitLab merge request completely by project ID and MR IID.

        The method uses the project-internal merge request IID, for example
        `1` for `!1`, not the global GitLab database ID. The raw GitLab API
        payload is omitted by default and can be included with include_raw=True.
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)

        safe_iid = int(merge_request_iid)
        if safe_iid <= 0:
            raise ValueError('merge_request_iid must be a positive integer')

        await ctx.eventer.status(
            'info',
            f'Lade GitLab-Merge-Request !{safe_iid} für Projekt {project_id} …',
            False,
        )
        mr = ctx.helper.get_json(f'/projects/{quote(str(project_id), safe="")}/merge_requests/{safe_iid}')
        result = {
            'ok': True,
            'project_id': project_id,
            'merge_request_iid': safe_iid,
            'merge_request': ctx.helper.merge_request_full(mr, include_raw=include_raw),
        }

        await ctx.eventer.status(
            'success',
            f'GitLab-Merge-Request !{safe_iid} vollständig geladen.',
            True,
        )
        return result

    async def read_merge_request(
        self,
        project_id: str,
        merge_request_iid: int,
        include_raw: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Alias for get_merge_request: read one GitLab merge request completely."""
        return await self.get_merge_request(
            project_id=project_id,
            merge_request_iid=merge_request_iid,
            include_raw=include_raw,
            __event_emitter__=__event_emitter__,
            __user__=__user__,
        )

    async def apply_text_edits_and_commit(
        self,
        project_id: str,
        branch: str,
        commit_message: str,
        edits: List[dict],
        start_branch: Optional[str] = None,
        create_branch_if_missing: bool = False,
        source_ref: Optional[str] = None,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
        dry_run: bool = False,
        stats: bool = True,
        force: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Apply structured text edits and commit the resulting full files.

        This method is intentionally more LLM-friendly than unified diffs. The
        model only has to provide stable anchors or exact text snippets instead
        of correct hunk line numbers and context. Each edit is validated against
        the current repository content before a commit action is created.

        Supported operations:
        - replace: replace exact old_text with new_text
        - regex_replace: replace regex matches with new_text
        - insert_before / insert_after: insert new_text around old_text anchor
        - prepend / append: add new_text at file start/end
        - create: create a new file with new_text
        - delete: delete an existing file
        - move: move previous_path to file_path, optionally replacing content
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)
        ctx.helper.enforce_branch_write_allowed(branch)

        commit_message = ctx.helper.ensure_ai_generated_commit_message(commit_message)
        if not edits:
            raise ValueError('edits must not be empty')
        if len(edits) > self.valves.max_batch_files:
            raise ValueError(f'Too many edited files. Max allowed: {self.valves.max_batch_files}')

        await ctx.eventer.status('info', f'Validating {len(edits)} structured edit(s) ...', False)

        branch_preexists = ctx.helper.branch_exists(project_id, branch)
        effective_source_ref = source_ref or (branch if branch_preexists else start_branch)
        if not effective_source_ref:
            raise ValueError('source_ref or start_branch is required when the target branch does not exist')

        # Keep dry runs side-effect free.
        if create_branch_if_missing and not branch_preexists and not (dry_run or ctx.user_valves.dry_run_only):
            if not start_branch:
                raise ValueError('start_branch is required when create_branch_if_missing is true')
            await ctx.eventer.status('info', f'Branch {branch} is missing. Creating it from {start_branch} ...', False)
            ctx.helper.create_branch(project_id, branch, start_branch)
            effective_source_ref = branch

        parsed_edits = ctx.helper.normalize_text_edits(edits)
        file_changes = ctx.helper.build_file_changes_from_text_edits(
            project_id=project_id,
            ref=effective_source_ref,
            edits=parsed_edits,
        )

        commit_result = await self.commit_file_changes(
            project_id=project_id,
            branch=branch,
            commit_message=commit_message,
            file_changes=file_changes,
            start_branch=start_branch,
            create_branch_if_missing=False,
            author_name=author_name,
            author_email=author_email,
            dry_run=dry_run,
            stats=stats,
            force=force,
            __event_emitter__=__event_emitter__,
            __user__=__user__,
        )
        commit_result['text_edits_count'] = len(parsed_edits)
        commit_result['source_ref'] = effective_source_ref
        return commit_result

    async def list_open_tasks(
        self,
        project_id: str,
        search: str = '',
        labels: str = '',
        assignee_id: Optional[int] = None,
        author_id: Optional[int] = None,
        milestone: str = '',
        due_date: str = '',
        created_after: str = '',
        updated_after: str = '',
        order_by: str = 'updated_at',
        sort: str = 'desc',
        per_page: int = 50,
        page: int = 1,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Read open GitLab tasks/issues for a project.

        Uses GitLab project issues with state=opened. Optional filters include
        search, labels (comma-separated), assignee_id, author_id, milestone,
        due_date, created_after, and updated_after.
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)

        safe_per_page = max(1, min(int(per_page or 50), 100))
        safe_page = max(1, int(page or 1))
        await ctx.eventer.status('info', f'Lade offene GitLab-Aufgaben für Projekt {project_id} …', False)

        params: Dict[str, Any] = {
            'state': 'opened',
            'per_page': safe_per_page,
            'page': safe_page,
            'order_by': order_by if order_by in {'created_at', 'updated_at', 'priority', 'due_date', 'relative_position', 'label_priority', 'milestone_due', 'popularity', 'weight'} else 'updated_at',
            'sort': sort if sort in {'asc', 'desc'} else 'desc',
        }
        if search.strip():
            params['search'] = search.strip()
        if labels.strip():
            params['labels'] = labels.strip()
        if assignee_id is not None:
            params['assignee_id'] = assignee_id
        if author_id is not None:
            params['author_id'] = author_id
        if milestone.strip():
            params['milestone'] = milestone.strip()
        if due_date.strip():
            params['due_date'] = due_date.strip()
        if created_after.strip():
            params['created_after'] = created_after.strip()
        if updated_after.strip():
            params['updated_after'] = updated_after.strip()

        issues = ctx.helper.get_json(
            f'/projects/{quote(str(project_id), safe="")}/issues',
            params=params,
        )
        tasks = [ctx.helper.issue_summary(issue) for issue in issues]

        await ctx.eventer.status('success', f'{len(tasks)} offene GitLab-Aufgaben geladen.', True)
        return {
            'project_id': project_id,
            'state': 'opened',
            'page': safe_page,
            'per_page': safe_per_page,
            'count': len(tasks),
            'tasks': tasks,
        }

    async def list_open_issues(
        self,
        project_id: str,
        search: str = '',
        labels: str = '',
        assignee_id: Optional[int] = None,
        author_id: Optional[int] = None,
        milestone: str = '',
        due_date: str = '',
        created_after: str = '',
        updated_after: str = '',
        order_by: str = 'updated_at',
        sort: str = 'desc',
        per_page: int = 50,
        page: int = 1,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Alias for list_open_tasks: read open GitLab project issues."""
        return await self.list_open_tasks(
            project_id=project_id,
            search=search,
            labels=labels,
            assignee_id=assignee_id,
            author_id=author_id,
            milestone=milestone,
            due_date=due_date,
            created_after=created_after,
            updated_after=updated_after,
            order_by=order_by,
            sort=sort,
            per_page=per_page,
            page=page,
            __event_emitter__=__event_emitter__,
            __user__=__user__,
        )

    async def get_issue(
        self,
        project_id: str,
        issue_iid: int,
        include_raw: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Read one GitLab project issue completely by project ID and issue IID.

        Unlike list_open_issues/list_open_tasks, this method calls GitLab's
        single-issue endpoint and returns a complete structured issue payload,
        including the description and detailed metadata. Raw API output is not
        included by default to avoid duplicating the same content in responses.
        Set include_raw=True only when the original GitLab payload is explicitly
        needed.
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)

        safe_iid = int(issue_iid)
        if safe_iid <= 0:
            raise ValueError('issue_iid must be a positive integer')

        await ctx.eventer.status('info', f'Lade GitLab-Issue #{safe_iid} für Projekt {project_id} …', False)
        issue = ctx.helper.get_json(f'/projects/{quote(str(project_id), safe="")}/issues/{safe_iid}')
        result = {
            'ok': True,
            'project_id': project_id,
            'issue_iid': safe_iid,
            'issue': ctx.helper.issue_full(issue, include_raw=include_raw),
        }

        await ctx.eventer.status('success', f'GitLab-Issue #{safe_iid} vollständig geladen.', True)
        return result

    async def read_issue(
        self,
        project_id: str,
        issue_iid: int,
        include_raw: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """Alias for get_issue: read one GitLab project issue completely."""
        return await self.get_issue(
            project_id=project_id,
            issue_iid=issue_iid,
            include_raw=include_raw,
            __event_emitter__=__event_emitter__,
            __user__=__user__,
        )

    async def create_task(
        self,
        project_id: str,
        title: str,
        description: str = '',
        labels: str = '',
        assignee_ids: Optional[List[int]] = None,
        milestone_id: Optional[int] = None,
        due_date: str = '',
        confidential: bool = False,
        dry_run: bool = False,
        __event_emitter__=None,
        __event_call__=None,
        __user__=None,
    ) -> dict:
        """Create a new GitLab task/issue in a project.

        The method validates inputs, emits status updates, supports dry runs,
        and asks for UI confirmation via __event_call__ before writing when
        OpenWebUI provides the callback.
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)
        if not self.valves.allow_issue_creation:
            raise ValueError('GitLab issue/task creation is disabled by admin valves')

        clean_title = ctx.helper.normalize_issue_text(title or '', single_line=True)
        if not clean_title:
            raise ValueError('title must not be empty')
        clean_description = ctx.helper.normalize_issue_text(description or '', single_line=False)
        description_bytes = len(clean_description.encode('utf-8'))
        if description_bytes > self.valves.max_issue_description_bytes:
            raise ValueError(f'Issue description too large: {description_bytes} bytes exceeds limit {self.valves.max_issue_description_bytes}')

        requested_labels = ctx.helper.normalize_csv(labels)
        default_labels = ctx.helper.normalize_csv(ctx.user_valves.default_issue_labels_csv)
        merged_labels = ctx.helper.merge_unique_strings(default_labels + requested_labels)
        normalized_assignee_ids = ctx.helper.normalize_int_list(assignee_ids or [])

        payload: Dict[str, Any] = {
            'title': clean_title,
            'description': clean_description,
            'confidential': confidential,
        }
        if merged_labels:
            payload['labels'] = ','.join(merged_labels)
        if normalized_assignee_ids:
            payload['assignee_ids'] = normalized_assignee_ids
        if milestone_id is not None:
            payload['milestone_id'] = int(milestone_id)
        if due_date.strip():
            payload['due_date'] = due_date.strip()

        preview = {
            'project_id': project_id,
            'title': clean_title,
            'description_bytes': description_bytes,
            'labels': merged_labels,
            'assignee_ids': normalized_assignee_ids,
            'milestone_id': milestone_id,
            'due_date': due_date.strip() or None,
            'confidential': confidential,
        }

        await ctx.eventer.status('info', f'Validiere neue GitLab-Aufgabe für Projekt {project_id} …', False)

        if dry_run or ctx.user_valves.dry_run_only:
            await ctx.eventer.notification('info', 'Dry run: GitLab-Aufgabe validiert. Es wurde keine Aufgabe angelegt.')
            await ctx.eventer.status('success', 'Dry run erfolgreich abgeschlossen.', True)
            return {'ok': True, 'dry_run': True, 'preview': preview}

        if __event_call__ is not None:
            confirmed = await ctx.eventer.confirmation(
                __event_call__,
                title='GitLab-Aufgabe anlegen?',
                message=(f'Soll im Projekt {project_id} eine neue GitLab-Aufgabe angelegt werden?\n\nTitel: {clean_title}'),
            )
            if not confirmed:
                await ctx.eventer.status('info', 'Anlegen der GitLab-Aufgabe abgebrochen.', True)
                return {'ok': False, 'cancelled': True, 'preview': preview}

        await ctx.eventer.status('info', f'Lege GitLab-Aufgabe in Projekt {project_id} an …', False)
        issue = ctx.helper.post_json(
            f'/projects/{quote(str(project_id), safe="")}/issues',
            json_body=payload,
        )
        result = {'ok': True, 'project_id': project_id, 'task': ctx.helper.issue_summary(issue)}
        await ctx.eventer.notification('success', f'GitLab-Aufgabe #{issue.get("iid", "")} erfolgreich angelegt.')
        await ctx.eventer.status('success', 'GitLab-Aufgabe erfolgreich angelegt.', True)
        return result

    async def create_issue(
        self,
        project_id: str,
        title: str,
        description: str = '',
        labels: str = '',
        assignee_ids: Optional[List[int]] = None,
        milestone_id: Optional[int] = None,
        due_date: str = '',
        confidential: bool = False,
        dry_run: bool = False,
        __event_emitter__=None,
        __event_call__=None,
        __user__=None,
    ) -> dict:
        """Alias for create_task: create a GitLab project issue."""
        return await self.create_task(
            project_id=project_id,
            title=title,
            description=description,
            labels=labels,
            assignee_ids=assignee_ids,
            milestone_id=milestone_id,
            due_date=due_date,
            confidential=confidential,
            dry_run=dry_run,
            __event_emitter__=__event_emitter__,
            __event_call__=__event_call__,
            __user__=__user__,
        )

    async def update_issue(
        self,
        project_id: str,
        issue_iid: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        labels: Optional[str] = None,
        add_labels: str = '',
        remove_labels: str = '',
        assignee_ids: Optional[List[int]] = None,
        milestone_id: Optional[int] = None,
        due_date: Optional[str] = None,
        confidential: Optional[bool] = None,
        discussion_locked: Optional[bool] = None,
        state_event: str = '',
        dry_run: bool = False,
        __event_emitter__=None,
        __event_call__=None,
        __user__=None,
    ) -> dict:
        """Update an existing GitLab project issue by project ID and issue IID.

        Supports common GitLab issue attributes such as title, description,
        labels, add_labels, remove_labels, assignee_ids, milestone_id,
        due_date, confidential, discussion_locked, and state_event
        ("close" or "reopen"). The method validates inputs, supports dry runs,
        and asks for UI confirmation via __event_call__ before writing when
        OpenWebUI provides the callback.
        """
        ctx = self._build_context(__event_emitter__, __user__)
        ctx.helper.enforce_project_access(project_id)
        if not self.valves.allow_issue_update:
            raise ValueError('GitLab issue/task updates are disabled by admin valves')

        safe_iid = int(issue_iid)
        if safe_iid <= 0:
            raise ValueError('issue_iid must be a positive integer')

        payload: Dict[str, Any] = {}
        preview: Dict[str, Any] = {'project_id': project_id, 'issue_iid': safe_iid}

        if title is not None:
            clean_title = ctx.helper.normalize_issue_text(title, single_line=True)
            if not clean_title:
                raise ValueError('title must not be empty when provided')
            payload['title'] = clean_title
            preview['title'] = clean_title

        if description is not None:
            clean_description = ctx.helper.normalize_issue_text(description, single_line=False)
            description_bytes = len(clean_description.encode('utf-8'))
            if description_bytes > self.valves.max_issue_description_bytes:
                raise ValueError(f'Issue description too large: {description_bytes} bytes exceeds limit {self.valves.max_issue_description_bytes}')
            payload['description'] = clean_description
            preview['description_bytes'] = description_bytes

        if labels is not None:
            normalized_labels = ctx.helper.normalize_csv(labels)
            payload['labels'] = ','.join(normalized_labels)
            preview['labels'] = normalized_labels

        normalized_add_labels = ctx.helper.normalize_csv(add_labels)
        if normalized_add_labels:
            payload['add_labels'] = ','.join(normalized_add_labels)
            preview['add_labels'] = normalized_add_labels

        normalized_remove_labels = ctx.helper.normalize_csv(remove_labels)
        if normalized_remove_labels:
            payload['remove_labels'] = ','.join(normalized_remove_labels)
            preview['remove_labels'] = normalized_remove_labels

        if assignee_ids is not None:
            normalized_assignee_ids = ctx.helper.normalize_int_list(assignee_ids)
            payload['assignee_ids'] = normalized_assignee_ids
            preview['assignee_ids'] = normalized_assignee_ids

        if milestone_id is not None:
            parsed_milestone_id = int(milestone_id)
            if parsed_milestone_id < 0:
                raise ValueError('milestone_id must be >= 0 when provided')
            payload['milestone_id'] = parsed_milestone_id
            preview['milestone_id'] = parsed_milestone_id

        if due_date is not None:
            clean_due_date = due_date.strip()
            payload['due_date'] = clean_due_date
            preview['due_date'] = clean_due_date or None

        if confidential is not None:
            payload['confidential'] = bool(confidential)
            preview['confidential'] = bool(confidential)

        if discussion_locked is not None:
            payload['discussion_locked'] = bool(discussion_locked)
            preview['discussion_locked'] = bool(discussion_locked)

        if state_event.strip():
            normalized_state_event = state_event.strip().lower()
            if normalized_state_event not in {'close', 'reopen'}:
                raise ValueError("state_event must be either 'close' or 'reopen'")
            payload['state_event'] = normalized_state_event
            preview['state_event'] = normalized_state_event

        if not payload:
            raise ValueError('At least one issue field must be provided for update')

        await ctx.eventer.status('info', f'Validiere Aktualisierung für GitLab-Issue #{safe_iid} in Projekt {project_id} …', False)

        if dry_run or ctx.user_valves.dry_run_only:
            await ctx.eventer.notification(
                'info',
                'Dry run: GitLab-Issue-Aktualisierung validiert. Es wurde nichts geändert.',
            )
            await ctx.eventer.status('success', 'Dry run erfolgreich abgeschlossen.', True)
            return {'ok': True, 'dry_run': True, 'preview': preview}

        if __event_call__ is not None:
            summary_parts = []
            if 'title' in preview:
                summary_parts.append(f'Titel: {preview["title"]}')
            if 'state_event' in preview:
                summary_parts.append(f'Statusaktion: {preview["state_event"]}')
            if 'labels' in preview:
                summary_parts.append(f'Labels ersetzen: {", ".join(preview["labels"]) or "(leer)"}')
            if 'add_labels' in preview:
                summary_parts.append(f'Labels hinzufügen: {", ".join(preview["add_labels"])}')
            if 'remove_labels' in preview:
                summary_parts.append(f'Labels entfernen: {", ".join(preview["remove_labels"])}')
            summary = '\n'.join(summary_parts) or f'{len(payload)} Feld(er) ändern'
            confirmed = await ctx.eventer.confirmation(
                __event_call__,
                title='GitLab-Issue aktualisieren?',
                message=(f'Soll Issue #{safe_iid} im Projekt {project_id} aktualisiert werden?\n\n{summary}'),
            )
            if not confirmed:
                await ctx.eventer.status('info', 'Aktualisierung des GitLab-Issues abgebrochen.', True)
                return {'ok': False, 'cancelled': True, 'preview': preview}

        await ctx.eventer.status('info', f'Aktualisiere GitLab-Issue #{safe_iid} in Projekt {project_id} …', False)
        issue = ctx.helper.put_json(
            f'/projects/{quote(str(project_id), safe="")}/issues/{safe_iid}',
            json_body=payload,
        )
        result = {
            'ok': True,
            'project_id': project_id,
            'issue_iid': safe_iid,
            'updated_fields': sorted(payload.keys()),
            'issue': ctx.helper.issue_summary(issue),
        }
        await ctx.eventer.notification('success', f'GitLab-Issue #{issue.get("iid", safe_iid)} erfolgreich aktualisiert.')
        await ctx.eventer.status('success', 'GitLab-Issue erfolgreich aktualisiert.', True)
        return result

    async def update_task(
        self,
        project_id: str,
        issue_iid: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        labels: Optional[str] = None,
        add_labels: str = '',
        remove_labels: str = '',
        assignee_ids: Optional[List[int]] = None,
        milestone_id: Optional[int] = None,
        due_date: Optional[str] = None,
        confidential: Optional[bool] = None,
        discussion_locked: Optional[bool] = None,
        state_event: str = '',
        dry_run: bool = False,
        __event_emitter__=None,
        __event_call__=None,
        __user__=None,
    ) -> dict:
        """Alias for update_issue: update an existing GitLab project issue/task."""
        return await self.update_issue(
            project_id=project_id,
            issue_iid=issue_iid,
            title=title,
            description=description,
            labels=labels,
            add_labels=add_labels,
            remove_labels=remove_labels,
            assignee_ids=assignee_ids,
            milestone_id=milestone_id,
            due_date=due_date,
            confidential=confidential,
            discussion_locked=discussion_locked,
            state_event=state_event,
            dry_run=dry_run,
            __event_emitter__=__event_emitter__,
            __event_call__=__event_call__,
            __user__=__user__,
        )

    async def evolve_files_and_commit(
        self,
        project_id: str,
        base_branch: str,
        work_branch: str,
        commit_message: str,
        file_changes: List[dict],
        merge_request_title: str = '',
        merge_request_description: str = '',
        create_branch_if_missing: bool = True,
        open_merge_request_after_commit: bool = False,
        dry_run: bool = False,
        __event_emitter__=None,
        __user__=None,
    ) -> dict:
        """High-level workflow: ensure branch, commit changes, optionally open an MR."""
        ctx = self._build_context(__event_emitter__, __user__)
        await ctx.eventer.status('info', 'Starte Schreib-Workflow für GitLab-Repository …', False)

        commit_result = await self.commit_file_changes(
            project_id=project_id,
            branch=work_branch,
            commit_message=commit_message,
            file_changes=file_changes,
            start_branch=base_branch,
            create_branch_if_missing=create_branch_if_missing,
            dry_run=dry_run,
            __event_emitter__=__event_emitter__,
            __user__=__user__,
        )

        result = {'ok': True, 'commit_result': commit_result}

        should_open_mr = not commit_result.get('dry_run', False) and (open_merge_request_after_commit or ctx.user_valves.require_merge_request_for_writes)
        if should_open_mr:
            mr_title = merge_request_title.strip() or commit_message.strip()
            mr = await self.open_merge_request(
                project_id=project_id,
                source_branch=work_branch,
                target_branch=base_branch,
                title=mr_title,
                description=merge_request_description,
                __event_emitter__=__event_emitter__,
                __user__=__user__,
            )
            result['merge_request'] = {
                'iid': mr.get('iid'),
                'title': mr.get('title'),
                'web_url': mr.get('web_url'),
                'state': mr.get('state'),
            }

        await ctx.eventer.status('success', 'GitLab-Schreib-Workflow abgeschlossen.', True)
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
        await self._emit(
            {
                'type': 'notification',
                'data': {
                    'type': level,
                    'content': content,
                },
            }
        )

    async def confirmation(
        self,
        event_call: Callable[..., Awaitable[Any]],
        title: str,
        message: str,
    ) -> bool:
        result = event_call(
            {
                'type': 'confirmation',
                'data': {'title': title, 'message': message},
            }
        )
        if asyncio.iscoroutine(result):
            result = await result
        return bool(result)

    async def debug(self, content: str):
        if not self.debug_enabled:
            return
        await self.notification('info', f'DEBUG: {content}')


class GitLabHelper:
    def __init__(
        self,
        valves: Tools.Valves,
        user_valves: Tools.UserValves,
        eventer: EventEmitterHelper,
    ):
        self.valves = valves
        self.user_valves = user_valves
        self.eventer = eventer
        self.base_url = f'{self.valves.gitlab_url.rstrip("/")}{self.valves.api_path}'
        self.session = requests.Session()
        token = self.user_valves.gitlab_access_token or self.valves.admin_access_token
        if not token:
            raise ValueError('No GitLab access token configured in UserValves or Valves')
        self.session.headers.update(
            {
                'PRIVATE-TOKEN': token,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )

        # Avoid noisy warnings only if SSL verification is intentionally disabled.
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

    def post_json(self, endpoint: str, json_body: dict) -> Any:
        response = self._request('POST', endpoint, data=json.dumps(json_body))
        return response.json()

    def put_json(self, endpoint: str, json_body: dict) -> Any:
        response = self._request('PUT', endpoint, data=json.dumps(json_body))
        return response.json()

    def _safe_error_text(self, response: requests.Response) -> str:
        try:
            payload = response.json()
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            text = response.text.strip()
            return text[:1000] if text else 'Unknown error'

    def project_summary(self, item: dict) -> dict:
        return {
            'id': item.get('id'),
            'name': item.get('name'),
            'name_with_namespace': item.get('name_with_namespace'),
            'path_with_namespace': item.get('path_with_namespace'),
            'default_branch': item.get('default_branch'),
            'web_url': item.get('web_url'),
            'visibility': item.get('visibility'),
            'archived': item.get('archived'),
        }

    def branch_summary(self, item: dict) -> dict:
        commit = item.get('commit') or {}
        return {
            'name': item.get('name'),
            'merged': item.get('merged'),
            'protected': item.get('protected'),
            'default': item.get('default'),
            'developers_can_push': item.get('developers_can_push'),
            'developers_can_merge': item.get('developers_can_merge'),
            'can_push': item.get('can_push'),
            'web_url': item.get('web_url'),
            'commit': {
                'id': commit.get('id'),
                'short_id': commit.get('short_id'),
                'title': commit.get('title'),
                'created_at': commit.get('created_at'),
                'author_name': commit.get('author_name'),
                'web_url': commit.get('web_url'),
            }
            if commit
            else None,
        }

    def user_summary(self, item: dict) -> Optional[dict]:
        if not item:
            return None
        return {
            'id': item.get('id'),
            'name': item.get('name'),
            'username': item.get('username'),
            'web_url': item.get('web_url'),
            'avatar_url': item.get('avatar_url'),
        }

    def merge_request_summary(self, item: dict) -> dict:
        return {
            'id': item.get('id'),
            'iid': item.get('iid'),
            'project_id': item.get('project_id'),
            'title': item.get('title'),
            'state': item.get('state'),
            'web_url': item.get('web_url'),
            'source_branch': item.get('source_branch'),
            'target_branch': item.get('target_branch'),
            'work_in_progress': item.get('work_in_progress'),
            'draft': item.get('draft'),
            'merge_status': item.get('merge_status'),
            'detailed_merge_status': item.get('detailed_merge_status'),
            'has_conflicts': item.get('has_conflicts'),
            'blocking_discussions_resolved': item.get('blocking_discussions_resolved'),
            'should_remove_source_branch': item.get('should_remove_source_branch'),
            'force_remove_source_branch': item.get('force_remove_source_branch'),
            'squash': item.get('squash'),
            'labels': item.get('labels') or [],
            'author': self.user_summary(item.get('author') or {}),
            'assignees': [self.user_summary(user) for user in (item.get('assignees') or [])],
            'reviewers': [self.user_summary(user) for user in (item.get('reviewers') or [])],
            'merge_user': self.user_summary(item.get('merge_user') or {}),
            'merged_by': self.user_summary(item.get('merged_by') or {}),
            'closed_by': self.user_summary(item.get('closed_by') or {}),
            'references': item.get('references'),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at'),
            'merged_at': item.get('merged_at'),
            'closed_at': item.get('closed_at'),
        }

    def merge_request_full(self, item: dict, include_raw: bool = False) -> dict:
        result = self.merge_request_summary(item)
        result.update(
            {
                'description': item.get('description'),
                'source_project_id': item.get('source_project_id'),
                'target_project_id': item.get('target_project_id'),
                'subscribed': item.get('subscribed'),
                'user_notes_count': item.get('user_notes_count'),
                'upvotes': item.get('upvotes'),
                'downvotes': item.get('downvotes'),
                'changes_count': item.get('changes_count'),
                'latest_build_started_at': item.get('latest_build_started_at'),
                'latest_build_finished_at': item.get('latest_build_finished_at'),
                'first_deployed_to_production_at': item.get('first_deployed_to_production_at'),
                'prepared_at': item.get('prepared_at'),
                'merge_after': item.get('merge_after'),
                'merged_commit_sha': item.get('merged_commit_sha'),
                'squash_commit_sha': item.get('squash_commit_sha'),
                'sha': item.get('sha'),
                'diff_refs': item.get('diff_refs'),
                'task_completion_status': item.get('task_completion_status'),
                'time_stats': item.get('time_stats'),
                'milestone': item.get('milestone'),
                'head_pipeline': item.get('head_pipeline'),
                'pipeline': item.get('pipeline'),
                'approvals_before_merge': item.get('approvals_before_merge'),
                'reference': item.get('reference'),
                'references': item.get('references'),
                'links': item.get('_links'),
            }
        )
        if include_raw:
            result['raw'] = item
        return result

    def fork_summary(self, item: dict) -> dict:
        namespace = item.get('namespace') or {}
        owner = item.get('owner') or {}
        return {
            'id': item.get('id'),
            'name': item.get('name'),
            'name_with_namespace': item.get('name_with_namespace'),
            'path': item.get('path'),
            'path_with_namespace': item.get('path_with_namespace'),
            'default_branch': item.get('default_branch'),
            'web_url': item.get('web_url'),
            'ssh_url_to_repo': item.get('ssh_url_to_repo'),
            'http_url_to_repo': item.get('http_url_to_repo'),
            'visibility': item.get('visibility'),
            'forked_from_project': item.get('forked_from_project'),
            'namespace': {
                'id': namespace.get('id'),
                'name': namespace.get('name'),
                'path': namespace.get('path'),
                'full_path': namespace.get('full_path'),
                'kind': namespace.get('kind'),
            }
            if namespace
            else None,
            'owner': {
                'id': owner.get('id'),
                'name': owner.get('name'),
                'username': owner.get('username'),
                'web_url': owner.get('web_url'),
            }
            if owner
            else None,
        }

    def issue_summary(self, item: dict) -> dict:
        assignees = item.get('assignees') or []
        milestone = item.get('milestone') or {}
        author = item.get('author') or {}
        return {
            'id': item.get('id'),
            'iid': item.get('iid'),
            'project_id': item.get('project_id'),
            'title': item.get('title'),
            'state': item.get('state'),
            'web_url': item.get('web_url'),
            'labels': item.get('labels') or [],
            'assignees': [
                {
                    'id': assignee.get('id'),
                    'name': assignee.get('name'),
                    'username': assignee.get('username'),
                    'web_url': assignee.get('web_url'),
                }
                for assignee in assignees
            ],
            'author': {
                'id': author.get('id'),
                'name': author.get('name'),
                'username': author.get('username'),
                'web_url': author.get('web_url'),
            }
            if author
            else None,
            'milestone': {
                'id': milestone.get('id'),
                'iid': milestone.get('iid'),
                'title': milestone.get('title'),
                'due_date': milestone.get('due_date'),
            }
            if milestone
            else None,
            'due_date': item.get('due_date'),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at'),
            'closed_at': item.get('closed_at'),
            'confidential': item.get('confidential'),
            'discussion_locked': item.get('discussion_locked'),
            'upvotes': item.get('upvotes'),
            'downvotes': item.get('downvotes'),
            'references': item.get('references'),
        }

    def issue_full(self, item: dict, include_raw: bool = False) -> dict:
        """Return a complete, structured representation of a GitLab issue.

        The normalized top-level keys below make common fields easy for the LLM
        and UI to consume. The unmodified GitLab API payload can be included on
        request via include_raw=True, but is omitted by default to avoid
        duplicating content such as the issue description.
        """
        assignees = item.get('assignees') or []
        assignee = item.get('assignee') or {}
        milestone = item.get('milestone') or {}
        author = item.get('author') or {}
        closed_by = item.get('closed_by') or {}

        result = {
            'id': item.get('id'),
            'iid': item.get('iid'),
            'project_id': item.get('project_id'),
            'title': item.get('title'),
            'description': item.get('description'),
            'state': item.get('state'),
            'state_reason': item.get('state_reason'),
            'issue_type': item.get('issue_type'),
            'web_url': item.get('web_url'),
            'labels': item.get('labels') or [],
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at'),
            'closed_at': item.get('closed_at'),
            'due_date': item.get('due_date'),
            'confidential': item.get('confidential'),
            'discussion_locked': item.get('discussion_locked'),
            'imported': item.get('imported'),
            'imported_from': item.get('imported_from'),
            'severity': item.get('severity'),
            'upvotes': item.get('upvotes'),
            'downvotes': item.get('downvotes'),
            'merge_requests_count': item.get('merge_requests_count'),
            'user_notes_count': item.get('user_notes_count'),
            'blocking_issues_count': item.get('blocking_issues_count'),
            'has_tasks': item.get('has_tasks'),
            'task_status': item.get('task_status'),
            'task_completion_status': item.get('task_completion_status'),
            'weight': item.get('weight'),
            'health_status': item.get('health_status'),
            'epic': item.get('epic'),
            'iteration': item.get('iteration'),
            'references': item.get('references'),
            'time_stats': item.get('time_stats'),
            'subscribed': item.get('subscribed'),
            'moved_to_id': item.get('moved_to_id'),
            'service_desk_reply_to': item.get('service_desk_reply_to'),
            'links': item.get('_links'),
            'author': {
                'id': author.get('id'),
                'name': author.get('name'),
                'username': author.get('username'),
                'web_url': author.get('web_url'),
                'avatar_url': author.get('avatar_url'),
            }
            if author
            else None,
            'closed_by': {
                'id': closed_by.get('id'),
                'name': closed_by.get('name'),
                'username': closed_by.get('username'),
                'web_url': closed_by.get('web_url'),
                'avatar_url': closed_by.get('avatar_url'),
            }
            if closed_by
            else None,
            'assignee': {
                'id': assignee.get('id'),
                'name': assignee.get('name'),
                'username': assignee.get('username'),
                'web_url': assignee.get('web_url'),
                'avatar_url': assignee.get('avatar_url'),
            }
            if assignee
            else None,
            'assignees': [
                {
                    'id': assignee_item.get('id'),
                    'name': assignee_item.get('name'),
                    'username': assignee_item.get('username'),
                    'web_url': assignee_item.get('web_url'),
                    'avatar_url': assignee_item.get('avatar_url'),
                }
                for assignee_item in assignees
            ],
            'milestone': {
                'id': milestone.get('id'),
                'iid': milestone.get('iid'),
                'title': milestone.get('title'),
                'description': milestone.get('description'),
                'state': milestone.get('state'),
                'due_date': milestone.get('due_date'),
                'start_date': milestone.get('start_date'),
                'web_url': milestone.get('web_url'),
            }
            if milestone
            else None,
        }
        if include_raw:
            result['raw'] = item
        return result

    def ensure_ai_generated_commit_message(self, commit_message: str) -> str:
        """Return a policy-compliant commit message for LLM-created commits."""
        message = (commit_message or '').strip()
        if not message:
            raise ValueError('commit_message must not be empty')

        prefix = (self.valves.ai_generated_commit_prefix or '').strip()
        if not self.valves.enforce_ai_generated_commit_prefix or not prefix:
            return message

        if message.casefold().startswith(prefix.casefold()):
            return message
        return f'{prefix} {message}'

    def ensure_ai_generated_merge_request_description(self, description: str) -> str:
        """Return a policy-compliant merge request description."""
        text = (description or '').strip()
        marker = (self.valves.ai_generated_merge_request_text or '').strip()
        if not self.valves.enforce_ai_generated_merge_request_text or not marker:
            return text

        if marker.casefold() in text.casefold():
            return text
        if not text:
            return marker
        return f'{marker}\n\n{text}'

    def enforce_project_access(self, project_id: str):
        allowed = [x.strip() for x in self.user_valves.allowed_project_ids_csv.split(',') if x.strip()]
        if allowed and str(project_id) not in allowed:
            raise ValueError(f'Project {project_id} is not in the allowed project list')

    def enforce_path_access(self, file_path: str):
        normalized = self.normalize_path(file_path)
        if re.search(self.valves.blocked_path_regex, normalized):
            raise ValueError(f'Path is blocked by admin policy: {normalized}')
        if self.user_valves.allowed_path_regex and not re.search(self.user_valves.allowed_path_regex, normalized):
            raise ValueError(f'Path is not permitted by user path policy: {normalized}')

    def enforce_branch_write_allowed(self, branch: str):
        if self.valves.prohibit_direct_default_branch_commits and re.match(self.valves.protected_branch_regex, branch):
            raise ValueError(f"Direct commits to protected branch '{branch}' are blocked by policy")

    def normalize_path(self, file_path: str) -> str:
        if not file_path or not isinstance(file_path, str):
            raise ValueError('file_path must be a non-empty string')
        normalized = file_path.replace('\\', '/').strip().lstrip('/')
        if not normalized:
            raise ValueError('file_path resolves to an empty path')
        if '/../' in f'/{normalized}' or normalized.startswith('../') or normalized.endswith('/..'):
            raise ValueError(f'Invalid file path traversal attempt: {file_path}')
        return normalized

    def normalize_issue_text(self, value: str, single_line: bool = False) -> str:
        """Normalize issue/task text before sending it to GitLab.

        LLM/tool-call inputs sometimes contain double-escaped whitespace, for
        example the two literal characters backslash+n instead of an actual line
        break. GitLab would otherwise store those characters verbatim. For issue
        descriptions we convert common escaped whitespace sequences to real
        whitespace; for titles we additionally collapse all whitespace to keep
        the title single-line.
        """
        text = '' if value is None else str(value)
        if self.valves.normalize_issue_escape_sequences:
            text = text.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n').replace('\\t', '\t')
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        if single_line:
            text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def normalize_csv(self, value: str) -> List[str]:
        if not value:
            return []
        return [item.strip() for item in value.split(',') if item.strip()]

    def merge_unique_strings(self, values: List[str]) -> List[str]:
        seen = set()
        result = []
        for value in values:
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    def normalize_int_list(self, values: List[Any]) -> List[int]:
        result: List[int] = []
        seen = set()
        for value in values:
            if value is None or value == '':
                continue
            parsed = int(value)
            if parsed <= 0:
                raise ValueError('IDs must be positive integers')
            if parsed in seen:
                continue
            seen.add(parsed)
            result.append(parsed)
        return result

    def branch_exists(self, project_id: str, branch: str) -> bool:
        endpoint = f'/projects/{quote(str(project_id), safe="")}/repository/branches/{quote(branch, safe="")}'
        response = self.session.get(
            f'{self.base_url}{endpoint}',
            verify=self.valves.verify_ssl,
            timeout=self.valves.request_timeout_seconds,
            headers={
                'PRIVATE-TOKEN': self.session.headers['PRIVATE-TOKEN'],
                'Accept': 'application/json',
            },
        )
        if response.status_code == 404:
            return False
        if not response.ok:
            detail = self._safe_error_text(response)
            raise ValueError(f'GitLab API error {response.status_code}: {detail}')
        return True

    def create_branch(self, project_id: str, branch_name: str, from_ref: str) -> dict:
        payload = {'branch': branch_name, 'ref': from_ref}
        return self.post_json(
            f'/projects/{quote(str(project_id), safe="")}/repository/branches',
            json_body=payload,
        )

    def read_file(self, project_id: str, file_path: str, ref: str, return_base64: bool = False) -> dict:
        normalized = self.normalize_path(file_path)
        encoded_path = quote(normalized, safe='')
        metadata = self.get_json(
            f'/projects/{quote(str(project_id), safe="")}/repository/files/{encoded_path}',
            params={'ref': ref},
        )
        size = int(metadata.get('size') or 0)
        if size > self.valves.max_file_bytes:
            raise ValueError(f'File too large: {normalized} has {size} bytes which exceeds limit {self.valves.max_file_bytes}')

        raw_response = self._request(
            'GET',
            f'/projects/{quote(str(project_id), safe="")}/repository/files/{encoded_path}/raw',
            params={'ref': ref},
        )
        raw_bytes = raw_response.content
        if return_base64:
            content = base64.b64encode(raw_bytes).decode('utf-8')
            encoding = 'base64'
        else:
            content = raw_bytes.decode('utf-8')
            encoding = 'text'

        return {
            'project_id': project_id,
            'ref': ref,
            'file_path': normalized,
            'blob_id': metadata.get('blob_id'),
            'commit_id': metadata.get('commit_id'),
            'last_commit_id': metadata.get('last_commit_id'),
            'size': size,
            'encoding': encoding,
            'content': content,
        }

    # -------------------------- Structured text-edit support --------------------------

    def normalize_text_edits(self, edits: List[Any]) -> List[Tools.TextEdit]:
        parsed: List[Tools.TextEdit] = []
        supported = {
            'replace',
            'regex_replace',
            'insert_before',
            'insert_after',
            'prepend',
            'append',
            'create',
            'delete',
            'move',
        }
        for index, item in enumerate(edits):
            try:
                if isinstance(item, Tools.TextEdit):
                    edit = item
                elif isinstance(item, dict):
                    edit = Tools.TextEdit(**item)
                else:
                    raise ValueError('Each edit must be a dict or TextEdit model')
            except Exception as exc:
                raise ValueError(f'Invalid edits[{index}]: {exc}') from exc

            if edit.operation not in supported:
                raise ValueError(f'Unsupported edit operation for {edit.file_path}: {edit.operation}')
            edit.file_path = self.normalize_path(edit.file_path)
            self.enforce_path_access(edit.file_path)
            if edit.previous_path:
                edit.previous_path = self.normalize_path(edit.previous_path)
                self.enforce_path_access(edit.previous_path)

            if edit.operation in {'replace', 'insert_before', 'insert_after'} and edit.old_text is None:
                raise ValueError(f"old_text is required for operation '{edit.operation}' on {edit.file_path}")
            if edit.operation == 'regex_replace' and not edit.regex:
                raise ValueError(f'regex is required for regex_replace on {edit.file_path}')
            if (
                edit.operation
                in {
                    'replace',
                    'regex_replace',
                    'insert_before',
                    'insert_after',
                    'prepend',
                    'append',
                    'create',
                }
                and edit.new_text is None
            ):
                raise ValueError(f"new_text is required for operation '{edit.operation}' on {edit.file_path}")
            if edit.operation == 'move' and not edit.previous_path:
                raise ValueError(f'previous_path is required for move operation to {edit.file_path}')
            if edit.count < 0:
                raise ValueError(f'count must be >= 0 for {edit.file_path}')
            parsed.append(edit)
        return parsed

    def build_file_changes_from_text_edits(
        self,
        project_id: str,
        ref: str,
        edits: List[Tools.TextEdit],
    ) -> List[dict]:
        """Convert structured text edits to GitLab commit file changes."""
        states: Dict[str, Dict[str, Any]] = {}

        def ensure_state(file_path: str, allow_missing: bool = False) -> Dict[str, Any]:
            if file_path in states:
                return states[file_path]
            try:
                content = self.read_file(project_id, file_path, ref)['content']
                state = {
                    'file_path': file_path,
                    'action': 'update',
                    'content': content,
                    'exists': True,
                    'previous_path': None,
                    'deleted': False,
                }
            except ValueError as exc:
                if not allow_missing:
                    raise ValueError(f'Could not read {file_path} at {ref}: {exc}') from exc
                state = {
                    'file_path': file_path,
                    'action': 'create',
                    'content': '',
                    'exists': False,
                    'previous_path': None,
                    'deleted': False,
                }
            states[file_path] = state
            return state

        for edit in edits:
            if edit.operation == 'create':
                if edit.file_path in states and states[edit.file_path].get('exists'):
                    raise ValueError(f'Cannot create {edit.file_path}: file already has pending state')
                states[edit.file_path] = {
                    'file_path': edit.file_path,
                    'action': 'create',
                    'content': edit.new_text or '',
                    'exists': False,
                    'previous_path': None,
                    'deleted': False,
                }
                continue

            if edit.operation == 'delete':
                state = ensure_state(edit.file_path)
                state['action'] = 'delete'
                state['content'] = None
                state['deleted'] = True
                continue

            if edit.operation == 'move':
                assert edit.previous_path is not None
                source_state = ensure_state(edit.previous_path)
                if edit.file_path in states:
                    raise ValueError(f'Cannot move to {edit.file_path}: target already has pending state')
                state = {
                    'file_path': edit.file_path,
                    'action': 'move',
                    'content': edit.new_text if edit.new_text is not None else source_state['content'],
                    'exists': True,
                    'previous_path': edit.previous_path,
                    'deleted': False,
                }
                source_state['deleted'] = True
                states[edit.file_path] = state
                continue

            state = ensure_state(edit.file_path, allow_missing=edit.create_if_missing)
            if state.get('deleted'):
                raise ValueError(f'Cannot edit deleted file {edit.file_path}')
            content = state.get('content') or ''

            if edit.operation == 'replace':
                assert edit.old_text is not None and edit.new_text is not None
                matches = content.count(edit.old_text)
                self._assert_expected_occurrences(edit.file_path, edit.operation, matches, edit.expected_occurrences)
                replace_count = edit.count if edit.count > 0 else -1
                state['content'] = content.replace(edit.old_text, edit.new_text, replace_count)
            elif edit.operation == 'regex_replace':
                assert edit.regex is not None and edit.new_text is not None
                pattern = re.compile(edit.regex, flags=re.MULTILINE)
                matches = len(pattern.findall(content))
                self._assert_expected_occurrences(edit.file_path, edit.operation, matches, edit.expected_occurrences)
                replace_count = edit.count if edit.count > 0 else 0
                state['content'] = pattern.sub(edit.new_text, content, count=replace_count)
            elif edit.operation in {'insert_before', 'insert_after'}:
                assert edit.old_text is not None and edit.new_text is not None
                matches = content.count(edit.old_text)
                self._assert_expected_occurrences(edit.file_path, edit.operation, matches, edit.expected_occurrences)
                if matches == 0:
                    raise ValueError(f'Anchor text not found in {edit.file_path} for {edit.operation}')
                anchor = edit.old_text
                replacement = edit.new_text + anchor if edit.operation == 'insert_before' else anchor + edit.new_text
                replace_count = edit.count if edit.count > 0 else -1
                state['content'] = content.replace(anchor, replacement, replace_count)
            elif edit.operation == 'prepend':
                assert edit.new_text is not None
                state['content'] = edit.new_text + content
            elif edit.operation == 'append':
                assert edit.new_text is not None
                state['content'] = content + edit.new_text
            else:
                raise ValueError(f'Unsupported edit operation: {edit.operation}')

        file_changes: List[dict] = []
        for file_path, state in states.items():
            if state.get('deleted') and state.get('action') != 'delete':
                continue
            if state['action'] == 'delete':
                file_changes.append({'file_path': file_path, 'action': 'delete'})
            elif state['action'] == 'move':
                file_changes.append(
                    {
                        'file_path': file_path,
                        'previous_path': state['previous_path'],
                        'action': 'move',
                        'content': state['content'],
                    }
                )
            else:
                file_changes.append(
                    {
                        'file_path': file_path,
                        'action': state['action'],
                        'content': state['content'],
                    }
                )
        return file_changes

    def _assert_expected_occurrences(
        self,
        file_path: str,
        operation: str,
        actual: int,
        expected: Optional[int],
    ) -> None:
        if expected is None:
            return
        if actual != expected:
            raise ValueError(f'Expected {expected} occurrence(s) for {operation} in {file_path}, found {actual}')

    # -------------------------- Commit action support --------------------------

    def normalize_file_changes(self, file_changes: List[Any]) -> List[Tools.FileChange]:
        parsed: List[Tools.FileChange] = []
        for index, item in enumerate(file_changes):
            try:
                if isinstance(item, Tools.FileChange):
                    fc = item
                elif isinstance(item, dict):
                    fc = Tools.FileChange(**item)
                else:
                    raise ValueError('Each file change must be a dict or FileChange model')
            except Exception as exc:
                raise ValueError(f'Invalid file_changes[{index}]: {exc}') from exc

            if fc.action not in {'create', 'update', 'delete', 'move'}:
                raise ValueError(f'Invalid action for {fc.file_path}: {fc.action}')
            fc.file_path = self.normalize_path(fc.file_path)
            self.enforce_path_access(fc.file_path)
            if fc.previous_path:
                fc.previous_path = self.normalize_path(fc.previous_path)
                self.enforce_path_access(fc.previous_path)
            if fc.action in {'create', 'update'} and fc.content is None:
                raise ValueError(f"content is required for action '{fc.action}' on {fc.file_path}")
            if fc.action == 'move' and not fc.previous_path:
                raise ValueError(f'previous_path is required for move action on {fc.file_path}')
            if fc.encoding not in {'text', 'base64'}:
                raise ValueError(f'Unsupported encoding for {fc.file_path}: {fc.encoding}')
            parsed.append(fc)
        return parsed

    def build_commit_actions(self, file_changes: List[Tools.FileChange]) -> Tuple[List[dict], List[dict]]:
        actions: List[dict] = []
        preview: List[dict] = []
        seen_targets = set()

        for fc in file_changes:
            if fc.file_path in seen_targets:
                raise ValueError(f'Duplicate target file_path in file_changes: {fc.file_path}')
            seen_targets.add(fc.file_path)

            action: Dict[str, Any] = {
                'action': fc.action,
                'file_path': fc.file_path,
            }
            content_bytes = 0
            if fc.previous_path:
                action['previous_path'] = fc.previous_path
            if fc.execute_filemode is not None:
                action['execute_filemode'] = fc.execute_filemode
            if fc.action in {'create', 'update', 'move'} and fc.content is not None:
                action['content'] = fc.content
                action['encoding'] = fc.encoding
                if fc.encoding == 'base64':
                    content_bytes = len(base64.b64decode(fc.content))
                else:
                    content_bytes = len(fc.content.encode('utf-8'))

            actions.append(action)
            preview.append(
                {
                    'action': fc.action,
                    'file_path': fc.file_path,
                    'previous_path': fc.previous_path,
                    'encoding': fc.encoding if fc.content is not None else None,
                    'content_bytes': content_bytes,
                    'execute_filemode': fc.execute_filemode,
                }
            )

        return actions, preview
