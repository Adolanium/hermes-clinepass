"""ClinePass model-provider plugin for Hermes Agent.

ClinePass serves curated open-weight coding models (GLM, Kimi, DeepSeek,
MiniMax, MiMo, Qwen) behind an OpenAI-compatible Chat Completions API at
``https://api.cline.bot/api/v1``. Model IDs are namespaced
(``cline-pass/<model>``) and pass through to the endpoint unchanged.

Authentication is a bearer ``CLINE_API_KEY`` from the Cline account dashboard
(Settings > API Keys). The gateway has no live ``/models`` catalog (404), so
this profile returns ``None`` from ``fetch_models`` and ships a curated
``fallback_models`` list instead.
"""

from __future__ import annotations

from providers import register_provider
from providers.base import ProviderProfile


class ClinePassProfile(ProviderProfile):
    """ClinePass OpenAI-compat gateway with a static model catalog."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        # api.cline.bot has no GET /models route (returns 404). Use the
        # curated fallback_models list for the picker and doctor paths.
        return None


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
        "cline-pass/glm-5.2",
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
