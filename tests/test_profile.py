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


def test_no_live_models_endpoint(profile):
    assert profile.fetch_models(api_key="dummy") is None
