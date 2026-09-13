"""Load every hub tool the way the app does and build its function specs.

Fails if a tool.py cannot be imported, has no `Tools` class, or exposes a
method whose type hints cannot be turned into a JSON schema.
"""

import re
import sys
import types
from inspect import signature
from pathlib import Path
from typing import Any, get_type_hints

from pydantic import create_model

HUB = Path(__file__).resolve().parent.parent

# Some tools import the host application. Importing it for real would drag in the
# database and config layers, so outside the app we stand in a stub: this check is
# about the tool file, not about the host.
try:
    import open_webui  # noqa: F401
except ImportError:

    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            return type(name, (), {})

    for module_name in (
        'open_webui',
        'open_webui.models',
        'open_webui.models.users',
        'open_webui.models.files',
        'open_webui.utils',
        'open_webui.utils.chat',
        'open_webui.constants',
    ):
        sys.modules.setdefault(module_name, _Stub(module_name))

# Same rule as backend/open_webui/utils/plugin.py::extract_frontmatter.
FRONTMATTER_RE = re.compile(r'^\s*([a-z_]+):\s*(.*)\s*$', re.IGNORECASE)


def frontmatter(content: str) -> dict:
    lines = content.splitlines()
    assert lines and lines[0].strip() == '"""', 'file must start with a bare triple quote'
    out = {}
    for line in lines[1:]:
        if '"""' in line:
            break
        match = FRONTMATTER_RE.match(line)
        if match:
            out[match.group(1).strip()] = match.group(2).strip()
    return out


failures = []
for tool_file in sorted(HUB.glob('tools/*/tool.py')):
    tool_id = tool_file.parent.name
    content = tool_file.read_text(encoding='utf-8')
    try:
        front = frontmatter(content)
        for key in ('title', 'description', 'version'):
            assert front.get(key), f'frontmatter is missing "{key}"'

        # Mirrors load_tool_module_by_id: the module must be registered in
        # sys.modules before exec, or pydantic cannot resolve the annotations of
        # nested models such as Valves/UserValves.
        module_name = f'tool_{tool_id}'
        module = types.ModuleType(module_name)
        sys.modules[module_name] = module
        module.__dict__['__file__'] = str(tool_file)
        exec(compile(content, str(tool_file), 'exec'), module.__dict__)
        tools = module.__dict__['Tools']()

        methods = [getattr(tools, name) for name in dir(tools) if not name.startswith('_') and callable(getattr(tools, name)) and not isinstance(getattr(tools, name), type)]
        assert methods, 'Tools exposes no callable methods'

        for method in methods:
            hints = get_type_hints(method)
            fields = {}
            for name, param in signature(method).parameters.items():
                fields[name] = (hints.get(name, Any), param.default if param.default is not param.empty else ...)
            create_model(method.__name__, **fields).model_json_schema()

        print(f'OK   {tool_id:16s} v{front["version"]:8s} {len(methods)} tools  ({front.get("license", "-")})')
    except Exception as exc:
        failures.append((tool_id, exc))
        print(f'FAIL {tool_id:16s} {type(exc).__name__}: {exc}')

print()
print(f'{len(failures)} failure(s)')
sys.exit(1 if failures else 0)
