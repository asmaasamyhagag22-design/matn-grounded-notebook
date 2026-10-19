"""Production C1 selects cached text-only vectors and keeps equal RRF."""
from matn_rag.search import Search
from matn_rag.scoring import fuse


def test_production_uses_text_only_embedding_inputs():
    class Repository:
        revision = 0
        def validate_selection(self, notebook, selected): pass
        def selected_chunks(self, notebook, selected):
            return []
        def source_stats(self, selected, variant):
            self.variant = variant
            return {}
        def vectors(self, selected, variant):
            assert variant == 'doc-input-no-prefix-v1'
            return {}
    repo = Repository()
    Search(repo, None).query('n', ['s'], 'question')
    assert repo.variant == 'doc-input-no-prefix-v1'


def test_production_fusion_remains_equal_rrf_k60():
    result = dict(fuse([('a', 9), ('b', 8)], [('b', .9), ('a', .8)]))
    assert result['a'] == result['b'] == 1/61 + 1/62
