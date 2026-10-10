"""Synthetic R-lite.1 PDFs; no dev-derived fixtures."""
from .pdf_fixtures import write_pdf

def text(x,y,s,font='F1',size=10):
    return f'BT /{font} {size} Tf {x} {y} Td ({s}) Tj ET\n'.encode()


def chart_fixture(path):
    content=text(72,730,'Body prose remains citable and contains 123.')
    content+=b'0.9 g 70 370 230 260 re f 0 g\n'
    for y in range(390,601,20):content+=f'80 {y} m 280 {y} l S\n'.encode()
    content+=b'80 390 m 80 610 l S 80 390 m 280 390 l S\n'
    for i in range(5):content+=text(60,390+i*40,str(i*25))
    content+=b'BT /F1 10 Tf 0 1 -1 0 48 430 Tm (Completion Rate) Tj ET\n'
    content+=b'BT /F1 10 Tf -1 0 0 -1 260 350 Tm (Higher is Better) Tj ET\n'
    return write_pdf(path,content)


