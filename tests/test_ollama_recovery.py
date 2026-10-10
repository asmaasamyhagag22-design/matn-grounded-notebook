"""Recovery must refuse corruption without replacing existing work."""
import hashlib
import json

import pytest

from scripts.recover_ollama_models import TAGS, recover


def test_model_recovery_verifies_copies_and_refuses_existing_corruption(tmp_path):
    source = tmp_path / 'source'
    destination = tmp_path / 'destination'
    data = b'public synthetic model fixture'
    sha = hashlib.sha256(data).hexdigest()
    blob = 'blobs/sha256-' + sha
    (source / blob).parent.mkdir(parents=True)
    (source / blob).write_bytes(data)
    layer = {'digest': 'sha256:' + sha, 'size': len(data)}
    for tag in TAGS:
        path = source / 'manifests/registry.ollama.ai/library' / tag
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'config': layer, 'layers': [layer]}))
    records = recover(source, destination)
    assert len(records) == 2
    assert (destination / blob).read_bytes() == data
    assert (source / blob).read_bytes() == data
    (destination / blob).write_bytes(b'corrupted existing work')
    with pytest.raises(ValueError, match='Destination differs'):
        recover(source, destination)
    assert (destination / blob).read_bytes() == b'corrupted existing work'
