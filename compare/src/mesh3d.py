"""Translucent undeformed mesh views of one joint of one case (default D6, J3): python mesh3d.py [--case D6] [--joint J3] [--opacity 0.4]
Writes exports/<date>_J3_images/images/<case>/J3_mesh_*.png and *_legend.png (colour key under the picture)."""
import argparse, csv, datetime, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import snapshot as snap
from PIL import Image, ImageDraw, ImageFont

COLORS = [('B1A-49', '#d9a066'), ('B1B-43', '#8fbf4d'), ('B1E-42', '#4daaa8'), ('B1F-48', '#a67c52'), ('B2A-41', '#e0c97a'),
          ('B2_2B-44', '#c97ac9'), ('STEELPLATE_CORNER', '#3a6fd8'), ('STEELPLATE_INTER-0', '#2bb3e6'), ('STEELPLATE_INTER-1', '#6a4fd0'),
          ('DWL_M14', '#e03030'), ('DWL_M16', '#ff8c1a')]
LABELS = {'B1A-49': 'timber B1A', 'B1B-43': 'timber B1B', 'B1E-42': 'timber B1E', 'B1F-48': 'timber B1F', 'B2A-41': 'timber B2A',
          'B2_2B-44': 'timber B2_2B', 'STEELPLATE_CORNER': 'steel plate (corner)', 'STEELPLATE_INTER-0': 'inter-module plate 0',
          'STEELPLATE_INTER-1': 'inter-module plate 1', 'DWL_M14': 'dowels M14', 'DWL_M16': 'dowels M16'}

ap = argparse.ArgumentParser()
ap.add_argument('--case', default='D6')
ap.add_argument('--joint', default='J3')
ap.add_argument('--opacity', type=float, default=0.4, help='1 = opaque; 0.4 = 60 %% transparent')
ap.add_argument('--date', default=datetime.date.today().isoformat())
ap.add_argument('--no-render', action='store_true', help='only rebuild the legend strips')
a = ap.parse_args()
rid = snap.latest_run(a.case)['run_id']
rd = snap.run_dir(a.case, rid)
elem = os.path.join(rd, 'extract', 'elem_stress.csv')
rows = [r for r in csv.DictReader(open(elem)) if r['joint'] == a.joint]
odbs = {r['odb'] for r in rows}
assert len(odbs) == 1, odbs
odb = os.path.join(rd, 'odb', odbs.pop())
ext = [[1e9] * 3, [-1e9] * 3]
for r in rows:
    for k, key in enumerate('xyz'):
        ext[0][k] = min(ext[0][k], float(r[key])); ext[1][k] = max(ext[1][k], float(r[key]))
d = [b - c for c, b in zip(*ext)]
out = os.path.join(ROOT, 'exports', '%s_J3_images' % a.date, 'images', a.case)
cfg = {'elem_csv': elem.replace('\\', '/'), 'odb': odb.replace('\\', '/'), 'joint': a.joint, 'out_dir': out.replace('\\', '/'),
       'size_px': [2400, 2000], 'colors': COLORS, 'opacity': a.opacity,
       'center': [(c + b) / 2.0 for c, b in zip(*ext)], 'view_height_mm': round(max(d[0], d[2]) * 1.25 + 80, 0),
       'views': [{'name': 'front', 'view_vector': [0, 1, 0]}, {'name': 'rot3d', 'view_vector': [0.85, 1.0, -0.55]}]}
cp = os.path.join(rd, 'mesh3d_config.json')
json.dump(cfg, open(cp, 'w'), indent=1)
os.makedirs(out, exist_ok=True)
if not a.no_render:
    script = os.path.join(HERE, 'abq', 'render_mesh3d.py')
    subprocess.run('cmd /c "call "C:\\SIMULIA\\Commands\\abaqus.bat" cae noGUI="%s" -- "%s""' % (script, cp), cwd=ROOT, stdin=subprocess.DEVNULL)
try:
    f = ImageFont.truetype('arial.ttf', 44)
except OSError:
    f = ImageFont.load_default()
for v in ('front', 'rot3d'):
    p = os.path.join(out, 'J3_mesh_%s.png' % v)
    if not os.path.isfile(p):
        continue
    im = Image.open(p).convert('RGB')
    cols = 4
    rows_n = -(-len(COLORS) // cols)
    W, H = im.size
    canvas = Image.new('RGB', (W, H + rows_n * 70 + 80), (255, 255, 255))
    canvas.paste(im, (0, 0))
    dr = ImageDraw.Draw(canvas)
    dr.text((20, H + 10), '%s | %s | undeformed, mesh, %d%% transparent' % (a.case, a.joint, round((1 - a.opacity) * 100)), fill=(20, 20, 20), font=f)
    for i, (k, c) in enumerate(COLORS):
        x, y = 20 + (i % cols) * (W // cols), H + 80 + (i // cols) * 70
        dr.rectangle([x, y, x + 50, y + 50], fill=c, outline=(60, 60, 60))
        dr.text((x + 65, y + 2), LABELS[k], fill=(30, 30, 30), font=f)
    canvas.save(os.path.join(out, 'J3_mesh_%s_legend.png' % v))
print('done', out)
