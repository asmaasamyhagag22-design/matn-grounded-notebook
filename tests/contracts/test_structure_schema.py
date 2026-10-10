from pathlib import Path
from matn_contracts.structure_schema_export import render_schema_files

def test_structure_schema_snapshots():
    root=Path(__file__).resolve().parents[2]/'schemas/contracts/structure'
    expected=render_schema_files()
    assert {p.name for p in root.glob('*.json')}==set(expected)
    for name,text in expected.items(): assert (root/name).read_text()==text
