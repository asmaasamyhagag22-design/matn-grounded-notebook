from eval.rag.r_lite_3_part2b import sanity_match


def test_sanity_requires_one_text_region_not_a_union():
    assert not sanity_match([0,0,10,10],[[0,0,4,10],[6,0,10,10]])
    assert sanity_match([0,0,10,10],[[0,0,5,10]])


def test_label_comparison_does_not_hide_confidence_difference(tmp_path):
    import json
    from eval.rag.r_lite_3_part2b import compare_labels
    first=tmp_path/'first.json';second=tmp_path/'second.json'
    a={'pages':[{'source':'example','pdf_page_index':0,'confidence':0.50000001}]}
    first.write_text(json.dumps(a));second.write_bytes(first.read_bytes())
    assert compare_labels(first,second)['byte_equal']
    a['pages'][0]['confidence']=0.50000002
    second.write_text(json.dumps(a))
    result=compare_labels(first,second)
    assert not result['byte_equal']
    assert result['changed_pages'][0]['pdf_page_index']==0
    assert result['metadata_equal']
