"""Profile smoke tests (require Hermes Agent on PYTHONPATH)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _require_providers():
    try:
        import providers  # noqa: F401
        from providers.base import ProviderProfile  # noqa: F401
    except ImportError:
        pytest.skip("Hermes Agent (providers package) is not installed")


@pytest.fixture
def profile():
    _require_providers()
    # Fresh import so register() runs against the live registry.
    if "clinepass" in sys.modules:
        del sys.modules["clinepass"]
    import clinepass as plugin

    importlib.reload(plugin)
    import providers

    p = providers.get_provider_profile("clinepass")
    assert p is not None
    return p


def test_identity(profile):
    assert profile.name == "clinepass"
    assert profile.base_url == "https://api.cline.bot/api/v1"
    assert profile.auth_type == "api_key"
    assert "CLINE_API_KEY" in profile.env_vars
    assert profile.display_name == "ClinePass"
    assert profile.supports_health_check is False


def test_aliases():
    _require_providers()
    if "clinepass" in sys.modules:
        del sys.modules["clinepass"]
    import clinepass  # noqa: F401
    import providers

    assert providers.get_provider_profile("cline-pass").name == "clinepass"
    assert providers.get_provider_profile("cline").name == "clinepass"


def test_catalog(profile):
    models = profile.fallback_models
    assert "cline-pass/glm-5.2" in models
    assert "cline-pass/kimi-k3" in models
    assert "cline-pass/deepseek-v4-flash" in models
    assert all(m.startswith("cline-pass/") for m in models)
    assert profile.default_aux_model == "cline-pass/deepseek-v4-flash"


def test_catalog_includes_newer_models(profile):
    models = profile.fallback_models
    assert "cline-pass/glm-5.3-flash" in models
    assert "cline-pass/glm-5.3" in models
    assert "cline-pass/qwen3.8-max" in models


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


def _patch_fetch(monkeypatch, *, body: bytes | None = None, error: Exception | None = None):
    """Route open_credentialed_url to a canned body or a raised error."""
    import hermes_cli.urllib_security as urllib_security

    seen = {}

    def fake_open(req, *, timeout, **_kwargs):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["timeout"] = timeout
        if error is not None:
            raise error
        return _FakeResponse(body or b"")

    monkeypatch.setattr(urllib_security, "open_credentialed_url", fake_open)
    return seen


def test_fetch_models_reads_clinepass_block(profile, monkeypatch):
    import json

    payload = {
        "recommended": [{"id": "anthropic/claude-sonnet-4.6"}],
        "clinePass": [
            {"id": "cline-pass/glm-5.3-flash", "name": "GLM 5.3 Flash", "tags": []},
            {"id": "cline-pass/kimi-k3", "name": "Kimi K3", "tags": ["new"]},
            {"name": "no id here"},
            "not-a-dict",
        ],
    }
    seen = _patch_fetch(monkeypatch, body=json.dumps(payload).encode())

    models = profile.fetch_models(api_key="dummy", timeout=3)

    assert models == ["cline-pass/glm-5.3-flash", "cline-pass/kimi-k3"]
    assert seen["url"] == "https://api.cline.bot/api/v1/ai/cline/recommended-models"
    assert seen["timeout"] == 3
    # Public endpoint: the user's key must never be sent.
    assert "authorization" not in seen["headers"]
    assert seen["headers"]["accept"] == "application/json"


def test_fetch_models_ignores_custom_base_url(profile, monkeypatch):
    import json

    payload = {"clinePass": [{"id": "cline-pass/kimi-k3"}]}
    seen = _patch_fetch(monkeypatch, body=json.dumps(payload).encode())

    profile.fetch_models(api_key="dummy", base_url="https://proxy.example.test/v1")

    assert seen["url"] == "https://api.cline.bot/api/v1/ai/cline/recommended-models"


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"clinePass": []}',
        b'{"clinePass": "nope"}',
        b'{"clinePass": [{"name": "missing id"}]}',
        b"[]",
        b"not json",
    ],
)
def test_fetch_models_returns_none_on_bad_shape(profile, monkeypatch, body):
    _patch_fetch(monkeypatch, body=body)
    assert profile.fetch_models(api_key="dummy") is None


def test_fetch_models_returns_none_on_network_error(profile, monkeypatch):
    _patch_fetch(monkeypatch, error=OSError("boom"))
    assert profile.fetch_models(api_key="dummy") is None
