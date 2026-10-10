"""Copy only the two approved model tags from a read-only Windows mount, verifying all blobs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

SOURCE = Path('/media/asmaa/Windows/Users/asmaa/.ollama/models')
DESTINATION = Path('/usr/share/ollama/.ollama/models')
TAGS = ('glm-ocr/bf16', 'qwen3.5/9b')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def recover(source: Path, destination: Path, *, owner: tuple[int, int] | None = None) -> list[dict]:
    records = []
    relative_root = Path('manifests/registry.ollama.ai/library')
    # Validate every source and existing destination before copying any file.
    files = {}
    for tag in TAGS:
        relative = relative_root / tag
        manifest_path = source / relative
        manifest = json.loads(manifest_path.read_bytes())
        files[relative] = digest(manifest_path)
        for layer in [manifest['config'], *manifest['layers']]:
            expected = layer['digest']
            if not expected.startswith('sha256:') or len(expected) != 71:
                raise ValueError('Invalid blob digest')
            int(expected[7:], 16)
            blob = Path('blobs') / expected.replace(':', '-')
            if (source / blob).stat().st_size != layer['size'] or digest(source / blob) != expected[7:]:
                raise ValueError(f'Source model hash/size mismatch: {blob}')
            files[blob] = expected[7:]
        records.append({'tag': tag, 'manifest_digest': files[relative]})
    for relative, expected in files.items():
        target = destination / relative
        if target.exists() and digest(target) != expected:
            raise ValueError(f'Destination differs; preserve and review before replacement: {target}')
    # Blobs first, manifests last; a partial copy never registers an incomplete tag.
    for relative in sorted(files, key=lambda path: path.parts[0] != 'blobs'):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name(target.name + '.migration-copy')
            if temporary.exists():
                raise FileExistsError(f'Previous partial copy retained: {temporary}')
            shutil.copyfile(source / relative, temporary)
            if digest(temporary) != files[relative]:
                raise ValueError(f'Copied hash mismatch; retained for inspection: {temporary}')
            temporary.rename(target)
        if digest(target) != files[relative]:
            raise ValueError(f'Post-copy hash mismatch: {target}')
        if owner:
            os.chown(target, *owner)
            parent = target.parent
            while parent != destination:
                os.chown(parent, *owner)
                parent = parent.parent
    return records


def main() -> None:
    import pwd
    if os.geteuid() != 0:
        raise PermissionError('System Ollama store requires root')
    options = subprocess.check_output(['findmnt', '-no', 'OPTIONS', '--target', str(SOURCE)], text=True).strip()
    if 'ro' not in options.split(','):
        raise RuntimeError('Windows source must be mounted read-only')
    account = pwd.getpwnam('ollama')
    print(json.dumps(recover(SOURCE, DESTINATION, owner=(account.pw_uid, account.pw_gid)), indent=2))


if __name__ == '__main__':
    main()
