"""Generate the substructure decks of one zone-offset specimen from the frozen B1/B2 templates.

The only parameter is t, the length of timber kept inside the joint substructure beyond the corner
block.  B2 is t=0, B1 is t=300.  Each of the three 300 mm stubs (post below, post above, beam end)
is a uniform 10-layer extrusion of 30 mm, so a cut at a multiple of 30 splits existing element
layers: no geometry, no remeshing, and the mesh stays bit-identical to B1's and B2's.

Joint side  (M52<case>, ...top, ...foundation)  keeps t      of each stub, from the corner block.
Main  side  (M52<case>main)                     keeps 300-t  of each stub, from the far end.

Nothing is hard-coded per rung: the cut plane, its axis, which instance it belongs to, which
reference node rides on it and which other surfaces share that face are all read out of the deck,
so the same code serves every offset and both frame lines.

usage: python make_specimen.py --case D3 [--outdir ../work/D3]
"""
import argparse
import os

from deck import FACES, TOL, Block, Deck

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
AXIS = 'XYZ'

STUB_PREFIXES = ('B1B', 'B1E', 'B2_2B')     # the three 300 mm stubs, on either frame line
LOAD_COUPLINGS = ('AN-4-SLAB', 'AN-5-WALL', 'AN-5-WALL-R')
CUT_SURFACES = ('AN-1', 'AN-2', 'AN-3')     # the substructure interfaces
STUB_LEN = 300.0

# Comparing a nominal reference-node position against a mesh plane: the mesh step is 29.9985, not
# 30, so nominal and actual differ by ~1e-3 after ten layers. The nearest distinct plane is 30 mm
# away, so a tolerance far above that drift and far below the spacing is unambiguous. (0.05 mm is
# also what backcalc/build_backcalc.py uses to match retained nodes.)
PLANE_TOL = 0.05

# offset t (mm) kept inside the joint substructure
def load_cases():
    """{case: offset t in mm}, read from zone_offset/params.csv -- the only place an offset is set."""
    import csv
    path = os.path.join(ROOT, 'zone_offset', 'params.csv')
    with open(path, newline='', encoding='utf8') as fh:
        return {r['case'].strip(): float(r['offset_mm']) for r in csv.DictReader(fh)
                if r['case'].strip()}


CASES = load_cases()

# The two ends of the ladder need no cutting at all: every deck is a template copied verbatim.
# t=0 keeps nothing of the stubs in the joint substructures -- that is B2's partition -- and t=300
# keeps everything, which is B1's. Only the global deck is generated, from the same wind-only
# B1-GLOBAL template as every other rung, which is what makes the ends comparable with the middle.
VERBATIM = {0.0: {'': 'M5B2', 'top': 'M52B2top', 'foundation': 'M52B2foundation',
                  'main': 'M52B2main'},
            STUB_LEN: {'main': 'M52B1main'}}


def to_distributing(d):
    """Make the mid-joint interfaces AN-1/2/3 distributing, as they are in M52B1 and every cut rung.

    The originals are not consistent here: B1's mid joint (M52B1) couples its interfaces with
    *Distributing, B2's (M5B2) with *Kinematic, while the top and foundation joints are kinematic in
    both. Copying M5B2 unchanged would give the t=0 rung a different boundary idealisation from the
    rest of the ladder, so its three sub-option lines are switched and nothing else is touched.
    """
    switched = []
    for i, b in enumerate(d.blocks):
        if b.name == '*coupling' and (b.param('constraint name') or '').upper() in CUT_SURFACES:
            sub = d.blocks[i + 1]
            if sub.name == '*kinematic':
                sub.kw, sub.data = '*Distributing, weighting method=UNIFORM', []
                switched.append(b.param('constraint name'))
    return switched

# role -> (template deck, output suffix)
ROLES = [('joint', 'M52B1', ''),
         ('top', 'M52B1top', 'top'),
         ('foundation', 'M52B1foundation', 'foundation'),
         ('main', 'M52B2main', 'main')]


