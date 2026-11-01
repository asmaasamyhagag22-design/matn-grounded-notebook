"""Static, evidence-linked dashboard. No third-party scripts or requests."""
from html import escape
import json
from pathlib import Path

from .data import relative_link


STYLE = '''
:root{font-family:system-ui,sans-serif;color:#203346;background:#f4f6f9}*{box-sizing:border-box}body{margin:0}
header{padding:32px 4vw 26px;background:#152d3c;color:#fff}header p{color:#c1d5df;max-width:970px;line-height:1.6}
h1{margin:0;font-size:30px;font-weight:650}h2{font-size:22px;margin:0 0 16px}h3{font-size:17px;margin:16px 0 8px}
main{padding:24px 4vw;display:grid;grid-template-columns:minmax(0,1fr);gap:24px}section{min-width:0;padding:24px;background:white;border:1px solid #dde5ec;border-radius:12px}
a{color:#006f77;text-underline-offset:3px}header a{color:#a2f0e1}.muted,small{color:#647580}.muted{line-height:1.5}
.scroll{max-width:100%;overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #e4ebf0;padding:12px 10px;text-align:left;vertical-align:top}
th{color:#506576;white-space:nowrap;font-size:12px;background:#f4f7fa}td.topic{min-width:220px;max-width:320px}td.code{max-width:140px;overflow-wrap:anywhere}
.tag{display:inline-block;padding:3px 8px;border-radius:20px;background:#e5f3f0;font-size:11px;white-space:nowrap}.bad{background:#fff0e9;color:#9a461d}.unknown{background:#f1f2f5;color:#647580}
details{border:1px solid #e3e8ed;border-radius:8px;margin:12px 0;padding:12px 16px}summary{cursor:pointer;font-weight:600}
.axis{padding:12px 0;border-bottom:1px solid #edf0f3}.axis:last-child{border:0}.axis p{line-height:1.5;margin:7px 0}.quote{border-left:3px solid #90bdb6;padding-left:12px;color:#475f6e}
label{display:block;font-size:13px;font-weight:600;margin:12px 0 5px}input,select,button{font:inherit;padding:10px;border-radius:6px;border:1px solid #b9c8d1}
input,select{width:100%;min-width:0;background:white}button{cursor:pointer;background:#156e6d;color:white;border-color:#156e6d;margin:16px 12px 8px 0}button.secondary{background:white;color:#156e6d}button:disabled{opacity:.45;cursor:default}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.metrics{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:18px}.metric{background:#f4f7fa;padding:12px 18px;border-radius:8px}.metric strong{font-size:22px;display:block}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;border-radius:6px;padding:14px;font-size:12px;line-height:1.5}iframe{width:100%;height:360px;border:1px solid #dce5e9;border-radius:8px;margin-top:12px}.hidden{display:none}
@media(max-width:800px){header,main{padding:20px}section{padding:16px}.form-grid{grid-template-columns:1fr}}
'''


def shown(value):
    return '—' if value is None else escape(str(value))


def seconds(value):
    return '—' if value is None else f'{value / 60:.1f} min'


def link(path, label, output):
    if not path:
        return ''
    return '<a href="' + escape(relative_link(path, output), quote=True) + '">' + escape(label) + '</a>'


def vendor_text(value, kind):
    total = value[kind + '_total']; count = value[kind + '_vendor']
    return f'{count}/{total} ({100 * count / total:.0f}%)' if total else '—'


