"""ClinePass model-provider plugin for Hermes Agent.

ClinePass serves curated open-weight coding models (GLM, Kimi, DeepSeek,
MiniMax, MiMo, Qwen) behind an OpenAI-compatible Chat Completions API at
``https://api.cline.bot/api/v1``. Pass model IDs are namespaced
(``cline-pass/<model>``); free models use their own gateway IDs. Both pass
through to the endpoint unchanged.

Authentication is a bearer ``CLINE_API_KEY`` from the Cline account dashboard
(Settings > API Keys). The generic model listing omits ClinePass IDs, but
the gateway advertises its catalog at ``GET /api/v1/ai/cline/recommended-models`` (keys
``clinePass`` and ``free``); ``fetch_models`` returns both blocks, preserving
their gateway IDs, and falls back to the curated ``fallback_models`` list
on any failure.
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
# Cline's own ClinePass picker includes free models alongside the pass catalog.
# Free IDs may use other namespaces and must pass through unchanged.
CATALOG_KEYS = ("clinePass", "free")

# Curated fallback for the provider profile when live discovery is unavailable.
CURATED_MODELS: tuple[str, ...] = (
    "cline-pass/glm-5.3-flash",
    "cline-pass/glm-5.3",
    "cline-pass/glm-5.2",
    "cline-pass/qwen3.8-max",
    "cline-pass/kimi-k3",
    "cline-pass/kimi-k2.7-code",
    "cline-pass/kimi-k2.6",
    "cline-pass/deepseek-v4-pro",
    "cline-pass/deepseek-v4-flash",
    "cline-pass/deepseek-v4.1-flash",
    "cline-pass/mimo-v2.5-pro",
    "cline-pass/mimo-v2.5",
    "cline-pass/minimax-m3",
    "cline-pass/qwen3.7-max",
    "cline-pass/qwen3.7-plus",
)


class ClinePassProfile(ProviderProfile):
    """ClinePass OpenAI-compat gateway with a live-recommended-models catalog."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        # The generic model listing omits ClinePass IDs. The recommended
        # models endpoint is the live
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

        if not isinstance(payload, dict):
            return None
        ids: list[str] = []
        for key in CATALOG_KEYS:
            block = payload.get(key)
            if not isinstance(block, list):
                continue
            ids.extend(
                m["id"]
                for m in block
                if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"].strip()
            )
        ids = list(dict.fromkeys(ids))
        if not ids:
            # Empty means the fetch is broken, not that there are no models.
            # Return None so callers use fallback_models.
            return None
        return ids


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
    fallback_models=CURATED_MODELS,
)


def register() -> None:
    """Entry point used by pip installs and explicit loaders."""
    register_provider(clinepass)


# Drop-in discovery imports this module and expects registration at import time.
register()
