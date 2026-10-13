"""M3 v2: only wrapped URL recognition differs from the frozen v1 algorithm."""
from .code_urls import url_lines
from collections import defaultdict
from statistics import median
import re


def decisions(source, rule):
    doc = source['document']
    by = {e.block.block_id: e for e in doc.elements}
    pages = defaultdict(list)
    unknown = []
    mono = re.compile(rule['font_regex'])
    url = re.compile(rule['url_regex'])
    for page in source['snapshot']['pages']:
        for record in page['blocks']:
            bid = record['block']['block_id']
            words = [w for l in record['lines'] for w in l['words']]
            if not words or not all(w.get('font_face') and w.get('size', 0)>0 and len(w.get('bbox', []))==4 for w in words):
                unknown.append(bid); continue
            if not by[bid].citable or by[bid].role in ('table', 'figure', 'caption'):
                continue
            for index, line in enumerate(record['lines']):
                ws = line['words']
                if not ws: continue
                text = ' '.join(w['text'] for w in ws)
                box = [min(w['bbox'][0] for w in ws), min(w['bbox'][1] for w in ws),
                       max(w['bbox'][2] for w in ws), max(w['bbox'][3] for w in ws)]
                fraction = sum(bool(mono.search(w['font_face'])) for w in ws)/len(ws)
                pages[page['page_index']].append({'bid': bid, 'index': index, 'words': ws,
                    'bbox': box, 'size': max(w['size'] for w in ws), 'y': (box[1]+box[3])/2,
                    'mono': fraction>=rule['mono_fraction_min'] and not url.fullmatch(text)})
    code = set(); gutter_words = set(); regions = []; gutters = []
    for page, lines in sorted(pages.items()):
        url_indices, _ = url_lines(lines, rule)
        mono_lines = [l for i,l in enumerate(lines) if l['mono'] and i not in url_indices]
        # Connected components of overlapping monospace lines with consecutive vertical leading.
        links = {i: set() for i in range(len(mono_lines))}
        for i, left in enumerate(mono_lines):
            for j in range(i+1, len(mono_lines)):
                right = mono_lines[j]; em = max(left['size'], right['size'])
                dy = abs(left['y']-right['y'])
                overlap = min(left['bbox'][2], right['bbox'][2]) > max(left['bbox'][0], right['bbox'][0])
                if rule['consecutive_y_min_em']*em <= dy <= rule['vertical_step_em_max']*em and overlap:
                    links[i].add(j); links[j].add(i)
        seen = set()
        for i in links:
            if i in seen: continue
            component = set(); todo = [i]
            while todo:
                j = todo.pop()
                if j in component: continue
                component.add(j); todo.extend(links[j]-component)
            seen.update(component)
            if len(component)>=rule['consecutive_lines_min']:
                members = [mono_lines[j] for j in sorted(component)]
                code.update(l['bid'] for l in members)
                regions.append({'page_index': page, 'line_refs': [[l['bid'],l['index']] for l in members]})
        numbers = []
        for line in lines:
            for wi, w in enumerate(line['words']):
                if re.fullmatch(rule['gutter_integer_regex'], w['text']):
                    numbers.append({'line':line,'wi':wi,'word':w,'value':int(w['text']),
                                    'right':w['bbox'][2],'y':(w['bbox'][1]+w['bbox'][3])/2})
        numbers.sort(key=lambda n:(n['y'], n['right'], n['line']['bid'],n['wi']))
        used = set()
        for ni, first in enumerate(numbers):
            if ni in used: continue
            run=[(ni, first)]; previous=first
            for nj, n in enumerate(numbers[ni+1:], ni+1):
                em=max(n['word']['size'],previous['word']['size'])
                dy=n['y']-previous['y']
                if n['value']==previous['value']+rule['gutter_value_step'] and 0<dy<=rule['gutter_vertical_step_em_max']*em and abs(n['right']-first['right'])<=rule['gutter_right_column_tolerance_em']*em:
                    run.append((nj,n));previous=n
            if len(run)<rule['gutter_sequence_min']:continue
            steps=[r['y']-l['y'] for (_,l),(_,r) in zip(run,run[1:])];step=median(steps)
            if any(abs(v-step)>rule['gutter_step_relative_tolerance']*step for v in steps):continue
            associates=[];pairs=[]
            for _, n in run:
                matches=[l for l in mono_lines if len(l['words'])>=rule['gutter_code_words_min'] and
                         abs(l['y']-n['y'])<=rule['gutter_code_y_tolerance_em']*max(l['size'],n['word']['size']) and
                         0<l['bbox'][0]-n['right']<=rule['gutter_code_x_gap_em_max']*max(l['size'],n['word']['size'])]
                pairs.append(bool(matches));associates.extend(matches)
            if sum(pairs)/len(run)<rule['gutter_adjacent_code_fraction_min']:continue
            used.update(i for i,_ in run)
            code.update(l['bid'] for l in associates)
            for _,n in run:gutter_words.add((n['line']['bid'],n['line']['index'],n['wi']))
            gutters.append({'page_index':page,'values':[n['value'] for _,n in run],
                            'word_refs':[[n['line']['bid'],n['line']['index'],n['wi']] for _,n in run],
                            'associated_code_block_ids':sorted({l['bid'] for l in associates})})
    excluded=set(); mixed=set()
    for page in source['snapshot']['pages']:
        for record in page['blocks']:
            bid=record['block']['block_id'];refs={(bid,li,wi) for li,l in enumerate(record['lines']) for wi,w in enumerate(l['words'])}
            if refs and refs<=gutter_words:excluded.add(bid)
            elif refs & gutter_words:
                mixed.add(bid)
                # Mixed gutter+marker blocks retain the entire text and get the existing code flag.
                code.add(bid)
    code-=excluded
    return {'code_block_ids':sorted(code), 'excluded_gutter_block_ids':sorted(excluded),
            'mixed_gutter_preserved_ids':sorted(mixed), 'unknown_ids':sorted(unknown),
            'regions':regions, 'gutters':gutters}


def apply(snapshot, elements):
    """Keep reader Blocks immutable; expose existing page flags and structure roles."""
    import copy
    import json
    from pathlib import Path
    from types import SimpleNamespace
    rule = json.loads(Path(__file__).with_name('code_rule.json').read_text())
    result = decisions({'snapshot': snapshot, 'document': SimpleNamespace(elements=elements)}, rule)
    code = set(result['code_block_ids']); gutter = set(result['excluded_gutter_block_ids'])
    prepared = copy.deepcopy(snapshot)
    for page in prepared['pages']:
        for record in page['blocks']:
            if record['block']['block_id'] in code:
                flag = {'kind': 'code_text', 'bbox': record['block']['bbox'], 'chars': len(record['block']['text'])}
                if flag not in page['flags']: page['flags'].append(flag)
    transformed = []
    for element in elements:
        bid = element.block.block_id
        if bid in code:
            element = element.model_copy(update={'role': 'text', 'flags': tuple(sorted(set(element.flags) | {'code_text'}))})
        if bid in gutter:
            element = element.model_copy(update={'citable': False, 'exclusion_reasons': ('regular_line_number_gutter',)})
        transformed.append(element)
    return prepared, tuple(transformed)