def render(data, output, ledgers=(), token=''):
    output = Path(output)
    known = [r for r in data['runs'] if r['id'] in {'devH','H','A','E','Oct27',*'JKLMNOPQ'}]
    nq = [r for r in known if r['id'] in set('NOPQ')]
    first = [r['first_verified_seconds'] for r in nq if r['first_verified_seconds'] is not None]
    cov = [r['display_coverage']['covered'] for r in nq]
    cards = [('Saved runs',len(data['runs'])), ('N–Q first unit',seconds(sum(first)/len(first)) if first else '—'),
             ('N–Q axes with verified units',f'{sum(cov)/len(cov):.2f}' if cov else '—'),('Build calls','0')]
    metrics = ''.join('<div class="metric"><small>'+escape(k)+'</small><strong>'+escape(str(v))+'</strong></div>' for k,v in cards)
    rows = []
    details = []
    for r in data['runs']:
        folder=Path(r['folder']); c=r['coverage']; dc=r['display_coverage']; errors=r['silent_errors']
        badge = ('bad' if errors or not r['page_exists'] or r.get('failure_page') else 'unknown' if errors is None else '')
        quality = 'unreviewed' if errors is None else str(errors)+' errors'
        if not r['page_exists']:
            quality = 'FAILED · no page'
        elif r.get('failure_page'):
            quality = 'FAILED · diagnostic page'
        reviews = link(r['review_path'],'review',output)
        result = link(folder / 'index.html','result',output) if r['page_exists'] else 'no result page'
        rows.append('<tr><td><strong>'+escape(r['id'])+'</strong><br>'+result+'</td><td class="topic">'+escape(r['topic'])+
            '<br><small>'+escape(r['audience'])+'</small></td><td class="code">'+escape(r['code'])+'<br><small>'+escape((r['code_identity'] or 'identity unavailable')[:16])+'</small></td>'+
            '<td title="'+escape(r['first_verified_basis'],quote=True)+'">'+seconds(r['first_verified_seconds'])+'</td><td title="'+escape(r['timing_scope'],quote=True)+'">'+seconds(r['total_seconds'])+'</td>'+
            '<td>'+shown(r['calls']['generation'])+' / '+shown(r['calls']['native'])+' / '+shown(r['searches'])+'</td><td>'+str(r['sources_read'])+' / '+str(r['sources_failed'])+'</td>'+
            '<td title="'+escape(r['vendor']['rule'],quote=True)+'">'+vendor_text(r['vendor'],'sources')+'<br><small>shown '+vendor_text(r['vendor'],'shown')+'</small>'+
            '<br><small>other sources '+str(r['vendor']['sources_other'])+' · shown '+str(r['vendor']['shown_other'])+' · unlabelled '+str(r['vendor']['shown_unknown'])+'</small>'+
            ('<br><small>recorded delivery shown '+vendor_text(r['vendor']['recorded_delivery'],'shown')+'</small>' if r['vendor'].get('recorded_delivery') else '')+'</td><td>'+shown(dc['planned'])+' / '+shown(dc['covered'])+' / '+shown(dc['empty'])+
            '<br><small>semantic covered '+shown(c['covered'])+' · empty '+shown(c['empty'])+' · unknown '+str(c['unknown'])+'</small>'+
            '<br><small>requirements met '+str(c['met'])+' · partial '+str(c['partial'])+'</small></td><td>'+str(r['units_shown'])+'</td><td><span class="tag '+badge+'">'+quality+'</span><br>'+escape(r['review_kind'])+
            '<br><small>'+str(r['borderline'])+' borderline ('+str(r['borderline_accepted'])+' owner accepted)</small><br>'+reviews+'</td></tr>')
        axis_html=[]
        for axis in r['axes']:
            if axis['status'] not in ('missing','unknown'):
                continue
            d=axis.get('diagnosis',{})
            evidence=[]
            for e in d.get('evidence',[]):
                path=e.get('path') if isinstance(e,dict) else e
                evidence.append(link(path, e.get('label',Path(path).name) if isinstance(e,dict) else Path(path).name,output))
            candidate=d.get('candidate') or {}
            present=d.get('suitable_present',d.get('suitable_passage_present'))
            presence='unknown' if present is None else 'yes (AI semantic audit)' if present else 'no suitable passage established in the read scope'
            axis_html.append('<div class="axis"><strong>'+escape(axis['label'])+' · '+escape(axis['id'])+'</strong><p>'+escape(axis.get('requirement',''))+'</p><p><span class="tag unknown">'+escape(d.get('stage',d.get('loss_stage','unknown')))+'</span> · suitable passage: '+presence+'</p><p>'+escape(d.get('reason','No stage audit saved.'))+'</p>'+
                ('<p class="quote">'+escape(candidate['quote'])+'</p>' if candidate.get('quote') else '')+'<small>'+' · '.join(evidence)+'</small></div>')
        if axis_html:
            details.append('<details><summary>'+escape(r['id'])+' · '+str(len(axis_html))+' empty or unreviewed requirements</summary>'+''.join(axis_html)+'</details>')
    bench_rows=[]
    for b in data['benches']:
        parts=[]
        for name,s in b['summary'].items():
            parts.append('<tr><td>'+escape(name)+'</td><td>'+str(s['hit'])+'/'+str(s['of'])+'</td><td>'+str(s['displayed_hit'])+'/'+str(s['displayed_of'])+'</td><td>'+str(s['vendor_slots'])+'/'+str(s['slots'])+'</td></tr>')
        bench_rows.append('<details><summary>'+escape(str(Path(b['path']).relative_to(output.parent.parent)))+'</summary>'+link(b['path'],'JSON evidence',output)+'<table><thead><tr><th>Variant</th><th>Reviewed hit</th><th>Displayed hit</th><th>Vendor slots</th></tr></thead><tbody>'+''.join(parts)+'</tbody></table>'+('<pre>'+escape(json.dumps(b['errors'],indent=2))+'</pre>' if b['errors'] else '')+'</details>')
    ledger_options=''.join('<option value="'+escape(str(p),quote=True)+'">'+escape(Path(p).name)+' · '+escape(str(p))+'</option>' for p in ledgers)
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Matn · Research evidence</title><style>'+STYLE+'</style><body><header><h1>مَتن · Research evidence</h1><p>Saved runs, reviewed quality and the exact stage where evidence was lost. The scoreboard makes zero model or search calls. AI reviews remain AI reviews; owner acceptance of borderline units is shown separately.</p></header><main><section><div class="metrics">'+metrics+'</div><h2>Scoreboard</h2><p class="muted">Primary axis counts mean a displayed verified unit; these match the pre-registration baseline. Semantic coverage is shown separately from saved reviews, with “met”, “partial” and unknown counts. Unknown measurements stay blank. Historical delivery ancestors keep their original errors and timing; corrected gallery replays are separate artifacts.</p><p>'+link(output.parent/'leap-20261030/gallery-v4.json','devH fallback',output)+' · '+link(output.parent/'topic-research-senior-20261029/gallery.json','H → A → E → Oct27 fallback',output)+'</p><div class="scroll"><table><thead><tr><th>Run</th><th>Topic / audience</th><th>Code identity</th><th>First verified</th><th>Total</th><th>Gen / native / search</th><th>Read / failed</th><th>Vendor share · reads / shown</th><th>Axes · planned / with units / empty</th><th>Units shown</th><th>Review / errors / borderline</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></section><section><h2>Why is this axis empty?</h2><p class="muted">Stage labels use saved candidate/shortlist/screen/selection checkpoints and explicit AI semantic audits. A source URL alone does not establish a suitable passage.</p>'+(''.join(details) or '<p>No audited empty axes found.</p>')+'</section><section><h2>Offline bench</h2><p class="muted">Recall of evidence the older pipeline already reviewed or displayed. This does not measure unseen evidence or fresh-topic generalization.</p>'+(''.join(bench_rows) or '<p>No saved bench results found.</p>')+'</section><section id="console"><h2>Run console</h2><p id="console-note" class="muted">Serve this page with the dashboard command to use the local console. No run starts from loading this page.</p><form id="run-form"><div class="form-grid"><div><label for="topic">Topic</label><input id="topic" name="topic" required maxlength="500"></div><div><label for="audience">Audience</label><input id="audience" name="audience" required maxlength="500"></div><div><label for="code">Code</label><select id="code" name="code"><option value="delivery">Delivery · original live.sh</option><option value="v2">research-v2 · worktree live.sh</option></select></div><div><label for="ledger">Explicit ledger</label><select id="ledger" name="ledger" required><option value="">Choose a ledger…</option>'+ledger_options+'</select></div></div><button type="button" id="preflight">Check preflight & budget</button><button id="start" type="submit" disabled>Start live run</button></form><pre id="preflight-result">No preflight checked.</pre><div id="run-status"></div><iframe id="progress" class="hidden" title="Existing research progress"></iframe><div id="quality"></div></section></main><script>const CSRF='+json.dumps(token)+';</script><script>'+SCRIPT+'</script></body></html>'


