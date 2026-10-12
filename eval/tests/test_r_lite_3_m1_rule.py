from eval.rag.r_lite_3_m1_rule import decide


def page(rects=(),lines=()):
    return {'rects':list(rects),'lines':[{'bbox':x} for x in lines],'curves':[],'chars':[]}


def test_variable_parallel_bars_are_chart_objects():
    p=page([{'bbox':[10,10+i*12,10+length,14+i*12],'fill':True} for i,length in enumerate((30,60,90))])
    assert decide(p,[0,0,120,70],6)['chart']


def test_equal_cell_rectangles_do_not_become_bars():
    p=page([{'bbox':[10,10+i*20,100,28+i*20],'fill':True} for i in range(3)])
    assert not decide(p,[0,0,120,90],6)['chart']


def test_ruled_grid_vetoes_bar_coincidence():
    p=page([{'bbox':[10,10+i*12,10+length,14+i*12],'fill':True} for i,length in enumerate((30,60,90))],
           [(0,y,120,y) for y in (0,35,70)]+[(x,0,x,70) for x in (0,60,120)])
    assert not decide(p,[0,0,120,70],6)['chart']


def test_missing_native_objects_is_explicit_unknown():
    assert decide(None,[0,0,120,70],6)['status']=='NO_NATIVE_OBJECTS'
