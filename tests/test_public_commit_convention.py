"""Regression tests for the public commit message hook."""
import importlib.util
from pathlib import Path


def test_public_messages_require_a_body_and_reject_trailers():
    spec = importlib.util.spec_from_file_location('public_commit_msg', Path(__file__).resolve().parents[1]/'.githooks/commit_msg.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.problems('feat: ship evidence notebook\n\nKeep claims bound to public sources.\n') == []
    assert module.problems('feat: ship evidence notebook')
    assert module.problems('feat: ship evidence notebook\n\nWhy.\n\nReviewed-by: Example Reviewer\n')
