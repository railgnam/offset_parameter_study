"""Presentation figures (tables and charts as PNG) from the comparison tables. Pillow only.

  python figures.py [--tag v2]          # reads exports/<date>_<tag>/tables/*.csv, writes exports/<date>_<tag>/figures/*.png

Design: one message per figure, the reference C always first, deviations from C printed under every value and
colour-coded by magnitude (green < 5 %, yellow < 15 %, orange < 30 %, red >= 30 %; the sign is always printed, so colour is not
the only carrier).  Case colours are fixed (A orange, B1 green, B2 purple, C dark grey) in every chart.
"""
import argparse, csv, datetime, glob, json, math, os, sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CASE_COLORS = {'A': '#d95f02', 'B1': '#1b9e77', 'B2': '#7570b3', 'C': '#303030'}
CASE_LABELS = {'A': 'A  module-wise', 'B1': 'B1  joint-wise (large)', 'B2': 'B2  joint-wise (small)', 'C': 'C  full model (reference)'}
# zone_offset additions: the corrected reference and the offset ladder (light -> dark with the offset)
CASE_COLORS.update({'C25': '#000000', 'C': '#8c8c8c',
                    'D0': '#c6dbef', 'D1': '#9ecae1', 'D2': '#6baed6', 'D3': '#4292c6',
                    'D4': '#2171b5', 'D5': '#08519c', 'D6': '#08306b', 'D3K': '#e7298a'})
CASE_LABELS.update({'C25': 'C25  full model, EMB-TIMBER r=25 (reference)',
                    'C': 'C  full model, EMB-TIMBER r=50 (superseded)',
                    'D0': 'D0  t=0 (B2 partition)', 'D1': 'D1  t=30', 'D2': 'D2  t=90',
                    'D3': 'D3  t=150', 'D4': 'D4  t=210', 'D5': 'D5  t=270',
                    'D6': 'D6  t=300 (B1 partition)', 'D3K': 'D3K  t=150, kinematic interfaces'})
DEV_FILLS = [(5, '#d8f0d0'), (15, '#fff3b0'), (30, '#fdd5a8'), (1e9, '#f6b0aa')]
INK, GREY, LINE, HEAD = '#1c1c1c', '#6b6b6b', '#cfcfcf', '#e6edf3'
PROBE_NAMES = {'FO-MIDSPAN': 'Mid-span, top module', 'FO3-BEAM-MID-LEFT': 'Beam, left end (module 2)', 'FO4-POST-BOTTOM-CORNER': 'Post, top corner (module 2)'}
CLASS_NAMES = {'timber': 'Timber', 'steel_corner': 'Steel plate, corner', 'steel_inter': 'Steel plates, inter-module', 'dowel': 'Dowels'}
JOINT_NAMES = {'J3': 'Joint-3 (left, module 1/2)', 'J6': 'Joint-6 (right, module 2/3)'}


