# abaqus python extract_case.py <job_config.json>
#
# Read-only extraction of one case into tidy CSVs (see GENERIC_WORKFLOW.md for the schema).
#   job_config.json = {"case": "B1", "step": "Step-2-WIND", "regions": ".../regions.json", "out_dir": "...",
#                      "odbs": [{"path": "...odb", "kind": "global|recovery|full"}, ...]}
# Outputs in out_dir:
#   elem_stress.csv  one row per (element, integration point[, section point]) inside the joint boxes
#   nodal.csv        U/UR of every node in the joint boxes (global ODB: all its nodes)
#   probes.csv       U/UR at the nodes of the named probe node sets (reference model only)
#   extract_meta.json counts, coverage, warnings
# Regions are global-coordinate boxes defined on C; part names come from the instance name (full model) or from the
# element sets '<part>_MAT-GLM' / '<part>_S235' / 'DWL_*__PICKEDSET*' (recovery ODBs, flattened into PART-1-1).
import sys, os, re, csv, json
import numpy as np
from odbAccess import openOdb

SUFFIX = re.compile(r'(-(LIN|RAD)-\d+(-\d+)*)+$', re.I)
STRESS_COLS = ['S11', 'S22', 'S33', 'S12', 'S13', 'S23']


def classify(part, classes):
    for cls, pat in classes:
        if re.search(pat, part, re.I):
            return cls
    return 'other'


def part_map_from_sets(inst):
    """element label -> part name, for flattened recovery ODBs."""
    m = {}
    for name, es in inst.elementSets.items():
        up = name.upper()
        mm = re.match(r'^(.*)_(MAT-GLM|S235)$', up)
        if mm:
            part = SUFFIX.sub('', mm.group(1))
        else:
            mm = re.match(r'^(DWL_M\d+-\d+.*?)__PICKEDSET\d+$', up)     # also DWL_M14-1-RAD-2-1__PICKEDSET34
            if not mm:
                continue
            part = SUFFIX.sub('', mm.group(1))
        for e in es.elements:
            m[e.label] = part
    return m


def mesh_arrays(inst):
    nodes = inst.nodes
    nl = np.array([n.label for n in nodes], dtype=np.int64)
    nc = np.array([n.coordinates for n in nodes], dtype=float).reshape(-1, 3)
    o = np.argsort(nl)
    nl, nc = nl[o], nc[o]
    els = inst.elements
    el = np.array([e.label for e in els], dtype=np.int64)
    et = [e.type for e in els]
    cen = np.zeros((len(els), 3))
    for i, e in enumerate(els):
        cen[i] = nc[np.searchsorted(nl, e.connectivity)].mean(axis=0)
    o = np.argsort(el)
    return {'nl': nl, 'nc': nc, 'el': el[o], 'cen': cen[o], 'et': [et[i] for i in o]}


def in_box(xyz, box_min, box_max):
    return np.all((xyz >= np.array(box_min)) & (xyz <= np.array(box_max)), axis=1)


def joint_of(xyz, joints):
    """array of joint ids ('' if outside all boxes)"""
    out = np.array([''] * len(xyz), dtype=object)
    for jid, j in joints.items():
        out[in_box(xyz, j['box_min'], j['box_max'])] = jid
    return out


def f(v):
    return '%.6g' % v


def ckey(x, y, z, cell=0.2):
    return (int(round(x / cell)), int(round(y / cell)), int(round(z / cell)))


def load_refmap(path):
    """centroid -> part name, from the reference (C) extraction"""
    m = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            m[ckey(float(r['x']), float(r['y']), float(r['z']))] = r['part']
    return m


def ref_part(refmap, c):
    k = ckey(c[0], c[1], c[2])
    if k in refmap:
        return refmap[k]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                v = refmap.get((k[0] + dx, k[1] + dy, k[2] + dz))
                if v:
                    return v
    return 'UNMAPPED'


