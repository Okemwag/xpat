"""Read submission documents (PDF, DOCX, text) into plain text for AI extraction.

The file type is detected from its bytes, not its name: broker submissions arrive with names like
"OFFER.docx.pdf". Untrusted input, so sizes are capped before and after decompression, and a PDF
with no text layer (a scan) is rejected rather than silently read as empty.
"""
import io
import re
import zipfile
from xml.etree import ElementTree
from ..core.errors import ModelError

MAX_FILE_BYTES = 15_000_000
MAX_PAGES = 80
MAX_CHARS = 120_000
MAX_DOCX_XML_BYTES = 30_000_000
MIN_CHARS_PER_PAGE = 20
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def detect_kind(data):
    if data[:5] == b'%PDF-': return 'pdf'
    if data[:4] == b'PK\x03\x04':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if 'word/document.xml' in z.namelist(): return 'docx'
        except zipfile.BadZipFile:
            pass
        raise ModelError('unsupported_document', 'This is a ZIP file but not a Word document')
    if data[:4] == b'\xd0\xcf\x11\xe0':
        raise ModelError('unsupported_document', 'Old Word (.doc) files are not supported; save as .docx or PDF')
    return 'text'

def _pdf_text(data):
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        raise ModelError('unsupported_document', "Install the 'ai' extra (pypdf) to read PDF files") from None
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try: reader.decrypt('')
            except Exception: raise ModelError('unsupported_document', 'The PDF is password-protected') from None
        pages = reader.pages
        if len(pages) > MAX_PAGES: raise ModelError('document_too_large', f'Documents are limited to {MAX_PAGES} pages')
        texts = [(page.extract_text() or '') for page in pages]
    except ModelError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise ModelError('unreadable_document', f'The PDF could not be read ({type(exc).__name__})') from None
    text = '\n\n'.join(f'[page {i}]\n{t.strip()}' for i, t in enumerate(texts, 1) if t.strip())
    if sum(len(t.strip()) for t in texts) < MIN_CHARS_PER_PAGE*max(1, len(texts)):
        raise ModelError('scanned_document', 'The PDF has no readable text layer (probably a scan); OCR is not supported')
    return text, len(texts)

def _docx_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = z.getinfo('word/document.xml')
        if info.file_size > MAX_DOCX_XML_BYTES: raise ModelError('document_too_large', 'The Word document is too large to read')
        root = ElementTree.fromstring(z.read(info))
    blocks = []
    body = root.find(f'{W}body')
    for element in (body if body is not None else []):
        if element.tag == f'{W}p':
            line = ''.join(t.text or '' for t in element.iter(f'{W}t'))
            if line.strip(): blocks.append(line)
        elif element.tag == f'{W}tbl':
            for row in element.iter(f'{W}tr'):
                cells = [' '.join(''.join(t.text or '' for t in p.iter(f'{W}t')) for p in cell.iter(f'{W}p')).strip()
                         for cell in row.iter(f'{W}tc')]
                if any(cells): blocks.append(' | '.join(cells))
    text = '\n'.join(blocks)
    if not text.strip(): raise ModelError('empty_document', 'The Word document has no text')
    return text, None

def read_document(data, filename=''):
    """Return {'text', 'kind', 'pages', 'chars', 'filename', 'redacted', 'name_mismatch'}; e-mails and phone numbers are removed."""
    if not data: raise ModelError('empty_document', 'The file is empty')
    if len(data) > MAX_FILE_BYTES: raise ModelError('document_too_large', f'Documents are limited to {MAX_FILE_BYTES//1_000_000} MB')
    kind = detect_kind(data)
    if kind == 'pdf': text, pages = _pdf_text(data)
    elif kind == 'docx': text, pages = _docx_text(data)
    else:
        try: text = data.decode('utf-8-sig')
        except UnicodeDecodeError: text = data.decode('cp1252', errors='replace')
        if '\x00' in text: raise ModelError('unsupported_document', 'This file type is not supported; use PDF, DOCX or plain text')
        pages = None
    text = re.sub(r'[ \t]+', ' ', text.replace('\r\n', '\n'))
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if len(text) > MAX_CHARS:
        raise ModelError('document_too_large', f'The document has {len(text):,} characters of text; the limit is {MAX_CHARS:,}. Split it and upload the property section.')
    from .privacy import redact
    text, removed = redact(text)  # contact details never leave this function
    suffix = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    expected = {'pdf': 'pdf', 'docx': 'docx', 'txt': 'text', 'md': 'text'}.get(suffix)
    return {'text': text, 'kind': kind, 'pages': pages, 'chars': len(text), 'filename': filename, 'redacted': removed,
            'name_mismatch': bool(expected and expected != kind) or ('.docx.' in filename.lower() and kind != 'docx')}