def font(size, bold=False):
    for name in (('arialbd.ttf' if bold else 'arial.ttf'), ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


FONT_SPEC = {'title': (44, True), 'sub': (26, False), 'head': (27, True), 'body': (27, False), 'bold': (27, True),
             'small': (22, False), 'tick': (22, False), 'dev': (22, False)}
F = {key: font(sz, b) for key, (sz, b) in FONT_SPEC.items()}


def num(s):
    try:
        v = float(s)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def read(tdir, name):
    p = os.path.join(tdir, name + '.csv')
    if not os.path.isfile(p):
        return []
    with open(p, newline='', encoding='utf8') as f:
        return list(csv.DictReader(f))


def dev_fill(d):
    if d is None:
        return '#ffffff'
    for lim, col in DEV_FILLS:
        if abs(d) < lim:
            return col
    return DEV_FILLS[-1][1]


def fnum(v, nd=1):
    if v is None:
        return '-'
    if abs(v) >= 100:
        return '%.0f' % v
    return ('%.' + str(nd) + 'f') % v


def sdev(d):
    if d is None:
        return ''
    if abs(d) < 0.05:
        return '0.0 %'
    return '%+.0f %%' % d if abs(d) >= 10 else '%+.1f %%' % d


# ------------------------------------------------------------------ generic table renderer
class Table:
    """cells: rows of dicts {t: str | [str, str], fill, bold, align, color, span}"""

    def __init__(self, col_w, title, subtitle, note_lines=(), width_pad=50):
        self.col_w, self.title, self.subtitle, self.notes, self.pad = col_w, title, subtitle, list(note_lines), width_pad
        self.rows, self.row_h = [], []
        self.data = None            # source rows (list of dicts) written to a 'Data' sheet of the Excel version

    def add(self, cells, h=52):
        self.rows.append(cells)
        self.row_h.append(h)

    def render(self, path, min_width=2048):
        nat = sum(self.col_w) + 2 * self.pad
        k = max(1.0, (min_width + 24) / float(nat))             # scale everything so the figure is at least 2K wide
        Fk = {key: font(int(round(sz * k)), b) for key, (sz, b) in FONT_SPEC.items()}
        pad, col_w, row_h = int(self.pad * k), [int(c * k) for c in self.col_w], [int(h * k) for h in self.row_h]
        W = sum(col_w) + 2 * pad
        top = int(150 * k)
        H = top + sum(row_h) + int(60 * k) + int(34 * k) * len(self.notes) + int(30 * k)
        im = Image.new('RGB', (W, H), '#ffffff')
        d = ImageDraw.Draw(im)
        d.text((pad, int(36 * k)), self.title, fill=INK, font=Fk['title'])
        d.text((pad, int(96 * k)), self.subtitle, fill=GREY, font=Fk['sub'])
        y = top
        for cells, h in zip(self.rows, row_h):
            x = pad
            ci = 0
            for c in cells:
                span = c.get('span', 1)
                w = sum(col_w[ci:ci + span])
                if c.get('fill'):
                    d.rectangle([x, y, x + w, y + h], fill=c['fill'])
                d.rectangle([x, y, x + w, y + h], outline=LINE)
                lines = c['t'] if isinstance(c['t'], list) else [c['t']]
                fonts = [Fk['bold' if c.get('bold') else 'body']] + [Fk['dev']] * (len(lines) - 1)
                heights = [f.size + 2 for f in fonts[:len(lines)]]
                ty = y + (h - sum(heights)) / 2.0
                for ln, f, hh in zip(lines, fonts, heights):
                    al = c.get('align', 'left')
                    if al == 'center':
                        d.text((x + w / 2.0, ty), ln, fill=c.get('color', INK), font=f, anchor='ma')
                    elif al == 'right':
                        d.text((x + w - 12 * k, ty), ln, fill=c.get('color', INK), font=f, anchor='ra')
                    else:
                        d.text((x + 12 * k, ty), ln, fill=c.get('color', INK), font=f)
                    ty += hh
                x += w
                ci += span
            y += h
        y += int(24 * k)
        for n in self.notes:
            d.text((pad, y), n, fill=GREY, font=Fk['small'])
            y += int(34 * k)
        im.save(path)
        self.write_xlsx(os.path.splitext(path)[0] + '.xlsx')
        print('figure', os.path.basename(path), im.size)

    def write_xlsx(self, path):
        """editable copy of the table figure: same layout, fills and fonts, numbers as numbers, plus the source data"""
        import xlsxwriter
        try:
            wb = xlsxwriter.Workbook(path)
        except Exception:
            return
        ws = wb.add_worksheet('Table')
        base = {'border': 1, 'border_color': LINE, 'valign': 'vcenter', 'text_wrap': True, 'font_name': 'Arial', 'font_size': 11}
        cache = {}

        def fm(c, small=False):
            key = (c.get('fill'), c.get('bold'), c.get('align', 'left'), c.get('color'), small)
            if key not in cache:
                p = dict(base)
                p['align'] = c.get('align', 'left')
                if c.get('bold'):
                    p['bold'] = True
                if c.get('fill'):
                    p['bg_color'] = c['fill']
                if c.get('color'):
                    p['font_color'] = c['color']
                if small:
                    p['font_size'] = 9
                    p['font_color'] = '#555555'
                    p['bold'] = False
                cache[key] = wb.add_format(p)
            return cache[key]

        ws.write(0, 0, self.title, wb.add_format({'bold': True, 'font_size': 16, 'font_name': 'Arial'}))
        ws.write(1, 0, self.subtitle, wb.add_format({'font_color': '#6b6b6b', 'font_name': 'Arial'}))
        r0 = 3
        for j, w in enumerate(self.col_w):
            ws.set_column(j, j, max(8, w / 7.5))
        for ri, (cells, h) in enumerate(zip(self.rows, self.row_h)):
            ws.set_row(r0 + ri, h * 0.62)
            ci = 0
            for c in cells:
                span = c.get('span', 1)
                t = c['t']
                if isinstance(t, list) and len(t) > 1:
                    ws.write_rich_string(r0 + ri, ci, fm(c), t[0] + '\n', fm(c, True), t[1], fm(c))
                else:
                    txt = t[0] if isinstance(t, list) else t
                    val = num(txt) if isinstance(txt, str) and txt.replace('.', '', 1).replace('-', '', 1).isdigit() else None
                    if span > 1:
                        ws.merge_range(r0 + ri, ci, r0 + ri, ci + span - 1, txt, fm(c))
                    elif val is not None:
                        ws.write_number(r0 + ri, ci, val, fm(c))
                    else:
                        ws.write(r0 + ri, ci, txt, fm(c))
                ci += span
        nr = r0 + len(self.rows) + 1
        for n in self.notes:
            ws.write(nr, 0, n, wb.add_format({'font_color': '#6b6b6b', 'font_name': 'Arial', 'font_size': 9}))
            nr += 1
        if self.data:
            wd = wb.add_worksheet('Data')
            cols = []
            for r in self.data:
                for k in r:
                    if k not in cols:
                        cols.append(k)
            hf = wb.add_format({'bold': True, 'bg_color': HEAD, 'border': 1})
            for j, k in enumerate(cols):
                wd.write(0, j, k, hf)
                wd.set_column(j, j, max(10, min(30, len(k) + 2)))
            for i, r in enumerate(self.data, start=1):
                for j, k in enumerate(cols):
                    v = r.get(k, '')
                    n = num(v)
                    wd.write(i, j, n if n is not None else v)
            wd.freeze_panes(1, 0)
        wb.close()


def hdr(t, span=1, align='center'):
    return {'t': t, 'fill': HEAD, 'bold': True, 'span': span, 'align': align}


def case_header(cases, label_w=1):
    return [hdr(CASE_LABELS.get(c, c).split('  ')[0] + ('\nref' if False else ''), align='center') for c in cases]


def value_cell(v, dev, nd=1):
    if v is None:
        return {'t': 'n/a', 'align': 'center', 'color': GREY}
    t = [fnum(v, nd)] + ([sdev(dev)] if dev is not None else [])
    return {'t': t, 'align': 'center', 'fill': dev_fill(dev)}


NOTE_DEV = 'Deviation from C = (case - C) / |C|.  Fill: green < 5 %, yellow < 15 %, orange < 30 %, red >= 30 %.  Stresses in MPa.'


# ------------------------------------------------------------------ figures
def cases_in(rows, order):
    cols = rows[0].keys() if rows else []
    return [c for c in order if c in cols]


def fig_displacements(tdir, out, order, ref):
    rows = read(tdir, 'T1_probe_displacements')
    if not rows:
        return
    cases = [ref] + [c for c in order if c != ref and ('U1_' + c) in rows[0]]
    cw = [430] + [200] * len(cases) * 2
    t = Table(cw, 'Global displacements at the retained probe nodes', 'Wind load, last frame; displacement in mm; each value with its deviation from the full model C',
              [NOTE_DEV.replace('Stresses in MPa.', 'Displacements in mm.')])
    if any('not retained' in str(r.get('U1_' + c, '')) for r in rows for c in cases if c != ref):
        t.notes.append('n/a: the node lies in a main substructure that Abaqus cannot recover; it appears once the back-calculated main substructure (backcalc/) is added to the case.')
    t.add([hdr('Probe', align='left')] + [hdr('U1 (horizontal)', span=len(cases))] + [hdr('U3 (vertical)', span=len(cases))])
    t.add([hdr('', align='left')] + [hdr(c) for c in cases] * 2, h=44)
    for r in rows:
        cells = [{'t': [PROBE_NAMES.get(r['probe'], r['probe']), 'x=%s z=%s mm' % (fnum(num(r['x']), 0), fnum(num(r['z']), 0))], 'bold': True}]
        for comp in ('U1', 'U3'):
            for c in cases:
                v = num(r.get('%s_%s' % (comp, c)))
                dv = num(r.get('dev_%s_%s_%%' % (comp, c)))
                cells.append(value_cell(v, dv, 1 if comp == 'U1' else 2) if c != ref else {'t': fnum(v, 1 if comp == 'U1' else 2), 'align': 'center', 'bold': True})
        t.add(cells, h=86)
    src = []
    for r in rows:
        if r['probe'] == 'FO-MIDSPAN':
            src = ['%s: %s' % (c, r.get('src_' + c) or 'not retained') for c in cases if c != ref]
    if src:
        t.notes.append('Mid-span node found in: ' + '   '.join(src))
    t.data = rows
    t.render(os.path.join(out, 'F1_global_displacements.png'))


def fig_stress_summary(tdir, out, order, ref):
    rows = read(tdir, 'T2_region_stress')
    if not rows:
        return
    cases = [ref] + [c for c in order if c != ref and c in rows[0]]
    idx = {(r['joint'], r['class'], r['quantity'], r['stat']): r for r in rows}
    spec = [('timber', 'S11', [('max', 'peak tension'), ('min', 'peak compression'), ('p95', '95th percentile')]),
            ('timber', 'S22', [('max', 'peak tension'), ('min', 'peak compression'), ('p95', '95th percentile')]),
            ('steel_corner', 'MISES', [('max', 'peak'), ('p95', '95th percentile'), ('mean', 'mean')]),
            ('steel_inter', 'MISES', [('max', 'peak'), ('p95', '95th percentile'), ('mean', 'mean')]),
            ('dowel', 'MISES', [('max', 'peak'), ('p95', '95th percentile'), ('mean', 'mean')])]
    for jid in sorted({r['joint'] for r in rows}):
        t = Table([600, 250] + [210] * len(cases), 'Local stresses: %s' % JOINT_NAMES.get(jid, jid), 'Peak, 95th percentile and mean over all integration points of each part; reference C first',
                  [NOTE_DEV, 'Timber: S11 parallel to grain, S22 perpendicular to grain (compression shown as signed value). Steel and dowels: von Mises.'])
        t.add([hdr('Part', align='left'), hdr('Statistic', align='left')] + [hdr(c) for c in cases])
        for cls, q, stats in spec:
            for k, (st, lab) in enumerate(stats):
                r = idx.get((jid, cls, q, st))
                if not r:
                    continue
                refv = num(r.get(ref))
                cells = [{'t': CLASS_NAMES[cls] + {'S11': ' || grain (S11)', 'S22': ' perp. to grain (S22)', 'MISES': ' (Mises)'}[q] if k == 0 else '', 'bold': True}, {'t': lab, 'color': GREY}]
                for c in cases:
                    v = num(r.get(c))
                    cells.append({'t': fnum(v), 'align': 'center', 'bold': True} if c == ref else value_cell(v, num(r.get('dev_%s_vs_%s_%%' % (c, ref)))))
                t.add(cells, h=80 if True else 52)
        t.data = [r for r in rows if r['joint'] == jid]
        t.render(os.path.join(out, 'F2_stress_summary_%s.png' % jid))


def fig_segments(tdir, out, order, ref):
    rows = read(tdir, 'T3_segments_B1B_B2_2B')
    if not rows:
        return
    cases = [ref] + [c for c in order if c != ref and c in rows[0]]
    idx = {(r['joint'], r['part'], r['quantity'], r['stat']): r for r in rows}
    seg_names = {'B1B-43': 'Post stub below (B1B)', 'B2_2B-44': 'Beam stub (B2_2B)', 'B1E-42': 'Post stub above (B1E)'}
    for jid in sorted({r['joint'] for r in rows}):
        t = Table([600, 250] + [210] * len(cases), 'Timber segments next to the joint: %s' % JOINT_NAMES.get(jid, jid),
                  'Stress parallel to grain S11 in the 300 mm stubs that close the joint substructure; reference C first',
                  [NOTE_DEV, 'B2: the stubs belong to its main substructure and are not recoverable (n/a).'])
        t.add([hdr('Segment', align='left'), hdr('Statistic', align='left')] + [hdr(c) for c in cases])
        for part, nm in seg_names.items():
            for k, (st, lab) in enumerate([('max', 'peak tension'), ('min', 'peak compression'), ('p95', '95th percentile'), ('mean', 'mean')]):
                r = idx.get((jid, part, 'S11', st))
                if not r:
                    continue
                cells = [{'t': nm if k == 0 else '', 'bold': True}, {'t': lab, 'color': GREY}]
                for c in cases:
                    v = num(r.get(c))
                    cells.append({'t': fnum(v, 2), 'align': 'center', 'bold': True} if c == ref else value_cell(v, num(r.get('dev_%s_vs_%s_%%' % (c, ref))), 2))
                t.add(cells, h=80)
        t.data = [r for r in rows if r['joint'] == jid]
        t.render(os.path.join(out, 'F3_segments_%s.png' % jid))


# ------------------------------------------------------------------ charts
def nice_ticks(lo, hi, n=5):
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / float(n)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=mag)
    start, end = math.floor(lo / step + 1e-9) * step, math.ceil(hi / step - 1e-9) * step     # ticks must cover [lo, hi]
    ticks, v = [], start
    while v <= end + 1e-9:
        ticks.append(round(v, 10))
        v += step
    return ticks


