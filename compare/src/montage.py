"""Assemble the rendered contour layers into per-case images and side-by-side montages with a shared legend.

  python montage.py [--tag mytag] [--cases A B1 B2 C]

Inputs : store/<case>/<run>/images/<joint>_<group>_<view>_<case>__<odb>.png  (from render_contours.py)
Outputs: exports/<date>_<tag>/images/<case>/<joint>_<group>_<view>.png        (all ODB layers of one case overlaid)
         exports/<date>_<tag>/images/montage_<joint>_<group>_<view>.png        (cases side by side + legend)
Needs only Pillow.
"""
import argparse, collections, datetime, glob, json, os, re, sys

from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import snapshot as snap


def font(size, bold=False):
    for name in (('arialbd.ttf' if bold else 'arial.ttf'), 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def nonwhite_mask(im, thr=10):
    diff = ImageChops.difference(im.convert('RGB'), Image.new('RGB', im.size, (255, 255, 255))).convert('L')
    return diff.point(lambda v: 255 if v > thr else 0)


def composite(paths):
    """overlay layers: every non-white pixel of a later layer replaces the earlier pixel"""
    base = None
    for p in paths:
        im = Image.open(p).convert('RGB')
        if base is None:
            base = Image.new('RGB', im.size, (255, 255, 255))
        base.paste(im, mask=nonwhite_mask(im))
    return base


def hex2rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def draw_legend(draw, x, y, w, colors, lo, hi, label, below, above, f_small, f_label, k=1.0):
    n = len(colors)
    sq = int(26 * k)
    sw = w / float(n)
    for i, c in enumerate(colors):
        draw.rectangle([x + i * sw, y, x + (i + 1) * sw, y + sq], fill=hex2rgb(c), outline=(60, 60, 60))
    for i in range(0, n + 1, max(1, n // 4)):
        v = lo + (hi - lo) * i / float(n)
        draw.line([x + i * sw, y + sq, x + i * sw, y + sq + int(6 * k)], fill=(60, 60, 60))
        draw.text((x + i * sw, y + sq + int(8 * k)), ('%g' % v), fill=(30, 30, 30), font=f_small, anchor='ma')
    draw.text((x, y - int(8 * k)), label, fill=(20, 20, 20), font=f_label, anchor='lb')
    bx = x + w + int(24 * k)
    draw.rectangle([bx, y, bx + sq, y + sq], fill=hex2rgb(below), outline=(60, 60, 60))
    draw.text((bx + sq + int(6 * k), y + sq / 2), '< %g' % lo, fill=(30, 30, 30), font=f_small, anchor='lm')
    draw.rectangle([bx + int(110 * k), y, bx + int(110 * k) + sq, y + sq], fill=hex2rgb(above), outline=(60, 60, 60))
    draw.text((bx + int(110 * k) + sq + int(6 * k), y + sq / 2), '> %g' % hi, fill=(30, 30, 30), font=f_small, anchor='lm')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='comparison')
    ap.add_argument('--cases', nargs='*')
    ap.add_argument('--panel', type=int, default=1000, help='panel width in px (4 panels -> montage > 4000 px wide)')
    a = ap.parse_args()
    reg = snap.load_registry()
    render = json.load(open(os.path.join(ROOT, 'study', 'render.json')))
    cases = a.cases or reg['order']
    runs = {}
    for c in cases:
        row = snap.latest_run(c)
        if row and glob.glob(os.path.join(snap.STORE, c, row['run_id'], 'images', '*.png')):
            runs[c] = row['run_id']
    out_dir = os.path.join(ROOT, 'exports', '%s_%s' % (datetime.date.today().isoformat(), a.tag), 'images')
    os.makedirs(out_dir, exist_ok=True)

    # (joint, group, view) -> {case: [layer paths]}
    items = collections.defaultdict(dict)
    for c, rid in runs.items():
        for p in sorted(glob.glob(os.path.join(snap.STORE, c, rid, 'images', '*.png'))):
            m = re.match(r'^(J\d+|GLOBAL)_([a-z0-9]+)_([A-Za-z0-9]+)_%s__' % re.escape(c), os.path.basename(p))
            if m:
                items[m.groups()].setdefault(c, []).append(p)

    k = a.panel / 640.0
    f_h, f_s, f_t = font(int(30 * k), True), font(int(20 * k)), font(int(24 * k))
    for (joint, group, view), per_case in sorted(items.items()):
        comp = {c: composite(paths) for c, paths in per_case.items()}
        # one common crop box (union of the non-white areas of all cases) so panels are directly comparable
        box = None
        for im in comp.values():
            b = nonwhite_mask(im).getbbox()
            if b:
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        if box is None:
            continue
        pad = 30
        sz = next(iter(comp.values())).size
        pad = int(pad * sz[0] / 1200.0)
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(sz[0], box[2] + pad), min(sz[1], box[3] + pad))
        for c, im in comp.items():
            os.makedirs(os.path.join(out_dir, c), exist_ok=True)
            im.crop(box).save(os.path.join(out_dir, c, '%s_%s_%s.png' % (joint, group, view)))
        var = render['groups'][group]['variable']
        lo, hi = render['limits'][var]
        try:
            auto = json.load(open(os.path.join(ROOT, 'study', 'limits_auto.json')))
            lo, hi = auto.get(group, {}).get(joint, [lo, hi])
        except (IOError, OSError, ValueError):
            pass
        pw = a.panel
        ph = int(pw * (box[3] - box[1]) / float(box[2] - box[0]))
        n = len(cases)
        head, foot, gap = int(90 * k), int(150 * k), int(20 * k)
        W, H = n * pw + (n + 1) * gap, head + ph + foot
        canvas = Image.new('RGB', (W, H), (255, 255, 255))
        d = ImageDraw.Draw(canvas)
        d.text((gap, int(12 * k)), '%s  |  %s  |  %s view' % (reg_label(reg, joint), group, view), fill=(20, 20, 20), font=f_t)
        for i, c in enumerate(cases):
            x0 = gap + i * (pw + gap)
            d.text((x0 + pw / 2, head - int(8 * k)), reg['cases'][c]['label'], fill=(20, 20, 20), font=f_h, anchor='ms')
            if c in comp:
                canvas.paste(comp[c].crop(box).resize((pw, ph), Image.LANCZOS), (x0, head))
                d.rectangle([x0, head, x0 + pw, head + ph], outline=(200, 200, 200))
            else:
                d.rectangle([x0, head, x0 + pw, head + ph], outline=(200, 200, 200))
                import textwrap
                msg = 'not available: %s' % reg['cases'][c].get('status_note', 'not solved / not extracted')
                lines = textwrap.wrap(msg, width=max(10, int(pw / (11 * k))))
                for li, line in enumerate(lines):
                    d.text((x0 + pw / 2, head + ph / 2 + (li - len(lines) / 2.0) * int(26 * k)), line, fill=(130, 130, 130), font=f_s, anchor='mm')
        draw_legend(d, gap, head + ph + int(50 * k), int(min(900, 2000 / 1.0) * k * 0.9), render['spectra'][var], lo, hi, render['units'][var],
                    render['outside'][var][0], render['outside'][var][1], f_s, f_s, k)
        d.text((gap, head + ph + int(112 * k)), 'Free edges only, deformed shape x%g, last frame of the wind step, identical camera and colour limits. Runs: %s' % (
            render['deform_scale'], ', '.join('%s=%s' % (c, runs[c]) for c in cases if c in runs)), fill=(90, 90, 90), font=f_s)
        canvas.save(os.path.join(out_dir, 'montage_%s_%s_%s.png' % (joint, group, view)))
        print('montage', joint, group, view, [c for c in cases if c in comp])
    print('wrote', out_dir)


def reg_label(reg, joint):
    if joint == 'GLOBAL':
        return 'Global structure (GLM timber only; B1/B2 main beams from the back-calculated substructures)'
    try:
        with open(os.path.join(ROOT, 'study', 'regions.json')) as f:
            return json.load(f)['joints'][joint]['label']
    except Exception:
        return joint


if __name__ == '__main__':
    main()
