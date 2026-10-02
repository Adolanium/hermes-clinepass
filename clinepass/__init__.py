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

# Curated catalog - the picker list and the /model validator's private
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
        # Self-heal: the live feed can gain ids the curated list predates.
        # Merge them into the registered validator catalog so a brand-new
        # pass or free model validates on first try; otherwise the /model
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

    @staticmethod
    def transform_response(response):
        """Unwrap the ClinePass envelope ONLY when the top level has no choices.

        The gateway returns an OpenAI-compatible ChatCompletion that ALSO
        carries extra ``data``/``success`` keys (the SDK parks them in
        ``model_extra``, so ``response.data`` is a truthy dict and
        ``response.choices`` is None). Verified against the live API
        2026-10-02: non-streaming completions are still double-wrapped::

            {"success": true, "data": {"choices": [...], "usage": {...}}}

        With ``streaming: false`` in Hermes (or any non-streaming code
        path: cron fallbacks, auxiliary clients), the caller reads
        ``response.choices[0]`` and fails with
        "response has no 'choices' attribute" after exhausting retries.
        Blindly returning ``response.data`` instead would break again the
        moment the gateway stops wrapping. This handles both conditionally.
        """
        # 1) Normal OpenAI shape - keep as-is.
        if getattr(response, "choices", None) is not None:
            return response

        # 2) Envelope shape - the payload lives under `.data` / dict["data"].
        data = getattr(response, "data", None)
        if data is None and isinstance(response, dict):
            data = response.get("data")

        if data is not None:
            if getattr(data, "choices", None) is not None:
                return data
            if isinstance(data, dict) and "choices" in data:
                return data

        # 3) Streaming responses (AsyncStream/Stream) have no choices yet -
        #    pass them through untouched so the caller can iterate chunks.
        return response


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

    # Wrap chat.completions.create() so every call has the ClinePass
    # `{"data": {...}}` envelope stripped before the caller tries to read
    # `response.choices[0]`. Covers BOTH the main chat path
    # (agent/chat_completion_helpers.py) and the auxiliary vision path
    # (agent/auxiliary_client.py).
    try:
        from openai import OpenAI, AsyncOpenAI  # type: ignore
    except Exception:  # pragma: no cover - openai not installed
        return

    # --- Class-level patch (MUST come first) -----------------------------
    # Instance-level patching (below) misses any client built *before* this
    # plugin loaded - e.g. a cached client held by the cron scheduler or the
    # auxiliary client cache. Those clients then return the raw
    # `{"data": {...}, "status": 200}` envelope, the agent sees
    # "response has no 'choices' attribute" and the run dies after 3
    # retries. Patching the class method covers every instance, old or new.
    try:
        from openai.resources.chat.completions import (  # type: ignore
            AsyncCompletions,
            Completions,
        )

        _orig_cls_create = Completions.create

        def _cls_create(self, *args, **kwargs):
            return ClinePassProfile.transform_response(
                _orig_cls_create(self, *args, **kwargs)
            )

        Completions.create = _cls_create  # type: ignore[method-assign]

        _orig_cls_acreate = AsyncCompletions.create

        async def _cls_acreate(self, *args, **kwargs):
            return ClinePassProfile.transform_response(
                await _orig_cls_acreate(self, *args, **kwargs)
            )

        AsyncCompletions.create = _cls_acreate  # type: ignore[method-assign]
    except Exception:  # pragma: no cover - keep instance patch as fallback
        pass

    # Drop any client cached before the patch was applied so the next
    # request rebuilds it (belt and braces with the class-level patch).
    try:
        from agent.auxiliary_client import _evict_cached_clients  # type: ignore

        _evict_cached_clients("clinepass")
    except Exception:  # pragma: no cover
        pass

    def _patch_completions(completions):
        if completions is None:
            return
        _original_create = completions.create

        def _create(*cargs, **ckwargs):
            response = _original_create(*cargs, **ckwargs)
            return ClinePassProfile.transform_response(response)

        # Preserve attribute access for tooling that introspects the method.
        try:
            _create.__wrapped__ = _original_create  # type: ignore[attr-defined]
        except Exception:
            pass
        completions.create = _create

    def _patch_sync_init(self, *args, **kwargs):
        _original_sync_init(self, *args, **kwargs)
        _patch_completions(getattr(getattr(self, "chat", None), "completions", None))

    def _patch_async_init(self, *args, **kwargs):
        _original_async_init(self, *args, **kwargs)
        completions = getattr(getattr(self, "chat", None), "completions", None)
        if completions is None:
            return
        _original_create = completions.create
        # AsyncOpenAI's completions.create is itself a coroutine - wrap it.
        async def _acreate(*acargs, **ackwargs):
            r = await _original_create(*acargs, **ackwargs)
            return ClinePassProfile.transform_response(r)
        try:
            _acreate.__wrapped__ = _original_create  # type: ignore[attr-defined]
        except Exception:
            pass
        completions.create = _acreate

    _original_sync_init = OpenAI.__init__
    OpenAI.__init__ = _patch_sync_init  # type: ignore[assignment]

    try:
        _original_async_init = AsyncOpenAI.__init__
        AsyncOpenAI.__init__ = _patch_async_init  # type: ignore[assignment]
    except Exception:
        pass


# Drop-in discovery imports this module and expects registration at import time.
register()

# Publish before the first /model validation, including circular discovery.
_register_validator_catalog()
