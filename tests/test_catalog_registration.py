"""Exercise provider discovery and the real Hermes validator in fresh processes."""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import copy
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile

repo, order, scenario = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix="clinepass-catalog-") as temp:
    home = Path(temp)
    os.environ["HERMES_HOME"] = str(home)
    os.environ["CLINE_API_KEY"] = "test-only"
    Path.home = classmethod(lambda cls: home)
    (home / "config.yaml").write_text("plugins:\n  enabled: [clinepass]\n")
    shutil.copytree(Path(repo) / "clinepass", home / "plugins/model-providers/clinepass",
                    ignore=shutil.ignore_patterns("__pycache__"))

    def offline(*args, **kwargs):
        raise OSError("network disabled in catalog regression test")

    socket.socket.connect = offline
    socket.socket.connect_ex = offline
    import providers
    original_list = providers.list_providers
    if order == "providers":
        providers.list_providers()
    elif order == "package":
        sys.path.insert(0, repo)
        import clinepass
    from hermes_cli import models, models_catalog_static
    from hermes_cli.models_validate import validate_requested_model

    profile = providers.get_provider_profile("clinepass")
    assert profile is not None
    assert models._PROVIDER_MODELS is models_catalog_static._PROVIDER_MODELS
    assert providers.list_providers is original_list, "plugin replaced provider discovery"
    original_catalog = copy.deepcopy(models_catalog_static._PROVIDER_MODELS)
    models.fetch_api_models = lambda *args, **kwargs: ["anthropic/other-model"]

    def accepted(model):
        return validate_requested_model(model, "clinepass", api_key="test-only",
                                        base_url=profile.base_url)["accepted"]

    if scenario == "startup":
        for model in profile.fallback_models:
            assert accepted(model), model
        assert not accepted("cline-pass/nonexistent-test-model")
    elif scenario == "free":
        from hermes_cli import urllib_security
        free = "stealth/pixel-canary"
        assert not accepted(free)
        urllib_security.open_credentialed_url = lambda *args, **kwargs: io.BytesIO(
            json.dumps({
                "clinePass": [{"id": "cline-pass/kimi-k3"}],
                "free": [{"id": free}],
            }).encode())
        picker = models.probe_profile_catalog("clinepass", profile, "test-only", profile.base_url)
        assert free in picker, "free feed entry is missing from the Hermes picker"
        assert accepted(free), "picker entry cannot be selected with /model"
        urllib_security.open_credentialed_url = offline
        assert profile.fetch_models(api_key="test-only") is None
        assert models.provider_model_ids("clinepass") == list(profile.fallback_models)
        assert not accepted(free), "unavailable free models must not persist in the static catalog"
        assert not accepted("stealth/nonexistent-test-model")
    else:
        from hermes_cli import urllib_security
        future = "cline-pass/new-model-from-feed"
        assert not accepted(future)
        urllib_security.open_credentialed_url = lambda *args, **kwargs: io.BytesIO(
            json.dumps({"clinePass": [{"id": future}]}).encode())
        assert future in profile.fetch_models(api_key="test-only")
        assert accepted(future)
        urllib_security.open_credentialed_url = offline
        assert profile.fetch_models(api_key="test-only") is None
        assert models.provider_model_ids("clinepass") == list(profile.fallback_models)
        assert not accepted(future), "live models must not persist in the static catalog"
        assert not accepted("cline-pass/nonexistent-test-model")
    assert models_catalog_static._PROVIDER_MODELS == original_catalog, "plugin changed the static catalog"
    assert providers.list_providers is original_list, "plugin replaced provider discovery"
    print("catalog validation passed", order, scenario)
'''


def run_probe(order, scenario):
    pytest.importorskip('providers')
    result = subprocess.run(
        [sys.executable, '-c', PROBE, str(ROOT), order, scenario],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('order', ['models', 'providers', 'package'])
def test_curated_models_validate_on_fresh_startup(order):
    run_probe(order, 'startup')


def test_live_catalog_uses_curated_fallback_after_a_failed_refresh():
    run_probe('models', 'refresh')


def test_free_catalog_models_appear_in_picker_and_validate():
    run_probe('models', 'free')
