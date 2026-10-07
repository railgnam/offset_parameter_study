"""F9 -- the study's payoff figure: joint-region error versus boundary offset.

Reads the comparison tables the normal pipeline produces and plots the deviation from the reference
against the offset t, so "how far out must the coupling boundary sit" is answered by a curve rather
than two points. Pillow only, reusing compare/src/figures.py for the axes and fonts.

  python trend.py [--tag zone_offset_c25]

The reference and the cases come from compare/study/cases.json: the curve is the D0..D6 ladder from
params.csv (one generator, one wind-only global template, one coupling convention), and any coupling
variant (D3K) is drawn as a separate marker at its base rung's offset.
"""
import argparse
import csv
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ZONE = os.path.dirname(HERE)
CSRC = os.path.join(ZONE, 'compare', 'src')
sys.path.insert(0, CSRC)

from PIL import Image, ImageDraw                                           # noqa: E402
from figures import CASE_COLORS, GREY, INK, JOINT_NAMES, LINE, F, num, panel_axes  # noqa: E402

EXPORTS = os.path.join(ZONE, 'compare', 'exports')
PARAMS = os.path.join(ZONE, 'params.csv')
REGISTRY = os.path.join(ZONE, 'compare', 'study', 'cases.json')
STAT_COLORS = {'max': '#c0392b', 'p95': '#d95f02', 'mean': '#1b9e77'}
STAT_LABELS = {'max': 'peak', 'p95': '95th percentile', 'mean': 'mean'}
PANELS = [('timber', 'S11', 'Timber, stress parallel to grain'),
          ('dowel', 'MISES', 'Dowels, von Mises')]


def ladder():
    with open(PARAMS, newline='', encoding='utf8') as fh:
        return {r['case'].strip(): float(r['offset_mm']) for r in csv.DictReader(fh)
                if r['case'].strip() and r['role'].strip() == 'test'}


