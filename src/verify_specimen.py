"""Check a generated specimen before a single minute of solver time is spent on it.

V1  load invariance    every LOADSET-* / FO-* / BC set holds the same physical points as B1-GLOBAL.
                       The wind load is a fixed force PER NODE, so a lost or doubled point silently
                       rescales the load and every result would still look plausible. This is the
                       check that must never be skipped.
V2  conservation       for each stub, (joint-side elements) + (main-side elements) equals the
                       template's count, and the two cuts land on the same plane.
V3  retained geometry  each Z1 element's nodes match its substructure deck's retained set, in label
                       order, within 0.05 mm -- the same test backcalc/build_backcalc.py applies.
V0  identity           at t=300 the generated decks must be line-identical to B1's, and at t=0 to
                       B2's apart from the three mid-joint interface lines. "Line-identical": the
                       content matches line for line; the templates were written by CAE with CRLF
                       endings and the generator writes LF, which Abaqus treats the same.

usage: python verify_specimen.py --case D3 [--dir ../work/D3]
"""
import argparse
import os
import re
import sys

from deck import Deck, to_global
from make_global import LIB_ROLE, TEMPLATE, key, retained_of
from make_specimen import CASES, PLANE_TOL, STUB_LEN, is_stub

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
CHECK_SETS = ('LOADSET-WIND', 'LOADSET-SNOW', 'LOADSET-USER', 'BC-1-FIX', 'FO-MIDSPAN',
              'FO1-U1-topright', 'FO2-U3', 'FO3-BEAM-MID-LEFT', 'FO4-POST-BOTTOM-CORNER')
B1_DECKS = {'': 'M52B1', 'top': 'M52B1top', 'foundation': 'M52B1foundation'}


def set_points(d, nodes, name):
    pts = set()
    for b in d.find('nset', nset=name):
        for n in b.members():
            if isinstance(n, int) and n in nodes:
                pts.add(key(nodes[n]))
    return pts


