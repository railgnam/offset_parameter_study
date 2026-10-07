"""Comparison tables + Excel export from the retained store (pure stdlib + xlsxwriter).

  python compare.py [--cases A B1 B2 C] [--ref C] [--tag mytag]

Reads store/<case>/<run>/extract/{elem_stress,nodal,probes}.csv (latest run per case, or --run CASE=RUN_ID) and
study/regions.json; writes exports/<date>_<tag>/{tables/*.csv, comparison.xlsx}.
Cases without an extracted run are listed as missing and left out; deviations are relative to --ref (default C).
"""
import argparse, collections, csv, datetime, math, os, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import snapshot as snap
import runstats

CASE_COLORS = {'A': '#d95f02', 'B1': '#1b9e77', 'B2': '#7570b3', 'C': '#222222'}
STAT_ORDER = ['max', 'min', 'p95', 'p05', 'mean', 'mean_abs']


# ------------------------------------------------------------------ data loading
def read_csv(path, numeric):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            for k in numeric:
                try:
                    r[k] = float(r[k])
                except (ValueError, KeyError):
                    r[k] = float('nan')
            rows.append(r)
    return rows


class CaseData:
    def __init__(self, case, run_id):
        self.case, self.run_id = case, run_id
        d = os.path.join(snap.STORE, case, run_id, 'extract')
        self.dir = d
        self.elem = read_csv(os.path.join(d, 'elem_stress.csv'), ['x', 'y', 'z', 'S11', 'S22', 'S33', 'S12', 'S13', 'S23', 'MISES'])
        self.nodal = read_csv(os.path.join(d, 'nodal.csv'), ['x', 'y', 'z', 'U1', 'U2', 'U3', 'UR1', 'UR2', 'UR3'])
        self.probes = read_csv(os.path.join(d, 'probes.csv'), ['x', 'y', 'z', 'U1', 'U2', 'U3', 'UR1', 'UR2', 'UR3', 'dist_mm'])


def find_runs(cases, pinned):
    out = {}
    for c in cases:
        row = snap.latest_run(c, pinned.get(c))
        if row and os.path.isfile(os.path.join(snap.STORE, c, row['run_id'], 'extract', 'elem_stress.csv')):
            out[c] = row['run_id']
    return out


# ------------------------------------------------------------------ statistics
def pct(sorted_vals, p):
    if not sorted_vals:
        return float('nan')
    k = (len(sorted_vals) - 1) * p / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def stats(vals):
    v = sorted(x for x in vals if x == x)
    if not v:
        return {'n': 0}
    return {'n': len(v), 'max': v[-1], 'min': v[0], 'p95': pct(v, 95), 'p05': pct(v, 5), 'mean': sum(v) / len(v),
            'mean_abs': sum(abs(x) for x in v) / len(v)}


def dev(x, ref):
    if x is None or ref is None or x != x or ref != ref or abs(ref) < 1e-9:
        return None
    return (x - ref) / abs(ref) * 100.0


def fmt(v, nd=3):
    return '' if v is None or v != v else round(v, nd)


# ------------------------------------------------------------------ selection helpers
def select(data, joint=None, cls=None, parts=None, xrange=None):
    out = []
    for r in data.elem:
        if joint and r['joint'] != joint:
            continue
        if cls and r['class'] != cls:
            continue
        if parts and r['part'] not in parts:
            continue
        if xrange and not (xrange[0] <= r['x'] <= xrange[1]):
            continue
        out.append(r)
    return out


def wide(rows_by_case, cases, ref, key_cols, value_fn):
    """rows_by_case: {case: {key: value}} -> list of dict rows with one column per case and deviation vs ref."""
    keys = sorted({k for c in cases for k in rows_by_case.get(c, {})})
    table = []
    for k in keys:
        row = dict(zip(key_cols, k))
        refv = rows_by_case.get(ref, {}).get(k)
        for c in cases:
            v = rows_by_case.get(c, {}).get(k)
            row[c] = fmt(v)
        for c in cases:
            if c != ref:
                is_count = k[-1] == 'n_values'
                row['dev_%s_vs_%s_%%' % (c, ref)] = '' if is_count else fmt(dev(rows_by_case.get(c, {}).get(k), refv), 1)
        table.append(row)
    return table


