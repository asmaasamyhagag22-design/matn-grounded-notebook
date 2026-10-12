"""Runner isolation check uses the main interpreter and never imports Docling."""
import subprocess
import sys


def test_main_venv_cannot_execute_the_reference_runner():
    result=subprocess.run([sys.executable,'eval/run_docling_part2b.py','--help'],capture_output=True,text=True)
    assert result.returncode!=0
    assert 'ISOLATED_DOCLING_VENV_REQUIRED' in result.stderr
    assert 'No module named' not in result.stderr


def test_reference_runner_is_not_importable():
    import runpy
    import pytest
    with pytest.raises(ImportError,match='STANDALONE_ONLY'):
        runpy.run_path('eval/run_docling_part2b.py')