def panel_axes(d, box, xs_range, ys_range, xlabel, ylabel, title, xticks=None):
    x0, y0, x1, y1 = box
    yt = nice_ticks(*ys_range)
    ymin, ymax = yt[0], yt[-1]
    xt = nice_ticks(*xs_range) if xticks is None else xticks
    xmin, xmax = xs_range

    def X(v):
        return x0 + (v - xmin) / float(xmax - xmin) * (x1 - x0)

    def Y(v):
        return y1 - (v - ymin) / float(ymax - ymin) * (y1 - y0)
    d.text((x0, y0 - 66), title, fill=INK, font=F['head'])
    for v in yt:
        d.line([x0, Y(v), x1, Y(v)], fill='#e3e3e3' if abs(v) > 1e-9 else '#8a8a8a', width=2 if abs(v) <= 1e-9 else 1)
        d.text((x0 - 12, Y(v)), ('%g' % round(v, 6)), fill=GREY, font=F['tick'], anchor='rm')
    for v in xt:
        d.line([X(v), y1, X(v), y1 + 8], fill=GREY)
        d.text((X(v), y1 + 12), '%g' % v, fill=GREY, font=F['tick'], anchor='ma')
    d.rectangle([x0, y0, x1, y1], outline=LINE)
    d.text(((x0 + x1) / 2.0, y1 + 52), xlabel, fill=GREY, font=F['small'], anchor='ma')
    d.text((x0 - 90, y0 - 24), ylabel, fill=GREY, font=F['small'], anchor='ls')
    return X, Y


