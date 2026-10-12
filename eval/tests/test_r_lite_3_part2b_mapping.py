from eval.rag.r_lite_3_part2b_mapping import convert_box, union_share, retype


def test_coordinate_origin_and_point_scale():
    box={'l':10,'t':90,'r':30,'b':70,'coord_origin':'BOTTOMLEFT'}
    assert convert_box(box,[100,100],[200,200])==[20,20,60,60]


def test_overlaps_are_unioned_not_double_counted():
    assert union_share([0,0,10,10],[[0,0,6,10],[0,0,6,10]])==0.6


def test_owner_mapping_uses_both_majorities():
    assert retype(0.5,0.49)
    assert not retype(0.5,0.5)
    assert not retype(0.49,0)