# ------------------------------------------------------------------ tables
def table_region_stress(D, cases, ref, reg):
    """per joint, class, quantity and statistic: timber -> S11, steel/dowel -> S11 and MISES"""
    res = collections.defaultdict(dict)
    for c in cases:
        for jid in reg['joints']:
            for cls in ['timber', 'steel_corner', 'steel_inter', 'dowel']:
                sel = select(D[c], jid, cls)
                for q in (('S11', 'S22', 'MISES') if cls == 'timber' else ('S11', 'MISES')):
                    st = stats([r[q] for r in sel])
                    for s in (('max', 'min', 'p95', 'p05', 'mean', 'mean_abs') if q in ('S11', 'S22') else ('max', 'p95', 'mean')):
                        if s in st:
                            res[c][(jid, cls, q, s)] = st[s]
                    if st['n']:
                        res[c][(jid, cls, q, 'n_values')] = st['n']
    return wide(res, cases, ref, ['joint', 'class', 'quantity', 'stat'], None)


def table_parts(D, cases, ref, reg, only=None):
    res = collections.defaultdict(dict)
    for c in cases:
        for jid in reg['joints']:
            parts = sorted({r['part'] for r in D[c].elem if r['joint'] == jid})
            for p in parts:
                if only and not only(p):
                    continue
                sel = select(D[c], jid, parts={p})
                for q in ('S11', 'MISES'):
                    st = stats([r[q] for r in sel])
                    for s in ('max', 'min', 'p95', 'mean'):
                        if s in st:
                            res[c][(jid, p, q, s)] = st[s]
                    res[c][(jid, p, q, 'n_values')] = st['n']
    return wide(res, cases, ref, ['joint', 'part', 'quantity', 'stat'], None)


def table_series(D, cases, ref, reg):
    res = collections.defaultdict(dict)
    for jid, s in reg['series'].items():
        hw = s['slab_halfwidth_mm']
        for c in cases:
            for k, x in enumerate(s['x_positions']):
                sel = select(D[c], jid, 'timber', parts=set(reg['beam_parts']), xrange=(x - hw, x + hw))
                st = stats([r['S11'] for r in sel])
                for stat in ('max', 'min', 'p95', 'p05', 'mean'):
                    if stat in st:
                        res[c][(jid, k + 1, x, stat)] = st[stat]
                res[c][(jid, k + 1, x, 'n_values')] = st['n']
    return wide(res, cases, ref, ['joint', 'section_no', 'x_mm', 'stat'], None)


