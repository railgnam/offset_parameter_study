"""Build the global deck of a zone-offset specimen from B1-GLOBAL.inp.

The instance list, placements, loads, boundary conditions and output requests are B1's and stay
untouched. What changes is, per Z1 instance: the substructure library it reads (file=), the retained
node coordinates, and how many retained nodes there are -- because a load point that moved to the
other substructure stops being retained on this side.

The global node sets are therefore rebuilt rather than relabelled, by two rules that survive the
interfaces moving:

  * the load and probe sets (LOADSET-*, FO-*, BC-1-FIX) are matched on true global coordinates
    against the canonical point sets read out of B1-GLOBAL. Those points are fixed features of the
    frame -- wall pressure heights, slab points, the support -- and B1 and B2 were verified to carry
    the identical sets, so coordinate matching is exact and is what keeps the applied load constant.
  * TIE-STACK-PLUS/MINUS are the coincident retained-node pairs of the STACK tie: a node of a main
    instance (PLUS) sitting at the same global point as a node of a joint/top/foundation instance
    (MINUS). Being geometric, this follows the interface wherever the offset puts it.

usage: python make_global.py --case D3 [--dir ../work/D3]
"""
import argparse
import os
import re

from deck import Deck, to_global, to_local

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
TEMPLATE = 'B1-GLOBAL.inp'
COORD_TOL = 0.05            # same tolerance backcalc uses to match retained nodes

# substructure library in B1-GLOBAL -> role, and the suffix of the generated deck
LIB_ROLE = {'M52B1': ('joint', ''), 'M52B1main': ('main', 'main'),
            'M52B1top': ('top', 'top'), 'M52B1foundation': ('foundation', 'foundation')}
# node sets matched by coordinate (everything except the stack tie, which is geometric)
COORD_SETS = ('LOADSET-WIND', 'LOADSET-SNOW', 'LOADSET-USER', 'BC-1-FIX',
              'FO-MIDSPAN', 'FO1-U1-topright', 'FO2-U3', 'FO3-BEAM-MID-LEFT',
              'FO4-POST-BOTTOM-CORNER')


def key(p):
    return tuple(round(v / COORD_TOL) for v in p)


class GlobalDeck:
    def __init__(self, path):
        self.d = Deck(path)
        self.nodes = self.d.nodes()                    # true global coordinates
        self.inst = self.d.instance_members()

    def z1_instances(self):
        """[(instance, library, element label, node labels, system)] in deck order."""
        out, cur, sys_cur = [], None, None
        for b in self.d.blocks:
            if b.name == '*system':
                from deck import system_of
                sys_cur = system_of(b.data)
            elif b.name == '*element' and 'z1' in (b.param('type') or '').lower():
                lab, conn = list(Deck._elem_rows(b))[0]
                out.append([cur, b.param('file'), lab, conn, sys_cur, b])
            for t in b.trail:
                m = re.match(r'\*\*\s*PART INSTANCE:\s*(\S+)', t)
                if m:
                    cur, sys_cur = m.group(1), None
        return out