def read_table(tdir, name):
    p = os.path.join(tdir, name + '.csv')
    if not os.path.exists(p):
        return []
    with open(p, newline='', encoding='utf8') as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='zone_offset_c25')
    a = ap.parse_args()
    cand = sorted(glob.glob(os.path.join(EXPORTS, '*_%s' % a.tag)))
    if not cand:
        raise SystemExit('no export directory *_%s under %s -- run the comparison first'
                         % (a.tag, EXPORTS))
    tdir = os.path.join(cand[-1], 'tables')
    rows = read_table(tdir, 'T2_region_stress')
    if not rows:
        raise SystemExit('T2_region_stress.csv is missing from %s' % tdir)

    reg = json.load(open(REGISTRY, encoding='utf8'))
    ref = reg['reference']
    ref_job = reg['cases'][ref]['jobs']['global']
    suffix = '_vs_%s_%%' % ref
    devcols = {c[len('dev_'):-len(suffix)]: c for c in rows[0]
               if c.startswith('dev_') and c.endswith(suffix)}
    off = ladder()
    curve = sorted([c for c in devcols if c in off], key=lambda c: off[c])
    variants = [(c, e['variant_of'], e.get('coupling', '')) for c, e in reg['cases'].items()
                if e.get('variant_of') in off and c in devcols]
    if not curve:
        raise SystemExit('none of the ladder cases are in the comparison yet')

    def value(jid, cls, qty, stat, case):
        hit = [r for r in rows if r['joint'] == jid and r['class'] == cls
               and r['quantity'] == qty and r['stat'] == stat]
        return num(hit[0].get(devcols[case])) if hit else None

    for jid in sorted({r['joint'] for r in rows}):
        W, H = 2400, 1000
        im = Image.new('RGB', (W, H), '#ffffff')
        d = ImageDraw.Draw(im)
        d.text((50, 30), 'Joint-region error vs the full model as the boundary moves out: %s'
               % JOINT_NAMES.get(jid, jid), fill=INK, font=F['title'])
        d.text((50, 88), 'Offset t = timber kept inside the joint substructure beyond the corner '
                         'block. D0 = B2 partition, D6 = B1 partition; every rung wind-only, '
                         'distributing mid-joint interfaces.',
               fill=GREY, font=F['sub'])

        boxes = [(180, 290, 1080, 730), (1400, 290, 2300, 730)]
        for (cls, qty, ttl), box in zip(PANELS, boxes):
            series = {}
            for stat in ('max', 'p95', 'mean'):
                pts = [(off[c], value(jid, cls, qty, stat, c)) for c in curve]
                pts = [p for p in pts if p[1] is not None]
                if pts:
                    series[stat] = pts
            if not series:
                continue
            vv = [value(jid, cls, qty, s, v) for v, _, _ in variants for s in series]
            allv = [p[1] for v in series.values() for p in v] + [x for x in vv if x is not None]
            lim = max(5, math.ceil(max(abs(min(allv)), abs(max(allv))) / 5.0) * 5.0)
            X, Y = panel_axes(d, box, (-15, 315), (-lim, lim), 'offset t [mm]', '',
                              '%s -- deviation from %s [%%]' % (ttl, ref),
                              [off[c] for c in curve])
            d.line([X(-15), Y(0), X(315), Y(0)], fill=LINE, width=2)
            for stat, pts in series.items():
                pp = [(X(x), Y(y)) for x, y in pts]
                if len(pp) > 1:
                    d.line(pp, fill=STAT_COLORS[stat], width=5)
                for p in pp:
                    d.ellipse([p[0] - 7, p[1] - 7, p[0] + 7, p[1] + 7], fill=STAT_COLORS[stat])
            # coupling variants: hollow diamond in the stat's colour, at the base rung's offset
            for v, base, _ in variants:
                for stat in series:
                    y = value(jid, cls, qty, stat, v)
                    if y is None:
                        continue
                    cx, cy = X(off[base]) + 16, Y(y)
                    d.polygon([(cx, cy - 11), (cx + 11, cy), (cx, cy + 11), (cx - 11, cy)],
                              outline=STAT_COLORS[stat], width=4)

        lx = 180
        for stat in ('max', 'p95', 'mean'):
            d.line([lx, 840, lx + 60, 840], fill=STAT_COLORS[stat], width=6)
            d.text((lx + 74, 840), STAT_LABELS[stat], fill=INK, font=F['body'], anchor='lm')
            lx += 260
        for v, base, coupling in variants:
            cx, cy = lx + 10, 840
            d.polygon([(cx, cy - 11), (cx + 11, cy), (cx, cy + 11), (cx - 11, cy)],
                      outline=INK, width=4)
            d.text((lx + 34, 840), '%s = %s with %s interfaces' % (v, base, coupling),
                   fill=INK, font=F['body'], anchor='lm')
            lx += 560
        d.text((180, 895), 'Reference %s = job %s: the full model with EMB-TIMBER influence radius '
                           '25, as in every substructure case.' % (ref, ref_job),
               fill=GREY, font=F['small'])
        d.text((180, 935), 'Judge with the 95th percentile and the mean: peaks next to the dowel '
                           'holes are mesh-sensitive (compare/GENERIC_WORKFLOW.md, rule 2). '
                           'Source: %s' % os.path.basename(cand[-1]),
               fill=GREY, font=F['small'])
        out = os.path.join(cand[-1], 'figures')
        os.makedirs(out, exist_ok=True)
        im.save(os.path.join(out, 'F9_zone_offset_%s.png' % jid))
        print('figure F9_zone_offset_%s.png' % jid)

    # the same numbers as a table, for the write-up
    cw = os.path.join(tdir, 'T10_zone_offset_trend.csv')
    with open(cw, 'w', newline='', encoding='utf8') as fh:
        w = csv.writer(fh)
        w.writerow(['joint', 'class', 'quantity', 'stat', 'case', 'offset_mm', 'coupling',
                    'dev_vs_%s_%%' % ref])
        cases = [(c, off[c], 'distributing') for c in curve] + \
                [(v, off[b], cp) for v, b, cp in variants]
        for r in rows:
            for c, t, cp in cases:
                v = num(r.get(devcols[c]))
                if v is not None:
                    w.writerow([r['joint'], r['class'], r['quantity'], r['stat'], c, '%g' % t, cp,
                                '%g' % v])
    print('table', os.path.basename(cw))


if __name__ == '__main__':
    main()
