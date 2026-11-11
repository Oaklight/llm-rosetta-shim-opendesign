"""The plugin registers the three Open Design Cloud shims."""

from __future__ import annotations

import pytest

from llm_rosetta.shims import get_shim
from llm_rosetta.shims.provider_shim import _reset_registry

from llm_rosetta_shim_opendesign import register_shims

_SHIMS = {
    "opendesign--chat_completions": "chat_completions",
    "opendesign--open_responses": "open_responses",
    "opendesign--messages": "messages",
}


@pytest.fixture()
def _registered():
    _reset_registry()  # clean registry, so only the plugin's shims are present
    register_shims()
    yield
    _reset_registry()


def test_registers_the_three_formats(_registered):
    for name, base in _SHIMS.items():
        shim = get_shim(name)
        assert shim is not None, name
        assert shim.name == name
        assert shim.model_type == "llm"
        assert shim.format == base
        assert shim.base == base


def test_the_vendor_manifest_supplies_the_connection_defaults(_registered):
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim.manifest is not None, name
        assert shim.connection.base_url == "https://amr-link.open-design.ai/v1"
        assert shim.connection.api_key_env == "OPENDESIGN_API_KEY"
        assert (
            shim.connection.models_path == "https://amr-link.open-design.ai/v1/models"
        )
        assert shim.connection.manage_usage_url == "https://open-design.ai/cloud/usage"


def test_the_package_ships_no_auth_or_quota_code(_registered):
    """v1 is model traffic only; the quota mechanism is a later follow-up."""
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim.auth is None, name
        assert shim.quota is None, name
        assert shim.quota_probes == (), name