def fig_series(tdir, out, order, ref):
    rows = read(tdir, 'T5_section_series')
    if not rows:
        return
    cases = [ref] + [c for c in order if c != ref and c in rows[0]]
    cfg = json.load(open(os.path.join(ROOT, 'study', 'regions.json')))
    for jid in sorted({r['joint'] for r in rows}):
        sub = [r for r in rows if r['joint'] == jid]
        plate_end = cfg['series'][jid]['plate_end']
        dirn = cfg['series'][jid]['direction']
        data = {}
        for r in sub:
            if r['stat'] not in ('max', 'p95', 'min'):
                continue
            dist = (num(r['x_mm']) - plate_end) * dirn
            for c in cases:
                data.setdefault((r['stat'], c), []).append((dist, num(r.get(c))))
        W, H = 2400, 940
        im = Image.new('RGB', (W, H), '#ffffff')
        d = ImageDraw.Draw(im)
        d.text((50, 30), 'Stress parallel to grain along the horizontal beam away from the corner plate: %s' % JOINT_NAMES.get(jid, jid), fill=INK, font=F['title'])
        d.text((50, 88), 'Sections every 50 mm, first one 50 mm beyond the end of the steel plate; last section = cut boundary of the B1 joint substructure', fill=GREY, font=F['sub'])
        xs = [p[0] for pts in data.values() for p in pts]
        xr = (min(xs) - 10, max(xs) + 10)
        xt = sorted({p[0] for pts in data.values() for p in pts})[::2]
        boxes = [(170, 270, 770, 740), (930, 270, 1530, 740), (1700, 270, 2300, 740)]
        for stat, box, ttl in (('max', boxes[0], 'Peak tension S11 [MPa]'), ('p95', boxes[1], '95th percentile S11 [MPa]')):
            vals = [p[1] for c in cases for p in data.get((stat, c), []) if p[1] is not None]
            if not vals:
                continue
            X, Y = panel_axes(d, box, xr, (0, max(vals) * 1.08), 'distance from plate end [mm]', '', ttl, xt)
            for c in cases:
                pts = [(X(a), Y(b)) for a, b in data.get((stat, c), []) if b is not None]
                if len(pts) > 1:
                    d.line(pts, fill=CASE_COLORS[c], width=5 if c == ref else 4)
                for p in pts:
                    d.ellipse([p[0] - 6, p[1] - 6, p[0] + 6, p[1] + 6], fill=CASE_COLORS[c])
        # deviation panel
        devs = {}
        for c in cases:
            if c == ref:
                continue
            for a, b in data.get(('max', c), []):
                rv = dict(data[('max', ref)]).get(a)
                if b is not None and rv:
                    devs.setdefault(c, []).append((a, (b - rv) / abs(rv) * 100.0))
        allv = [p[1] for v in devs.values() for p in v] or [0]
        lim = max(10, math.ceil(max(abs(min(allv)), abs(max(allv))) / 5.0) * 5.0)
        X, Y = panel_axes(d, boxes[2], xr, (-lim, lim), 'distance from plate end [mm]', '', 'Deviation of the peak from C [%]', xt)
        for c, pts in devs.items():
            pp = [(X(a), Y(b)) for a, b in pts]
            if len(pp) > 1:
                d.line(pp, fill=CASE_COLORS[c], width=4)
            for p in pp:
                d.ellipse([p[0] - 6, p[1] - 6, p[0] + 6, p[1] + 6], fill=CASE_COLORS[c])
        d.text((170, 880), 'B2: only the part of the beam inside its joint substructure is available (B2A-41); the stub B2_2B-44 belongs to its main substructure.', fill=GREY, font=F['small'])
        lx = 170
        for c in cases:
            d.line([lx, 835, lx + 60, 835], fill=CASE_COLORS[c], width=6)
            d.text((lx + 74, 835), CASE_LABELS.get(c, c), fill=INK, font=F['body'], anchor='lm')
            lx += 500
        im.save(os.path.join(out, 'F4_section_series_%s.png' % jid))
        print('figure', 'F4_section_series_%s.png' % jid)


