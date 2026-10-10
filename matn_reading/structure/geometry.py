"""Known OCR frame inverse. Coarse boxes remain coarse, never char-interpolated."""
import math
from matn_contracts.structure import BBoxRef


def inverse_box(box,cropbox,preprocess,dpi=300):
    angle=math.radians(preprocess.get('rotation_deg',0))
    size=preprocess.get('size')
    if not size: raise ValueError('missing OCR frame size')
    cx,cy=size[0]/2,size[1]/2
    points=[]
    for x,y in [(box[0],box[1]),(box[2],box[1]),(box[2],box[3]),(box[0],box[3])]:
        x=(x-cropbox[0])*dpi/72-cx;y=(y-cropbox[1])*dpi/72-cy
        # PIL positive forward angle is counterclockwise in screen coordinates;
        # this maps processed coordinates back to original coordinates.
        px=math.cos(angle)*x-math.sin(angle)*y+cx
        py=math.sin(angle)*x+math.cos(angle)*y+cy
        points.append((cropbox[0]+px*72/dpi,cropbox[1]+py*72/dpi))
    return min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points)


def box_ref(box,precision='word',page=None):
    if page and page.get('ocr'):
        box=inverse_box(box,page['cropbox'],page['ocr']['preprocess'])
    return BBoxRef(coordinates=tuple(box),bbox_precision=precision)


def inside(inner,outer,tolerance=0.5):
    return inner[0]>=outer[0]-tolerance and inner[1]>=outer[1]-tolerance and inner[2]<=outer[2]+tolerance and inner[3]<=outer[3]+tolerance
