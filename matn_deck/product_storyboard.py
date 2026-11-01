"""Content-led refinement for the three original Matn templates only."""
from dataclasses import replace
import math
import re
from .storyboard_v2 import Text,SlideSpec,LABELS,_Citations,_bullet,_unit_notes,axis_title


def display_topic(topic):
    return re.sub(r"[A-Za-z][A-Za-z'-]*",lambda m:m[0] if m[0].isupper() else m[0][:1].upper()+m[0][1:],topic)


def balanced_groups(items,maximum=4):
    count=max(1,math.ceil(len(items)/maximum));small,extra=divmod(len(items),count)
    groups=[];start=0
    for i in range(count):
        size=small+(i<extra);groups.append(items[start:start+size]);start+=size
    return groups


def gap_rows(catalog):
    coverage=catalog.origin.get('axis_coverage',{})
    queries=catalog.origin.get('searches_by_axis',{})
    rows={}
    for axis in catalog.plan.axes:
        units=[u for u in catalog.units if u.axis==axis.id]
        status=coverage.get(axis.id)
        if status=='full' and units:continue
        if units and status not in ('part','none') and not any(g.axis==axis.id for g in catalog.gaps):continue
        reason=('No independently verified statement was displayed.' if not units else
                'Verified evidence covers only part of this axis; the full answer remains unestablished.')
        rows[axis.id]=dict(title=axis_title(axis.title),reason=reason,queries=queries.get(axis.id,[]))
    return rows


def composition(catalog,units):
    if len(units)==1:return 'quote'
    years=[re.findall(r'\b(?:18|19|20)\d{2}\b',u.text) for u in units]
    if len(units)<=4 and all(len(set(y))==1 for y in years) and len({y[0] for y in years})>=2:return 'timeline'
    if len(units)==2 and len({u.source for u in units})==2:return 'comparison'
    return 'grouped'


def refine(catalog,slides,controls,detail,decisions):
    cite=_Citations();result=[];done=set()
    for slide in slides:
        if slide.kind=='title':
            result.append(replace(slide,title=Text(display_topic(catalog.plan.topic),'plan_case','topic')))
        elif slide.kind=='agenda':result.append(replace(slide,composition='visual_agenda'))
        elif slide.kind=='figure':
            axis=next(a for a in catalog.plan.axes if a.id==slide.axis)
            result.append(replace(slide,title=Text(axis_title(axis.title),'axis',axis.id)))
        elif slide.kind=='gaps':
            lines=[];notes=[]
            for axis,row in gap_rows(catalog).items():
                lines.extend((Text(row['title'],'axis',axis),Text(row['reason'],'gap_reason',axis)))
                if row['queries']:lines.append(Text('Searched: '+row['queries'][0],'search_query',axis))
                else:lines.append(Text('No search phrase was recorded.','label'))
                notes.extend('Search: '+q for q in row['queries'])
                notes.extend(g.reason for g in catalog.gaps if g.axis==axis and g.reason)
            result.append(replace(slide,lines=tuple(lines) or (Text(LABELS['no_gaps'],'label'),),notes=tuple(notes)))
        elif slide.kind=='assertion':
            if slide.axis in done:continue
            done.add(slide.axis)
            units=[u for u in catalog.units if u.axis==slide.axis]
            title=Text(axis_title(next(a.title for a in catalog.plan.axes if a.id==slide.axis)),'axis',slide.axis)
            groups=balanced_groups(units)
            if len(groups)>1:
                result.append(SlideSpec('section',title,slide.axis,lines=(Text(LABELS['section'],'label'),),composition='section'))
            for i,group in enumerate(groups):
                comp=composition(catalog,group)
                if comp=='timeline':group=sorted(group,key=lambda u:re.findall(r'\b(?:18|19|20)\d{2}\b',u.text)[0])
                bullets=tuple(_bullet(catalog,u,cite) for u in group)
                titles=()
                if comp=='comparison':titles=tuple(Text(catalog.source(u.source).publisher,'source_meta',u.source) for u in group)
                elif comp=='timeline':titles=tuple(Text(re.findall(r'\b(?:18|19|20)\d{2}\b',u.text)[0],'unit_date',u.id) for u in group)
                notes=tuple(line for u in group for line in _unit_notes(catalog,u,cite(u.source)))
                result.append(SlideSpec('assertion',title,slide.axis,bullets,item_titles=titles,notes=notes,
                    part=(i+1,len(groups)) if len(groups)>1 else None,composition=comp))
            decisions.append('GROUPED:'+str(slide.axis)+':'+','.join(str(len(g)) for g in groups)+'; renderer splits only after measured overflow')
            # A hero number is a copied quantity, never an ordinal or a chart.
            numeric=next((n for n in catalog.numbers if n.unit_id in {u.id for u in units} and n.unit
                          and not re.fullmatch(r'(?:18|19|20)\d{2}',n.value_as_written.strip())
                          and n.origin=='unit'),None)
            if numeric and detail!='summary':
                unit=catalog.unit(numeric.unit_id)
                result.append(SlideSpec('assertion',title,slide.axis,(_bullet(catalog,unit,cite),),
                    lines=(Text(numeric.value_as_written,'number_value',numeric.id),),facts=(numeric.id,),
                    notes=tuple(_unit_notes(catalog,unit,cite(unit.source))),composition='key_number'))
        else:result.append(slide)
    if len(catalog.units)>=4:
        takeaways=[]
        for axis in catalog.plan.axes:
            unit=next((u for u in catalog.units if u.axis==axis.id),None)
            if unit:takeaways.append(unit)
            if len(takeaways)==2:break
        if takeaways:
            result.append(SlideSpec('closing',Text(LABELS['closing'],'label'),bullets=tuple(_bullet(catalog,u,cite) for u in takeaways),
                notes=tuple(line for u in takeaways for line in _unit_notes(catalog,u,cite(u.source))),composition='closing'))
    else:
        # Small briefs end with navigation rather than duplicating their few
        # claims into another slide (which would retain a removed citation).
        result.append(SlideSpec('closing',Text(LABELS['closing'],'label'),
            lines=(Text(LABELS['section'],'label'),),composition='closing'))
    from matn_research.quality import commercial_warning
    warning=commercial_warning(catalog.sources,catalog.units)['warning']
    if warning:
        index=next((i for i,s in enumerate(result) if s.kind in ('gaps','sources','methods')),len(result))
        result.insert(index,SlideSpec('warning',Text(LABELS['source_balance'],'label'),lines=(Text(warning,'label'),),composition='warning'))
    decisions.append('PRODUCT_EVIDENCE_DESIGN:v1')
    return result
