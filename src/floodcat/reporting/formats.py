"""Render a report `Document` as PDF (fpdf2), Word (python-docx) or Excel (openpyxl). All return bytes.

PDF and Word are for reading: formatted figures, charts, the data appendix left out. Excel is for analysts: every table
on a sheet with numbers kept as numbers, plus every property's loss for every scenario (with its `synthetic` flag).
User-supplied text is written to Excel as text, never as a formula.
"""
import io
from decimal import Decimal
from .document import Table, fmt
from . import charts

LABEL_COLOURS = {'REAL': (27, 135, 82), 'PROXY': (196, 98, 16), 'SYNTHETIC': (124, 77, 200), 'ASSUMPTION': (100, 100, 96), 'AI': (42, 120, 214)}
_PDF_TEXT = str.maketrans({'→': '->', '≈': '~', '≥': '>=', '≤': '<=', 'σ': 'sigma ', 'ρ': 'rho ', '✓': 'yes', '✗': 'no', '\u00a0': ' ', '−': '-',
                           '—': '-', '–': '-', '‘': "'", '’': "'", '“': '"', '”': '"', '•': '-', '…': '...'})

def _labels(labels):
    return ' · '.join(dict.fromkeys(labels))

def _tables(doc, data_only=None):
    return [b for b in doc.blocks if isinstance(b, Table) and (data_only is None or b.data_only == data_only)]