def is_stub(name):
    n = (name or '').upper()
    return any(n.startswith(p + '-') or n == p for p in STUB_PREFIXES)


def face_plane(nodes, conn, code):
    """(axis, value) if the given element face is planar along one axis, else None."""
    try:
        pts = [nodes[conn[i - 1]] for i in FACES[code]]
    except (KeyError, IndexError):
        return None
    for ax in range(3):
        v = [p[ax] for p in pts]
        if max(v) - min(v) < TOL:
            return ax, sum(v) / 4.0
    return None


class Cut:
    """One stub instance cut back to a new interface plane."""

    def __init__(self, inst, ax, p_old, p_new, anchor, kept_e, gone_n, gone_e, surface):
        self.inst, self.ax, self.p_old, self.p_new = inst, ax, p_old, p_new
        self.anchor, self.kept_e, self.gone_n, self.gone_e = anchor, kept_e, gone_n, gone_e
        self.surface = surface
        # t=300 keeps the whole stub: leave the deck untouched so that rung is provably identical
        # to B1 rather than merely equivalent to it
        self.noop = not gone_e and abs(p_new - p_old) < PLANE_TOL


class Specimen:
    def __init__(self, d, report):
        self.d = d
        self.nodes = d.nodes()
        self.elems = d.elements()
        self.inst = d.instance_members()
        self.inst_of = {lab: nm for nm, (_, es) in self.inst.items() for lab in es}
        self.report = report
        self.cuts = []

    def bbox(self, inst):
        """Extent of an instance's real geometry.

        Taken from the nodes its elements actually use, not from the instance's node block: the
        assembly-level coupling reference nodes are written after the last part section and would
        otherwise be attributed to it, inflating that box until every point looked 'inside' it.
        """
        ns = {n for e in self.inst[inst][1] for n in self.elems.get(e, ())}
        pts = [self.nodes[n] for n in ns if n in self.nodes]
        if not pts:
            return None
        return ([min(p[a] for p in pts) for a in range(3)],
                [max(p[a] for p in pts) for a in range(3)])

    def elems_of(self, elset_name, inst=None):
        out = []
        for b in self.d.find('elset', elset=elset_name):
            for lab in b.members():
                if isinstance(lab, int) and lab in self.elems:
                    if inst is None or self.inst_of.get(lab) == inst:
                        out.append(lab)
        return out

    def surface_rows(self, s):
        """[(elset name, face code)] of an element-based *Surface block."""
        out = []
        for l in s.data:
            v = [t.strip() for t in l.split(',') if t.strip()]
            if len(v) == 2:
                out.append((v[0], v[1]))
        return out

    # ------------------------------------------------------------------ cuts
    def plan_cuts(self, keep_len):
        """Work out, per stub instance carrying an interface, what survives the cut."""
        for s in self.d.find('surface'):
            sname = s.param('name')
            if (sname or '').upper() not in CUT_SURFACES:
                continue
            per = {}
            for en, code in self.surface_rows(s):
                for lab in self.elems_of(en):
                    per.setdefault(self.inst_of.get(lab, '?'), []).append((code, lab))
            for inst, entries in sorted(per.items()):
                if not is_stub(inst):
                    self.report.append('    %-6s on %-16s not a stub, left alone' % (sname, inst))
                    continue
                planes = {face_plane(self.nodes, self.elems[l], c) for c, l in entries}
                planes = {(a, round(v, 3)) for a, v in planes if a is not None}
                if len(planes) != 1:
                    raise SystemExit('%s/%s: interface is not planar: %s' % (sname, inst, planes))
                ax, p_old = planes.pop()
                lo, hi = self.bbox(inst)
                anchor = lo[ax] if abs(hi[ax] - p_old) < PLANE_TOL else hi[ax]
                if abs(abs(p_old - anchor) - STUB_LEN) > 1.0:
                    raise SystemExit('%s/%s: stub is %.3f mm along %s, expected %.0f -- this is not'
                                     ' a 300 mm stub' % (sname, inst, abs(p_old - anchor),
                                                         AXIS[ax], STUB_LEN))
                sgn = 1.0 if p_old > anchor else -1.0
                keep_n = {n for n in self.inst[inst][0]
                          if sgn * (self.nodes[n][ax] - anchor) <= keep_len + TOL}
                gone_n = self.inst[inst][0] - keep_n
                gone_e = {e for e in self.inst[inst][1]
                          if any(n in gone_n for n in self.elems[e])}
                kept_e = self.inst[inst][1] - gone_e
                if not kept_e:
                    raise SystemExit('%s/%s: keep %.1f mm leaves no elements' % (sname, inst,
                                                                                 keep_len))
                # the exact surviving node plane, not the nominal offset: the mesh step is 29.9985,
                # and taking it from the mesh is what makes the joint and main cuts coincide.
                p_new = (max if sgn > 0 else min)(self.nodes[n][ax] for n in keep_n)
                self.cuts.append(Cut(inst, ax, p_old, p_new, anchor, kept_e, gone_n, gone_e,
                                     sname))
                ref = self.ref_node_on(sname, ax, p_old, inst)
                if ref is not None and not self.cuts[-1].noop:
                    self.d.move_node(ref, ax, round(p_new, 3))
                self.report.append(
                    '    %-6s %-16s %s %9.3f -> %9.3f  keep %5.1f mm  %4d/%4d elems  ref %s'
                    % (sname, inst, AXIS[ax], p_old, p_new, abs(p_new - anchor),
                       len(kept_e), len(self.inst[inst][1]), ref))
        return self.cuts

    def ref_node_on(self, sname, ax, plane, inst):
        """The coupling reference node of `sname` sitting on this instance's interface."""
        try:
            members = [x for x in self.d.one('nset', nset=sname).members() if isinstance(x, int)]
        except KeyError:
            return None
        box = self.bbox(inst)
        if box is None:
            return None
        lo, hi = box
        for n in members:
            c = self.nodes.get(n)
            if c is None or abs(c[ax] - plane) > 1.0:
                continue
            if all(lo[a] - 1.0 <= c[a] <= hi[a] + 1.0 for a in range(3) if a != ax):
                return n
        return None

    # -------------------------------------------------------------- surfaces
    def rewrite_cut_surfaces(self):
        """Re-point every surface that lay on a cut face onto the new face layer.

        Besides the interfaces themselves this catches the leftover surfaces CAE wrote on the same
        face (CP-*, TIE-GLM*, AAA): they are unused in the deck they appear in, but a *Surface
        pointing at an emptied *Elset is an input error, so they move with the cut.

        Surfaces are rebuilt for all their cut instances at once, because CAE writes one *Elset per
        instance under a single shared name -- rewriting them one instance at a time would discard
        the sibling instance's faces.
        """
        by_inst = {c.inst: c for c in self.cuts if not c.noop}
        for s in list(self.d.find('surface')):
            sname = s.param('name')
            rows, mine, elsets = [], [], set()
            for en, code in self.surface_rows(s):
                hit = [i for i in by_inst if self.elems_of(en, i)]
                if hit:
                    mine.append((en, code, hit))
                    elsets.add(en)
                else:
                    rows.append('%s, %s' % (en, code))
            if not mine:
                continue
            # only move a surface that lies wholly on the cut planes; one that merely touches the
            # stub from another direction (the wall face at X=0) is left to the label purge
            on_cut = True
            for en, code, hits in mine:
                for i in hits:
                    for lab in self.elems_of(en, i):
                        fp = face_plane(self.nodes, self.elems[lab], code)
                        if not fp or fp[0] != by_inst[i].ax or \
                                abs(fp[1] - by_inst[i].p_old) > PLANE_TOL:
                            on_cut = False
            if not on_cut:
                continue
            by_code = {}
            for i in {i for _, _, h in mine for i in h}:
                c = by_inst[i]
                for e in sorted(c.kept_e):
                    for code in FACES:
                        fp = face_plane(self.nodes, self.elems[e], code)
                        if fp and fp[0] == c.ax and abs(fp[1] - c.p_new) < PLANE_TOL:
                            by_code.setdefault(code, []).append(e)
            for en in elsets:
                for b in self.d.find('elset', elset=en):
                    self.d.delete_block(b)
            for code in sorted(by_code):
                en = '_%s_%s' % (sname, code)
                b = Block('*Elset, elset=%s' % en)
                b.set_members(by_code[code])
                self.d.blocks.insert(self.d.blocks.index(s), b)
                rows.append('%s, %s' % (en, code))
            s.data = rows
            self.report.append('    surface %-28s -> %s' % (
                sname, ', '.join('%s:%d' % (c, len(v)) for c, v in sorted(by_code.items()))))

    # ------------------------------------------------------------ ref nodes
    def prune_load_refs(self, cut_planes, drop_on_plane):
        """Drop load reference nodes that no longer lie in this deck's geometry.

        A point exactly on the cut belongs to the joint substructure, so the main deck drops it and
        the joint deck keeps it. Without that tie-break the rung at t=150 -- where every wall and
        slab reference point lands exactly on the cut -- would apply its loads in both
        substructures at once, silently changing the total load.
        """
        boxes = [b for b in (self.bbox(i) for i in self.inst) if b]
        dropped = []
        for c in self.d.find('coupling'):
            cname = (c.param('constraint name') or '').upper()
            if cname not in [x.upper() for x in LOAD_COUPLINGS]:
                continue
            try:
                blk = self.d.one('nset', nset=c.param('ref node'))
            except KeyError:
                continue
            keep = []
            for n in blk.members():
                if not isinstance(n, int) or n not in self.nodes:
                    keep.append(n)
                    continue
                p = self.nodes[n]
                on_cut = any(abs(p[a] - v) < PLANE_TOL for a, v in cut_planes)
                inside = any(all(lo[a] - PLANE_TOL <= p[a] <= hi[a] + PLANE_TOL for a in range(3))
                             for lo, hi in boxes)
                if inside and not (drop_on_plane and on_cut):
                    keep.append(n)
                else:
                    dropped.append((cname, n, p))
            if len(keep) != len(blk.members()):
                blk.set_members(keep)
        return dropped

    def drop_dead_couplings(self):
        """Remove a load coupling whose reference node migrated to the other substructure.

        The real t=0 model does the same thing in effect: M52B2top keeps a vestigial AN-5-WALL
        coupling but leaves its reference node out of the retained set, so the wall load over that
        face is applied from whichever substructure owns the stub. Deleting the coupling outright is
        load-equivalent and leaves no dangling reference. The resulting change in how that load
        spreads is the partitioning effect this study measures, not an error.
        """
        removed = []
        for c in list(self.d.find('coupling')):
            cname = c.param('constraint name')
            if (cname or '').upper() not in [x.upper() for x in LOAD_COUPLINGS]:
                continue
            rs, sf = c.param('ref node'), c.param('surface')
            try:
                blk = self.d.one('nset', nset=rs)
            except KeyError:
                continue
            if [x for x in blk.members() if isinstance(x, int)]:
                continue
            # *Distributing / *Kinematic is a block of its own, not data of *Coupling, so the
            # sub-option must go with it. Left behind, it attaches to the preceding coupling and
            # Abaqus rejects the deck with "ONLY ONE SUB-OPTION MAY BE SPECIFIED FOR THE *COUPLING
            # OPTION", followed by a cascade of unrelated-looking influence-radius errors.
            i = self.d.blocks.index(c)
            doomed = [c]
            j = i + 1
            while j < len(self.d.blocks) and \
                    self.d.blocks[j].name in ('*distributing', '*kinematic'):
                doomed.append(self.d.blocks[j])
                j += 1
            for b in doomed:
                self.d.delete_block(b)
            for b in self.d.find('nset', nset=rs):
                self.d.delete_block(b)
            for s in list(self.d.find('surface', name=sf)):
                for en, _ in self.surface_rows(s):
                    for b in self.d.find('elset', elset=en):
                        self.d.delete_block(b)
                self.d.delete_block(s)
            removed.append(cname)
        return removed

    def prune_retained(self):
        """Keep the retained set in step with the reference nodes that survived.

        Every retained node in these decks is a coupling reference node (checked for all four
        templates), so the retained set is exactly the set of live reference nodes.
        """
        rb = self.d.find('retained nodal dofs')
        if not rb or not rb[0].data:
            return []
        blk = self.d.one('nset', nset=rb[0].data[0].split(',')[0].strip())
        live = set()
        for c in self.d.find('coupling'):
            try:
                live.update(x for x in self.d.one('nset', nset=c.param('ref node')).members()
                            if isinstance(x, int))
            except KeyError:
                pass
        before = blk.members()
        keep = [n for n in before if not isinstance(n, int) or n in live]
        if len(keep) != len(before):
            blk.set_members(keep)
        return [n for n in before if n not in keep]