def fig_deviation_bars(tdir, out, order, ref):
    rows = read(tdir, 'T2_region_stress')
    if not rows:
        return
    cases = [c for c in order if c != ref and c in rows[0]]
    idx = {(r['joint'], r['class'], r['quantity'], r['stat']): r for r in rows}
    cats = [('timber', 'S11', 'max', 'Timber || grain\npeak'), ('timber', 'S11', 'p95', 'Timber || grain\n95th pct'),
            ('timber', 'S22', 'max', 'Timber perp.\npeak'), ('timber', 'S22', 'p95', 'Timber perp.\n95th pct'), ('steel_corner', 'MISES', 'max', 'Corner plate\npeak'),
            ('steel_corner', 'MISES', 'p95', 'Corner plate\n95th pct'), ('steel_inter', 'MISES', 'max', 'Inter-module\nplates peak'),
            ('steel_inter', 'MISES', 'p95', 'Inter-module\nplates 95th pct'), ('dowel', 'MISES', 'max', 'Dowels\npeak'), ('dowel', 'MISES', 'p95', 'Dowels\n95th pct')]
    for jid in sorted({r['joint'] for r in rows}):
        vals = {}
        for c in cases:
            for k, (cls, q, st, _) in enumerate(cats):
                r = idx.get((jid, cls, q, st))
                vals[(c, k)] = num(r.get('dev_%s_vs_%s_%%' % (c, ref))) if r else None
        allv = [v for v in vals.values() if v is not None] or [0]
        lim = max(10, math.ceil(max(abs(min(allv)), abs(max(allv))) / 10.0) * 10.0)
        W, H = 2400, 1000
        im = Image.new('RGB', (W, H), '#ffffff')
        d = ImageDraw.Draw(im)
        d.text((50, 30), 'How far each modelling strategy is from the full model: %s' % JOINT_NAMES.get(jid, jid), fill=INK, font=F['title'])
        d.text((50, 88), 'Deviation of local stresses from C in percent (positive = higher than the full model); bars beyond the axis are clipped', fill=GREY, font=F['sub'])
        box = (170, 200, 2330, 760)
        X, Y = panel_axes(d, box, (0, len(cats)), (-lim, lim), '', 'deviation from C [%]', '', [])
        gw = (box[2] - box[0]) / float(len(cats))
        bw = gw * 0.7 / len(cases)
        for k, (_, _, _, lab) in enumerate(cats):
            gx = box[0] + k * gw
            for i, c in enumerate(cases):
                v = vals.get((c, k))
                x0 = gx + gw * 0.15 + i * bw
                if v is None:
                    d.text((x0 + bw / 2, Y(0) - 10), 'n/a', fill=GREY, font=F['tick'], anchor='ms', )
                    continue
                vc = max(-lim, min(lim, v))
                d.rectangle([x0, min(Y(0), Y(vc)), x0 + bw - 4, max(Y(0), Y(vc))], fill=CASE_COLORS[c])
                ty = Y(vc) - 8 if v >= 0 else Y(vc) + 8
                d.text((x0 + bw / 2 - 2, ty), ('0' if abs(v) < 0.5 else '%+.0f' % v), fill=INK, font=F['tick'], anchor='ms' if v >= 0 else 'ma')
            for li, ln in enumerate(lab.split('\n')):
                d.text((gx + gw / 2, box[3] + 14 + li * 28), ln, fill=INK, font=F['small'], anchor='ma')
        lx = 170
        for c in cases:
            d.rectangle([lx, 880, lx + 40, 910], fill=CASE_COLORS[c])
            d.text((lx + 54, 895), CASE_LABELS.get(c, c), fill=INK, font=F['body'], anchor='lm')
            lx += 560
        im.save(os.path.join(out, 'F5_deviation_bars_%s.png' % jid))
        print('figure', 'F5_deviation_bars_%s.png' % jid)


