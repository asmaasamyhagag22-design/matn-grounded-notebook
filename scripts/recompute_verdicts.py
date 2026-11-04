"""Recompute every registered verdict (M7, M4, answers v2) from owner labels.

Owner label beats AI review for its exact bound unit; borderline counts as each
pre-registered rule states (verdict-bases.json). Never writes owner labels:
they are appended only through the labelling tool.
"""
import argparse
import json
from pathlib import Path

from matn_app.labels import LabelStore
from matn_app.runtime import DATA_ROOT
from matn_app.store import write


def recompute(root):
    summary = LabelStore(root).summary()
    rows = {key: dict(status=v['status'], owner_labelled=v['owner_labelled'], AI_only=v['AI_review'], errors=v['errors'],
                      borderline=v['borderline'], borderline_is_error=v['borderline_is_error'], direct_answers=v['direct_answers'],
                      fixed_gates_pass=v['fixed_gates_pass'])
            for key, v in summary['verdicts'].items()}
    value = dict(verdicts=rows, owner_labelled=summary['owner_labelled'], AI_only=summary['total'] - summary['owner_labelled'],
                 review='Owner labels override AI review for their exact units; everything else is AI review, not human gold.')
    write(Path(root) / 'verdicts.json', value)
    return value


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=DATA_ROOT / 'labels')
    a = p.parse_args()
    value = recompute(a.root)
    for key, v in value['verdicts'].items():
        print(f"{key}: {v['status']} · owner-labelled {v['owner_labelled']} / AI-only {v['AI_only']}")
