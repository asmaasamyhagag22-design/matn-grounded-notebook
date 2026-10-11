"""Ordered leaf ownership: bookmarks, layout headings, fixed page windows."""
import re
from collections import Counter
from matn_contracts.structure import Section,StructureIssue
from matn_contracts.structure_ids import structure_id,section_material,SECTION_IDENTITY_VERSION
from .versions import PAGE_WINDOW

_NUMBER=re.compile(r'^\s*(\d+(?:\.\d+)*)(?:[.)]?\s+)(?=[A-Za-z])')
_CHAPTER=re.compile(r'^\s*Chapter\s+\w+',re.I)

def title_key(text): return ' '.join(text.split()).casefold()

def build_sections(snapshot,elements):
    citable=[e for e in elements if e.citable];issues=[];anchors={}
    raw={r['block']['block_id']:r for p in snapshot['pages'] for r in p['blocks']}
    weighted=Counter()
    for e in citable:
        if e.block.style.font_size_pt and e.role not in ('caption','footnote','table'):
            weighted[e.block.style.font_size_pt]+=len(e.block.text)
    body=weighted.most_common(1)[0][0] if weighted else 10.
    sizes=sorted({e.block.style.font_size_pt for e in citable if e.role=='heading' and e.block.style.font_size_pt},reverse=True)
    def forbidden(text):
        return bool(re.search(r'\.{3,}\s*\d+\s*$',text) or re.search(r'^\s*\d+\s+.*\b(?:Street|St\.|Road|Rd\.|Avenue|Ave\.)\b',text,re.I))
    def line_boxes(e):
        return [(min(w['bbox'][0] for w in line['words']),min(w['bbox'][1] for w in line['words']),max(w['bbox'][2] for w in line['words']),max(w['bbox'][3] for w in line['words'])) for line in raw[e.block.block_id]['lines'] if line['words']]
    def own_lines(i,e):
        # A separate column is a different line: only touching/nearby line boxes compete.
        sz=e.block.style.font_size_pt or body;boxes=line_boxes(e)
        for peer in citable:
            if peer.block.page_index!=e.block.page_index or peer.block.block_id==e.block.block_id:continue
            for a in boxes:
                for b in line_boxes(peer):
                    if abs(a[3]-b[3])<=.2*sz and max(a[0],b[0])-min(a[2],b[2])<=2*sz:return False
        if i:
            previous=citable[i-1]
            if previous.block.page_index==e.block.page_index and not previous.block.text.rstrip().endswith(('.',':','!','?',';')):
                if any(abs(a[3]-b[3])<=.2*sz for a in boxes for b in line_boxes(previous)):return False
        return bool(boxes)
    for i,e in enumerate(citable):
        text=e.block.text.strip();num=_NUMBER.match(text);meaningful=any(ch.isalpha() for ch in text)
        sized=(e.block.style.font_size_pt or 0)>=1.15*body
        eligible=meaningful and not forbidden(text) and (sized or (e.role=='heading' and own_lines(i,e)))
        if eligible and e.role not in ('table','caption','footnote'):
            depth=len(num.group(1).split('.')) if num else (sizes.index(e.block.style.font_size_pt)+1 if e.block.style.font_size_pt in sizes else 1)
            anchors[i]=[depth,'layout_heading',text]
        elif e.role=='heading':
            issues.append(StructureIssue(reason='heading_demoted' if meaningful else 'heading_without_title',pdf_page_index=e.block.page_index,block_id=e.block.block_id,detail='TOC/address/inline or body-size heading policy'))
        elif e.role=='text' and num and len(text)>150:
            issues.append(StructureIssue(reason='fused_heading',pdf_page_index=e.block.page_index,block_id=e.block.block_id))
    last=-1
    for mark in snapshot.get('outline',[]):
        matches=[i for i,e in enumerate(citable) if e.block.page_index==mark['page_index'] and title_key(e.block.text)==title_key(mark['title']) and not forbidden(e.block.text)]
        if len(matches)!=1 or matches[0]<=last:
            issues.append(StructureIssue(reason='outline_heading_mismatch',pdf_page_index=mark.get('page_index'),detail=mark['title']))
        else:
            i=matches[0];anchors[i]=[mark['level']+1,'outline',mark['title']];last=i
    if not citable: return (),tuple(issues)
    doc=snapshot['doc_id'];nodes=[];ids=set()
    def node(title,depth,source,path,parent,indices,anchor=None):
        blocks=tuple(citable[i].block.block_id for i in indices)
        pages=[citable[i].block.page_index for i in indices] or [0]
        page_range=(min(pages),max(pages))
        sid=structure_id(doc,'s',SECTION_IDENTITY_VERSION,section_material(source,path,anchor,parent,page_range))
        if sid in ids: raise ValueError('DUPLICATE_SECTION_ID')
        ids.add(sid)
        n={'producer_version':SECTION_IDENTITY_VERSION,'section_id':sid,'doc_id':doc,'title':title,'parent_id':parent,'child_ids':(), 'level':depth,'path':path,'source':source,'heading_block_id':anchor,'block_ids':blocks,'page_range':page_range}
        nodes.append(n);return n
    if not anchors:
        group=[];window=None
        for i,e in enumerate(citable):
            w=e.block.page_index//PAGE_WINDOW
            if group and w!=window:
                title=f'Pages {window*PAGE_WINDOW+1}–{(window+1)*PAGE_WINDOW}'
                node(title,1,'page_window',(title,),None,group);group=[]
            group.append(i);window=w
        title=f'Pages {window*PAGE_WINDOW+1}–{(window+1)*PAGE_WINDOW}'
        node(title,1,'page_window',(title,),None,group)
    else:
        stack=[];starts=sorted(anchors)
        if starts[0]>0:
            opening=node(snapshot['title'],1,'layout_heading',(snapshot['title'],),None,range(starts[0]))
            opening['issues']=(StructureIssue(reason='synthetic_opening'),)
        for position,start in enumerate(starts):
            end=starts[position+1] if position+1<len(starts) else len(citable)
            depth,source,title=anchors[start]
            while stack and stack[-1]['level']>=depth: stack.pop()
            parent=stack[-1] if stack else None
            if parent and depth>parent['level']+1: issues.append(StructureIssue(reason='heading_level_jump',pdf_page_index=citable[start].block.page_index,block_id=citable[start].block.block_id))
            path=tuple(parent['path'] if parent else ())+(title,)
            current=node(title,depth,source,path,parent['section_id'] if parent else None,range(start,end),citable[start].block.block_id)
            if parent: parent['child_ids']+= (current['section_id'],)
            stack.append(current)
        # Parent introductions own a leaf, not the parent node.
        for n in list(nodes):
            if n['child_ids'] and n['block_ids']:
                original=n['block_ids'];n['block_ids']=()
                indices=[i for i,e in enumerate(citable) if e.block.block_id in original]
                intro=node(n['title'],n['level']+1,n['source'],n['path'],n['section_id'],indices)
                intro['issues']=(StructureIssue(reason='synthetic_opening',block_id=n['heading_block_id']),)
                n['child_ids']=(intro['section_id'],)+n['child_ids']
        by_id={n['section_id']:n for n in nodes}
        def extent(n):
            if n['child_ids']:
                spans=[extent(by_id[s]) for s in n['child_ids']];n['page_range']=(min(s[0] for s in spans),max(s[1] for s in spans))
            return n['page_range']
        for n in nodes: extent(n)
    return tuple(Section(**n) for n in nodes),tuple(issues)
