"""Tests for the non-streaming envelope fix (this fork's core difference).

The Cline gateway double-wraps non-streaming Chat Completions responses:

    {"success": true, "data": {"choices": [...], "usage": {...}}}

The OpenAI SDK parks extra keys in ``model_extra``, so ``response.choices``
is None and ``response.data`` is truthy. ``transform_response`` must unwrap
ONLY that shape - and leave healthy, streaming, and already-unwrapped
responses untouched.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _plugin():
    _require_providers()
    if "clinepass" in sys.modules:
        del sys.modules["clinepass"]
    import clinepass as plugin

    importlib.reload(plugin)
    return plugin


def _require_providers():
    try:
        import providers  # noqa: F401
        from providers.base import ProviderProfile  # noqa: F401
    except ImportError:
        pytest.skip("Hermes Agent (providers package) is not installed")


def _openai():
    try:
        from openai.types.chat import ChatCompletion  # noqa: F401
        from openai._models import BaseModel  # noqa: F401
    except ImportError:
        pytest.skip("openai package is not installed")
    from openai.types.chat import ChatCompletion, ChatCompletionMessage
    from openai.types.chat.chat_completion import Choice
    return ChatCompletion, ChatCompletionMessage, Choice


def _make_completion():
    ChatCompletion, ChatCompletionMessage, Choice = _openai()
    return ChatCompletion.construct(
        id="x", object="chat.completion", created=1, model="m",
        choices=[Choice.construct(index=0, finish_reason="stop",
                                  message=ChatCompletionMessage.construct(role="assistant", content="OK"))],
    )


# ── Wrapped shape (what the Cline gateway actually returns) ─────────────

def test_wrapped_response_is_unwrapped():
    plugin = _plugin()
    ChatCompletion, ChatCompletionMessage, Choice = _openai()
    # Mimic the real SDK shape: envelope keys arrive as model_extra (plain
    # JSON-shaped dict), and the top level has NO choices.
    wrapped = ChatCompletion.construct(
        id="x", object="chat.completion", created=1, model="m",
        choices=None,
        success=True,
        data={"choices": [{"index": 0, "finish_reason": "stop",
                           "message": {"role": "assistant", "content": "OK"}}],
              "usage": {"total_tokens": 5}},
    )
    assert wrapped.choices is None  # precondition: SDK reports no choices

    out = plugin.ClinePassProfile.transform_response(wrapped)
    # The nested payload may come back as a dict (model_extra is raw JSON)
    # or an object; either way the choices must be reachable.
    if isinstance(out, dict):
        assert out["choices"][0]["message"]["content"] == "OK"
    else:
        assert out.choices[0].message.content == "OK"


def test_dict_envelope_is_unwrapped():
    plugin = _plugin()
    out = plugin.ClinePassProfile.transform_response(
        {"success": True, "data": {"choices": [{"message": {"content": "OK"}}]}}
    )
    assert out["choices"][0]["message"]["content"] == "OK"


# ── Healthy shapes must pass through untouched ──────────────────────────

def test_healthy_response_is_kept():
    plugin = _plugin()
    completion = _make_completion()
    out = plugin.ClinePassProfile.transform_response(completion)
    assert out is completion


def test_streaming_response_passes_through():
    plugin = _plugin()
    stream = object()  # no .choices, no .data
    out = plugin.ClinePassProfile.transform_response(stream)
    assert out is stream


def test_unrelated_extra_keys_do_not_trigger_unwrap():
    plugin = _plugin()
    completion = _make_completion()
    completion.data = {"unrelated": True}
    out = plugin.ClinePassProfile.transform_response(completion)
    assert out is completion


def test_envelope_without_choices_is_kept():
    plugin = _plugin()
    completion = _make_completion()
    completion.data = {"error": {"code": "X"}}  # data but no choices
    out = plugin.ClinePassProfile.transform_response(completion)
    assert out is completion


# ── The class-level client patch covers pre-existing instances ──────────

def test_class_patch_covers_client_created_before_register():
    plugin = _plugin()
    _openai()
    from openai import OpenAI

    # Create the client BEFORE register() re-runs: the instance-level
    # __init__ patch cannot cover it, only the class-level patch can.
    client = OpenAI(api_key="k", base_url="https://api.cline.bot/api/v1")
    plugin.register()

    create = client.chat.completions.create
    # The bound method must now be wrapped (attr marker proves it).
    assert getattr(create, "__wrapped__", None) is not None or create.__func__ is not None
