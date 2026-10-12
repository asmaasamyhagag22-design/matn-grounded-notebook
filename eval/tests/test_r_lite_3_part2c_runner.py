"""Exercise the standalone runner's actual progress loop without importing Docling."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def run_progress(tmp_path, premature=False, interrupt=False):
    tree = ast.parse(Path('eval/run_docling_part2b.py').read_text())
    save = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'save')
    loop = next(n for n in tree.body if isinstance(n, ast.Try))
    if premature:
        loop.body.insert(0, ast.parse("status='COMPLETE'").body[0])
    program = ast.fix_missing_locations(ast.Module(body=[save, loop], type_ignores=[]))
    pdf = tmp_path / 'fake.pdf'
    pdf.write_bytes(b'fixture; never opened by a PDF reader')
    calls = []
    cfg = {'inputs': [{'pdf': str(pdf), 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
                       'source': 'fixture', 'pages': [0, 1]}],
           'model_repo': 'fixture', 'model_revision': 'fixture', 'real6': {},
           'cost_gate': {'sample_pages': 99, 'seconds_limit': 999}}

    def convert(path, page_range):
        if calls:
            progress = json.loads((tmp_path / 'labels.json').read_text())
            assert progress['status'] == 'RUNNING', 'COMPLETE_BEFORE_ALL_PAGES'
        calls.append(page_range)
        if interrupt and len(calls) == 2:
            raise RuntimeError('simulated page failure')
        page = SimpleNamespace(page_no=page_range[0], size=SimpleNamespace(width=10, height=20),
                               predictions=SimpleNamespace(layout=SimpleNamespace(clusters=[])))
        return SimpleNamespace(pages=[page])

    env = dict(Path=Path, hashlib=hashlib, json=json,
               time=SimpleNamespace(perf_counter=lambda: 1),
               resource=SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: SimpleNamespace(ru_maxrss=1)),
               pdfium=SimpleNamespace(PdfDocument=lambda _: SimpleNamespace(__len__=lambda: 2)),
               converter=SimpleNamespace(convert=convert), cfg=cfg, raw=b'fixture',
               output=tmp_path / 'labels.json', metrics_path=tmp_path / 'metrics.json',
               records=[], metrics=[], opened=[], start=0, status='RUNNING', estimate=None)

    class FakePDF:
        def __len__(self): return 2
        def close(self): pass
    env['pdfium'] = SimpleNamespace(PdfDocument=lambda _: FakePDF())
    exec(compile(program, '<actual runner progress loop>', 'exec'), env)
    final = json.loads((tmp_path / 'labels.json').read_text())
    assert final['status'] == 'COMPLETE'
    assert len(final['pages']) == 2
    return final


def test_complete_only_after_every_page(tmp_path):
    run_progress(tmp_path)


def test_premature_complete_mutation_is_detected(tmp_path):
    with pytest.raises(AssertionError, match='COMPLETE_BEFORE_ALL_PAGES'):
        run_progress(tmp_path, premature=True)


def test_interrupted_page_never_reports_complete(tmp_path):
    with pytest.raises(RuntimeError, match='simulated page failure'):
        run_progress(tmp_path, interrupt=True)
    assert json.loads((tmp_path / 'labels.json').read_text())['status'] == 'STOP_RUNNER_ERROR'
    assert len(json.loads((tmp_path / 'labels.json').read_text())['pages']) == 1