SCRIPT = r'''
const $=s=>document.querySelector(s);let checked=null;
function values(){return Object.fromEntries(new FormData($('#run-form')))}
function text(el,value){el.textContent=typeof value==='string'?value:JSON.stringify(value,null,2)}
async function api(path,value){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Matn-Token':CSRF},body:JSON.stringify(value)});let d=await r.json();if(!r.ok)throw new Error(d.error||r.status);return d}
if(location.protocol==='http:'){$('#console-note').textContent='Local preflight checks ledger, deadlines and installed runtime. Provider quota is checked by live.sh before search. Starting reserves the full 12-search allowance; loading and checking this dashboard spend nothing.'}
$('#run-form').addEventListener('input',()=>{checked=null;$('#start').disabled=true});
$('#preflight').onclick=async()=>{try{checked=await api('/api/preflight',values());text($('#preflight-result'),checked);$('#start').disabled=checked.verdict!=='GO'}catch(e){text($('#preflight-result'),e.message)}};
$('#run-form').onsubmit=async e=>{e.preventDefault();$('#start').disabled=true;try{let r=await api('/api/run',values());text($('#run-status'),'Run '+r.id+' started');poll(r.id)}catch(e){text($('#run-status'),e.message)}};
async function poll(id){try{let r=await fetch('/api/run/'+encodeURIComponent(id)).then(x=>x.json());text($('#run-status'),r);if(r.progress_url){$('#progress').classList.remove('hidden');if(!$('#progress').src.endsWith(r.progress_url))$('#progress').src=r.progress_url}if(r.done){let box=$('#quality');box.textContent='Quality panel · '+JSON.stringify(r.quality,null,2);if(r.result_url){let a=document.createElement('a');a.href=r.result_url;a.textContent='Open result';box.append(document.createElement('br'),a)}let a=document.createElement('a');a.href='/dashboard/index.html';a.textContent='Refresh scoreboard';box.append(document.createElement('br'),a)}else setTimeout(()=>poll(id),2000)}catch(e){text($('#run-status'),e.message)}}
'''
