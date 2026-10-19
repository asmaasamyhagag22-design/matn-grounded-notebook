"""Descriptive C1b operations metrics; no support labels or accuracy inference."""
from eval.chat.realistic import summarize
from eval.verification.pilot import quantiles


def summarize_run(rows,memory):
    result=summarize(rows);pairs=[];latencies={}
    for row in rows:
        attempts=row.get('trace',[])
        for a in attempts:
            for key,value in a.get('timings',{}).items():latencies.setdefault(key,[]).append(value)
        if len(attempts)>1:
            first=attempts[0].get('timings',{}).get('prompt_eval_seconds')
            redraft=attempts[1].get('timings',{}).get('prompt_eval_seconds')
            if first is not None and redraft is not None:
                pairs.append({'id':row.get('id'),'first_prompt_eval_seconds':first,'redraft_prompt_eval_seconds':redraft,
                    'redraft_to_first_ratio':redraft/first if first else None,
                    'prefix_identical':attempts[1].get('payload',{}).get('prompt','').startswith(attempts[0].get('payload',{}).get('prompt',''))})
    result['attempt_latency_seconds']={k:quantiles(v) for k,v in latencies.items()}
    result['prefix_cache']={'pairs':pairs,'ratios':quantiles([r['redraft_to_first_ratio'] for r in pairs if r['redraft_to_first_ratio'] is not None]),
        'scope':'observed prompt-eval comparison, different suffix and potentially different token counts; no causal speed claim'}
    result['memory']={'samples':len(memory),'sample_interval_seconds':1,
        'min_available_bytes':min((m['available_bytes'] for m in memory),default=None),
        'peak_ollama_runner_rss_bytes':max((m['ollama_runner_rss_bytes'] for m in memory),default=0),
        'peak_l4_worker_rss_bytes':max((m['l4_worker_rss_bytes'] for m in memory),default=0),
        'peak_combined_runner_l4_rss_bytes':max((m['ollama_runner_rss_bytes']+m['l4_worker_rss_bytes'] for m in memory),default=0),
        'scope':'sampled process RSS, excludes collector, tokenizer and other processes; MemAvailable is whole system'}
    return result
