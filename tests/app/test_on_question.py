"""ADR-0037: a verified answer is shown only if it addresses the question."""
from matn_app.on_question import BOUNDARY, gate

VALUE = dict(sentences=[dict(kind='generated_verified_unit', text='Agencies must document data sources.'),
                        dict(kind='notice', text='Sources listed below.')])


class Fixed:
    def __init__(self, score): self.score = score
    def rank(self, question, hits): return [dict(hits[0], rerank_score=self.score)]


class Broken:
    def rank(self, question, hits): raise RuntimeError('worker died')


def test_on_question_answer_is_kept():
    keep, audit = gate('What must agencies document?', VALUE, Fixed(0.99))
    assert keep and audit['passed'] and audit['boundary'] == BOUNDARY == 0.5


def test_off_question_answer_is_withheld():
    keep, audit = gate('What must agencies document?', VALUE, Fixed(0.03))
    assert not keep and audit['reason'] == 'off_question'


def test_scoring_failure_never_passes_silently():
    keep, audit = gate('q', VALUE, Broken())
    assert not keep and audit['reason'] == 'scoring_failed' and audit['error'] == 'RuntimeError'


def test_no_generated_answer_is_not_scored():
    keep, audit = gate('q', dict(sentences=[dict(kind='notice', text='x')]), Broken())
    assert keep and audit['applied'] is False
