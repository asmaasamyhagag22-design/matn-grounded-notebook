"""The application requires the tokenizer subprocess even in a lean export."""
from importlib.util import find_spec
import json
from pathlib import Path
import re


def test_tokenizer_worker_and_pinned_profile_are_shipped():
    spec = find_spec('eval.chat.tokenizer_worker')
    assert spec is not None and spec.origin
    profile = json.loads(Path(spec.origin).with_name('tokenizer_profile.json').read_bytes())
    assert re.fullmatch(r'sha256-[0-9a-f]{64}', profile['gguf_blob'])