def main():
    cfg = json.load(open(sys.argv[1]))
    reg = json.load(open(cfg['regions']))
    joints, classes = reg['joints'], reg['classes']
    out = cfg['out_dir']
    if not os.path.isdir(out):
        os.makedirs(out)
    meta = {'case': cfg['case'], 'step': cfg['step'], 'odbs': {}, 'warnings': [], 'counts': {}}
    fe = open(os.path.join(out, 'elem_stress.csv'), 'w', newline='')
    fn = open(os.path.join(out, 'nodal.csv'), 'w', newline='')
    fp = open(os.path.join(out, 'probes.csv'), 'w', newline='')
    we, wn, wp = csv.writer(fe), csv.writer(fn), csv.writer(fp)
    we.writerow(['case', 'odb', 'instance', 'joint', 'part', 'class', 'element', 'etype', 'ip', 'sp', 'x', 'y', 'z'] + STRESS_COLS + ['MISES'])
    wn.writerow(['case', 'odb', 'instance', 'joint', 'node', 'x', 'y', 'z', 'U1', 'U2', 'U3', 'UR1', 'UR2', 'UR3'])
    wp.writerow(['case', 'odb', 'probe', 'instance', 'node', 'x', 'y', 'z', 'U1', 'U2', 'U3', 'UR1', 'UR2', 'UR3', 'dist_mm'])

    refmap = load_refmap(cfg['part_reference_csv']) if cfg.get('part_reference_csv') and any(o_['kind'] == 'backcalc' for o_ in cfg['odbs']) else {}
    probes = reg.get('probes', {})
    for od in cfg['odbs']:
        path, kind = od['path'], od['kind']
        n_unmapped = 0
        name = os.path.basename(path)
        o = openOdb(path, readOnly=True)
        info = {'kind': kind, 'step_found': False, 'n_elem_rows': 0, 'n_nodal_rows': 0, 'frame_time': None}
        meta['odbs'][name] = info
        stepname = ('BC-' + cfg['step']) if kind == 'backcalc' else cfg['step']      # back-calculation ODBs name their steps BC-<step>
        step = o.steps[stepname] if stepname in o.steps.keys() else None
        if step is None or len(step.frames) == 0:
            info['note'] = 'step missing or without frames'
            meta['warnings'].append('%s: step %s missing/empty' % (name, stepname))
            o.close()
            continue
        frame = step.frames[len(step.frames) - 1]
        info['step_found'] = True
        info['frame_time'] = float(frame.frameValue)
        meshes, parts = {}, {}
        for iname, inst in o.rootAssembly.instances.items():
            m = mesh_arrays(inst)
            meshes[iname] = m
            if kind == 'full':
                parts[iname] = SUFFIX.sub('', iname.upper())      # one part name per instance
            elif kind == 'backcalc':
                parts[iname] = None                               # no sets in back-calculated ODBs: parts come from the reference model by centroid
            else:
                parts[iname] = part_map_from_sets(inst)           # label -> part
        seen_el, seen_nd = set(), set()      # a few instances appear in two field blocks (identical values): keep one
        # ---------------- element stress ----------------
        if 'S' in frame.fieldOutputs:
            for blk in frame.fieldOutputs['S'].bulkDataBlocks:
                iname = blk.instance.name
                m = meshes[iname]
                lab = np.asarray(blk.elementLabels)
                pos = np.searchsorted(m['el'], lab)
                cen = m['cen'][pos]
                jid = joint_of(cen, joints)
                keep = np.where(jid != '')[0]
                if len(keep) == 0:
                    continue
                data = np.asarray(blk.data)
                comps = list(blk.componentLabels)
                ips = np.asarray(blk.integrationPoints) if blk.integrationPoints is not None else np.zeros(len(lab), dtype=int)
                sp = getattr(blk, 'sectionPoint', None)
                sp_s = ''
                try:
                    sp_s = str(sp.number) if sp is not None else ''
                except Exception:
                    sp_s = ''
                for r in keep:
                    e = int(lab[r])
                    k = (iname, e, int(ips[r]), sp_s)
                    if k in seen_el:
                        continue
                    seen_el.add(k)
                    if kind == 'full':
                        part = parts[iname]
                    elif kind == 'backcalc':
                        part = ref_part(refmap, cen[r])
                        if part == 'UNMAPPED':
                            n_unmapped += 1
                    else:
                        part = parts[iname].get(e, 'UNMAPPED')
                    row = {c: data[r][comps.index(c)] if c in comps else 0.0 for c in STRESS_COLS}
                    s11, s22, s33, s12, s13, s23 = [row[c] for c in STRESS_COLS]
                    if len(comps) >= 6:
                        mis = np.sqrt(0.5 * ((s11 - s22) ** 2 + (s22 - s33) ** 2 + (s33 - s11) ** 2) + 3.0 * (s12 ** 2 + s13 ** 2 + s23 ** 2))
                    else:   # beam elements: axial + transverse shear
                        mis = np.sqrt(s11 ** 2 + 3.0 * (s12 ** 2 + s13 ** 2))
                    we.writerow([cfg['case'], name, iname, jid[r], part, classify(part, classes), e, m['et'][pos[r]], int(ips[r]), sp_s,
                                 f(cen[r][0]), f(cen[r][1]), f(cen[r][2]), f(s11), f(s22), f(s33), f(s12), f(s13), f(s23), f(mis)])
                    info['n_elem_rows'] += 1
        else:
            meta['warnings'].append('%s: no S field output' % name)
        if n_unmapped:
            meta['warnings'].append('%s: %d element rows without a matching reference part' % (name, n_unmapped))
        # ---------------- nodal U / UR ----------------
        ur_blocks = {}
        if 'UR' in frame.fieldOutputs:
            for blk in frame.fieldOutputs['UR'].bulkDataBlocks:
                if blk.instance is None:       # assembly-level nodes (reference points): not part of any instance
                    continue
                for lab, d in zip(np.asarray(blk.nodeLabels), np.asarray(blk.data)):
                    ur_blocks[(blk.instance.name, int(lab))] = d
        if 'U' in frame.fieldOutputs:
            for blk in frame.fieldOutputs['U'].bulkDataBlocks:
                if blk.instance is None:
                    meta['warnings'].append('%s: skipped U block without instance (reference points)' % name)
                    continue
                iname = blk.instance.name
                m = meshes[iname]
                lab = np.asarray(blk.nodeLabels)
                pos = np.searchsorted(m['nl'], lab)
                xyz = m['nc'][pos]
                jid = joint_of(xyz, joints)
                sel = np.arange(len(lab)) if kind == 'global' else np.where(jid != '')[0]
                data = np.asarray(blk.data)
                if kind != 'full':
                    for pname, pc in probes.items():
                        dist = np.sqrt(((xyz - np.array(pc)) ** 2).sum(axis=1))
                        for r in np.where(dist < 1.0)[0]:
                            ur = ur_blocks.get((iname, int(lab[r])))
                            ur = ur if ur is not None else [np.nan] * 3
                            wp.writerow([cfg['case'], name, pname, iname, int(lab[r]), f(xyz[r][0]), f(xyz[r][1]), f(xyz[r][2]),
                                         f(data[r][0]), f(data[r][1]), f(data[r][2]), f(ur[0]), f(ur[1]), f(ur[2]), f(dist[r])])
                for r in sel:
                    kn = (iname, int(lab[r]))
                    if kn in seen_nd:
                        continue
                    seen_nd.add(kn)
                    ur = ur_blocks.get((iname, int(lab[r])))
                    ur = ur if ur is not None else [np.nan] * 3
                    wn.writerow([cfg['case'], name, iname, jid[r], int(lab[r]), f(xyz[r][0]), f(xyz[r][1]), f(xyz[r][2]),
                                 f(data[r][0]), f(data[r][1]), f(data[r][2]), f(ur[0]), f(ur[1]), f(ur[2])])
                    info['n_nodal_rows'] += 1
        # ---------------- probes (named node sets, reference model) ----------------
        if kind == 'full':
            for pname in reg.get('probe_sets_C', []):
                ns = o.rootAssembly.nodeSets[pname] if pname in o.rootAssembly.nodeSets.keys() else None
                if ns is None:
                    meta['warnings'].append('%s: probe set %s not found' % (name, pname))
                    continue
                coords = {}
                for arr in ns.nodes:
                    for nd in arr:
                        coords[(nd.instanceName or '', nd.label)] = nd.coordinates
                uf = frame.fieldOutputs['U'].getSubset(region=ns)
                urf = frame.fieldOutputs['UR'].getSubset(region=ns) if 'UR' in frame.fieldOutputs else None

                def key_of(v):
                    return ((v.instance.name if v.instance is not None else ''), v.nodeLabel)
                urd = {}
                if urf is not None:
                    for v in urf.values:
                        urd[key_of(v)] = v.data
                for v in uf.values:
                    k = key_of(v)
                    cc = coords.get(k, (float('nan'),) * 3)
                    ur = urd.get(k, [np.nan] * 3)
                    wp.writerow([cfg['case'], name, pname, k[0], k[1], f(cc[0]), f(cc[1]), f(cc[2]),
                                 f(v.data[0]), f(v.data[1]), f(v.data[2]), f(ur[0]), f(ur[1]), f(ur[2]), 0])
        o.close()
        print('%s: %d element rows, %d nodal rows' % (name, info['n_elem_rows'], info['n_nodal_rows']))
    for h in (fe, fn, fp):
        h.close()
    with open(os.path.join(out, 'extract_meta.json'), 'w') as fm:
        json.dump(meta, fm, indent=1)
    print('done', out)


if __name__ == '__main__':
    main()
