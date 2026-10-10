import pytest
from matn_reading.structure.geometry import inverse_box

def test_inverse_deskew_and_crop_origin():
    assert inverse_box((10,20,30,40),[10,20,110,120],{'size':[400,400],'rotation_deg':0},300)==pytest.approx((10,20,30,40))
    box=inverse_box((40,40,60,60),[0,0,100,100],{'size':[100,100],'rotation_deg':90},72)
    assert box==pytest.approx((40,40,60,60))
    assert inverse_box((0,0,10,20),[0,0,100,100],{'size':[100,100],'rotation_deg':90},72)==pytest.approx((80,0,100,10))