# PDF ----------------------------------------------------------------------------------------------------
def to_pdf(doc, report, ylt=None):
    from fpdf import FPDF
    from fpdf.fonts import FontFace
    t = lambda s: str(s).translate(_PDF_TEXT).encode('latin-1', 'replace').decode('latin-1')   # core fonts are Latin-1

    class PDF(FPDF):
        def footer(self):
            self.set_y(-12); self.set_font('Helvetica', '', 7); self.set_text_color(120, 120, 116)
            self.cell(0, 5, t(f'{doc.title} · indicative, uncalibrated model · page {self.page_no()}/{{nb}}'), align='C')

    pdf = PDF(format='A4'); pdf.set_auto_page_break(True, margin=16); pdf.set_margins(16, 16, 16); pdf.alias_nb_pages()
    pdf.set_title(t(doc.title)); pdf.set_creator('Xpat flood model'); pdf.add_page()
    width = pdf.epw
    pdf.set_font('Helvetica', 'B', 18); pdf.set_text_color(25, 25, 24); pdf.multi_cell(width, 8, t(doc.title))
    pdf.set_font('Helvetica', '', 10); pdf.set_text_color(107, 107, 102); pdf.multi_cell(width, 5, t(doc.subtitle)); pdf.ln(2)
    pdf.set_font('Helvetica', '', 8)
    for k, v in doc.meta:
        pdf.set_text_color(107, 107, 102); pdf.cell(38, 4.5, t(k)); pdf.set_text_color(40, 40, 38); pdf.multi_cell(width-38, 4.5, t(v))
    pdf.ln(3)
    for block in doc.blocks:
        if isinstance(block, Table):
            if block.data_only: continue
            pdf.set_font('Helvetica', 'B', 10); pdf.set_text_color(25, 25, 24); pdf.multi_cell(width, 5.5, t(block.title))
            widths = _col_widths(pdf, block, width, t)
            pdf.set_font('Helvetica', '', 7.5); pdf.set_text_color(40, 40, 38)
            with pdf.table(col_widths=widths, text_align=['LEFT' if f == 'text' else 'RIGHT' for _, f in block.columns], line_height=4.2,
                           headings_style=FontFace(emphasis='BOLD', fill_color=(238, 241, 246)), borders_layout='HORIZONTAL_LINES',
                           cell_fill_color=(250, 250, 248), cell_fill_mode='ROWS', padding=1.2) as table:
                table.row([t(h) for h, _ in block.columns])
                for r in block.rows: table.row([t(fmt(v, f)) for v, (_, f) in zip(r, block.columns)])
            note = (block.note + ' ' if block.note else '') + (f'[{_labels(block.labels)}]' if block.labels else '')
            if note.strip():
                pdf.set_font('Helvetica', 'I', 7); pdf.set_text_color(107, 107, 102); pdf.multi_cell(width, 3.8, t(note))
            pdf.ln(3); continue
        kind = block[0]
        if kind == 'heading':
            _, text, level, labels = block
            if level == 1 and pdf.get_y() > pdf.h - 70: pdf.add_page()
            pdf.ln(2 if level > 1 else 4)
            pdf.set_font('Helvetica', 'B', {1: 13, 2: 11, 3: 10}[level]); pdf.set_text_color(25, 25, 24); pdf.multi_cell(width, 6, t(text))
            if labels:
                pdf.set_font('Helvetica', 'B', 7)
                for label in dict.fromkeys(labels):
                    pdf.set_text_color(*LABEL_COLOURS[label]); pdf.cell(pdf.get_string_width(label)+4, 4.5, label)
                pdf.ln(5.5)
        elif kind == 'para':
            pdf.set_font('Helvetica', '', 9); pdf.set_text_color(40, 40, 38); pdf.multi_cell(width, 4.6, t(block[1])); pdf.ln(1.5)
        elif kind == 'bullets':
            pdf.set_font('Helvetica', '', 8.5); pdf.set_text_color(40, 40, 38)
            for item in block[1]: pdf.set_x(pdf.l_margin+2); pdf.multi_cell(width-2, 4.3, t('-  ' + item))
            pdf.ln(1.5)
        elif kind == 'callout':
            pdf.set_fill_color(255, 246, 230); pdf.set_draw_color(237, 161, 0); pdf.set_font('Helvetica', '', 8.5); pdf.set_text_color(90, 60, 0)
            pdf.multi_cell(width, 4.6, t(block[1]), border=1, fill=True, padding=2.5); pdf.ln(3)
        elif kind == 'kpis':
            items = block[1]; w = width/len(items); y = pdf.get_y()
            pdf.set_draw_color(220, 220, 216)
            for i, (label, value, note) in enumerate(items):
                x = pdf.l_margin + i*w
                pdf.rect(x+0.8, y, w-1.6, 21)
                pdf.set_xy(x+2.5, y+2); pdf.set_font('Helvetica', '', 7); pdf.set_text_color(107, 107, 102); pdf.multi_cell(w-5, 3.3, t(label))
                pdf.set_xy(x+2.5, y+8.5); pdf.set_font('Helvetica', 'B', 11 if len(items) < 5 else 9.5); pdf.set_text_color(25, 25, 24); pdf.cell(w-5, 5, t(value))
                pdf.set_xy(x+2.5, y+14.5); pdf.set_font('Helvetica', '', 6.5); pdf.set_text_color(107, 107, 102); pdf.multi_cell(w-5, 3, t(note))
            pdf.set_xy(pdf.l_margin, y+24)
        elif kind == 'chart':
            png = charts.render(block[1], report, ylt)
            pdf.image(io.BytesIO(png), w=width)
            pdf.set_font('Helvetica', 'I', 7.5); pdf.set_text_color(107, 107, 102); pdf.multi_cell(width, 3.8, t(block[2])); pdf.ln(2)
    return bytes(pdf.output())

def _col_widths(pdf, table, total, t):
    """Measured widths: never narrower than the longest single word in a column, otherwise in proportion to its typical content."""
    pdf.set_font('Helvetica', 'B', 7.5)
    words, wants = [], []
    for i, (h, f) in enumerate(table.columns):
        cells = [t(fmt(r[i], f)) for r in table.rows[:80]]
        word = max([pdf.get_string_width(w) for c in [t(h)] + cells for w in c.split()] or [5]) + 3.5
        want = max([pdf.get_string_width(c) for c in cells] or [5]) + 3.5
        words.append(word); wants.append(min(want, total*0.55))
    wants = [max(w, m) for w, m in zip(wants, words)]
    if sum(wants) <= total: return [w*total/sum(wants) for w in wants]
    spare = total - sum(words)
    if spare <= 0: return [w*total/sum(words) for w in words]
    extra = [w-m for w, m in zip(wants, words)]
    return [m + spare*e/sum(extra) for m, e in zip(words, extra)]

