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


def test_survey_coverage_counts_displayed_base_not_deep_eval_hits():
    from eval.rag.run import survey_summary
    sources=[{'source_id':str(i),'citable_count':20,'hits':10} for i in range(4)]
    hits=[{'source_id':'0','matched_lexical_terms':['topic']} for _ in range(12)]
    hits += [{'source_id':str(i),'matched_lexical_terms':[]} for i in range(1,4) for _ in range(10)]
    report=survey_summary({'summary':sources,'hits':hits})
    assert report['base_depth']==12 and report['hits']==12 and report['unmatched_slots']==0
    assert [r['hits'] for r in report['sources']]==[12,0,0,0]
    assert [r['coverage_shortfall'] for r in report['sources']]==[0,2,2,2]
