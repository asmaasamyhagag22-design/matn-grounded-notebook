"""Research must resolve subject and audience before planning or spending searches."""
import time
from pathlib import Path
import pytest
from matn_app.service import App
from matn_app.store import read,write


def complete(app,c,job):
    end=time.monotonic()+5
    while time.monotonic()<end:
        state=app.store.get(c);current=next(j for j in state['jobs'] if j['id']==job['id'])
        if current['status'] not in ('queued','running'):
            assert current['status']=='complete',current
            return state
        time.sleep(.01)
    raise AssertionError('Local clarification did not complete')


@pytest.mark.parametrize('topic',['transformer','python','mercury'])
def test_known_ambiguity_asks_once_without_defaulting_audience(tmp_path,monkeypatch,topic):
    app=App(tmp_path/'app',fake=True);app.fake=False
    monkeypatch.setattr(app.processes,'run',lambda *a,**k:pytest.fail('No model or search before explicit scope'))
    try:
        c=app.store.create()['id'];state=complete(app,c,app.action(c,dict(text=topic)))
        assert not state['plans'] and not state['audience_explicit']
        pending=state['pending_research']
        assert pending['needs_meaning'] and pending['needs_audience']
        assert pending['options'][-1]['label']=='Other'
        assert len([m for m in state['messages'] if m.get('kind')=='clarification'])==1
        assert not (app.store.root/'search-reservations.json').exists()
        seen=[]
        monkeypatch.setattr(app,'_plan',lambda conversation,topic,job,emit,**kw:seen.append((topic,kw)))
        complete(app,c,app.action(c,dict(action='clarify',choice='0',audience='Engineers')))
        state=app.store.get(c)
        assert state['audience']=='Engineers' and state['audience_explicit']
        assert seen==[(pending['options'][0]['topic'],dict(clarified=True))]
        assert state['pending_research'] is None
    finally:app.close()


def test_unambiguous_control_with_explicit_audience_proceeds_to_plan(tmp_path,monkeypatch):
    app=App(tmp_path/'app',fake=True);app.fake=False
    checks=[]
    def worker(module,request,folder,emit,**kwargs):
        checks.append(request)
        return dict(senses=[],metrics=dict(generation_calls=0))
    def process(command,folder,emit,**kwargs):
        assert '--plan-only' in command and command[command.index('--audience')+1]=='Building managers'
        run=Path(command[command.index('--out')+1])
        plan=dict(facets=[dict(id='axis'+str(i),label='Public evidence '+str(i),success='Find source-backed evidence for the specified topic',searches=['public building photovoltaic panels']) for i in range(4)])
        write(run/'outcome.json',dict(plan=plan));return 0
    monkeypatch.setattr(app,'_worker',worker);monkeypatch.setattr(app.processes,'run',process)
    try:
        c=app.store.create(audience='Building managers')['id']
        state=complete(app,c,app.action(c,dict(text='Photovoltaic panels on public buildings')))
        assert state['plans'] and not state.get('pending_research')
        assert checks==[dict(operation='clarify',topic='Photovoltaic panels on public buildings')]
        assert not (app.store.root/'search-reservations.json').exists()
    finally:app.close()


def test_failed_generic_sense_check_recovers_to_explicit_scope(tmp_path,monkeypatch):
    app=App(tmp_path/'app',fake=True);app.fake=False
    def fail(*args,**kwargs):raise TimeoutError('Bounded local test failure')
    monkeypatch.setattr(app,'_worker',fail)
    try:
        c=app.store.create()['id'];state=complete(app,c,app.action(c,dict(text='Unspecified term')))
        assert state['pending_research']['require_topic'] and not state['plans']
        with pytest.raises(ValueError,match='meaning and audience'):
            app.action(c,dict(action='clarify',choice='0',audience='Reviewers'))
        assert 'RECOVERED' in (app.store.root/'recovered.jsonl').read_text()
    finally:app.close()
