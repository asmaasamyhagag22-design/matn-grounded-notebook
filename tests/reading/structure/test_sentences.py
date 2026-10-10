from matn_reading.structure.sentences import sentence_spans

def test_decimals_abbreviations_percent_ranges_lists():
    text='Fig. 2.4 shows U.S. growth of 2.4% over 10–20 years. No. 2 is an example, e.g. this one. Final.'
    spans=sentence_spans(text)
    assert [text[s.start:s.end].strip() for s in spans]==['Fig. 2.4 shows U.S. growth of 2.4% over 10–20 years.','No. 2 is an example, e.g. this one.','Final.']
    assert ''.join(text[s.start:s.end] for s in spans)==text
    assert len(sentence_spans('1. Growth is 2.4%.'))==1