# Word ---------------------------------------------------------------------------------------------------
def to_docx(doc, report, ylt=None):
    from docx import Document as Docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor
    out = Docx()
    for s in out.sections: s.left_margin = s.right_margin = Cm(1.8); s.top_margin = s.bottom_margin = Cm(1.6)
    out.styles['Normal'].font.name = 'Calibri'; out.styles['Normal'].font.size = Pt(10)
    out.core_properties.title = doc.title; out.core_properties.author = 'Xpat flood model'
    out.add_heading(doc.title, 0)
    p = out.add_paragraph(doc.subtitle); p.runs[0].italic = True
    meta = out.add_table(rows=0, cols=2)
    for k, v in doc.meta:
        cells = meta.add_row().cells; cells[0].text = k; cells[1].text = str(v)
        cells[0].paragraphs[0].runs[0].font.color.rgb = RGBColor(107, 107, 102)
    style = 'Light Grid Accent 1' if 'Light Grid Accent 1' in [s.name for s in out.styles] else 'Table Grid'
    for block in doc.blocks:
        if isinstance(block, Table):
            if block.data_only: continue
            out.add_paragraph().add_run(block.title).bold = True
            table = out.add_table(rows=1, cols=len(block.columns)); table.style = style
            for cell, (h, _) in zip(table.rows[0].cells, block.columns): cell.text = h
            for r in block.rows:
                cells = table.add_row().cells
                for cell, v, (_, f) in zip(cells, r, block.columns):
                    cell.text = fmt(v, f)
                    if f != 'text': cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            for row in table.rows:
                for cell in row.cells:
                    for run in cell.paragraphs[0].runs: run.font.size = Pt(8)
            note = (block.note + ' ' if block.note else '') + (f'[{_labels(block.labels)}]' if block.labels else '')
            if note.strip():
                run = out.add_paragraph().add_run(note); run.italic = True; run.font.size = Pt(8); run.font.color.rgb = RGBColor(107, 107, 102)
            continue
        kind = block[0]
        if kind == 'heading':
            _, text, level, labels = block
            out.add_heading(text, level)
            if labels:
                p = out.add_paragraph()
                for label in dict.fromkeys(labels):
                    run = p.add_run(label + '   '); run.bold = True; run.font.size = Pt(8); run.font.color.rgb = RGBColor(*LABEL_COLOURS[label])
        elif kind == 'para':
            out.add_paragraph(block[1])
        elif kind == 'bullets':
            for item in block[1]: out.add_paragraph(item, style='List Bullet')
        elif kind == 'callout':
            p = out.add_paragraph(); run = p.add_run(block[1]); run.font.color.rgb = RGBColor(120, 80, 0); run.font.size = Pt(9)
        elif kind == 'kpis':
            table = out.add_table(rows=2, cols=len(block[1])); table.style = style
            for i, (label, value, note) in enumerate(block[1]):
                table.cell(0, i).text = label
                cell = table.cell(1, i); cell.text = ''
                cell.paragraphs[0].add_run(value).bold = True
                if note:
                    run = cell.add_paragraph().add_run(note); run.font.size = Pt(8); run.font.color.rgb = RGBColor(107, 107, 102)
        elif kind == 'chart':
            out.add_picture(io.BytesIO(charts.render(block[1], report, ylt)), width=Cm(17))
            run = out.add_paragraph().add_run(block[2]); run.italic = True; run.font.size = Pt(8)
    buf = io.BytesIO(); out.save(buf); return buf.getvalue()

# Excel --------------------------------------------------------------------------------------------------
NUMBER_FORMATS = {'kes': '#,##0', 'pct': '0.00%', 'ratio': '0.0%', 'rp': '"1-in-"#,##0', 'int': '#,##0', 'num': '0.000'}

