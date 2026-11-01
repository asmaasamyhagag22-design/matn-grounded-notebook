"""The delivery identity detects drift and additional executable app source."""
import subprocess

import pytest

from git_environment import git_environment
from matn_app import freeze
from matn_app.store import write


def test_runtime_tampering_and_new_runtime_files_invalidate_freeze(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=git_environment(), check=True)
    source = tmp_path / "matn_app/service.py"
    source.parent.mkdir()
    source.write_text("policy = 'original'\n")
    manifest = tmp_path / "frozen.json"
    write(manifest, freeze.identity(tmp_path))
    actual_identity = freeze.identity
    monkeypatch.setattr(freeze, "identity", lambda: actual_identity(tmp_path))
    assert freeze.verify(manifest)["status"] == "PRODUCT_IDENTITY_MATCHES"
    source.write_text("policy = 'changed'\n")
    with pytest.raises(ValueError, match="matn_app/service.py"):
        freeze.verify(manifest)
    source.write_text("policy = 'original'\n")
    (source.parent / "extra.py").write_text("extra = True\n")
    with pytest.raises(ValueError, match="matn_app/extra.py"):
        freeze.verify(manifest)


def test_documentation_and_run_outputs_are_outside_runtime_identity(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=git_environment(), check=True)
    (tmp_path / "app.sh").write_text("python -m matn_app\n")
    manifest = tmp_path / "frozen.json"
    write(manifest, freeze.identity(tmp_path))
    actual_identity = freeze.identity
    monkeypatch.setattr(freeze, "identity", lambda: actual_identity(tmp_path))
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/HANDOFF.md").write_text("Final documentation\n")
    (tmp_path / "out").mkdir()
    (tmp_path / "out/result.json").write_text('{}')
    assert freeze.verify(manifest)["status"] == "PRODUCT_IDENTITY_MATCHES"


@pytest.mark.parametrize("relative", ["matn_presentation/render.py", "matn_summarization/policy.py",
    "document_store.py", "design/chart_rules.json", "schemas/runtime.json",
    "eval/reading/thresholds.json", "requirements-app.txt", "git_environment.py"])
def test_transitive_runtime_dependencies_cannot_drift(tmp_path, monkeypatch, relative):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=git_environment(), check=True)
    source = tmp_path / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("original")
    manifest = tmp_path / "frozen.json"
    write(manifest, freeze.identity(tmp_path))
    actual = freeze.identity
    monkeypatch.setattr(freeze, "identity", lambda: actual(tmp_path))
    source.write_text("changed")
    with pytest.raises(ValueError, match="PRODUCT_CODE_DRIFT"):
        freeze.verify(manifest)
