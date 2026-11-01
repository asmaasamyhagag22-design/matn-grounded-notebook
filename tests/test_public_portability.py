"""Public setup must work without the private vault and keep explicit external vaults read-only."""
from pathlib import Path
import pytest
from matn_app import runtime, service


def test_public_default_data_and_missing_replays(tmp_path, monkeypatch):
    assert runtime.ORIGINAL == runtime.ROOT
    assert runtime.DATA_ROOT == runtime.ROOT / '.matn-data'
    monkeypatch.setattr(service, 'ORIGINAL', tmp_path)
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    app = service.App(tmp_path / '.matn-data/app', fake=True)
    try:
        assert app.bootstrap()['replays'] == []
        assert app.store.create()['id']
    finally:
        app.close()


def test_explicit_external_vault_remains_read_only(tmp_path, monkeypatch):
    vault = tmp_path / 'vault'
    monkeypatch.setattr(service, 'ORIGINAL', vault)
    monkeypatch.setattr(service, 'ROOT', tmp_path / 'public')
    with pytest.raises(ValueError, match='read-only vault'):
        service.App(vault / 'data', fake=True)


def test_native_environment_configuration_reaches_existing_adapter(monkeypatch):
    from matn_chat import engine
    seen = []
    class Adapter:
        def __init__(self, python, model):
            seen.append((python, model))
        def check(self, *args):
            return 'same-adapter'
        def close(self):
            pass
    monkeypatch.setattr(engine, 'L4Adapter', Adapter)
    monkeypatch.setenv('MATN_NLI_PYTHON', '/opt/local-nli/bin/python')
    monkeypatch.setenv('MATN_MINICHECK_DIR', '/opt/local-models/MiniCheck-RoBERTa-Large')
    model = engine.MiniCheck()
    try:
        assert model.check('text', [], 'claim') == 'same-adapter'
        assert seen == [(Path('/opt/local-nli/bin/python'), Path('/opt/local-models/MiniCheck-RoBERTa-Large'))]
    finally:
        model.close()
