"""On-question gate for generated answers (week-loop RCA-004 / ADR-0037).

Verification proves each sentence is faithful to its cited span, not that the
answer addresses the question. Before display, the pinned Qwen3-Reranker-0.6B
judges whether the verified answer text meets the question. The decision uses
the reranker's own yes/no boundary (P(yes) > 0.5), not a threshold fitted to
data. A failed answer is withheld, so the existing coverage path explains what
the sources do cover instead. Fake runs and reranker failures are recorded and
never silently pass: an unscored answer is withheld too.
"""
VERSION = 'reranker-yes-boundary-v1'
BOUNDARY = 0.5


def answer_text(value):
    return ' '.join(s.get('text', '') for s in value.get('sentences', []) if s.get('kind') == 'generated_verified_unit').strip()


def gate(question, value, reranker):
    """Return (keep, audit). `reranker.rank(question, hits)` returns hits with `rerank_score`."""
    text = answer_text(value)
    if not text:
        return True, dict(policy=VERSION, applied=False, reason='no_generated_answer')
    try:
        score = float(reranker.rank(str(question), [dict(chunk_id='answer', text=text)])[0]['rerank_score'])
    except Exception as exc:  # recorded; an answer that cannot be scored is not shown as a direct answer
        return False, dict(policy=VERSION, applied=True, passed=False, reason='scoring_failed', error=type(exc).__name__)
    passed = score > BOUNDARY
    return passed, dict(policy=VERSION, applied=True, passed=passed, score=round(score, 4), boundary=BOUNDARY,
                        reason='answers_question' if passed else 'off_question')
