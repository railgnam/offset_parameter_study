# abaqus cae noGUI=render_mesh3d.py -- <mesh3d_config.json>
# Undeformed, translucent mesh views of one joint (all parts, one colour per part/section) from the element selection in elem_stress.csv.
import sys, os, json, csv, collections
from abaqus import *
from abaqusConstants import *
import visualization

cfg = json.load(open(sys.argv[-1]))
out_dir = cfg['out_dir']
if not os.path.isdir(out_dir):
    os.makedirs(out_dir)
LOG = open(os.path.join(out_dir, 'mesh3d_log.txt'), 'w')


def log(*a):
    LOG.write(' '.join(str(x) for x in a) + '\n')
    LOG.flush()


def ranges(labels):
    labels = sorted(set(int(v) for v in labels))
    out, i = [], 0
    while i < len(labels):
        j = i
        while j + 1 < len(labels) and labels[j + 1] == labels[j] + 1:
            j += 1
        out.append(str(labels[i]) if i == j else '%d:%d' % (labels[i], labels[j]))
        i = j + 1
    return tuple(out)


sel = collections.defaultdict(set)      # instance -> element labels of the joint in this ODB
with open(cfg['elem_csv']) as f:
    for r in csv.DictReader(f):
        if r['joint'] == cfg['joint'] and r['odb'] == os.path.basename(cfg['odb']):
            sel[r['instance']].add(int(r['element']))

session.printOptions.setValues(rendition=COLOR, vpDecorations=OFF, vpBackground=OFF)
session.pngOptions.setValues(imageSize=tuple(cfg['size_px']))
vp = session.viewports['Viewport: 1']
vp.setValues(width=200, height=200 * cfg['size_px'][1] / float(cfg['size_px'][0]))
vp.viewportAnnotationOptions.setValues(legend=OFF, title=OFF, state=OFF, compass=OFF, triad=OFF)

odb = session.openOdb(name=cfg['odb'], readOnly=True)
vp.setValues(displayedObject=odb)
od = vp.odbDisplay
if 'displayGroupOdbToolset' not in sys.modules:
    __import__('displayGroupOdbToolset')
dgo = sys.modules['displayGroupOdbToolset']
od.display.setValues(plotState=(UNDEFORMED,))
od.commonOptions.setValues(visibleEdges=ALL, edgeLineThickness=VERY_THIN, edgeColorWireHide='#707070', edgeColorFillShade='#707070')
leaves = [dgo.LeafFromElementLabels(partInstanceName=i, elementLabels=ranges(l)) for i, l in sel.items()]
od.displayGroup.replace(leaf=leaves[0])
for lf in leaves[1:]:
    od.displayGroup.add(leaf=lf)

cm = vp.colorMappings['Section']
vp.setColor(colorMapping=cm)
ov = {}
for sname in odb.sections.keys():
    for key, col in cfg['colors']:
        if key in sname:
            ov[sname] = (True, col, 'Default')
            break
cm.updateOverrides(overrides=ov)
log('section overrides', len(ov), 'of', len(odb.sections.keys()), list(odb.sections.keys())[-6:])
od.commonOptions.setValues(translucency=ON, translucencyFactor=cfg['opacity'])
log('translucency', od.commonOptions.translucency, od.commonOptions.translucencyFactor)

tgt = tuple(cfg['center'])
cam_h = cfg['view_height_mm']
cam_w = cam_h * cfg['size_px'][0] / float(cfg['size_px'][1])
for v in cfg['views']:
    vv = v['view_vector']
    vp.view.setValues(cameraPosition=tuple(tgt[k] - 4000.0 * vv[k] for k in range(3)), cameraTarget=tgt, cameraUpVector=(0, 0, 1))
    vp.view.setProjection(projection=PARALLEL)
    vp.view.setValues(width=cam_w, height=cam_h, nearPlane=1500.0, farPlane=9000.0)
    fn = os.path.join(out_dir, 'J3_mesh_%s.png' % v['name'])
    session.printToFile(fileName=fn, format=PNG, canvasObjects=(vp,))
    log('wrote', fn)
odb.close()
log('done')
LOG.close()
