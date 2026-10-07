"""Generate, verify and solve one zone-offset specimen (system python, stdlib only).

  python run_specimens.py --case D3 --datacheck     # generate + verify + Abaqus datacheck only
  python run_specimens.py --case D3                 # ... then generate the 4 substructures and solve
  python run_specimens.py --case D3 --skip-generate  # solve decks that are already there

Abaqus is launched the way compare/src/run_study.py does it -- one pre-quoted 'cmd /c "..."' string
with stdin closed -- because the wrapper can hang silently otherwise. Every job runs with the work
directory as its cwd, so the .jnl/.rpy/.sta litter and the generated .sim files stay inside
work/<case>/ instead of the repo root.
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
ABAQUS = r'C:\SIMULIA\Commands\abaqus.bat'

# substructure generations first, then the global job that reads their .sim files
def job_order(case):
    return ['M52%s' % case, 'M52%smain' % case, 'M52%stop' % case,
            'M52%sfoundation' % case, '%s-GLOBAL' % case]


def run(step, args, cwd, log=None):
    """Launch Abaqus and, when asked, keep its console output as <job>.log.

    'interactive' makes the call block, which is what lets the jobs be sequenced -- but it streams
    the log to the console instead of writing <job>.log. The comparison pipeline gates on that file
    (compare/src/snapshot.py: job_completed), and the existing A/B1/B2/C cases all have one, so the
    captured output is written there verbatim.
    """
    cmd = 'cmd /c "%s"' % ('call "%s" %s' % (ABAQUS, args))
    print('>> [%s] %s' % (step, cmd))
    r = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = r.stdout or ''
    sys.stdout.write(out)
    if log:
        with open(os.path.join(cwd, log), 'w', newline='\n') as fh:
            fh.write(out)
    return r.returncode


def py(script, args):
    r = subprocess.run([sys.executable, os.path.join(HERE, script)] + args,
                       cwd=HERE, stdin=subprocess.DEVNULL)
    return r.returncode


def completed(wdir, job):
    """True when the job finished, judged the way compare/src/snapshot.py judges it."""
    for name in (job + '.log', job + '.sta'):
        p = os.path.join(wdir, name)
        if os.path.exists(p):
            txt = open(p, errors='replace').read()
            if 'COMPLETED' in txt and 'exited with errors' not in txt:
                return True
    return False


def errors_in(wdir, job):
    """Lines worth showing from a .dat/.msg when a job did not complete."""
    out = []
    for ext in ('.dat', '.msg'):
        p = os.path.join(wdir, job + ext)
        if not os.path.exists(p):
            continue
        txt = open(p, errors='replace').read()
        for m in re.finditer(r'^.*\*\*\*ERROR.*$', txt, re.M):
            out.append('%s: %s' % (job + ext, m.group(0).strip()))
    return out[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--datacheck', action='store_true',
                    help='only check that Abaqus accepts the decks; no substructures, no solve')
    ap.add_argument('--skip-generate', action='store_true')
    ap.add_argument('--cpus', type=int, default=4)
    a = ap.parse_args()
    wdir = os.path.join(ROOT, 'zone_offset', 'work', a.case)

    if not a.skip_generate:
        for script in ('make_specimen.py', 'make_global.py', 'verify_specimen.py'):
            if py(script, ['--case', a.case]):
                raise SystemExit('%s failed for %s -- nothing submitted' % (script, a.case))
        print('[%s] generated and verified' % a.case)

    jobs = job_order(a.case)
    if a.datacheck:
        bad = []
        for j in jobs:
            if j.endswith('-GLOBAL') and not os.path.exists(
                    os.path.join(wdir, 'M52%s_Z1.sim' % a.case)):
                print('[%s] %-20s skipped: the global deck reads the .sim files, which only exist '
                      'once the substructures have been generated' % (a.case, j))
                continue
            rc = run('datacheck', 'job=%s datacheck interactive cpus=1' % j, wdir)
            # a datacheck writes no .log, so judge it by the .dat: present and free of ***ERROR
            dat = os.path.join(wdir, j + '.dat')
            ok = rc == 0 and os.path.exists(dat) and \
                '***ERROR' not in open(dat, errors='replace').read()
            print('[%s] %-20s datacheck rc=%s accepted=%s' % (a.case, j, rc, ok))
            if not ok:
                bad.append(j)
                for e in errors_in(wdir, j):
                    print('    ' + e)
        if bad:
            raise SystemExit('datacheck failed: %s' % ', '.join(bad))
        print('[%s] every deck accepted by Abaqus' % a.case)
        return

    for j in jobs:
        rc = run('solve', 'job=%s interactive cpus=%d' % (j, a.cpus), wdir, log=j + '.log')
        if not completed(wdir, j):
            for e in errors_in(wdir, j):
                print('    ' + e)
            raise SystemExit('[%s] %s did not complete (rc=%s) -- stopping before the next job'
                             % (a.case, j, rc))
        print('[%s] %-20s COMPLETED' % (a.case, j))
    print('[%s] all jobs completed' % a.case)


if __name__ == '__main__':
    main()
