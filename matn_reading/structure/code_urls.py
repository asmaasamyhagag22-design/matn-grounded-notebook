"""URL recognition across mono line breaks, using M3's existing line geometry."""
import re


def url_lines(lines, rule):
    """Return original line indices and joined URL tokens; never edits source text.

    Adjacent fragments on the same baseline are joined only at touching bboxes.
    Consecutive mono logical lines use the unchanged M3 leading/overlap limits.
    At a wrap, concatenate without a synthetic space; accept URL tokens only.
    """
    mono = re.compile(rule['font_regex']); url = re.compile(rule['url_regex'])
    candidates = []
    for i,line in enumerate(lines):
        if not all(mono.search(w['font_face']) for w in line['words']):continue
        candidates.append({'refs':[i], 'text':' '.join(w['text'] for w in line['words']),
                           'bbox':list(line['bbox']), 'y':line['y'],'size':line['size']})
    candidates.sort(key=lambda l:(l['y'],l['bbox'][0],l['refs']))
    # Layout may split a URL punctuation/domain fragment into another Block on the same baseline.
    logical=[]
    for line in candidates:
        previous=next((l for l in reversed(logical) if
                       abs(l['y']-line['y']) < rule['consecutive_y_min_em']*max(l['size'],line['size']) and
                       l['bbox'][2]==line['bbox'][0]),None)
        if previous is not None:
            previous['text']+=line['text'];previous['refs']+=line['refs'];previous['bbox'][2]=line['bbox'][2]
        else:logical.append(line)
    logical.sort(key=lambda l:(l['y'],l['bbox'][0],l['refs']))
    selected=set();tokens=[]
    for i,line in enumerate(logical):
        text=line['text']
        if not text.split() or not all(url.fullmatch(t) for t in text.split()):continue
        refs=list(line['refs']);current=line
        for other in logical[i+1:]:
            em=max(current['size'],other['size']);dy=other['y']-current['y']
            if dy < rule['consecutive_y_min_em']*em:continue
            if dy > rule['vertical_step_em_max']*em:break
            if min(current['bbox'][2],other['bbox'][2])<=max(current['bbox'][0],other['bbox'][0]):continue
            joined=text+other['text']
            if not joined.split() or not all(url.fullmatch(t) for t in joined.split()):break
            text=joined;refs+=other['refs'];current=other
        selected.update(refs);tokens.append({'line_indices':sorted(set(refs)),'url_tokens':text.split()})
    return selected,tokens
