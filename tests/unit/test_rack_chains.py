"""Devices deeper inside a rack chain can be addressed with chain_device_index."""
import types
from unittest.mock import MagicMock, patch

import pytest

from MCP_Server import server
from AbletonMCP_Remote_Script import AbletonMCP


class _P:
    def __init__(self, name, value=0.0):
        self.name, self.value, self.min, self.max = name, value, 0.0, 1.0
        self.is_enabled, self.is_quantized, self.value_items = True, False, []

    def __str__(self):
        return str(self.value)


def _dev(name, params):
    return types.SimpleNamespace(name=name, class_name=name, can_have_chains=False,
                                 parameters=[_P(n) for n in params])


def _rs():
    serum = _dev("Serum", ["Device On", "Macro 1"])
    reverb = _dev("Reverb", ["Device On", "Dry/Wet"])
    chain = types.SimpleNamespace(name="Lead", devices=[serum, reverb])
    rack = types.SimpleNamespace(name="Instrument Rack", can_have_chains=True, chains=[chain])
    track = types.SimpleNamespace(name="Lead", devices=[rack])
    rs = AbletonMCP.__new__(AbletonMCP)
    rs._song = types.SimpleNamespace(tracks=[track])
    return rs, serum, reverb


def test_second_device_in_chain():
    rs, serum, reverb = _rs()
    rs._set_device_parameter(0, 0, 0, "Dry/Wet", None, 0.3, chain_device_index=1)
    assert reverb.parameters[1].value == pytest.approx(0.3)


def test_default_is_first_device():
    rs, serum, reverb = _rs()
    assert rs._get_device_parameters(0, 0, 0)["device_name"] == "Serum"


def test_chain_bounds_are_checked():
    rs, _, _ = _rs()
    with pytest.raises(IndexError, match="Chain index 3"):
        rs._set_device_enabled(0, 0, 3, False)
    with pytest.raises(IndexError, match="Device 5 out of range"):
        rs._get_device_parameters(0, 0, 0, chain_device_index=5)


@patch('MCP_Server.server.get_ableton_connection')
def test_server_sends_chain_device_index(mock_conn):
    ableton = MagicMock()
    ableton.send_command.return_value = {"device_name": "Reverb", "parameters": [],
                                         "parameter_count": 0}
    mock_conn.return_value = ableton
    server.get_device_parameters(MagicMock(), 1, 1, chain_index=1, chain_device_index=2)
    params = ableton.send_command.call_args[0][1]
    assert params["chain_index"] == 0 and params["chain_device_index"] == 1
