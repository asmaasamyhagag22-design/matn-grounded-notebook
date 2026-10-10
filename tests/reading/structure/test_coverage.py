import pytest
from matn_contracts.structure import PrimarySpan
from matn_reading.structure.coverage import interval_partition, resolve_citation

def test_primary_spans_partition_citable_characters():
    def spans(*pairs): return [PrimarySpan(block_id='b',start=a,end=z) for a,z in pairs]
    interval_partition({'b':10},spans((0,4),(4,10)))
    for bad in [spans((0,4),(5,10)),spans((0,6),(5,10)),spans((0,10),(0,10)),[]]:
        with pytest.raises(ValueError): interval_partition({'b':10},bad)

def test_every_primary_numeric_token_is_accounted_for():
    from .conftest import snapshot,record
    from matn_reading.structure.document import assemble
    from matn_reading.structure.coverage import validate_coverage
    d=assemble(snapshot([record('Growth 12.')]))
    missing=d.chunks[0].model_copy(update={'numeric_tokens':()})
    with pytest.raises(ValueError,match='NUMBER_COVERAGE'):
        validate_coverage(d.elements,d.sections,(missing,))