def _cell_value(value, kind):
    if value is None or value == '': return None
    if kind in ('kes', 'num', 'ratio', 'rp'): return float(Decimal(str(value)))
    if kind == 'pct': return float(value)/100
    if kind == 'int': return int(value)
    return str(value)

def to_xlsx(doc, report, ylt=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook(); summary = wb.active; summary.title = 'Summary'
    bold, muted = Font(bold=True), Font(color='6B6B66', italic=True)
    head_fill = PatternFill('solid', fgColor='EEF1F6')

    def text(cell, value):
        cell.value = value
        if isinstance(value, str): cell.data_type = 's'           # never a formula, whatever the text starts with
        return cell

    text(summary.cell(1, 1), doc.title).font = Font(bold=True, size=14)
    text(summary.cell(2, 1), doc.subtitle).font = muted
    row = 4
    for k, v in doc.meta: text(summary.cell(row, 1), k).font = muted; text(summary.cell(row, 2), v); row += 1
    row += 1
    for block in doc.blocks:
        if isinstance(block, Table): continue
        kind = block[0]
        if kind == 'kpis':
            for label, value, note in block[1]:
                text(summary.cell(row, 1), label); text(summary.cell(row, 2), value).font = bold; text(summary.cell(row, 3), note).font = muted; row += 1
            row += 1
        elif kind == 'callout':
            text(summary.cell(row, 1), block[1]).alignment = Alignment(wrap_text=True); summary.merge_cells(start_row=row, end_row=row, start_column=1, end_column=4)
            summary.row_dimensions[row].height = 60; row += 2
    text(summary.cell(row, 1), 'Sheets').font = bold; row += 1
    sheets = {}
    for table in _tables(doc):
        name = (table.sheet or table.title)[:31]
        if name not in sheets:
            ws = wb.create_sheet(name); sheets[name] = [ws, 1]
            text(summary.cell(row, 1), name); text(summary.cell(row, 2), table.title).font = muted; row += 1
        ws, r = sheets[name]
        text(ws.cell(r, 1), table.title).font = Font(bold=True, size=12); r += 1
        if table.labels: text(ws.cell(r, 1), _labels(table.labels)).font = muted; r += 1
        for c, (h, _) in enumerate(table.columns, 1):
            cell = text(ws.cell(r, c), h); cell.font = bold; cell.fill = head_fill
        if table.data_only: ws.freeze_panes = ws.cell(r+1, 1)
        r += 1
        for values in table.rows:
            for c, (v, (_, kind)) in enumerate(zip(values, table.columns), 1):
                cell = text(ws.cell(r, c), _cell_value(v, kind))
                if kind in NUMBER_FORMATS: cell.number_format = NUMBER_FORMATS[kind]
            r += 1
        if table.note: text(ws.cell(r, 1), table.note).font = muted; r += 1
        sheets[name][1] = r + 1
        for c, (h, kind) in enumerate(table.columns, 1):
            letter = get_column_letter(c)
            ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 0, min(60, max(12, len(h)+2, 16 if kind == 'kes' else 0)))
    summary.column_dimensions['A'].width = 30; summary.column_dimensions['B'].width = 48; summary.column_dimensions['C'].width = 36
    lim = wb.create_sheet('Limitations')
    text(lim.cell(1, 1), 'Limitations').font = Font(bold=True, size=12)
    for i, item in enumerate(report['limitations'], 3): text(lim.cell(i, 1), item)
    lim.column_dimensions['A'].width = 140
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

RENDERERS = {'pdf': (to_pdf, 'application/pdf'),
             'docx': (to_docx, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
             'xlsx': (to_xlsx, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}

def render(doc, kind, report, ylt=None):
    """(bytes, mime type) for 'pdf', 'docx' or 'xlsx'."""
    fn, mime = RENDERERS[kind]
    return fn(doc, report, ylt), mime
