import pytest
from matn_contracts.structure import PrimarySpan
from matn_reading.structure.coverage import interval_partition, resolve_citation

def test_primary_spans_partition_citable_characters():
    def spans(*pairs): return [PrimarySpan(block_id='b',start=a,end=z) for a,z in pairs]
    interval_partition({'b':10},spans((0,4),(4,10)))
    for bad in [spans((0,4),(5,10)),spans((0,6),(5,10)),spans((0,10),(0,10)),[]]:
        with pytest.raises(ValueError): interval_partition({'b':10},bad)
