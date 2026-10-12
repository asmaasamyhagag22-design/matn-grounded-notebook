"""Frozen general M1 diagnostic rule, committed before annotation agreement.

This module is not imported by production. No document, page or block identifiers,
annotation labels, or absolute layout positions enter the decision. Native objects
must be supplied by a caller; missing evidence is UNKNOWN, never a chart inference.
"""
from collections import Counter
from statistics import median

PARAMETERS = {
    'alignment_em':0.1,
    'min_bar_count':3,
    'bar_min_aspect':3.0,
    'bar_min_thickness_em':0.2,
    'bar_max_thickness_em':2.0,
    'bar_thickness_relative_tolerance':0.2,
    'min_length_range_em':1.0,
    'min_parallel_row_separation_em':0.2,
    'grid_min_rows':3,
    'grid_min_columns':3,
    'grid_min_intersections':9,
    'grid_min_span_share':0.5,
    'cell_min_columns':2,
    'cell_min_common_rows':3,
    'curve_min_objects':12,
    'curve_min_extent_em':2.0,
    'min_numeric_labels':4,
    'max_numeric_label_characters':12,
    'legend_min_swatches':2,
    'legend_max_extent_em':2.0,
    'legend_min_aspect':0.5,
    'legend_max_aspect':2.0,
}


def inside(box,region):
    x=(box[0]+box[2])/2;y=(box[1]+box[3])/2
    return region[0]<=x<=region[2] and region[1]<=y<=region[3]


def clusters(values,tolerance):
    groups=[]
    for v in sorted(values):
        if groups and abs(v-median(groups[-1]))<=tolerance:groups[-1].append(v)
        else:groups.append([v])
    return [median(x) for x in groups]


def decide(page,box,fallback_font_size):
    if page is None:return {'chart':False,'status':'NO_NATIVE_OBJECTS','evidence':{}}
    p=PARAMETERS
    chars=[c for c in page['chars'] if inside(c['bbox'],box) and c['text'].strip() and c['size']>0]
    em=median(c['size'] for c in chars) if chars else fallback_font_size
    if not em or em<=0:return {'chart':False,'status':'NO_FONT_SCALE','evidence':{}}
    tol=p['alignment_em']*em
    rects=[r['bbox'] for r in page['rects'] if r.get('fill') and inside(r['bbox'],box)]
    lines=[r['bbox'] for r in page['lines'] if inside(r['bbox'],box)]
    width=box[2]-box[0];height=box[3]-box[1]
    hs=[b for b in lines if abs(b[3]-b[1])<=tol and b[2]-b[0]>=p['grid_min_span_share']*width]
    vs=[b for b in lines if abs(b[2]-b[0])<=tol and b[3]-b[1]>=p['grid_min_span_share']*height]
    intersections=sum(h[0]-tol<=v[0]<=h[2]+tol and v[1]-tol<=h[1]<=v[3]+tol for h in hs for v in vs)
    grid=(len(clusters([h[1] for h in hs],tol))>=p['grid_min_rows'] and
          len(clusters([v[0] for v in vs],tol))>=p['grid_min_columns'] and
          intersections>=p['grid_min_intersections'])
    # Repeated full-width cell rectangles in multiple columns, aligned on the same rows.
    cell_groups=[]
    for r in rects:
        found=next((g for g in cell_groups if abs(g[0][0]-r[0])<=tol and abs(g[0][2]-r[2])<=tol),None)
        if found is None:cell_groups.append([r])
        else:found.append(r)
    cell_columns=[g for g in cell_groups if len(clusters([r[1] for r in g],tol))>=p['cell_min_common_rows']]
    cell_grid=False
    for i,a in enumerate(cell_columns):
        for b in cell_columns[i+1:]:
            if a[0][2]>b[0][0]+tol and b[0][2]>a[0][0]+tol:continue
            common=sum(any(abs(r[1]-s[1])<=tol for s in b) for r in a)
            if common>=p['cell_min_common_rows']:cell_grid=True
    bar_groups=[]
    for orientation in (0,1):
        bars=[]
        for r in rects:
            length=r[2+orientation]-r[orientation];thick=r[3-orientation]-r[1-orientation]
            if thick>0 and length/thick>=p['bar_min_aspect'] and p['bar_min_thickness_em']*em<=thick<=p['bar_max_thickness_em']*em:
                bars.append({'bbox':r,'start':r[orientation],'row':r[1-orientation],'length':length,'thickness':thick})
        for seed in bars:
            group=[b for b in bars if abs(b['start']-seed['start'])<=tol and abs(b['thickness']-seed['thickness'])<=p['bar_thickness_relative_tolerance']*seed['thickness']]
            rows=clusters([b['row'] for b in group],p['min_parallel_row_separation_em']*em)
            if len(rows)>=p['min_bar_count'] and max(b['length'] for b in group)-min(b['length'] for b in group)>=p['min_length_range_em']*em:
                bar_groups.append([b['bbox'] for b in group]);break
    curves=[r for r in page['curves'] if inside(r['bbox'],box) and any(op[0]=='c' for op in r.get('path',[])) and max(r['bbox'][2]-r['bbox'][0],r['bbox'][3]-r['bbox'][1])>=p['curve_min_extent_em']*em]
    # Native digit runs, joined only for this geometric numeric-axis control; no OCR.
    digit_lines=Counter(round(c['bbox'][1]/max(tol,1e-9)) for c in chars if c['text'].isdigit())
    numeric_labels=sum(1 for count in digit_lines.values() if count<=p['max_numeric_label_characters'])
    swatches=[r for r in rects if r[3]>r[1] and p['legend_min_aspect']<=(r[2]-r[0])/(r[3]-r[1])<=p['legend_max_aspect'] and max(r[2]-r[0],r[3]-r[1])<=p['legend_max_extent_em']*em]
    curve_chart=len(curves)>=p['curve_min_objects'] and bool(hs and vs) and intersections>0 and numeric_labels>=p['min_numeric_labels'] and len(swatches)>=p['legend_min_swatches']
    veto=grid or cell_grid
    return {'chart':not veto and bool(bar_groups or curve_chart),'status':'OBJECT_RULE','evidence':{'font_scale_pt':em,'bar_groups':bar_groups,'ruled_grid':grid,'aligned_cell_grid':cell_grid,'grid_intersections':intersections,'curve_objects':len(curves),'numeric_label_rows':numeric_labels,'legend_swatches':len(swatches),'curve_chart':curve_chart,'raster_images_unclassified':len(page.get('images',[]))}}