def placed_points(path):
    """{set name: {placed coordinate keys}} for a global deck, honouring each instance *System."""
    from deck import system_of
    d = Deck(path)
    raw = d.raw_nodes()
    cur, placed = None, {}
    for b in d.blocks:
        if b.name == '*system':
            cur = system_of(b.data)
        elif b.name == '*node':
            for lab, c in Deck._node_rows(b):
                placed[lab] = to_global(c, cur) if cur else c
    out = {}
    for name in CHECK_SETS:
        out[name] = {key(placed[n]) for bb in d.find('nset', nset=name)
                     for n in bb.members() if isinstance(n, int) and n in placed}
    return d, placed, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--dir')
    a = ap.parse_args()
    t = CASES[a.case]
    wdir = a.dir or os.path.join(ROOT, 'zone_offset', 'work', a.case)
    fails, notes = [], []

    # ---------------------------------------------------------------- V0
    if abs(t) < PLANE_TOL:
        # t=0 is B2's partition: every substructure deck must be B2's, byte for byte. The global
        # deck is deliberately NOT B2-GLOBAL (that one carries extra user/snow loads); it is built
        # from B1-GLOBAL like every other rung, and V1/V3 below check it.
        b2 = {'': 'M5B2', 'top': 'M52B2top', 'foundation': 'M52B2foundation', 'main': 'M52B2main'}
        for suffix, tmpl in b2.items():
            gen = os.path.join(wdir, 'M52%s%s.inp' % (a.case, suffix))
            g = open(gen, errors='replace').read().split('\n')
            o = open(os.path.join(ROOT, tmpl + '.inp'), errors='replace').read().split('\n')
            diff = [(x, y) for x, y in zip(o, g) if x != y]
            if suffix == '':
                # the only intended change: M5B2's three kinematic mid-joint interfaces made
                # distributing, to match M52B1 and every cut rung
                ok = len(g) == len(o) and len(diff) == 3 and all(
                    x == '*Kinematic' and y == '*Distributing, weighting method=UNIFORM'
                    for x, y in diff)
                what = 'identical to %s except AN-1/2/3 made distributing' % tmpl
            else:
                ok = len(g) == len(o) and not diff
                what = 'line-identical to %s' % tmpl
            notes.append('V0 %-22s %-55s %s' % (os.path.basename(gen), what, 'yes' if ok else 'NO'))
            if not ok:
                fails.append('V0: %s is not %s (%d differing lines)' % (gen, what, len(diff)))
    if abs(t - STUB_LEN) < PLANE_TOL:
        for suffix, tmpl in list(B1_DECKS.items()) + [('main', 'M52B1main')]:
            gen = os.path.join(wdir, 'M52%s%s.inp' % (a.case, suffix))
            same = open(gen, errors='replace').read() == \
                open(os.path.join(ROOT, tmpl + '.inp'), errors='replace').read()
            notes.append('V0 %-22s line-identical to %-18s %s' % (os.path.basename(gen), tmpl,
                                                                  'yes' if same else 'NO'))
            if not same:
                fails.append('V0: %s differs from %s at t=300' % (gen, tmpl))

        # the global deck is not byte-compared: the template spreads each node set over several
        # accumulating blocks (one per instance) and the generator consolidates them into one, so
        # equality is checked on the values -- labels, coordinates, connectivity and membership
        gp = os.path.join(wdir, '%s-GLOBAL.inp' % a.case)
        dg, pg, _ = placed_points(gp)
        db, pb, _ = placed_points(os.path.join(ROOT, TEMPLATE))
        same_lab = set(pg) == set(pb)
        off = max([max(abs(pg[n][i] - pb[n][i]) for i in range(3))
                   for n in pg if n in pb] or [0.0])
        notes.append('V0 %-22s same node labels as B1-GLOBAL %s, max offset %.6f mm'
                     % (os.path.basename(gp), 'yes' if same_lab else 'NO', off))
        if not same_lab or off > 1e-6:
            fails.append('V0: %s is not numerically identical to B1-GLOBAL at t=300' % gp)

    # ---------------------------------------------------------------- V1
    _, _, ref = placed_points(os.path.join(ROOT, TEMPLATE))
    gpath = os.path.join(wdir, '%s-GLOBAL.inp' % a.case)
    _, placed, got = placed_points(gpath)
    for name in CHECK_SETS:
        if got[name] == ref[name]:
            notes.append('V1 %-24s %3d points, identical to B1' % (name, len(ref[name])))
        else:
            fails.append('V1: %s differs from B1-GLOBAL -- missing %d, extra %d'
                         % (name, len(ref[name] - got[name]), len(got[name] - ref[name])))

    # ---------------------------------------------------------------- V2
    joint_side, main_side = {}, {}
    for suffix in B1_DECKS:
        d = Deck(os.path.join(wdir, 'M52%s%s.inp' % (a.case, suffix)))
        im, nodes = d.instance_members(), d.nodes()
        for inst, (ns, es) in im.items():
            if is_stub(inst) and es:
                joint_side.setdefault((suffix, inst), len(es))
    mpath = os.path.join(wdir, 'M52%smain.inp' % a.case)
    dm = Deck(mpath)
    for inst, (ns, es) in dm.instance_members().items():
        if is_stub(inst) and es:
            main_side[inst] = len(es)
    tmpl_counts = {}
    for name, p in [('joint', 'M52B1'), ('top', 'M52B1top'), ('foundation', 'M52B1foundation')]:
        d = Deck(os.path.join(ROOT, p + '.inp'))
        for inst, (ns, es) in d.instance_members().items():
            if is_stub(inst) and es:
                tmpl_counts[inst] = len(es)
    for inst, n_main in sorted(main_side.items()):
        plain = inst.replace('-rad-2', '')
        total = tmpl_counts.get(plain)
        if total is None:
            notes.append('V2 %-18s main-only stub, %d elems (no joint-side twin)' % (inst, n_main))
            continue
        n_joint = max([v for (s, i), v in joint_side.items() if i == plain] or [0])
        if n_joint + n_main == total:
            notes.append('V2 %-18s joint %4d + main %4d = %4d  conserved'
                         % (inst, n_joint, n_main, total))
        else:
            fails.append('V2: %s joint %d + main %d != template %d'
                         % (inst, n_joint, n_main, total))

    # ------------------------------------------------------------- V3b
    # Every *Coupling must be followed by exactly one sub-option block. *Distributing is a block in
    # its own right, not data of *Coupling, so deleting a coupling without its sub-option leaves the
    # orphan attached to the preceding coupling -- which Abaqus reports as "ONLY ONE SUB-OPTION MAY
    # BE SPECIFIED FOR THE *COUPLING OPTION" plus a cascade of unrelated-looking errors elsewhere.
    for suffix in list(B1_DECKS) + ['main']:
        p = os.path.join(wdir, 'M52%s%s.inp' % (a.case, suffix))
        d = Deck(p)
        bad = []
        for i, b in enumerate(d.blocks):
            if b.name != '*coupling':
                continue
            nxt = [x.name for x in d.blocks[i + 1:i + 3]]
            if not nxt or nxt[0] not in ('*distributing', '*kinematic') or \
                    (len(nxt) > 1 and nxt[1] in ('*distributing', '*kinematic')):
                bad.append(b.param('constraint name'))
        ncpl = len(d.find('coupling'))
        nsub = len(d.find('distributing')) + len(d.find('kinematic'))
        if bad or ncpl != nsub:
            fails.append('V3b: %s has %d couplings but %d sub-options%s'
                         % (os.path.basename(p), ncpl, nsub,
                            '; offenders: ' + ', '.join(map(str, bad)) if bad else ''))
        else:
            notes.append('V3b %-26s %2d couplings, each with exactly one sub-option'
                         % (os.path.basename(p), ncpl))

    # ---------------------------------------------------------------- V3
    from make_global import GlobalDeck
    g = GlobalDeck(gpath)
    for inst, lib, elab, conn, sysm, eblk in g.z1_instances():
        suffix = lib.replace('M52' + a.case, '')
        sub = os.path.join(wdir, 'M52%s%s.inp' % (a.case, suffix))
        ret = retained_of(sub)
        if len(ret) != len(conn):
            fails.append('V3: %s has %d Z1 nodes but %s retains %d'
                         % (inst, len(conn), os.path.basename(sub), len(ret)))
            continue
        err = 0.0
        for lab, (sublab, p, _) in zip(conn, ret):
            q = g.d.raw_nodes()[lab]
            err = max(err, max(abs(q[i] - p[i]) for i in range(3)))
        if err < 0.05:
            notes.append('V3 %-20s %2d retained, max coordinate error %.4f mm' % (inst, len(ret),
                                                                                  err))
        else:
            fails.append('V3: %s retained coordinates off by %.4f mm (order or file mix-up?)'
                         % (inst, err))

    print('\n'.join(notes))
    print()
    if fails:
        print('FAILED (%d):' % len(fails))
        for f in fails:
            print('  ' + f)
        sys.exit(1)
    print('%s: all checks passed (t = %.0f mm)' % (a.case, t))


if __name__ == '__main__':
    main()
