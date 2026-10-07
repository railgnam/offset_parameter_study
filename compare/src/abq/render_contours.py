# abaqus cae noGUI=render_contours.py -- <render_config.json>
#
# Contour images of the joint regions, one PNG per (ODB, joint, group, view), always with
#   * identical orthographic camera per joint (so layers from several ODBs overlay pixel-exactly),
#   * fixed colour limits and a fixed 12-colour spectrum (legend is added later by montage.py),
#   * free edges only, deformed shape scaled by cfg['deform_scale'].
# The element selection comes from the retained elem_stress.csv (same elements as the tables).
#
# render_config.json = {"case","step","regions","elem_csv","out_dir","deform_scale","size_px",
#                       "odbs":[{"path","kind"}], "groups":{name:{"classes":[..],"variable":"S11"|"MISES"}},
#                       "limits":{"S11":[-20,20],"MISES":[0,350]}, "views":[{"name","kind":"front"|"cut","normal","origin"}],
#                       "spectra":{"S11":[12 hex colours],"MISES":[12 hex colours]}, "joints":["J3","J6"]}
import sys, os, json, csv, collections
from abaqus import *
from abaqusConstants import *
import visualization


def get_dgo():
    # the display-group toolset is registered in sys.modules once an ODB has been displayed (not at start-up in noGUI)
    if 'displayGroupOdbToolset' not in sys.modules:
        __import__('displayGroupOdbToolset')
    return sys.modules['displayGroupOdbToolset']


cfg = json.load(open(sys.argv[-1]))
reg = json.load(open(cfg['regions']))
out_dir = cfg['out_dir']
if not os.path.isdir(out_dir):
    os.makedirs(out_dir)
LOG = open(os.path.join(out_dir, 'render_log.txt'), 'w')


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


# element labels per (odb file, joint, class, instance) from the retained CSV
sel = collections.defaultdict(lambda: collections.defaultdict(set))
with open(cfg['elem_csv']) as f:
    for r in csv.DictReader(f):
        sel[(r['odb'], r['joint'], r['class'])][r['instance']].add(int(r['element']))

for name, colors in cfg['spectra'].items():
    session.Spectrum(name='spec_' + name, colors=tuple(colors))

session.printOptions.setValues(rendition=COLOR, vpDecorations=OFF, vpBackground=OFF)
session.pngOptions.setValues(imageSize=tuple(cfg['size_px']))
vp = session.viewports['Viewport: 1']
vp.setValues(width=200, height=200 * cfg['size_px'][1] / float(cfg['size_px'][0]))
vp.viewportAnnotationOptions.setValues(legend=OFF, title=OFF, state=OFF, compass=OFF, triad=OFF)

cut_counter = [0]
cam_h = cfg.get('view_height_mm', 1600.0)
cam_w = cam_h * cfg['size_px'][0] / float(cfg['size_px'][1])

