"""ClinePass model-provider plugin for Hermes Agent.

ClinePass serves curated open-weight coding models (GLM, Kimi, DeepSeek,
MiniMax, MiMo, Qwen) behind an OpenAI-compatible Chat Completions API at
``https://api.cline.bot/api/v1``. Model IDs are namespaced
(``cline-pass/<model>``) and pass through to the endpoint unchanged.

Authentication is a bearer ``CLINE_API_KEY`` from the Cline account dashboard
(Settings > API Keys). The generic model listing omits ClinePass IDs, but
the gateway advertises its catalog at ``GET /api/v1/ai/cline/recommended-models`` (key
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

# Curated catalog — the picker list and the /model validator's private
# _PROVIDER_MODELS registry (see _register_validator_catalog below).
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


def _register_validator_catalog() -> None:
    """Publish known IDs into the static catalog used by Hermes' validator.

    Provider discovery can run while models_catalog_static is still building
    _PROVIDER_MODELS. If that dict is not available yet, defer registration
    until the module's later list_providers call. The wrapper removes itself
    when registration is retried. Both import orders are covered by fresh-
    process tests against Hermes.

    models.py shares the owning module's dict, so one write serves both
    readers. Preserve IDs learned from the recommended feed on retries.
    """
    try:
        import sys

        curated = list(CURATED_MODELS)

        def _register_into(mod) -> bool:
            try:
                existing = mod._PROVIDER_MODELS.get("clinepass", [])
                # Keep live-feed IDs through a later timeout or empty response.
                merged = list(dict.fromkeys([*existing, *curated]))
                if existing != merged:
                    mod._PROVIDER_MODELS["clinepass"] = merged
                return True
            except AttributeError:
                return False

        # Preferred target: the owning module, when its dict is live.
        static_mod = sys.modules.get("hermes_cli.models_catalog_static")
        if static_mod is None:
            try:
                from hermes_cli import models_catalog_static as static_mod
            except Exception:
                static_mod = None
        if static_mod is not None and _register_into(static_mod):
            return

        # Fallback: the re-exporting module (post-import callers). If both
        # dicts are live, prefer the owner so identity is guaranteed.
        mod = sys.modules.get("hermes_cli.models")
        if mod is not None and _register_into(mod):
            return
        try:
            from hermes_cli import models as _hermes_models

            if _register_into(_hermes_models):
                return
        except Exception:
            logger.debug("_PROVIDER_MODELS registration skipped (mid-import)", exc_info=True)

        # The canonical-provider block imports list_providers after building
        # the dict, so it picks up this wrapper and retries registration.
        try:
            import providers as _providers_mod

            if getattr(_providers_mod.list_providers, "_clinepass_arm", False):
                return  # already armed, don't double-wrap
            _orig_list = _providers_mod.list_providers

            def _armed_list_providers(*a, **k):
                try:
                    _restore = _providers_mod.list_providers is _armed_list_providers
                    if _restore:
                        _providers_mod.list_providers = _orig_list
                    _register_validator_catalog()
                finally:
                    # Restore this wrapper if registration did not already replace it.
                    if _providers_mod.list_providers is _armed_list_providers:
                        _providers_mod.list_providers = _orig_list
                return _orig_list(*a, **k)

            _armed_list_providers._clinepass_arm = True
            _providers_mod.list_providers = _armed_list_providers
            logger.debug("clinepass: list_providers hook armed for deferred _PROVIDER_MODELS registration")
        except Exception:
            logger.debug("clinepass: could not arm list_providers hook", exc_info=True)
    except Exception:
        logger.debug("_PROVIDER_MODELS registration skipped", exc_info=True)


class ClinePassProfile(ProviderProfile):
    """ClinePass OpenAI-compat gateway with a live-recommended-models catalog."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        # Re-assert the validator catalog every time the picker asks for
        # models: by then hermes_cli.models is fully imported (the picker
        # code itself lives there), so the circular-import window is closed.
        _register_validator_catalog()

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

        block = payload.get(CATALOG_KEY) if isinstance(payload, dict) else None
        if not isinstance(block, list):
            return None
        ids = [
            m["id"]
            for m in block
            if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]
        ]
        if not ids:
            # Empty means the fetch is broken, not that there are no models.
            # Return None so callers use fallback_models.
            return None
        # Self-heal: the live feed can gain ids the curated list predates.
        # Merge them into the registered validator catalog so a brand-new
        # cline-pass/* model validates on first try; otherwise the /model
        # validator's curated-catalog soft-accept check would reject it
        # until the plugin shipped an update. Mutates the same dict that
        # models.py and models_catalog_static share.
        try:
            import sys

            static_mod = sys.modules.get("hermes_cli.models_catalog_static")
            models_mod = sys.modules.get("hermes_cli.models")
            target = static_mod if static_mod is not None and hasattr(static_mod, "_PROVIDER_MODELS") else models_mod
            if target is not None and hasattr(target, "_PROVIDER_MODELS"):
                registry = target._PROVIDER_MODELS.get("clinepass")
                if isinstance(registry, list):
                    merged = registry + [mid for mid in ids if mid not in registry]
                    target._PROVIDER_MODELS["clinepass"] = merged
        except Exception:
            logger.debug("clinepass: live-catalog merge skipped", exc_info=True)
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

# Publish before the first /model validation, including circular discovery.
_register_validator_catalog()
