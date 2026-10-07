"""Back-up ("snapshot") of the files that make up one case, into store/<case>/<run_id>/.

Pure stdlib. Never modifies the sources; only copies them (or hard-links an identical file already
stored by an earlier snapshot, so unchanged files do not cost disk space twice).

  python snapshot.py --case B1 [--with-sim] [--with-cae] [--force] [--allow-incomplete]
"""
import argparse, csv, datetime, glob, hashlib, json, os, re, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # .../compare
STORE = os.path.join(ROOT, 'store')
MANIFEST = os.path.join(STORE, 'manifest.csv')
SHA_INDEX = os.path.join(STORE, '_sha_index.json')
MANIFEST_COLS = ['case', 'run_id', 'created', 'combined_sha', 'n_files', 'bytes', 'complete', 'with_sim', 'with_cae', 'note']


def load_registry(path=None):
    path = path or os.path.join(ROOT, 'study', 'cases.json')
    with open(path, encoding='utf8') as f:
        reg = json.load(f)
    reg['_dir'] = os.path.dirname(os.path.abspath(path))
    return reg


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def expand(reg, patterns):
    """Glob patterns relative to the registry's `root` (itself relative to the registry folder);
    returns sorted unique existing files."""
    out = []
    base = os.path.normpath(os.path.join(reg['_dir'], reg.get('root', '.')))
    for pat in patterns:
        full = pat if os.path.isabs(pat) else os.path.join(base, pat)
        out.extend(glob.glob(full))
    return sorted({os.path.normpath(p) for p in out if os.path.isfile(p)})


def job_completed(reg, logs):
    """True if every listed solver log/.sta ends with a successful completion marker."""
    notes = []
    for pat in logs:
        for p in expand(reg, [pat]):
            txt = open(p, errors='replace').read()
            ok = ('COMPLETED' in txt and 'exited with errors' not in txt) or 'THE ANALYSIS HAS BEEN COMPLETED' in txt
            notes.append((os.path.basename(p), ok))
    return (len(notes) > 0 and all(ok for _, ok in notes)), notes


def read_manifest():
    if not os.path.exists(MANIFEST):
        return []
    with open(MANIFEST, newline='', encoding='utf8') as f:
        return list(csv.DictReader(f))


def append_manifest(row):
    new = not os.path.exists(MANIFEST)
    os.makedirs(STORE, exist_ok=True)
    with open(MANIFEST, 'a', newline='', encoding='utf8') as f:
        w = csv.DictWriter(f, MANIFEST_COLS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, '') for k in MANIFEST_COLS})


def latest_run(case, run=None):
    rows = [r for r in read_manifest() if r['case'] == case]
    if run:
        rows = [r for r in rows if r['run_id'] == run]
    return rows[-1] if rows else None


def run_dir(case, run_id):
    return os.path.join(STORE, case, run_id)


def snapshot(case, with_sim=False, with_cae=False, force=False, allow_incomplete=False, reg=None):
    reg = reg or load_registry()
    c = reg['cases'][case]
    if c.get('status') in ('missing', 'pending'):
        print('[%s] status=%s (%s) -> nothing to snapshot' % (case, c.get('status'), c.get('status_note', '')))
        return None
    files = c['files']
    groups = {'odb': expand(reg, files.get('odb', [])),
              'inputs': expand(reg, files.get('inputs', []))}
    if with_sim:
        groups['sim'] = expand(reg, files.get('sim', []))
    if with_cae:
        groups['cae'] = expand(reg, files.get('cae', []))
    # back-calculated main-substructure ODBs (written by backcalc/): only when finished = file exists and has not changed for 90 s
    bc, seen_names = [], set()
    for pat in files.get('backcalc', []):                      # patterns in priority order; first file per name wins
        for p in expand(reg, [pat]):
            if os.path.basename(p) not in seen_names and time.time() - os.path.getmtime(p) > 90:
                seen_names.add(os.path.basename(p))
                bc.append(p)
    if bc:
        groups['backcalc'] = bc
    elif files.get('backcalc'):
        print('[%s] back-calculation ODB not (yet) available -> main substructure not included' % case)
    complete, notes = job_completed(reg, files.get('completion_check', []))
    if not complete and not allow_incomplete:
        print('[%s] job(s) not confirmed COMPLETED %s -> refusing (use --allow-incomplete)' % (case, notes))
        return None
    if not groups['odb']:
        print('[%s] no ODB files matched' % case)
        return None

    entries = []   # (group, src, rel, sha, size)
    for g, paths in groups.items():
        for p in paths:
            rel = os.path.join(g, os.path.basename(p))
            entries.append((g, p, rel, sha256(p), os.path.getsize(p)))
    names = [e[2] for e in entries]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        sys.exit('[%s] basename collision inside snapshot groups: %s' % (case, sorted(dup)))
    combined = hashlib.sha256('\n'.join('%s:%s' % (e[2], e[3]) for e in sorted(entries, key=lambda e: e[2])).encode()).hexdigest()

    prev = [r for r in read_manifest() if r['case'] == case and r['combined_sha'] == combined]
    if prev and not force:
        print('[%s] unchanged since run %s -> reusing' % (case, prev[-1]['run_id']))
        return prev[-1]['run_id']

    run_id = '%s_%s' % (datetime.datetime.now().strftime('%Y%m%d-%H%M%S'), combined[:8])
    dst_root = run_dir(case, run_id)
    index = json.load(open(SHA_INDEX)) if os.path.exists(SHA_INDEX) else {}
    total = 0
    for g, src, rel, sha, size in entries:
        dst = os.path.join(dst_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        known = index.get(sha)
        if known and os.path.exists(known):
            try:
                os.link(known, dst)
            except OSError:
                shutil.copy2(src, dst)
        else:
            shutil.copy2(src, dst)
            index[sha] = dst
        total += size
    with open(SHA_INDEX, 'w') as f:
        json.dump(index, f, indent=0)
    with open(os.path.join(dst_root, 'SHA256SUMS'), 'w') as f:
        for g, src, rel, sha, size in sorted(entries, key=lambda e: e[2]):
            f.write('%s  %s\n' % (sha, rel.replace(os.sep, '/')))
    meta = {'case': case, 'run_id': run_id, 'label': c.get('label'), 'created': datetime.datetime.now().isoformat(timespec='seconds'),
            'combined_sha': combined, 'complete': complete, 'completion_notes': notes, 'units': reg.get('units'),
            'abaqus': reg.get('abaqus'), 'step': c.get('step'), 'sources': [{'rel': e[2], 'src': e[1], 'size': e[4],
            'mtime': datetime.datetime.fromtimestamp(os.path.getmtime(e[1])).isoformat(timespec='seconds')} for e in entries]}
    with open(os.path.join(dst_root, 'meta.json'), 'w', encoding='utf8') as f:
        json.dump(meta, f, indent=1)
    append_manifest({'case': case, 'run_id': run_id, 'created': meta['created'], 'combined_sha': combined, 'n_files': len(entries),
                     'bytes': total, 'complete': complete, 'with_sim': with_sim, 'with_cae': with_cae,
                     'note': 'incomplete job' if not complete else ''})
    print('[%s] snapshot %s: %d files, %.1f MB' % (case, run_id, len(entries), total / 1e6))
    return run_id


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--with-sim', action='store_true')
    ap.add_argument('--with-cae', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--allow-incomplete', action='store_true')
    a = ap.parse_args()
    snapshot(a.case, a.with_sim, a.with_cae, a.force, a.allow_incomplete)
