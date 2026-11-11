"""The bundled YAML declares the canonical names and bilingual hints."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_PROVIDERS = _ROOT / "src" / "llm_rosetta_shim_opendesign" / "providers"
_VENDOR = _PROVIDERS / "opendesign" / "provider.yaml"
_LEAVES = {
    "chat_completions": _PROVIDERS
    / "opendesign"
    / "llm"
    / "chat_completions"
    / "provider.yaml",
    "open_responses": _PROVIDERS
    / "opendesign"
    / "llm"
    / "open_responses"
    / "provider.yaml",
    "messages": _PROVIDERS / "opendesign" / "llm" / "messages" / "provider.yaml",
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_vendor_manifest_declares_only_connection_defaults():
    cfg = _load(_VENDOR)
    assert set(cfg) == {"connection"}
    connection = cfg["connection"]
    assert connection["base_url"] == "https://amr-link.open-design.ai/v1"
    assert connection["api_key_env"] == "OPENDESIGN_API_KEY"
    assert connection["models_path"] == "https://amr-link.open-design.ai/v1/models"
    assert connection["manage_usage_url"] == "https://open-design.ai/cloud/usage"
    assert "quota" not in cfg


@pytest.mark.parametrize("fmt,path", sorted(_LEAVES.items()))
def test_each_leaf_names_its_format(fmt: str, path: Path):
    cfg = _load(path)
    assert cfg["name"] == f"opendesign--{fmt}"
    assert cfg["model_type"] == "llm"
    assert cfg["format"] == fmt


@pytest.mark.parametrize("fmt,path", sorted(_LEAVES.items()))
def test_each_hint_is_bilingual(fmt: str, path: Path):
    hint = _load(path)["hint_msg"]
    assert isinstance(hint, dict)
    assert set(hint) == {"en", "zh"}
    assert all(isinstance(value, str) and value.strip() for value in hint.values())


@pytest.mark.parametrize("fmt,path", sorted(_LEAVES.items()))
def test_no_leaf_declares_a_credential_or_quota(fmt: str, path: Path):
    """The vendor manifest is the only credential home; quota is deferred."""
    cfg = _load(path)
    credential_keys = {
        "api_key",
        "api_key_env",
        "control_api_key",
        "control_api_key_env",
        "token_command",
        "token_command_env",
    }
    assert credential_keys.isdisjoint(cfg)
    assert credential_keys.isdisjoint(cfg.get("connection") or {})
    assert "quota" not in cfg
