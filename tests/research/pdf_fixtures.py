"""Small authored PDFs for research tests; no PDF-library license dependency.

This extends the byte-writing pattern used by tests.reading.pdf_fixtures with
multiple pages and nested bookmarks. Positions use the tests' top-left frame.
"""


def _literal(text):
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').encode('ascii')


def text(text, *, x=50, y=60, size=11):
    lines = text.splitlines()
    commands = [b'BT /F1 %g Tf %g TL %g %g Td' % (size, size * 1.25, x, 792 - y)]
    for i, line in enumerate(lines):
        if i:
            commands.append(b'T*')
        commands.append(b'(' + _literal(line) + b') Tj')
    return b'\n'.join(commands + [b'ET']) + b'\n'


def pdf_bytes(pages, *, outline=()):
    """Return PDF bytes; outline rows are (one-based level, title, page number)."""
    count = len(pages); first_outline = 4 + 2 * count
    catalog = b'<< /Type /Catalog /Pages 2 0 R'
    if outline:
        catalog += b' /Outlines %d 0 R' % first_outline
    objects = [catalog + b' >>', b'<< /Type /Pages /Count %d /Kids [' % count
               + b' '.join(b'%d 0 R' % (4 + 2 * i) for i in range(count)) + b'] >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for i, content in enumerate(pages):
        objects.extend([b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]'
                        b' /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>' % (5 + 2 * i),
                        b'<< /Length %d >>\nstream\n' % len(content) + content + b'endstream'])
    if outline:
        nodes = []; stack = []; children = {first_outline: []}
        for i, (level, title, page) in enumerate(outline):
            while len(stack) >= level:
                stack.pop()
            if len(stack) != level - 1:
                raise ValueError('fixture outline level gap')
            number = first_outline + 1 + i; parent = stack[-1] if stack else first_outline
            children.setdefault(parent, []).append(number); children[number] = []
            nodes.append((number, parent, title, page)); stack.append(number)
        roots = children[first_outline]
        objects.append(b'<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>'
                       % (roots[0], roots[-1], len(nodes)))
        for number, parent, title, page in nodes:
            siblings = children[parent]; index = siblings.index(number)
            body = b'<< /Title (' + _literal(title) + b') /Parent %d 0 R' % parent
            if page is not None:
                body += b' /Dest [%d 0 R /Fit]' % (4 + 2 * (page - 1))
            else:
                body += b' /A << /S /URI /URI (https://fixture.example/) >>'
            if index:
                body += b' /Prev %d 0 R' % siblings[index - 1]
            if index + 1 < len(siblings):
                body += b' /Next %d 0 R' % siblings[index + 1]
            if children[number]:
                body += b' /First %d 0 R /Last %d 0 R /Count %d' % (children[number][0], children[number][-1], len(children[number]))
            objects.append(body + b' >>')
    output = b'%PDF-1.4\n'; offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(output)); output += b'%d 0 obj\n' % number + body + b'\nendobj\n'
    xref = len(output); output += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    output += b''.join(b'%010d 00000 n \n' % offset for offset in offsets)
    output += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return output