def grid_index(rows, cell=0.5):
    idx = collections.defaultdict(list)
    for r in rows:
        idx[(int(r['x'] // cell), int(r['y'] // cell), int(r['z'] // cell))].append(r)
    return idx


def nearest(idx, x, y, z, tol, cell=0.5):
    cx, cy, cz = int(x // cell), int(y // cell), int(z // cell)
    best, bd = None, tol
    n = int(math.ceil(tol / cell))
    for i in range(cx - n, cx + n + 1):
        for j in range(cy - n, cy + n + 1):
            for k in range(cz - n, cz + n + 1):
                for r in idx.get((i, j, k), ()):
                    d = math.sqrt((r['x'] - x) ** 2 + (r['y'] - y) ** 2 + (r['z'] - z) ** 2)
                    if d <= bd:
                        best, bd = r, d
    return best, bd


def table_probes(D, cases, ref, tol=1.0):
    """probe nodes of C (named node sets) and the node at the same coordinates in every other case, searched in the global ODB,
    the recovery ODBs and the back-calculated main substructures (the source ODB is listed)"""
    rows = []
    seen = set()
    for p in D[ref].probes if ref in D else []:
        if (p['probe'], p['instance'], p['node']) in seen:
            continue
        seen.add((p['probe'], p['instance'], p['node']))
        row = {'probe': p['probe'], 'x': fmt(p['x'], 1), 'y': fmt(p['y'], 1), 'z': fmt(p['z'], 1)}
        for comp in ('U1', 'U3'):
            row['%s_%s' % (comp, ref)] = fmt(p[comp], 4)
        for c in cases:
            if c == ref:
                continue
            cand = [q for q in D[c].probes if q['probe'] == p['probe']]
            best = min(cand, key=lambda q: q['dist_mm'] if q['dist_mm'] == q['dist_mm'] else 0.0) if cand else None
            dist = (best['dist_mm'] if best['dist_mm'] == best['dist_mm'] else 0.0) if best else None
            if best is None:
                best, dist = nearest(grid_index(D[c].nodal), p['x'], p['y'], p['z'], tol)
            for comp in ('U1', 'U3'):
                row['%s_%s' % (comp, c)] = fmt(best[comp], 4) if best else 'not retained'
                row['dev_%s_%s_%%' % (comp, c)] = fmt(dev(best[comp], p[comp]), 1) if best else ''
            row['node_dist_%s_mm' % c] = fmt(dist, 2) if best else ''
            row['src_%s' % c] = best['odb'] if best else ''
        rows.append(row)
    return rows


def table_nodal_matches(D, cases, ref, reg, tol=0.5):
    """coincident nodes inside each joint box: reference (C) values, case values and the difference"""
    rows = []
    if ref not in D:
        return rows
    for c in cases:
        if c == ref:
            continue
        for jid in reg['joints']:
            refn = [r for r in D[ref].nodal if r['joint'] == jid]
            idx = grid_index(refn)
            diffs, rmag, cmag, r1, r3, c1, c3 = [], [], [], [], [], [], []
            for r in D[c].nodal:
                if r['joint'] != jid:
                    continue
                m, d = nearest(idx, r['x'], r['y'], r['z'], tol)
                if m is None:
                    continue
                diffs.append(math.sqrt(sum((r[k] - m[k]) ** 2 for k in ('U1', 'U2', 'U3'))))
                rmag.append(math.sqrt(sum(m[k] ** 2 for k in ('U1', 'U2', 'U3'))))
                cmag.append(math.sqrt(sum(r[k] ** 2 for k in ('U1', 'U2', 'U3'))))
                r1.append(m['U1']); r3.append(m['U3']); c1.append(r['U1']); c3.append(r['U3'])
            n = len(diffs)
            if not n:
                rows.append({'case': c, 'joint': jid, 'n_matched_nodes': 0})
                continue
            rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v))
            rows.append({'case': c, 'joint': jid, 'n_matched_nodes': n,
                         'C_mean_U1_mm': fmt(sum(r1) / n, 3), 'C_mean_U3_mm': fmt(sum(r3) / n, 3), 'C_rms_U_mm': fmt(rms(rmag), 3), 'C_max_U_mm': fmt(max(rmag), 3),
                         'case_mean_U1_mm': fmt(sum(c1) / n, 3), 'case_mean_U3_mm': fmt(sum(c3) / n, 3), 'case_rms_U_mm': fmt(rms(cmag), 3), 'case_max_U_mm': fmt(max(cmag), 3),
                         'max_abs_diff_mm': fmt(max(diffs), 4), 'rms_diff_mm': fmt(rms(diffs), 4), 'rel_rms_diff_%': fmt(rms(diffs) / rms(rmag) * 100 if rms(rmag) else None, 2)})
    return rows


def table_elementwise(D, cases, ref, reg, tol_cell=0.1):
    """elements matched by centroid (+ ip/sp) between case and reference: C values, case values and error statistics"""
    rows = []
    if ref not in D:
        return rows

    def key(r):
        return (round(r['x'] / tol_cell), round(r['y'] / tol_cell), round(r['z'] / tol_cell), r['ip'], r['sp'], r['etype'][:3])
    refmap = {key(r): r for r in D[ref].elem}
    rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v))
    for c in cases:
        if c == ref:
            continue
        acc = collections.defaultdict(lambda: collections.defaultdict(list))
        total = collections.Counter()
        for r in D[c].elem:
            total[(r['joint'], r['class'])] += 1
            m = refmap.get(key(r))
            if m is None:
                continue
            a = acc[(r['joint'], r['class'])]
            for q in ('S11', 'MISES'):
                a['c_' + q].append(r[q]); a['r_' + q].append(m[q]); a['d_' + q].append(r[q] - m[q])
        for (j, cls), t in sorted(total.items()):
            a = acc.get((j, cls))
            if not a or not a['d_S11']:
                rows.append({'case': c, 'joint': j, 'class': cls, 'n_elements': t, 'n_matched': 0})
                continue
            row = {'case': c, 'joint': j, 'class': cls, 'n_elements': t, 'n_matched': len(a['d_S11'])}
            for q in ('S11', 'MISES'):
                row['C_%s_rms_MPa' % q] = fmt(rms(a['r_' + q]), 3)
                row['C_%s_maxabs_MPa' % q] = fmt(max(abs(v) for v in a['r_' + q]), 3)
                row['case_%s_rms_MPa' % q] = fmt(rms(a['c_' + q]), 3)
                row['case_%s_maxabs_MPa' % q] = fmt(max(abs(v) for v in a['c_' + q]), 3)
                row['%s_diff_rmse_MPa' % q] = fmt(rms(a['d_' + q]), 3)
                row['%s_diff_maxabs_MPa' % q] = fmt(max(abs(v) for v in a['d_' + q]), 3)
                row['%s_rel_rmse_%%' % q] = fmt(rms(a['d_' + q]) / rms(a['r_' + q]) * 100 if rms(a['r_' + q]) else None, 2)
            rows.append(row)
    return rows


