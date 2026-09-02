"""ClinePass model-provider plugin for Hermes Agent.

ClinePass serves curated open-weight coding models (GLM, Kimi, DeepSeek,
MiniMax, MiMo, Qwen) behind an OpenAI-compatible Chat Completions API at
``https://api.cline.bot/api/v1``. Model IDs are namespaced
(``cline-pass/<model>``) and pass through to the endpoint unchanged.

Authentication is a bearer ``CLINE_API_KEY`` from the Cline account dashboard
(Settings > API Keys). ``GET /models`` is a 404, but the gateway advertises
its live catalog at ``GET /api/v1/ai/cline/recommended-models`` (key
``clinePass``); ``fetch_models`` returns that, falling back to the curated
``fallback_models`` list on any failure.
"""

from __future__ import annotations

import json
import logging
import urllib.request

from providers import register_provider
from providers.base import ProviderProfile, _profile_user_agent

logger = logging.getLogger(__name__)

# Public, no auth needed. Response is a dict with keys ``recommended``,
# ``free``, ``clinePass`` and ``clineCloud``. Each is a list of
# ``{"id": ..., "name": ..., "description": ..., "tags": [...]}``.
RECOMMENDED_MODELS_URL = "https://api.cline.bot/api/v1/ai/cline/recommended-models"
CATALOG_KEY = "clinePass"


class ClinePassProfile(ProviderProfile):
    """ClinePass OpenAI-compat gateway with a live-recommended-models catalog."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        # GET /models on api.cline.bot returns 404, so the base class probe
        # is useless here. The recommended-models endpoint is the live
        # catalog instead. It is public, so no api_key is sent. base_url is
        # ignored on purpose: a user proxy for inference does not change
        # where the catalog lives.
        from hermes_cli.urllib_security import open_credentialed_url

        req = urllib.request.Request(RECOMMENDED_MODELS_URL)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", _profile_user_agent())
        try:
            with open_credentialed_url(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode())
        except Exception as exc:
            logger.debug("fetch_models(%s): %s", self.name, exc)
            return None

        block = payload.get(CATALOG_KEY) if isinstance(payload, dict) else None
        if not isinstance(block, list):
            return None
        ids = [
            m["id"]
            for m in block
            if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]
        ]
        # Empty means the fetch is broken, not that there are no models.
        # Return None so callers use fallback_models.
        return ids or None


clinepass = ClinePassProfile(
    name="clinepass",
    aliases=("cline-pass", "cline"),
    env_vars=("CLINE_API_KEY", "CLINE_BASE_URL"),
    display_name="ClinePass",
    description=(
        "ClinePass: curated open-weight coding models "
        "(Kimi K3, GLM, DeepSeek, MiniMax, MiMo, Qwen)"
    ),
    signup_url="https://cline.bot/cline-pass",
    base_url="https://api.cline.bot/api/v1",
    hostname="api.cline.bot",
    auth_type="api_key",
    supports_health_check=False,
    default_aux_model="cline-pass/deepseek-v4-flash",
    fallback_models=(
        "cline-pass/glm-5.3-flash",
        "cline-pass/glm-5.3",
        "cline-pass/glm-5.2",
        "cline-pass/qwen3.8-max",
        "cline-pass/kimi-k3",
        "cline-pass/kimi-k2.7-code",
        "cline-pass/kimi-k2.6",
        "cline-pass/deepseek-v4-pro",
        "cline-pass/deepseek-v4-flash",
        "cline-pass/mimo-v2.5-pro",
        "cline-pass/mimo-v2.5",
        "cline-pass/minimax-m3",
        "cline-pass/qwen3.7-max",
        "cline-pass/qwen3.7-plus",
    ),
)


def register() -> None:
    """Entry point used by pip installs and explicit loaders."""
    register_provider(clinepass)


# Drop-in discovery imports this module and expects registration at import time.
register()
