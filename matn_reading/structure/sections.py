"""Ordered leaf ownership: bookmarks, layout headings, fixed page windows."""
import re
from matn_contracts.structure import Section,StructureIssue
from matn_contracts.structure_ids import structure_id
from .versions import VERSION,PAGE_WINDOW

_NUMBER=re.compile(r'^\s*(\d+(?:\.\d+)*)(?:[.)]?\s+)(?=[A-Za-z])')
_CHAPTER=re.compile(r'^\s*Chapter\s+\w+',re.I)

def title_key(text): return ' '.join(text.split()).casefold()

def build_sections(snapshot,elements):
    citable=[e for e in elements if e.citable];issues=[];anchors={}
    sizes=sorted({e.block.style.font_size_pt for e in citable if e.role=='heading' and e.block.style.font_size_pt},reverse=True)
    for i,e in enumerate(citable):
        text=e.block.text.strip();num=_NUMBER.match(text)
        supplemental=(num or _CHAPTER.match(text)) and len(text)<=150
        if e.role=='heading' or supplemental:
            depth=len(num.group(1).split('.')) if num else (sizes.index(e.block.style.font_size_pt)+1 if e.block.style.font_size_pt in sizes else 1)
            anchors[i]=[depth,'layout_heading',text]
        elif num and len(text)>150:
            issues.append(StructureIssue(reason='fused_heading',pdf_page_index=e.block.page_index,block_id=e.block.block_id))
    last=-1
    for mark in snapshot.get('outline',[]):
        matches=[i for i in anchors if citable[i].block.page_index==mark['page_index'] and title_key(citable[i].block.text)==title_key(mark['title'])]
        if len(matches)!=1 or matches[0]<=last:
            issues.append(StructureIssue(reason='outline_heading_mismatch',pdf_page_index=mark.get('page_index'),detail=mark['title']))
        else:
            i=matches[0];anchors[i]=[mark['level']+1,'outline',mark['title']];last=i
    if not citable: return (),tuple(issues)
    doc=snapshot['doc_id'];nodes=[]
    def node(title,depth,source,path,parent,indices,anchor=None):
        blocks=tuple(citable[i].block.block_id for i in indices)
        pages=[citable[i].block.page_index for i in indices] or [0]
        sid=structure_id(doc,'s',VERSION,[source,list(path),anchor,list(blocks)])
        n={'section_id':sid,'doc_id':doc,'title':title,'parent_id':parent,'child_ids':(), 'level':depth,'path':path,'source':source,'heading_block_id':anchor,'block_ids':blocks,'page_range':(min(pages),max(pages))}
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
        if starts[0]>0: node('Introduction',1,'layout_heading',('Introduction',),None,range(starts[0]))
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
                intro=node('Introduction',n['level']+1,n['source'],n['path']+('Introduction',),n['section_id'],indices)
                n['child_ids']=(intro['section_id'],)+n['child_ids']
        by_id={n['section_id']:n for n in nodes}
        def extent(n):
            if n['child_ids']:
                spans=[extent(by_id[s]) for s in n['child_ids']];n['page_range']=(min(s[0] for s in spans),max(s[1] for s in spans))
            return n['page_range']
        for n in nodes: extent(n)
    return tuple(Section(**n) for n in nodes),tuple(issues)