def retained_of(path):
    """[(label, true coordinate)] of a substructure deck's retained nodes, sorted by label.

    Sorted by label because that is the order Abaqus assigns the Z1 element's nodes
    (backcalc/build_backcalc.py relies on the same ordering).
    """
    d = Deck(path)
    rb = d.find('retained nodal dofs')
    rname = rb[0].data[0].split(',')[0].strip()
    nodes = d.nodes()
    labs = sorted(x for x in d.one('nset', nset=rname).members() if isinstance(x, int))
    # which coupling reference set each retained node came from, for the report
    origin = {}
    for c in d.find('coupling'):
        try:
            for n in d.one('nset', nset=c.param('ref node')).members():
                if isinstance(n, int):
                    origin[n] = c.param('constraint name')
        except KeyError:
            pass
    return [(l, nodes[l], origin.get(l, '?')) for l in labs if l in nodes]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--dir')
    a = ap.parse_args()
    wdir = a.dir or os.path.join(ROOT, 'zone_offset', 'work', a.case)

    g = GlobalDeck(os.path.join(ROOT, TEMPLATE))
    insts = g.z1_instances()

    # canonical coordinate sets, straight out of B1-GLOBAL
    canon = {}
    for name in COORD_SETS:
        pts = set()
        for b in g.d.find('nset', nset=name):
            for n in b.members():
                if isinstance(n, int) and n in g.nodes:
                    pts.add(key(g.nodes[n]))
        canon[name] = pts

    report = ['%s global deck from %s' % (a.case, TEMPLATE)]
    new_sets = {name: [] for name in COORD_SETS}
    plus, minus = [], []
    next_label = {}
    spare = [max(g.nodes) if g.nodes else 0]       # first free label above everything in the deck

    for inst, lib, elab, conn, sysm, eblk in insts:
        role, suffix = LIB_ROLE[lib]
        sub = os.path.join(wdir, 'M52%s%s.inp' % (a.case, suffix))
        if not os.path.exists(sub):
            raise SystemExit('missing substructure deck %s -- run make_specimen.py first' % sub)
        ret = retained_of(sub)
        # Reuse this instance's own labels from B1-GLOBAL. They are not contiguous (50360 and 50362
        # are absent), so reusing them rather than renumbering keeps the t=300 rung identical to B1
        # and cannot collide with a neighbouring instance. Extra retained nodes -- which appear when
        # a load point moves into the main substructure -- take labels above everything in the deck.
        labels = list(conn[:len(ret)])
        while len(labels) < len(ret):
            spare[0] += 1
            labels.append(spare[0])
        next_label[inst] = labels

        # emit the node block for this instance, in the sub deck's own (local) frame
        nb = [b for b in g.d.blocks if b.name == '*node'
              and set(l for l, _ in Deck._node_rows(b)) & set(conn)]
        assert len(nb) == 1, 'instance %s: expected one *Node block' % inst
        # B1-GLOBAL lists each instance's nodes in the substructure's OWN frame and lets the
        # instance *System place them (M52B1-1-1 and the mirrored M52B1-1-2 carry identical
        # coordinates), so the sub deck's coordinates go in verbatim.
        rows = []
        for lab, (sublab, p, origin) in zip(labels, ret):
            rows.append('%8d, %13.6f, %13.6f, %13.6f' % (lab, p[0], p[1], p[2]))
        # leave the block alone when nothing actually moves, so the t=300 rung stays line-identical
        # to B1-GLOBAL instead of merely numerically equal to it
        was = [(l, c) for l, c in Deck._node_rows(nb[0])]
        now = [(l, p) for l, (_, p, _) in zip(labels, ret)]
        if not (len(was) == len(now) and all(a == b and max(abs(x[i] - y[i]) for i in range(3))
                                             < 1e-9 for (a, x), (b, y) in zip(was, now))):
            nb[0].data = rows

        # the Z1 connectivity is the retained nodes in label order
        wrapped = []
        for i in range(0, len(labels), 15):
            chunk = labels[i:i + 15]
            line = ('%d, ' % elab if i == 0 else '   ') + ', '.join(str(x) for x in chunk)
            wrapped.append(line + (',' if i + 15 < len(labels) else ''))
        eblk.data = wrapped
        eblk.kw = re.sub(r'file\s*=\s*[\w.-]+', 'file=M52%s%s' % (a.case, suffix), eblk.kw)

        # classify each retained node
        for lab, (sublab, p, origin) in zip(labels, ret):
            k = key(to_global(p, sysm) if sysm else p)      # where the instance actually puts it
            for name in COORD_SETS:
                if k in canon[name]:
                    new_sets[name].append(lab)
            (plus if role == 'main' else minus).append((lab, k))
        report.append('  %-20s %-16s %2d retained (%s)'
                      % (inst, 'M52%s%s' % (a.case, suffix), len(ret),
                         ', '.join(sorted({o for _, _, o in ret}))))

    # the stack tie: coincident main / non-main retained node pairs
    mk = {}
    for lab, k in minus:
        mk.setdefault(k, []).append(lab)
    tie_plus, tie_minus = [], []
    for lab, k in plus:
        if k in mk:
            tie_plus.append(lab)
            tie_minus.extend(mk[k])
    tie_minus = sorted(set(tie_minus))
    report.append('  STACK tie: %d main-side / %d joint-side coincident nodes'
                  % (len(tie_plus), len(tie_minus)))
    if len(tie_plus) != len(tie_minus):
        report.append('  WARNING stack tie is not one-to-one')

    # rewrite the global node sets: one block per set, the rest emptied out
    done = set()
    for b in list(g.d.blocks):
        if b.name != '*nset':
            continue
        nm = (b.param('nset') or '').upper()
        target = {'TIE-STACK-PLUS': tie_plus, 'TIE-STACK-MINUS': tie_minus}.get(nm)
        if target is None:
            for name in COORD_SETS:
                if nm == name.upper():
                    target = sorted(set(new_sets[name]))
        if target is None:
            continue
        if nm in done:
            g.d.delete_block(b)
        else:
            # same reasoning: an unchanged set keeps its original 'generate' form
            cur = sorted({x for x in b.members() if isinstance(x, int)})
            if cur != sorted(set(target)):
                b.set_members(target)
            done.add(nm)

    out = os.path.join(wdir, '%s-GLOBAL.inp' % a.case)
    g.d.write(out)
    for name in COORD_SETS:
        report.append('  %-26s %3d nodes' % (name, len(set(new_sets[name]))))
    report.append('  -> %s' % out)
    print('\n'.join(report))


if __name__ == '__main__':
    main()