def table_size_time(cases, reg_cases):
    rows = runstats.collect(reg_cases, cases)
    out = []
    for r in rows:
        out.append({k: r[k] for k in runstats.COLS})
    totals = runstats.case_totals(rows)
    return out, totals


# ------------------------------------------------------------------ export
def unlocked(path):
    """path, or a time-stamped sibling when the file is locked (e.g. open in Excel)"""
    try:
        with open(path, 'ab'):
            pass
        return path
    except PermissionError:
        base, ext = os.path.splitext(path)
        alt = '%s_%s%s' % (base, datetime.datetime.now().strftime('%H%M%S'), ext)
        print('WARNING: %s is locked (open in Excel?) -> writing %s' % (path, alt))
        return alt


def write_csv(path, rows):
    if not rows:
        return
    path = unlocked(path)
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(path, 'w', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(rows)


def write_xlsx(path, sheets, cases, ref, series_rows, reg, notes):
    import xlsxwriter
    wb = xlsxwriter.Workbook(path)
    hdr = wb.add_format({'bold': True, 'bg_color': '#e8eef4', 'border': 1, 'text_wrap': True, 'valign': 'top'})
    cell = wb.add_format({'border': 1})
    wsn = wb.add_worksheet('README')
    wsn.set_column(0, 0, 120)
    for i, line in enumerate(notes):
        wsn.write(i, 0, line)
    for name, rows in sheets:
        ws = wb.add_worksheet(name[:31])
        if not rows:
            ws.write(0, 0, 'no data')
            continue
        cols = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        for j, c in enumerate(cols):
            ws.write(0, j, c, hdr)
            ws.set_column(j, j, max(10, min(28, len(str(c)) + 2)))
        for i, r in enumerate(rows, start=1):
            for j, c in enumerate(cols):
                v = r.get(c, '')
                ws.write(i, j, v, cell)
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, len(rows), len(cols) - 1)
        if name == 'T5_section_series':
            add_series_charts(wb, ws, rows, cols, cases, reg)
    wb.close()


