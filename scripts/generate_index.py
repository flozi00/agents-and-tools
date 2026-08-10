#!/usr/bin/env python3
"""Regenerate index.json from tools/*/tool.py and assistants/*/assistant.json.

Validates ids, versions, and assistant tool references. Exits non-zero on any
violation so it can run as a CI check.
"""

import json
import re
import sys
from pathlib import Path

HUB_DIR = Path(__file__).resolve().parent.parent
ASSISTANT_ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


def fail(message: str) -> None:
    print(f'error: {message}', file=sys.stderr)
    sys.exit(1)


def parse_frontmatter(content: str) -> dict:
    match = re.match(r'\s*("""|\'\'\')(.*?)\1', content, re.DOTALL)
    if not match:
        return {}
    frontmatter = {}
    for line in match.group(2).splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            frontmatter[key.strip()] = value.strip()
    return frontmatter


def collect_tools() -> list[dict]:
    entries = []
    tools_dir = HUB_DIR / 'tools'
    for tool_dir in sorted(tools_dir.iterdir()) if tools_dir.is_dir() else []:
        if not tool_dir.is_dir():
            continue
        tool_id = tool_dir.name
        if not (tool_id.isidentifier() and tool_id == tool_id.lower()):
            fail(f'tool id "{tool_id}" must be a lowercase Python identifier')
        tool_file = tool_dir / 'tool.py'
        if not tool_file.is_file():
            fail(f'tools/{tool_id}/tool.py is missing')
        frontmatter = parse_frontmatter(tool_file.read_text(encoding='utf-8'))
        if not frontmatter.get('version'):
            fail(f'tools/{tool_id}/tool.py frontmatter needs a version')
        entries.append(
            {
                'id': tool_id,
                'name': frontmatter.get('title') or tool_id,
                'description': frontmatter.get('description') or '',
                'version': frontmatter['version'],
                **({'requirements': frontmatter['requirements']} if frontmatter.get('requirements') else {}),
            }
        )
    return entries


def collect_assistants(tool_ids: set[str]) -> list[dict]:
    entries = []
    assistants_dir = HUB_DIR / 'assistants'
    for assistant_dir in sorted(assistants_dir.iterdir()) if assistants_dir.is_dir() else []:
        if not assistant_dir.is_dir():
            continue
        assistant_id = assistant_dir.name
        if not ASSISTANT_ID_RE.fullmatch(assistant_id):
            fail(f'assistant id "{assistant_id}" must be lowercase kebab-case')
        assistant_file = assistant_dir / 'assistant.json'
        if not assistant_file.is_file():
            fail(f'assistants/{assistant_id}/assistant.json is missing')
        try:
            template = json.loads(assistant_file.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            fail(f'assistants/{assistant_id}/assistant.json is invalid JSON: {e}')
        if template.get('id') != assistant_id:
            fail(f'assistants/{assistant_id}: "id" must equal the directory name')
        for key in ('name', 'version', 'description', 'system_prompt'):
            if not template.get(key):
                fail(f'assistants/{assistant_id}: "{key}" is required')
        for forbidden in ('base_model_id', 'access_grants', 'access_control', 'knowledgeBaseIds'):
            if forbidden in template:
                fail(f'assistants/{assistant_id}: "{forbidden}" is not portable and not allowed in templates')
        for tool_id in template.get('tools', []):
            if tool_id not in tool_ids:
                fail(f'assistants/{assistant_id}: references unknown hub tool "{tool_id}"')
        entries.append(
            {
                'id': assistant_id,
                'name': template['name'],
                'description': template['description'],
                'version': template['version'],
                'tools': template.get('tools', []),
                **({'profile_image_url': template['profile_image_url']} if template.get('profile_image_url') else {}),
            }
        )
    return entries


def main() -> None:
    tools = collect_tools()
    assistants = collect_assistants({tool['id'] for tool in tools})
    index = {'version': 1, 'assistants': assistants, 'tools': tools}
    (HUB_DIR / 'index.json').write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'index.json written: {len(assistants)} assistants, {len(tools)} tools')


if __name__ == '__main__':
    main()
