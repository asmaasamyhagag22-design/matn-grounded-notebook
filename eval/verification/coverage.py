"""Explicit five-dev-snapshot coverage only; never discover PDFs or sealed inputs."""
import argparse
import json
from pathlib import Path
from matn_contracts.structure import DocumentStructure
from matn_verification.rules import coverage

DEV_PATHS = {
    name: f'out/r-lite-3/closure/production/{name}/05_document.json'
    for name in ('2601-14525v1','gao-21-519sp','wb-eem-2021-12','wef-future-of-jobs-2025')
}
DEV_PATHS['egypt-2021-vnr'] = 'out/smoke/egypt-2021-vnr/baseline/05_document.json'


def load_documents():
    return {name:DocumentStructure.model_validate_json(Path(path).read_bytes()) for name,path in DEV_PATHS.items()}


def measure():
    return {name:{**coverage(doc),'path':DEV_PATHS[name]} for name,doc in load_documents().items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='out/v1/coverage.json')
    args=parser.parse_args()
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(measure(),ensure_ascii=False,sort_keys=True,indent=2)+'\n')


if __name__=='__main__': main()
