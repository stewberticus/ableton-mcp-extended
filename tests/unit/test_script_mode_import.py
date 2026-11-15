"""server.py must import cleanly when launched as a plain script.

The documented MCP client config runs ``python MCP_Server/server.py``. In that
mode only ``MCP_Server/`` is on ``sys.path``, so ``import MCP_Server.*`` used to
fail at call time and broke get_device_parameters / set_device_parameter.
"""
import os
import subprocess
import sys
import textwrap

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERVER_PATH = os.path.join(REPO_ROOT, "MCP_Server", "server.py")


def test_server_imports_plugin_aliases_in_script_mode():
    code = textwrap.dedent(
        """
        import importlib.util, sys
        from unittest.mock import MagicMock
        # Simulate `python MCP_Server/server.py`: script dir first, repo root absent.
        sys.path = [p for p in sys.path if p not in ('', {root!r})]
        sys.path.insert(0, {srv_dir!r})
        sys.modules['mcp'] = MagicMock()
        sys.modules['mcp.server'] = MagicMock()
        sys.modules['mcp.server.fastmcp'] = MagicMock()
        spec = importlib.util.spec_from_file_location('server_script', {path!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.resolve_alias)
        assert callable(mod.get_categories)
        print('ok')
        """
    ).format(
        root=REPO_ROOT,
        srv_dir=os.path.dirname(SERVER_PATH),
        path=SERVER_PATH,
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd="/",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout
