"""Owner-fixed reference mapping; consumes JSON only, never imports Docling."""


def convert_box(box,docling_size,pdf_size):
    dw,dh=docling_size;pw,ph=pdf_size
    if min(dw,dh,pw,ph)<=0:raise ValueError('INVALID_PAGE_DIMENSIONS')
    l,t,r,b=(box[k] for k in ('l','t','r','b'))
    if box['coord_origin']=='BOTTOMLEFT':t,b=dh-t,dh-b
    elif box['coord_origin']!='TOPLEFT':raise ValueError('UNKNOWN_COORDINATE_ORIGIN')
    if r<l or b<t:raise ValueError('INVERTED_REGION_BBOX')
    return [l*pw/dw,t*ph/dh,r*pw/dw,b*ph/dh]


def union_share(box,regions):
    x0,y0,x1,y1=box;area=max(0,x1-x0)*max(0,y1-y0)
    if not area:raise ValueError('ZERO_BLOCK_AREA')
    clipped=[]
    for a,b,c,d in regions:
        rect=(max(x0,a),max(y0,b),min(x1,c),min(y1,d))
        if rect[2]>rect[0] and rect[3]>rect[1]:clipped.append(rect)
    edges=sorted({v for r in clipped for v in (r[0],r[2])});total=0
    for a,b in zip(edges,edges[1:]):
        spans=sorted((r[1],r[3]) for r in clipped if r[0]<=a and r[2]>=b)
        length=0;start=end=None
        for c,d in spans:
            if start is None:start,end=c,d
            elif c<=end:end=max(end,d)
            else:length+=end-start;start,end=c,d
        if start is not None:length+=end-start
        total+=(b-a)*length
    return total/area


def retype(picture_share,table_share):return picture_share>=0.5 and table_share<0.5