def build(role, template, keep_len, out, report):
    report.append('  %-10s <- %-16s keep %5.1f mm' % (role, template + '.inp', keep_len))
    d = Deck(os.path.join(ROOT, template + '.inp'))
    sp = Specimen(d, report)
    cuts = sp.plan_cuts(keep_len)
    sp.rewrite_cut_surfaces()
    planes = [(c.ax, c.p_new) for c in cuts]
    d.drop(nodes=set().union(*[c.gone_n for c in cuts]),
           elems=set().union(*[c.gone_e for c in cuts]))

    # the geometry changed, so re-read it before deciding which load points still sit inside it
    sp2 = Specimen(d, report)
    for cname, n, p in sp2.prune_load_refs(planes, drop_on_plane=(role == 'main')):
        report.append('    load point moves to the other substructure: %-12s node %d '
                      '(%.3f, %.3f, %.3f)' % (cname, n, p[0], p[1], p[2]))
    for cname in sp2.drop_dead_couplings():
        report.append('    coupling %s removed: its load point now belongs to the other '
                      'substructure' % cname)
    gone = sp2.prune_retained()
    if gone:
        report.append('    retained set loses %d node(s): %s' % (len(gone), gone))
    empt = sorted({n for _, n in d.empty_sets()})
    if empt:
        report.append('    WARNING empty sets: %s' % empt)
    rname = d.find('retained nodal dofs')[0].data[0].split(',')[0].strip()
    nret = len([x for x in d.one('nset', nset=rname).members() if isinstance(x, int)])
    d.write(out)
    report.append('    -> %-26s dropped %d nodes, %d elements; %d retained'
                  % (os.path.basename(out), sum(len(c.gone_n) for c in cuts),
                     sum(len(c.gone_e) for c in cuts), nret))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--outdir')
    a = ap.parse_args()
    if a.case not in CASES:
        raise SystemExit('unknown case %r; known: %s' % (a.case, ', '.join(sorted(CASES))))
    t = CASES[a.case]
    out = a.outdir or os.path.join(ROOT, 'zone_offset', 'work', a.case)
    os.makedirs(out, exist_ok=True)

    report = ['%s: offset t = %.1f mm  (joint keeps %.1f, main keeps %.1f)'
              % (a.case, t, t, STUB_LEN - t)]
    for role, tmpl, suffix in ROLES:
        dest = os.path.join(out, 'M52%s%s.inp' % (a.case, suffix))
        copy = next((v.get(suffix) for k, v in VERBATIM.items() if abs(t - k) < TOL), None)
        if copy:
            d = Deck(os.path.join(ROOT, copy + '.inp'))
            switched = to_distributing(d) if role == 'joint' else []
            d.write(dest)
            report.append('  %-10s <- %-16s copied verbatim (nothing to cut at t=%.0f)%s'
                          % (role, copy + '.inp', t,
                             '; mid-joint interfaces %s set to distributing, as in M52B1'
                             % ', '.join(switched) if switched else ''))
            continue
        build(role, tmpl, t if role != 'main' else STUB_LEN - t, dest, report)
    print('\n'.join(report))


if __name__ == '__main__':
    main()
