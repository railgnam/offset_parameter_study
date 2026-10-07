"""Orchestrator for the comparative study (system python, stdlib only).

  python run_study.py --cases B1 C --snapshot --extract --compare [--force] [--with-sim] [--with-cae] [--tag mytag]
  python run_study.py --all               # snapshot + extract + compare for every case that is 'available'

Steps are incremental: a snapshot is re-used when nothing changed (hash), extraction is skipped when the run already
has extract/extract_meta.json (unless --force).  Abaqus is only used to READ the snapshot copies of the ODBs.
"""
import argparse, glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import snapshot as snap

ABAQUS = r'C:\SIMULIA\Commands\abaqus.bat'
EXTRACT = os.path.join(HERE, 'abq', 'extract_case.py')


def fwd(p):
    return os.path.abspath(p).replace('\\', '/')


def run_abaqus_python(script, args, cwd):
    inner = 'call "%s" python "%s" %s' % (ABAQUS, script, ' '.join('"%s"' % a for a in args))
    cmd = 'cmd /c "%s"' % inner          # one pre-quoted string: a list would be re-escaped by subprocess
    print('>>', cmd)
    r = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL)
    return r.returncode


def odb_kinds(reg, case, run_dir):
    c = reg['cases'][case]
    job = c['jobs']['global']
    out = []
    for p in sorted(glob.glob(os.path.join(run_dir, 'backcalc', '*.odb'))):
        out.append({'path': fwd(p), 'kind': 'backcalc'})
    for p in sorted(glob.glob(os.path.join(run_dir, 'odb', '*.odb'))):
        b = os.path.basename(p)
        # a case without substructures is a full model, reference or not (zone_offset keeps the
        # superseded C next to the corrected reference C25)
        if c.get('role') == 'reference' or not c['jobs'].get('substructures'):
            kind = 'full'
        elif b == job + '.odb':
            kind = 'global'
        elif re.match(r'^%s_\d+\.odb$' % re.escape(job), b):
            kind = 'recovery'
        else:
            continue
        out.append({'path': fwd(p), 'kind': kind})
    return out


def extract(case, run_id, reg, force=False):
    run_dir = snap.run_dir(case, run_id)
    out_dir = os.path.join(run_dir, 'extract')
    if os.path.isfile(os.path.join(out_dir, 'extract_meta.json')) and not force:
        print('[%s] run %s already extracted' % (case, run_id))
        return True
    cfg = {'case': case, 'step': reg['cases'][case]['step'], 'regions': fwd(os.path.join(ROOT, 'study', 'regions.json')),
           'out_dir': fwd(out_dir), 'odbs': odb_kinds(reg, case, run_dir)}
    refrow = snap.latest_run(reg.get('reference'))
    if refrow and case != reg.get('reference'):
        cfg['part_reference_csv'] = fwd(os.path.join(snap.run_dir(reg['reference'], refrow['run_id']), 'extract', 'elem_stress.csv'))
    os.makedirs(out_dir, exist_ok=True)
    cfg_path = os.path.join(out_dir, 'job_config.json')
    with open(cfg_path, 'w') as f:
        json.dump(cfg, f, indent=1)
    rc = run_abaqus_python(EXTRACT, [cfg_path], ROOT)
    ok = rc == 0 and os.path.isfile(os.path.join(out_dir, 'extract_meta.json'))
    if ok:
        meta = json.load(open(os.path.join(out_dir, 'extract_meta.json')))
        rows = sum(v.get('n_elem_rows', 0) for v in meta['odbs'].values())
        if rows == 0:
            ok = False
            print('[%s] extraction produced 0 element rows: %s' % (case, meta.get('warnings')))
            os.remove(os.path.join(out_dir, 'extract_meta.json'))     # so it is retried next time
    print('[%s] extraction %s' % (case, 'OK' if ok else 'FAILED (rc=%s)' % rc))
    return ok


RENDER = os.path.join(HERE, 'abq', 'render_contours.py')


def nice_ceil(m):
    """round a maximum up to a readable limit (50 above 100, 10 above 20, 5 below)"""
    import math
    step = 50.0 if m >= 100 else 10.0 if m >= 20 else 5.0
    return max(step, math.ceil(m / step - 1e-9) * step)


