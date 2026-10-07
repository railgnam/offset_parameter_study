# abaqus python discover_odb.py <out.json> <odb> [<odb> ...]
# Read-only inventory of ODBs: steps/frames, field outputs, instances (nodes, element types,
# bounding boxes), element/node sets, sections/materials. Use it to define regions on the
# reference model (C) and to cross-check the other cases.
import sys, json, os
from odbAccess import openOdb


def bbox_of(nodes):
    xs = [float(n.coordinates[0]) for n in nodes]
    ys = [float(n.coordinates[1]) for n in nodes]
    zs = [float(n.coordinates[2]) for n in nodes]
    if not xs:
        return None
    return {'min': [min(xs), min(ys), min(zs)], 'max': [max(xs), max(ys), max(zs)]}


def describe(path, slow=False):
    # slow=True also loops over every node/element (bounding boxes, element-type counts); the default
    # lists names, set sizes, steps and field outputs only, which is fast even for 400k-element models.
    o = openOdb(path, readOnly=True)
    d = {'odb': os.path.abspath(path), 'name': o.name, 'steps': {}, 'instances': {}, 'sections': {}, 'materials': {}}
    for sname, st in o.steps.items():
        frames = st.frames
        fo = {}
        t_last = None
        if len(frames):
            last = frames[len(frames) - 1]
            t_last = float(last.frameValue)
            for k, f in last.fieldOutputs.items():
                fo[k] = {'type': str(f.type), 'components': list(f.componentLabels),
                         'locations': [str(l.position) for l in f.locations]}
        d['steps'][sname] = {'nframes': len(frames), 'procedure': st.procedure, 'last_frame_time': t_last,
                             'fieldOutputs': fo, 'historyRegions': list(st.historyRegions.keys())[:50]}
    ra = o.rootAssembly
    for iname, inst in ra.instances.items():
        types = {}
        if slow:
            for e in inst.elements:
                types[e.type] = types.get(e.type, 0) + 1
        d['instances'][iname] = {
            'n_nodes': len(inst.nodes), 'n_elements': len(inst.elements), 'element_types': types,
            'bbox': bbox_of(inst.nodes) if slow else None,
            'elsets': {k: len(v.elements) for k, v in inst.elementSets.items()},
            'nsets': {k: len(v.nodes) for k, v in inst.nodeSets.items()}}
    def set_size(s, attr):
        # assembly sets hold a tuple of per-instance sequences; instance sets hold a flat sequence
        items = getattr(s, attr)
        try:
            return sum(len(x) for x in items)
        except TypeError:
            return len(items)
    d['assembly_elsets'] = {k: set_size(v, 'elements') for k, v in ra.elementSets.items()}
    d['assembly_nsets'] = {k: set_size(v, 'nodes') for k, v in ra.nodeSets.items()}
    try:
        for k, s in o.sections.items():
            d['sections'][k] = {'repr': str(s)[:200]}
        for k, m in o.materials.items():
            d['materials'][k] = {'repr': str(m)[:200]}
    except Exception as ex:
        d['sections_error'] = str(ex)
    o.close()
    return d


if __name__ == '__main__':
    slow = '--slow' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--slow']
    out = args[0]
    res = {}
    for p in args[1:]:
        try:
            res[os.path.basename(p)] = describe(p, slow)
        except Exception as ex:
            res[os.path.basename(p)] = {'error': repr(ex)}
    with open(out, 'w') as f:
        json.dump(res, f, indent=1)
    print('wrote', out)
