"""Precommitted geometry-guarded tracked-word join; eval-only, no reader edits."""
import re
from eval.rag.r_lite_3_part2c_m4_data import block_data
from matn_reading.structure.elements import word_ledger


def decisions(source,objects,key,rule):
    texts={};remaps={};details=[];unknown=[]
    for page in source['snapshot']['pages']:
        for record in page['blocks']:
            bid=record['block']['block_id'];data,reason=block_data(page,record,objects,key)
            if reason:unknown.append({'block_id':bid,'reason':reason});continue
            old,ledger,words=word_ledger(record,digital=True)
            if old!=record['block']['text']:unknown.append({'block_id':bid,'reason':'CACHED_WORD_LEDGER_NOT_EXACT'});continue
            deleted=set();joins=[];wi=0
            for line in record['lines']:
                for j,(left,right) in enumerate(zip(line['words'],line['words'][1:])):
                    li=wi+j;ri=li+1;em=max(left['size'],right['size']);gap=right['bbox'][0]-left['bbox'][2]
                    if not re.fullmatch(rule['eligible_word_pattern'],left['text']) or not re.fullmatch(rule['eligible_word_pattern'],right['text']):continue
                    if left['font_face']!=right['font_face']:continue
                    if abs(left['size']-right['size'])/em>rule['maximum_size_relative_difference']:continue
                    if abs(sum(left['bbox'][1::2])/2-sum(right['bbox'][1::2])/2)>rule['maximum_baseline_center_difference_em']*em:continue
                    if not rule['minimum_gap_pt']<=gap<=rule['maximum_gap_em']*em:continue
                    center=(sum(left['bbox'][1::2])+sum(right['bbox'][1::2]))/4
                    spaces=[c['object_id'] for c in data['chars'] if c['text'].isspace() and left['bbox'][2]<=(c['bbox'][0]+c['bbox'][2])/2<=right['bbox'][0] and abs((c['bbox'][1]+c['bbox'][3])/2-center)<=rule['literal_space_y_tolerance_em']*em]
                    if spaces:continue
                    offsets=[p for p,ch in enumerate(old) if ch==' ' and p>0 and ledger[p]==ri and ledger[p-1]==li]
                    if len(offsets)!=1:continue
                    deleted.update(offsets);joins.append({'left_word_index':li,'right_word_index':ri,'gap_em':gap/em,'deleted_space_offset':offsets[0],'native_glyph_ids':[c['object_id'] for c in data['word_matches'][li]+data['word_matches'][ri]]})
                wi+=len(line['words'])
            if not deleted:continue
            text=''.join(ch for i,ch in enumerate(old) if i not in deleted)
            assert ''.join(old.split())==''.join(text.split()),'SOURCE_GLYPH_LOST'
            positions=[i for i in range(len(old)) if i not in deleted];inverse=[None]*len(old)
            for i,p in enumerate(positions):inverse[p]=i
            texts[bid]=text;remaps[bid]={'new_to_old':positions,'old_to_new':inverse,'deleted_synthetic_space_offsets':sorted(deleted)}
            details.append({'block_id':bid,'pdf_page_index':page['page_index'],'old_text':old,'new_text':text,'joins':joins,'normalization':rule['name'],'native_glyphs_retained':[{'object_id':c['object_id'],'text':c['text']} for match in data['word_matches'] for c in match]})
    return {'texts':texts,'offset_remaps':remaps,'details':details,'unknown':unknown}
