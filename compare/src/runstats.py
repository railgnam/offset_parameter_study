"""Model size, solver time and file-size statistics per case (global job + substructure-generation jobs).

Pure stdlib text parsing of the solver .dat files and file system sizes; no Abaqus needed.

  python runstats.py [--cases A B1 C] [--out model_size.csv]

Rows: one per job (role=global / substructure) with nodes, elements, DOFs, CPU/wall/user/system seconds (the final
JOB TIME SUMMARY of the .dat), and file sizes in MB per extension (+ recovery ODBs `<global>_<n>.odb`).
"""
import argparse, csv, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from snapshot import load_registry

EXTS = ['odb', 'inp', 'dat', 'msg', 'sta', 'sim', 'stt', 'mdl', 'prt']
COLS = ['case', 'role', 'job', 'nodes', 'elements', 'dofs', 'cpu_s', 'wall_s', 'user_s', 'system_s',
        'n_recovery_odb', 'recovery_odb_mb'] + ['%s_mb' % e for e in EXTS] + ['total_mb', 'dat_found', 'completed']


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_dat(path):
    out = {'nodes': None, 'elements': None, 'dofs': None, 'cpu_s': None, 'wall_s': None, 'user_s': None, 'system_s': None}
    if not os.path.isfile(path):
        return out
    txt = open(path, errors='replace').read()
    for key, pat in (('elements', r'NUMBER OF ELEMENTS IS\s+(\d+)'), ('nodes', r'NUMBER OF NODES IS\s+(\d+)'),
                     ('dofs', r'TOTAL NUMBER OF VARIABLES IN THE MODEL\s+(\d+)')):
        m = re.search(pat, txt)
        if m:
            out[key] = int(m.group(1))
    # the last JOB TIME SUMMARY block describes the whole job
    blocks = list(re.finditer(r'JOB TIME SUMMARY(.*?)(?=\n\s*\n|\Z)', txt, re.S))
    if blocks:
        b = blocks[-1].group(1)
        for key, pat in (('user_s', r'USER TIME \(SEC\)\s*=\s*([0-9.Ee+\-]+)'), ('system_s', r'SYSTEM TIME \(SEC\)\s*=\s*([0-9.Ee+\-]+)'),
                         ('cpu_s', r'TOTAL CPU TIME \(SEC\)\s*=\s*([0-9.Ee+\-]+)'), ('wall_s', r'WALLCLOCK TIME \(SEC\)\s*=\s*([0-9.Ee+\-]+)')):
            m = re.search(pat, b)
            if m:
                out[key] = _num(m.group(1))
    return out


def mb(path_list):
    return sum(os.path.getsize(p) for p in path_list if os.path.isfile(p)) / 1e6


def job_row(root, case, role, job, stem_dat=None):
    row = {'case': case, 'role': role, 'job': job}
    dat = os.path.join(root, '%s.dat' % job)
    row.update(parse_dat(dat))
    row['dat_found'] = os.path.isfile(dat)
    log = os.path.join(root, '%s.log' % job)
    sta = os.path.join(root, '%s.sta' % job)
    txt = ''.join(open(p, errors='replace').read() for p in (log, sta) if os.path.isfile(p))
    row['completed'] = bool(txt) and ('exited with errors' not in txt) and ('COMPLETED' in txt)
    total = 0.0
    for e in EXTS:
        # substructure generation writes <job>_Z1.sim/.stt/.mdl/.prt next to the .odb/.inp
        files = [os.path.join(root, '%s.%s' % (job, e)), os.path.join(root, '%s_Z1.%s' % (job, e))]
        v = mb(files)
        row['%s_mb' % e] = round(v, 3)
        total += v
    rec = sorted(glob.glob(os.path.join(root, '%s_[0-9]*.odb' % job)))
    row['n_recovery_odb'] = len(rec)
    row['recovery_odb_mb'] = round(mb(rec), 3)
    total += mb(rec)
    row['total_mb'] = round(total, 3)
    return row


def collect(reg, cases=None):
    root = os.path.normpath(os.path.join(reg['_dir'], reg.get('root', '.')))
    rows = []
    for case in cases or reg['order']:
        c = reg['cases'][case]
        jobs = c['jobs']
        rows.append(job_row(root, case, 'global', jobs['global']))
        for s in jobs.get('substructures', []):
            rows.append(job_row(root, case, 'substructure', s))
    return rows


def case_totals(rows):
    """Per case: substructure-generation CPU/wall (one-off), global CPU/wall, and total disk."""
    tot = {}
    for r in rows:
        t = tot.setdefault(r['case'], {'case': r['case'], 'gen_cpu_s': 0.0, 'gen_wall_s': 0.0, 'global_cpu_s': None,
                                       'global_wall_s': None, 'global_dofs': None, 'global_nodes': None, 'total_mb': 0.0})
        if r['role'] == 'substructure':
            t['gen_cpu_s'] += r['cpu_s'] or 0.0
            t['gen_wall_s'] += r['wall_s'] or 0.0
        else:
            t['global_cpu_s'], t['global_wall_s'] = r['cpu_s'], r['wall_s']
            t['global_dofs'], t['global_nodes'] = r['dofs'], r['nodes']
        t['total_mb'] += r['total_mb']
    return list(tot.values())


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', nargs='*')
    ap.add_argument('--out')
    a = ap.parse_args()
    reg = load_registry()
    rows = collect(reg, a.cases)
    if a.out:
        with open(a.out, 'w', newline='', encoding='utf8') as f:
            w = csv.DictWriter(f, COLS)
            w.writeheader()
            w.writerows(rows)
        print('wrote', a.out)
    for r in rows:
        print('%-3s %-12s %-22s nodes=%-8s el=%-8s dof=%-9s cpu=%-7s wall=%-5s total=%.1f MB %s' % (
            r['case'], r['role'], r['job'], r['nodes'], r['elements'], r['dofs'], r['cpu_s'], r['wall_s'], r['total_mb'],
            '' if r['completed'] else '[NOT COMPLETED]'))
    print()
    for t in case_totals(rows):
        print(t)
