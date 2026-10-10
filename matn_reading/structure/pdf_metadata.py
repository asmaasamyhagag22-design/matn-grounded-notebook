"""Read-only PDF metadata, using the already installed PDF libraries."""
import pdfplumber
import pypdfium2 as pdfium


def read_metadata(path):
    with pdfplumber.open(path) as pdf:
        title=(pdf.metadata or {}).get('Title') or ''
    pdf=pdfium.PdfDocument(str(path))
    try:
        outline=[]
        for mark in pdf.get_toc():
            dest=mark.get_dest()
            outline.append({'title':mark.get_title(),'level':mark.level,'page_index':dest.get_index() if dest else None})
        pages=[]
        for i in range(len(pdf)):
            page=pdf[i]
            try: pages.append({'page_index':i,'rotation':page.get_rotation(),'render_size':list(page.get_size()),'page_label':pdf.get_page_label(i) or None})
            finally: page.close()
        return {'title':str(title).strip(),'outline':outline,'pdf_metadata_pages':pages}
    finally: pdf.close()
