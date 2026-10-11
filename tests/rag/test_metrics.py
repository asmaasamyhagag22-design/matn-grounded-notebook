import importlib
import math


def api(name):
    try: fn=getattr(importlib.import_module('eval.rag.metrics'),name,None)
    except ModuleNotFoundError:fn=None
    assert callable(fn),f'Missing evaluation behavior: {name}'
    return fn


def test_wilson_and_exact_discordant_pairs():
    interval=api('wilson');exact=api('paired_exact')
    lo,hi=interval(0,10);assert lo==0 and .27<hi<.29
    lo,hi=interval(10,10);assert .71<lo<.73 and math.isclose(hi,1)
    assert exact(0,0)==1 and exact(0,6)==.03125


def test_rank_metrics_exclude_neighbors_and_keep_reading_ceiling():
    measure=api('measure')
    questions=[{'id':'a','reachable':True,'relevant_chunk_ids':['target']},{'id':'b','reachable':False,'relevant_chunk_ids':[]}]
    raw={'a':{'hits':[{'chunk_id':'other'},{'chunk_id':'target'}],'context':[{'chunk_id':'target'}]},'b':{'hits':[],'context':[]}}
    r=measure(questions,raw)
    assert r['hit']['1']['successes']==0 and r['hit']['5']['successes']==1
    assert r['hit']['5']['n']==1 and r['end_to_end_hit']['5']==.5
    assert r['mrr10']==.5 and r['reachable']==1 and r['total']==2