def fig_nodal_elementwise(tdir, out, order, ref):
    rows = read(tdir, 'T6_nodal_vs_ref')
    if rows:
        t = Table([300, 150, 200, 190, 190, 190, 190, 190, 190], 'Nodal displacements in the joint regions: values of C and of each case',
                  'All nodes of the joint box that coincide (within 0.5 mm) with a node of the full model C; displacement magnitude |U| in mm',
                  ['rms = root mean square over the matched nodes; difference = |U_case - U_C| per node.', 'Relative = rms difference / rms of C.'])
        t.add([hdr('Case', align='left'), hdr('Joint'), hdr('matched nodes'), hdr('C: mean U1'), hdr('case: mean U1'), hdr('C: rms |U|'), hdr('case: rms |U|'), hdr('rms diff.'), hdr('relative')], h=60)
        for r in rows:
            if not num(r.get('n_matched_nodes')):
                continue
            c = r['case']
            rel = num(r.get('rel_rms_diff_%'))
            t.add([{'t': CASE_LABELS.get(c, c).split('  ')[0], 'bold': True}, {'t': r['joint'], 'align': 'center'}, {'t': '%d' % num(r['n_matched_nodes']), 'align': 'center'},
                   {'t': fnum(num(r.get('C_mean_U1_mm')), 1), 'align': 'center', 'bold': True}, {'t': fnum(num(r.get('case_mean_U1_mm')), 1), 'align': 'center'},
                   {'t': fnum(num(r.get('C_rms_U_mm')), 1), 'align': 'center', 'bold': True}, {'t': fnum(num(r.get('case_rms_U_mm')), 1), 'align': 'center'},
                   {'t': fnum(num(r.get('rms_diff_mm')), 2), 'align': 'center'}, {'t': '%.1f %%' % rel if rel is not None else '-', 'align': 'center', 'fill': dev_fill(rel)}])
        t.data = rows
        t.render(os.path.join(out, 'F6_nodal_vs_C.png'))
    rows = read(tdir, 'T7_elementwise_vs_ref')
    if rows:
        t = Table([260, 120, 330, 160, 170, 170, 170, 170, 170, 170], 'Element-by-element stress comparison with C',
                  'Elements matched by centroid; values of C and of the case, difference per element; stress in MPa (timber: S11, steel/dowels: von Mises)',
                  ['Dowels: element-wise differences are sensitive to the ordering of the section points; judge dowels with the statistics in F2.',
                   'Steel plates of B1/B2 are partitioned differently from C, so fewer plate elements can be matched.'])
        t.add([hdr('Case', align='left'), hdr('Joint'), hdr('Part', align='left'), hdr('matched'), hdr('C: rms'), hdr('case: rms'), hdr('C: max'), hdr('case: max'), hdr('rms diff.'), hdr('relative')], h=60)
        for r in rows:
            if not num(r.get('n_matched')):
                continue
            q = 'S11' if r['class'] == 'timber' else 'MISES'
            rel = num(r.get('%s_rel_rmse_%%' % q))
            t.add([{'t': CASE_LABELS.get(r['case'], r['case']).split('  ')[0], 'bold': True}, {'t': r['joint'], 'align': 'center'}, {'t': CLASS_NAMES.get(r['class'], r['class'])},
                   {'t': '%d / %d' % (num(r['n_matched']), num(r['n_elements'])), 'align': 'center'},
                   {'t': fnum(num(r.get('C_%s_rms_MPa' % q))), 'align': 'center', 'bold': True}, {'t': fnum(num(r.get('case_%s_rms_MPa' % q))), 'align': 'center'},
                   {'t': fnum(num(r.get('C_%s_maxabs_MPa' % q))), 'align': 'center', 'bold': True}, {'t': fnum(num(r.get('case_%s_maxabs_MPa' % q))), 'align': 'center'},
                   {'t': fnum(num(r.get('%s_diff_rmse_MPa' % q)), 2), 'align': 'center'}, {'t': '%.0f %%' % rel if rel is not None else '-', 'align': 'center', 'fill': dev_fill(rel)}], h=48)
        t.data = rows
        t.render(os.path.join(out, 'F7_elementwise_vs_C.png'))


