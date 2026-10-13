"""The diagnostic second-opinion runner cannot import or execute in main .venv."""
import runpy
import subprocess
import sys
import pytest


def test_second_opinion_runner_stays_isolated():
    r=subprocess.run([sys.executable,'eval/run_docling_part2c.py'],capture_output=True,text=True)
    assert r.returncode!=0 and 'ISOLATED_DOCLING_VENV_REQUIRED' in r.stderr
    assert 'No module named' not in r.stderr


def test_second_opinion_runner_is_standalone_only():
    with pytest.raises(ImportError,match='STANDALONE_ONLY'):
        runpy.run_path('eval/run_docling_part2c.py')