def add_series_charts(wb, ws, rows, cols, cases, reg):
    """one line chart per joint: p95 and max of S11 vs distance from plate end, per case"""
    for jid in reg['series']:
        for stat in ('max', 'p95'):
            idx = [i for i, r in enumerate(rows, start=1) if r.get('joint') == jid and r.get('stat') == stat]
            if not idx:
                continue
            first, last = min(idx), max(idx)
            ch = wb.add_chart({'type': 'line'})
            xcol = cols.index('x_mm')
            for c in cases:
                if c not in cols:
                    continue
                ccol = cols.index(c)
                ch.add_series({'name': c, 'categories': [ws.get_name(), first, xcol, last, xcol],
                               'values': [ws.get_name(), first, ccol, last, ccol],
                               'line': {'color': CASE_COLORS.get(c, '#888888'), 'width': 2}, 'marker': {'type': 'circle', 'size': 4}})
            ch.set_title({'name': '%s: S11 %s along beam sections' % (jid, stat)})
            ch.set_x_axis({'name': 'x of section [mm]'})
            ch.set_y_axis({'name': 'S11 [MPa]'})
            ch.set_size({'width': 640, 'height': 320})
            ws.insert_chart(2 + (0 if stat == 'max' else 17) , len(cols) + 1 + (0 if jid == list(reg['series'])[0] else 11), ch)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', nargs='*')
    ap.add_argument('--ref')
    ap.add_argument('--tag', default='comparison')
    ap.add_argument('--run', nargs='*', default=[], help='pin run ids: CASE=RUN_ID')
    a = ap.parse_args()
    reg_cases = snap.load_registry()
    with open(os.path.join(ROOT, 'study', 'regions.json')) as f:
        reg = json.load(f)
    want = a.cases or reg_cases['order']
    ref = a.ref or reg_cases.get('reference', 'C')
    pinned = dict(x.split('=', 1) for x in a.run)
    runs = find_runs(want, pinned)
    missing = [c for c in want if c not in runs]
    cases = [c for c in want if c in runs]
    if ref not in cases:
        print('WARNING: reference %s has no extracted run; deviations will be empty' % ref)
    D = {c: CaseData(c, runs[c]) for c in cases}
    print('cases used:', {c: runs[c] for c in cases}, '| missing:', missing)

    out_dir = os.path.join(ROOT, 'exports', '%s_%s' % (datetime.date.today().isoformat(), a.tag))
    os.makedirs(os.path.join(out_dir, 'tables'), exist_ok=True)
    size_rows, size_totals = table_size_time(want, reg_cases)
    sheets = [
        ('T1_probe_displacements', table_probes(D, cases, ref)),
        ('T2_region_stress', table_region_stress(D, cases, ref, reg)),
        ('T3_segments_B1B_B2_2B', table_parts(D, cases, ref, reg, only=lambda p: p in reg['segments'].values())),
        ('T4_steelplates_dowels', table_parts(D, cases, ref, reg, only=lambda p: p.startswith(('STEELPLATE', 'DWL')))),
        ('T5_section_series', table_series(D, cases, ref, reg)),
        ('T6_nodal_vs_ref', table_nodal_matches(D, cases, ref, reg)),
        ('T7_elementwise_vs_ref', table_elementwise(D, cases, ref, reg)),
        ('T8_size_time_per_job', size_rows),
        ('T9_size_time_per_case', size_totals),
    ]
    notes = ['Comparison of portalframe substructuring cases (generated %s).' % datetime.datetime.now().isoformat(timespec='seconds'),
             'Reference: %s.  Cases used: %s.  Missing/not extracted: %s.' % (ref, ', '.join(cases), ', '.join(missing) or '-'),
             'Run ids: %s' % json.dumps({c: runs[c] for c in cases}),
             'Units: mm, N, tonne, s -> stress MPa, displacement mm.  Regions: boxes defined on C (study/regions.json).',
             'Stats: max/min = peak values, p95/p05 = 95th/5th percentile, mean = signed mean, mean_abs = mean |value| over all integration-point values in the region.',
             'S11 is the stress in the material 1-direction (parallel to grain for timber; steel/dowel: Mises recommended). Dowels are beam (B31) elements: S11 = axial+bending stress.',
             'Deviation columns dev_<case>_vs_<ref>_% = (case-ref)/|ref|*100; peak values next to dowel holes are mesh dependent -> prefer p95/mean for judging.']
    for name, rows in sheets:
        write_csv(os.path.join(out_dir, 'tables', name + '.csv'), rows)
    write_xlsx(unlocked(os.path.join(out_dir, 'comparison.xlsx')), sheets, cases, ref, None, reg, notes)
    with open(os.path.join(out_dir, 'README.txt'), 'w') as f:
        f.write('\n'.join(notes) + '\n')
    print('wrote', out_dir)


if __name__ == '__main__':
    main()
