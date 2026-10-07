"""Build study/regions.json from the reference model C (discovery JSON + C input-file joint composition).

Regions are defined ONCE on C (complete non-reduced model) as global-coordinate boxes + part-name rules, and then applied
unchanged to every case (A, B1, B2), because all models share the same global geometry and part names.

  python make_regions.py            # needs study/discovery/C_GLOBAL-1_slow.json and C_joint_instances.json
"""
import csv, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DISC = os.path.join(ROOT, 'study', 'discovery')
OUT = os.path.join(ROOT, 'study', 'regions.json')

SUFFIX = re.compile(r'(-(LIN|RAD)-\d+(-\d+)*)+$', re.I)
TOL = 1.0   # mm, box padding

# joint -> (C joint set, instance-name suffix of the joint's horizontal-beam / post segments in C)
JOINTS = {
    'J3': {'c_set': 'JOINT-3_IML', 'seg_suffix': '', 'top_suffix': '-LIN-1-2', 'side': 'left', 'label': 'Joint-3 (left, module 1/2 inter-module level)'},
    'J6': {'c_set': 'JOINT-6_IMR', 'seg_suffix': '-RAD-2-LIN-1-2', 'top_suffix': '-RAD-2-LIN-1-3', 'side': 'right', 'label': 'Joint-6 (right, module 2/3 inter-module level)'},
}
# 300 mm stubs that complete the B1 joint substructure: post below (B1B), beam end (B2_2B), post above (B1E)
SEGMENTS = {'post_segment': 'B1B-43', 'beam_segment': 'B2_2B-44', 'post_segment_top': 'B1E-42'}
BEAM_PARTS = ['B2A-41', 'B2_2B-44']          # horizontal beam timber parts used for the section series
CORNER_PLATE = 'STEELPLATE_CORNER-0-50'


def union(bbs):
    return [[min(b['min'][k] for b in bbs) for k in range(3)], [max(b['max'][k] for b in bbs) for k in range(3)]]


def main():
    inst = json.load(open(os.path.join(DISC, 'C_GLOBAL-1_slow.json')))['C-GLOBAL-1.odb']['instances']
    jsets = json.load(open(os.path.join(DISC, 'C_joint_instances.json')))
    regions = {'defined_on': 'C-GLOBAL-1.odb', 'units': 'mm', 'box_pad_mm': TOL, 'axes': {'horizontal': 'X', 'vertical': 'Z', 'thickness': 'Y'},
               'segments': SEGMENTS, 'beam_parts': BEAM_PARTS, 'corner_plate': CORNER_PLATE,
               'classes': [['dowel', '^DWL_'], ['steel_corner', '^STEELPLATE_CORNER'], ['steel_inter', '^(STEELPLATE_INTER|STEELPATE|STEELPLATE-BASE)'],
                           ['timber', '^B[12]']],
               'probe_sets_C': ['FO-MIDSPAN', 'FO3-BEAM-MID-LEFT', 'FO4-POST-BOTTOM-CORNER'],
               'stats': ['peak', 'mean', 'p95'], 'series': {}, 'joints': {}}
    for jid, j in JOINTS.items():
        names = list(jsets[j['c_set']])
        seg = [SEGMENTS['post_segment'] + j['seg_suffix'], SEGMENTS['beam_segment'] + j['seg_suffix'],
               SEGMENTS['post_segment_top'] + j['top_suffix']]
        for n in seg:
            if n.upper() not in inst:
                sys.exit('segment instance %s not found in C' % n)
        allinst = names + seg
        bbs = [inst[n.upper()]['bbox'] for n in allinst]
        box = union(bbs)
        box = [[v - TOL for v in box[0]], [v + TOL for v in box[1]]]
        parts = sorted({SUFFIX.sub('', n).upper() for n in allinst})
        regions['joints'][jid] = {'label': j['label'], 'side': j['side'], 'c_joint_set': j['c_set'], 'c_instances': allinst,
                                  'box_min': box[0], 'box_max': box[1], 'parts': parts}
        # section series along the horizontal beam, starting 50 mm beyond the end of the corner steel plate
        plate = [n for n in names if SUFFIX.sub('', n).upper() == CORNER_PLATE][0]
        pb = inst[plate.upper()]['bbox']
        direction = -1 if j['side'] == 'left' else 1          # beam runs away from the post: -X on the left, +X on the right
        plate_end = pb['min'][0] if direction < 0 else pb['max'][0]
        beam_bbs = [inst[(p + j['seg_suffix']).upper()]['bbox'] for p in BEAM_PARTS if (p + j['seg_suffix']).upper() in inst]
        boundary = min(b['min'][0] for b in beam_bbs) if direction < 0 else max(b['max'][0] for b in beam_bbs)
        regions['series'][jid] = {'axis': 'X', 'plate_end': plate_end, 'direction': direction, 'start_offset_mm': 50.0, 'step_mm': 50.0,
                                  'slab_halfwidth_mm': 25.0, 'boundary': boundary,
                                  'x_positions': []}
        x = plate_end + direction * 50.0
        while (x - boundary) * direction < 1e-6 and (direction * (boundary - x)) >= -1e-6:
            regions['series'][jid]['x_positions'].append(round(x, 3))
            x += direction * 50.0
        # keep only positions up to (and including) the substructure boundary
        regions['series'][jid]['x_positions'] = [p for p in regions['series'][jid]['x_positions'] if (p - boundary) * direction <= 1e-6]
    # probe coordinates = the named node sets of C, taken from the retained C extraction
    sys.path.insert(0, HERE)
    try:
        import snapshot as snap
        row = snap.latest_run('C')
        pr = {}
        if row:
            with open(os.path.join(snap.STORE, 'C', row['run_id'], 'extract', 'probes.csv'), newline='') as fh:
                for r in csv.DictReader(fh):
                    pr[r['probe']] = [float(r['x']), float(r['y']), float(r['z'])]
        regions['probes'] = pr
        print('probes', pr)
    except Exception as ex:
        print('probes not set:', ex)
    with open(OUT, 'w') as f:
        json.dump(regions, f, indent=1)
    for jid, j in regions['joints'].items():
        print(jid, 'box', [round(v) for v in j['box_min']], [round(v) for v in j['box_max']], 'parts', len(j['parts']))
        print('   series', regions['series'][jid]['x_positions'])
    print('wrote', OUT)


if __name__ == '__main__':
    main()
