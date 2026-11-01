"""Replay availability against saved validated documents, without any acquisition.

Example: python -m eval.research.catalogue_trace --pack saved/input.json \
    --document saved/source/document.json --output out/catalogue-trace.json
The frozen pack and reader snapshots are read-only. A new output is required.
"""
import argparse
import json
from pathlib import Path

from matn_contracts.structure import DocumentStructure
from matn_research.catalogue_audit import availability


def trace(pack_path, document_paths, output_path):
    paths = [Path(pack_path), *map(Path, document_paths)]
    for path in [*paths, Path(output_path)]:
        # This diagnostic is development-only, never a milestone/test-gold read.
        parts = path.resolve().parts
        if any(parts[i:i+3] == ('eval', 'gold', 'test') for i in range(len(parts)-2)):
            raise ValueError('SEALED_TEST_INPUT_FORBIDDEN')
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError('NEW_AUDIT_OUTPUT_REQUIRED')
    pack = json.loads(paths[0].read_bytes())
    documents = [DocumentStructure.model_validate_json(path.read_bytes()) for path in paths[1:]]
    if len({d.doc_id for d in documents}) != len(documents):
        raise ValueError('DUPLICATE_DOCUMENT_SNAPSHOT')
    audit = availability(documents, pack)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('x', encoding='utf-8') as output:
        json.dump(audit, output, ensure_ascii=False, indent=2)
        output.write('\n')
    return {key: audit[key] for key in ('version', 'sources', 'task', 'counts', 'first_unavailable_counts')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', required=True, type=Path)
    parser.add_argument('--document', required=True, action='append', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(trace(args.pack, args.document, args.output)))


if __name__ == '__main__':
    main()
