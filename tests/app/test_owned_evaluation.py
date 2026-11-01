"""Fresh app runs stay visible in Evaluation alongside the read-only history."""
from matn_app.service import App
from matn_app.demo import research


def test_owned_runs_get_unique_ids_and_safe_replay_paths(tmp_path,monkeypatch):
    import eval.research.dashboard.data
    monkeypatch.setattr(eval.research.dashboard.data,'collect',lambda root:dict(runs=[],benches=[]))
    app=App(tmp_path/'app',fake=True)
    try:
        c=app.store.create()['id'];folders=[]
        for job in ('first','second'):
            folder=app.store.folder(c)/'jobs'/job/'research';research(folder,'Public fixture '+job);folders.append(folder)
        app.store.update(c,lambda v:v['runs'].extend(dict(folder=str(p),status='saved') for p in folders))
        rows=app.evaluation()['scoreboard']['runs']
        assert len(rows)==2 and len({r['id'] for r in rows})==2
        assert {app._saved_run(r['id']) for r in rows}==set(folders)
        outside=tmp_path/'outside'/'research';research(outside,'Excluded fixture')
        app.store.update(c,lambda v:v['runs'].append(dict(folder=str(outside),status='saved')))
        assert len(app.evaluation()['scoreboard']['runs'])==2
    finally:app.close()
