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
    """Publish CURATED_MODELS into hermes_cli.models._PROVIDER_MODELS.

    validate_requested_model hard-rejects model ids missing from both the
    live /v1/models listing and the in-repo _PROVIDER_MODELS dict. api.cline.bot
    now serves an aggregator listing (z-ai/*, anthropic/*, …) with no
    cline-pass/* ids, so without this our ids always reject.

    Timing: this plugin is imported by providers/ discovery, which
    hermes_cli/models_catalog_static.py itself triggers at import time (its
    CANONICAL_PROVIDERS auto-extend block, line ~356) — that runs while
    hermes_cli.models_catalog_static is STILL mid-import (its _PROVIDER_MODELS
    at line ~155 IS defined by then) and while hermes_cli.models is
    mid-import too (it imported models_catalog_static at its line 31, before
    defining anything). sys.modules["hermes_cli.models"] therefore exists but
    has no _PROVIDER_MODELS yet, and a real import returns that same partial
    module, so both paths raised AttributeError and were swallowed — the
    /model validator then hard-rejected every cline-pass/* id (v1.2.0 bug).

    Fix: register into hermes_cli.models_catalog_static, the module that OWNS
    the dict. models.py re-exports it by reference (from-import binds the
    same object), so one write serves both readers.

    The window is deeper than "models.py mid-import": discovery is triggered
    from models_catalog_static's own module init — _codex_curated_models()
    (line ~73, BEFORE _PROVIDER_MODELS at ~155) → codex_models →
    agent.model_metadata → providers.list_providers() → discovery → this
    module. At that instant NEITHER _PROVIDER_MODELS exists, so both direct
    targets fail. The guaranteed post-definition touchpoint is
    models_catalog_static line ~361: its CANONICAL_PROVIDERS auto-extend
    block calls providers.list_providers() again AFTER the dict is built.
    So when both targets are missing, install a one-shot self-removing
    wrapper around providers.list_providers: the auto-extend call triggers
    it, registration lands, then the original function is restored. Still
    re-asserted from fetch_models as belt-and-braces. Idempotent.
    """
    try:
        import sys

        curated = list(CURATED_MODELS)

        def _register_into(mod) -> bool:
            try:
                existing = mod._PROVIDER_MODELS.get("clinepass")
                if existing != curated:
                    mod._PROVIDER_MODELS["clinepass"] = curated
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

        # Circular window (neither dict exists yet): arm the deferred hook on
        # providers.list_providers. models_catalog_static's auto-extend block
        # calls it AFTER its dict is built; the wrapper registers then and
        # restores the original. list_providers is captured from the live
        # providers module object — the from-import in models_catalog_static
        # bound the ORIGINAL function there, so re-binding the module attr
        # is exactly what that call site will invoke.
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
                    # Un-arm even on failure so a broken hook can't loop.
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

# Register eagerly: during gateway/CLI startup this module executes from
# models_catalog_static's CANONICAL_PROVIDERS auto-extend block, while BOTH
# hermes_cli.models and hermes_cli.models_catalog_static are still mid-import —
# but the static module's _PROVIDER_MODELS (its line ~155) already exists, and
# _register_validator_catalog targets that owning module first. models.py
# re-exports the same dict object, so a direct `/model cline-pass/...` switch
# validates correctly even if fetch_models never ran.
_register_validator_catalog()