def fig_cost(tdir, out, order, ref):
    rows = read(tdir, 'T9_size_time_per_case')
    jobs = read(tdir, 'T8_size_time_per_job')
    if not rows:
        return
    glob = {r['case']: r for r in jobs if r['role'] == 'global'}
    t = Table([360, 190, 200, 210, 210, 230, 230, 220], 'Computational cost and storage',
              'Global analysis (the assembled model) and the one-off generation of the substructures; file sizes include all ODBs, inputs and substructure files',
              ['CPU time = total CPU seconds of the Abaqus job (.dat); wall = elapsed seconds. Substructure generation is paid once and reused for load cases.',
               'Disk: sum of ODB, input, output and substructure files of the case in the project folder.'])
    t.add([hdr('Case', align='left'), hdr('nodes'), hdr('DOFs'), hdr('global CPU [s]'), hdr('global wall [s]'), hdr('substr. gen. CPU [s]'), hdr('substr. gen. wall [s]'), hdr('disk [MB]')], h=70)
    for c in [ref] + [o for o in order if o != ref]:
        r = next((x for x in rows if x['case'] == c), None)
        if not r:
            continue
        t.add([{'t': CASE_LABELS.get(c, c), 'bold': True},
               {'t': '{:,}'.format(int(num(r['global_nodes']) or 0)).replace(',', ' '), 'align': 'center'}, {'t': '{:,}'.format(int(num(r['global_dofs']) or 0)).replace(',', ' '), 'align': 'center'},
               {'t': fnum(num(r['global_cpu_s']), 0), 'align': 'center'}, {'t': fnum(num(r['global_wall_s']), 0), 'align': 'center'},
               {'t': fnum(num(r['gen_cpu_s']), 0) if num(r['gen_cpu_s']) else '-', 'align': 'center'}, {'t': fnum(num(r['gen_wall_s']), 0) if num(r['gen_wall_s']) else '-', 'align': 'center'},
               {'t': fnum(num(r['total_mb']), 0), 'align': 'center'}], h=64)
    t.data = rows + [{}] + jobs
    t.render(os.path.join(out, 'F8_cost_and_storage.png'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='comparison')
    ap.add_argument('--date')
    a = ap.parse_args()
    reg = json.load(open(os.path.join(ROOT, 'study', 'cases.json')))
    order, ref = reg['order'], reg.get('reference', 'C')
    base = os.path.join(ROOT, 'exports', '%s_%s' % (a.date or datetime.date.today().isoformat(), a.tag))
    tdir, out = os.path.join(base, 'tables'), os.path.join(base, 'figures')
    os.makedirs(out, exist_ok=True)
    fig_displacements(tdir, out, order, ref)
    fig_stress_summary(tdir, out, order, ref)
    fig_segments(tdir, out, order, ref)
    fig_series(tdir, out, order, ref)
    fig_deviation_bars(tdir, out, order, ref)
    fig_nodal_elementwise(tdir, out, order, ref)
    fig_cost(tdir, out, order, ref)
    print('wrote', out)


if __name__ == '__main__':
    main()