for od_cfg in cfg['odbs']:
    path = od_cfg['path']
    obase = os.path.basename(path)
    joints_here = [j for j in cfg['joints'] if any(k[0] == obase and k[1] == j for k in sel)]
    if not joints_here and not cfg.get('global_views'):
        log('skip', obase, '(no elements in joint boxes)')
        continue
    odb = session.openOdb(name=path, readOnly=True)
    stepname = ('BC-' + cfg['step']) if od_cfg['kind'] == 'backcalc' else cfg['step']
    if stepname not in odb.steps.keys() or len(odb.steps[stepname].frames) == 0:
        log('skip', obase, 'no frames in step')
        odb.close()
        continue
    vp.setValues(displayedObject=odb)
    od = vp.odbDisplay
    dgo = get_dgo()
    step_idx = list(odb.steps.keys()).index(stepname)
    od.setFrame(step=step_idx, frame=len(odb.steps[stepname].frames) - 1)
    od.display.setValues(plotState=(CONTOURS_ON_DEF,))
    od.commonOptions.setValues(visibleEdges=FREE, deformationScaling=UNIFORM, uniformScaleFactor=cfg['deform_scale'])
    try:
        od.basicOptions.setValues(renderBeamProfiles=ON)
    except Exception as ex:
        log('beam profiles', ex)
    for jid in joints_here:
        box = (reg['joints'][jid]['box_min'], reg['joints'][jid]['box_max'])
        center = [(box[0][k] + box[1][k]) / 2.0 + cfg.get('camera_shift', {}).get(jid, [0, 0, 0])[k] for k in range(3)]
        for gname, g in cfg['groups'].items():
            if cfg.get('only_groups') and gname not in cfg['only_groups']:
                continue
            if g.get('global_only'):
                continue
            leaves = []
            for cls in g['classes']:
                for inst, labs in sel.get((obase, jid, cls), {}).items():
                    leaves.append(dgo.LeafFromElementLabels(partInstanceName=inst, elementLabels=ranges(labs)))
            if not leaves:
                continue
            od.displayGroup.replace(leaf=leaves[0])
            for lf in leaves[1:]:
                od.displayGroup.add(leaf=lf)
            var = g['variable']
            lo, hi = cfg.get('limits_by_joint', {}).get(gname, {}).get(jid, cfg['limits'][var])
            log('limits', jid, gname, lo, hi)
            if var == 'MISES':
                od.setPrimaryVariable(variableLabel='S', outputPosition=INTEGRATION_POINT, refinement=(INVARIANT, 'Mises'))
            else:
                od.setPrimaryVariable(variableLabel='S', outputPosition=INTEGRATION_POINT, refinement=(COMPONENT, var))
            od.contourOptions.setValues(spectrum='spec_' + var, numIntervals=len(cfg['spectra'][var]), intervalType=UNIFORM,
                                        maxAutoCompute=OFF, maxValue=hi, minAutoCompute=OFF, minValue=lo,
                                        outsideLimitsMode=SPECIFY, outsideLimitsAboveColor=cfg['outside'][var][1],
                                        outsideLimitsBelowColor=cfg['outside'][var][0])
            gframe = cfg.get('framing', {}).get(jid, {}).get(gname)
            for v in cfg['views']:
                if gname not in v.get('groups', list(cfg['groups'])):
                    continue
                if v['kind'] == 'cut':
                    # a fresh, uniquely named cut for every image: names are session-wide, so re-using a name across ODBs/groups
                    # silently kept an earlier cut definition (A, which spans two ODBs, got the wrong plane)
                    cut_counter[0] += 1
                    cname = 'cut%03d' % cut_counter[0]
                    vcut = od.ViewCut(name=cname, shape=PLANE, origin=tuple(v['origin']), normal=tuple(v['normal']), axis2=tuple(v.get('axis2', (1, 0, 0))), csysName='',
                                      followDeformation=OFF, overrideAveraging=OFF, referenceFrame=LAST_FRAME)
                    # Abaqus puts a new plane at the CENTRE of the displayed model whatever the origin is (position is auto-set):
                    # force the plane through the requested origin by setting the offset along the normal to zero
                    vcut.setValues(position=0.0)
                    od.setValues(viewCut=ON, viewCutNames=(cname,))
                    log('cut', cname, v['name'], v['origin'], v['normal'], 'position', vcut.position, 'range', vcut.cutRange, 'in', obase, jid, gname)
                else:
                    od.setValues(viewCut=OFF)
                view_vec = v.get('view_vector', (0, 1, 0))
                tgt = tuple(gframe['center']) if gframe else tuple(center)
                pos = tuple(tgt[k] - 4000.0 * view_vec[k] for k in range(3))
                vp.view.setValues(cameraPosition=pos, cameraTarget=tgt, cameraUpVector=tuple(v.get('up', (0, 0, 1))))
                vp.view.setProjection(projection=PARALLEL)           # orthographic: no perspective distortion in any view
                vh = gframe['height'] if gframe else v.get('view_height_mm', cam_h)
                vp.view.setValues(width=vh * cam_w / cam_h, height=vh, nearPlane=2500.0, farPlane=6000.0)
                log('projection', vp.view.projection)
                fn = os.path.join(out_dir, '%s_%s_%s_%s__%s.png' % (jid, gname, v['name'], cfg['case'], obase.replace('.odb', '')))
                try:
                    session.printToFile(fileName=fn, format=PNG, canvasObjects=(vp,))
                    log('wrote', fn)
                except Exception as ex:
                    log('FAILED', fn, ex)
            od.setValues(viewCut=OFF)
    # ---------------- global views: all GLM (timber) elements of the ODB, no joint boxes ----------------
    for gv in cfg.get('global_views', []):
        g = cfg['groups'][gv['group']]
        if cfg.get('only_groups') and gv['group'] not in cfg['only_groups']:
            continue
        var = g['variable']
        sets = []
        for iname, inst in odb.rootAssembly.instances.items():
            for sname in inst.elementSets.keys():
                up = sname.upper()
                if up == 'MAT-GLM' or up.endswith('_MAT-GLM'):
                    sets.append('%s.%s' % (iname, sname))
        if od_cfg['kind'] == 'backcalc':       # no sets in back-calculated ODBs: the whole instance is timber (main substructure)
            leaves = [dgo.LeafFromPartInstance(partInstanceName=(iname,)) for iname in odb.rootAssembly.instances.keys()]
        else:
            if not sets:
                log('no GLM sets in', obase)
                continue
            leaves = [dgo.LeafFromElementSets(elementSets=(sn,)) for sn in sets]
        od.displayGroup.replace(leaf=leaves[0])
        for lf in leaves[1:]:
            od.displayGroup.add(leaf=lf)
        lo, hi = cfg['limits'][var]
        if var == 'U1':
            od.setPrimaryVariable(variableLabel='U', outputPosition=NODAL, refinement=(COMPONENT, 'U1'))
        else:
            od.setPrimaryVariable(variableLabel='S', outputPosition=INTEGRATION_POINT, refinement=(COMPONENT, var))
        od.contourOptions.setValues(spectrum='spec_' + var, numIntervals=len(cfg['spectra'][var]), intervalType=UNIFORM,
                                    maxAutoCompute=OFF, maxValue=hi, minAutoCompute=OFF, minValue=lo, outsideLimitsMode=SPECIFY,
                                    outsideLimitsAboveColor=cfg['outside'][var][1], outsideLimitsBelowColor=cfg['outside'][var][0])
        od.commonOptions.setValues(deformationScaling=UNIFORM, uniformScaleFactor=gv.get('deform_scale', cfg['deform_scale']))
        od.setValues(viewCut=OFF)
        view_vec = gv.get('view_vector', (0, 1, 0))
        tgt = tuple(gv['center'])
        vp.view.setValues(cameraPosition=tuple(tgt[k] - 8000.0 * view_vec[k] for k in range(3)), cameraTarget=tgt, cameraUpVector=tuple(gv.get('up', (0, 0, 1))))
        vp.view.setProjection(projection=PARALLEL)
        vh = gv['view_height_mm']
        vp.view.setValues(width=vh * cam_w / cam_h, height=vh, nearPlane=4000.0, farPlane=14000.0)
        fn = os.path.join(out_dir, 'GLOBAL_%s_%s_%s__%s.png' % (gv['group'], gv['name'], cfg['case'], obase.replace('.odb', '')))
        try:
            session.printToFile(fileName=fn, format=PNG, canvasObjects=(vp,))
            log('wrote', fn)
        except Exception as ex:
            log('FAILED', fn, ex)
    odb.close()
log('done')
LOG.close()
