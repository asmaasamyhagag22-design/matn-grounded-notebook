from time import monotonic
from types import SimpleNamespace

from matn_app.answer_engine import AppChatEngine


def test_short_write_reuses_the_plan_context_and_long_write_can_grow():
    app = object.__new__(AppChatEngine)
    app.num_ctx = 4096
    app.token_counter = int
    app.clock = monotonic
    app.trace = []
    app.generator = SimpleNamespace(
        generate=lambda body: {'done': True, 'done_reason': 'stop', 'response': '{}'}
    )
    timings = {'generation_seconds': 0.0}

    def context(tokens, kind):
        payload = {'prompt': str(tokens), 'format': {}, 'options': {'num_predict': 160}}
        app._call(payload, timings, kind)
        return payload['options']['num_ctx']

    assert context(1800, 'answer_plan') == 2560
    assert context(500, 'answer_write') == 2560
    assert context(2600, 'answer_repair') == 3584
    assert context(500, 'answer_plan') == 2048