def auto_limits(reg, rcfg):
    """per group in rcfg['auto_limit_groups'] and per joint: [0, rounded-up maximum von Mises over ALL cases]; saved for montage.py"""
    import csv
    out = {}
    for gname in rcfg.get('auto_limit_groups', []):
        classes = set(rcfg['groups'][gname]['classes'])
        mx = {}
        for c in reg['order']:
            row = snap.latest_run(c)
            p = os.path.join(snap.run_dir(c, row['run_id']), 'extract', 'elem_stress.csv') if row else None
            if not p or not os.path.isfile(p):
                continue
            with open(p, newline='') as fh:
                for r in csv.DictReader(fh):
                    if r['class'] in classes and r['joint']:
                        mx[r['joint']] = max(mx.get(r['joint'], 0.0), float(r['MISES']))
        out[gname] = {j: [0, nice_ceil(v)] for j, v in mx.items()}
    with open(os.path.join(ROOT, 'study', 'limits_auto.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    return out


def contours(case, run_id, reg, force=False):
    run_dir = snap.run_dir(case, run_id)
    img_dir = os.path.join(run_dir, 'images')
    if glob.glob(os.path.join(img_dir, '*.png')) and not force:
        print('[%s] run %s already rendered' % (case, run_id))
        return True
    elem_csv = os.path.join(run_dir, 'extract', 'elem_stress.csv')
    if not os.path.isfile(elem_csv):
        print('[%s] no extraction yet -> cannot render' % case)
        return False
    rcfg = json.load(open(os.path.join(ROOT, 'study', 'render.json')))
    rcfg.update({'case': case, 'step': reg['cases'][case]['step'], 'regions': fwd(os.path.join(ROOT, 'study', 'regions.json')),
                 'elem_csv': fwd(elem_csv), 'out_dir': fwd(img_dir), 'odbs': odb_kinds(reg, case, run_dir)})
    rcfg['limits_by_joint'] = auto_limits(reg, rcfg)
    # camera: centred on the deformed joint, using the reference case's mean displacement (same camera for all cases)
    shift = {}
    refc = reg.get('reference')
    row = snap.latest_run(refc) if refc else None
    nodal = os.path.join(snap.run_dir(refc, row['run_id']), 'extract', 'nodal.csv') if row else None
    if nodal and os.path.isfile(nodal):
        import csv
        acc = {}
        with open(nodal, newline='') as fh:
            for r in csv.DictReader(fh):
                if r['joint']:
                    a = acc.setdefault(r['joint'], [0.0, 0.0, 0.0, 0])
                    a[0] += float(r['U1']); a[1] += float(r['U2']); a[2] += float(r['U3']); a[3] += 1
        sc = rcfg.get('deform_scale', 1)
        shift = {j: [a[0] / a[3] * sc, a[1] / a[3] * sc, a[2] / a[3] * sc] for j, a in acc.items() if a[3]}
    rcfg['camera_shift'] = shift
    framing = {}
    if nodal and os.path.isfile(nodal):
        import csv, math
        ref_csv = os.path.join(snap.run_dir(refc, row['run_id']), 'extract', 'elem_stress.csv')
        gcl = {g: set(rcfg['groups'][g]['classes']) for g in rcfg.get('framing_groups', [])}
        ext = {}
        with open(ref_csv, newline='') as fh:
            for rr in csv.DictReader(fh):
                for g, cl in gcl.items():
                    if rr['class'] in cl and rr['joint']:
                        e = ext.setdefault((rr['joint'], g), [[1e9] * 3, [-1e9] * 3])
                        for k, key in enumerate(('x', 'y', 'z')):
                            v = float(rr[key])
                            e[0][k] = min(e[0][k], v)
                            e[1][k] = max(e[1][k], v)
        for (j, g), (lo, hi) in ext.items():
            d = [b - a for a, b in zip(lo, hi)]
            h = (math.sqrt(sum(x * x for x in d)) * 1.15 if g == 'dowel' else max(d[0], d[2]) * 1.3) + 80.0
            sh = shift.get(j, [0, 0, 0])
            framing.setdefault(j, {})[g] = {'center': [(a + b) / 2.0 + sh[k] for k, (a, b) in enumerate(zip(lo, hi))], 'height': round(h, 0)}
    rcfg['framing'] = framing
    os.makedirs(img_dir, exist_ok=True)
    for old in glob.glob(os.path.join(img_dir, '*.png')):          # stale layers of earlier group/view definitions
        os.remove(old)
    cfg_path = os.path.join(img_dir, 'render_config.json')
    with open(cfg_path, 'w') as f:
        json.dump(rcfg, f, indent=1)
    inner = 'call "%s" cae noGUI="%s" -- "%s"' % (ABAQUS, RENDER, cfg_path)
    cmd = 'cmd /c "%s"' % inner
    print('>>', cmd)
    rc = subprocess.run(cmd, cwd=ROOT, stdin=subprocess.DEVNULL).returncode
    n = len(glob.glob(os.path.join(img_dir, '*.png')))
    print('[%s] rendering rc=%s, %d images' % (case, rc, n))
    return n > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', nargs='*')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--snapshot', action='store_true')
    ap.add_argument('--extract', action='store_true')
    ap.add_argument('--compare', action='store_true')
    ap.add_argument('--contours', action='store_true')
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--with-sim', action='store_true')
    ap.add_argument('--with-cae', action='store_true')
    ap.add_argument('--tag', default='comparison')
    a = ap.parse_args()
    if a.all:
        a.snapshot = a.extract = a.compare = a.contours = True
    reg = snap.load_registry()
    cases = a.cases or [c for c in reg['order'] if reg['cases'][c].get('status') == 'available']
    runs = {}
    for c in cases:
        if a.snapshot:
            rid = snap.snapshot(c, a.with_sim, a.with_cae, a.force)
        else:
            row = snap.latest_run(c)
            rid = row['run_id'] if row else None
        if rid:
            runs[c] = rid
        else:
            print('[%s] no snapshot run available' % c)
    if a.extract:
        for c, rid in runs.items():
            extract(c, rid, reg, a.force)
    if a.contours:
        for c, rid in runs.items():
            contours(c, rid, reg, a.force)
        import montage
        sys.argv = ['montage.py', '--tag', a.tag]
        montage.main()
    if a.compare:
        import compare
        sys.argv = ['compare.py', '--cases'] + [c for c in reg['order']] + ['--tag', a.tag]
        compare.main()
    if a.stats:
        import runstats
        for r in runstats.collect(reg, cases):
            print(r['case'], r['job'], r['nodes'], r['dofs'], r['cpu_s'], r['wall_s'], r['total_mb'])


if __name__ == '__main__':
    main()
