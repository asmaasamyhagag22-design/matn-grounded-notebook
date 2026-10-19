"""Standard-library-only pinned model file validation for isolated workers."""
import hashlib
from pathlib import Path

PINS = {
    'lytang/MiniCheck-RoBERTa-Large': '74c8919647e61ed0f71bc177d94f10930f090068',
    'vectara/hallucination_evaluation_model': 'de9a5e6ba9ba49531a022dba17e35ffeb2a6fad8',
}


def validate_files(root, manifest):
    root=Path(root).resolve()
    if manifest.get('repo') not in PINS or manifest.get('revision') != PINS.get(manifest.get('repo')) or not manifest.get('files'):
        raise ValueError('unapproved model identity')
    for name,digest in manifest['files'].items():
        p=(root/name).resolve()
        if not p.is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            raise ValueError('model file hash mismatch')



def validate_foundation(manifest):
    revision='7bcac572ce56db69c1ea7c8af255c5d7c9672fc2'
    if manifest.get('repo')!='google/flan-t5-base' or manifest.get('revision')!=revision or manifest.get('weights_downloaded') is not False:
        raise ValueError('foundation identity drift')
    for record in manifest['files'].values():
        p=Path(record['cache_path'])
        if p.parent.name!=revision or hashlib.sha256(p.read_bytes()).hexdigest()!=record['sha256']:
            raise ValueError('foundation hash mismatch')
        if (p.parents[2]/'refs'/'main').read_text().strip()!=revision:
            raise ValueError('foundation offline reference drift')
