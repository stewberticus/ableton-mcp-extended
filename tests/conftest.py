"""Shared test setup for Ableton MCP Extended tests.

Neither layer can be imported as-is in a plain Python test run:
- MCP_Server.server needs the `mcp` package, and its @mcp.tool() decorator
  must pass functions through so tests can call tools directly.
- The Remote Script imports `_Framework.ControlSurface`, which only exists
  inside Ableton Live.

Both are stubbed here, once, before any test module imports them. Test
modules must not install their own stubs: whichever stub is imported first
wins for the whole run, so per-file stubs made results depend on file order.
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _install_mcp_stub():
    fastmcp = MagicMock()
    fastmcp.FastMCP.return_value.tool.return_value = lambda fn: fn
    sys.modules["mcp"] = MagicMock()
    sys.modules["mcp.server"] = MagicMock()
    sys.modules["mcp.server.fastmcp"] = fastmcp


class _StubControlSurface:
    """Minimal stand-in for Live's _Framework.ControlSurface."""

    def __init__(self, c_instance=None):
        pass

    def log_message(self, msg):
        pass

    def show_message(self, msg):
        pass

    def schedule_message(self, delay, callback):
        callback()


def _install_framework_stub():
    framework = types.ModuleType("_Framework")
    control_surface = types.ModuleType("_Framework.ControlSurface")
    control_surface.ControlSurface = _StubControlSurface
    framework.ControlSurface = control_surface
    sys.modules["_Framework"] = framework
    sys.modules["_Framework.ControlSurface"] = control_surface


_install_mcp_stub()
_install_framework_stub()

# Import both layers now so every test module shares these exact modules.
import MCP_Server.server  # noqa: E402,F401
import AbletonMCP_Remote_Script  # noqa: E402,F401


@pytest.fixture
def time_signature_4_4():
    """Standard 4/4 time signature."""
    return {"numerator": 4, "denominator": 4}


@pytest.fixture
def time_signature_3_4():
    """Waltz 3/4 time signature."""
    return {"numerator": 3, "denominator": 4}


@pytest.fixture
def time_signature_6_8():
    """Compound 6/8 time signature."""
    return {"numerator": 6, "denominator": 8}
