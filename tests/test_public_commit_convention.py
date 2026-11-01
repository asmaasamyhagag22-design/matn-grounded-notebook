"""The public convention is distinct from the private development trailer policy."""
import importlib.util
from pathlib import Path


def test_public_owner_messages_have_why_body_and_no_agent_trailer():
    spec = importlib.util.spec_from_file_location('public_commit_msg', Path(__file__).resolve().parents[1]/'.githooks/commit_msg.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.problems('feat: ship evidence notebook\n\nKeep claims bound to public sources.\n') == []
    assert module.problems('feat: ship evidence notebook')
    assert module.problems('feat: ship evidence notebook\n\nWhy.\n\nAgent: codex\n')
