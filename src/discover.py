"""Report the substructure-interface anatomy of a deck: cut faces, reference nodes, retained set.

Run this against the B1/B2 templates before trusting the generator -- it is the evidence that the
coordinate-driven transform in make_specimen.py is reading the decks the way they are really built.

usage: python discover.py <deck.inp> [...]
"""
import sys

from deck import TOL, FACES, Deck

AXIS = 'XYZ'


def face_plane(nodes, conn, code):
    """(axis, value) if the given element face is planar along one axis, else None."""
    pts = [nodes[conn[i - 1]] for i in FACES[code]]
    for ax in range(3):
        vals = [p[ax] for p in pts]
        if max(vals) - min(vals) < TOL:
            return ax, sum(vals) / 4.0
    return None


def surface_geometry(d, nodes, elems, inst_of, sname):
    """Which instance a *Surface sits on, and the plane it lies in."""
    _, pairs = d.surface_faces(sname)
    labs, planes, insts = [], set(), set()
    for elset_name, code in pairs:
        for b in d.find('elset', elset=elset_name):
            for lab in b.members():
                if not isinstance(lab, int) or lab not in elems:
                    continue
                labs.append(lab)
                insts.add(inst_of.get(lab, '?'))
                fp = face_plane(nodes, elems[lab], code)
                if fp:
                    planes.add((fp[0], round(fp[1], 3)))
    return labs, planes, insts


def main(paths):
    for p in paths:
        d = Deck(p)
        nodes, elems = d.nodes(), d.elements()
        inst = d.instance_members()
        inst_of = {lab: name for name, (_, es) in inst.items() for lab in es}
        print('=' * 100)
        print(p)

        # retained set
        rb = d.find('retained nodal dofs')
        rset = rb[0].data[0].split(',')[0].strip() if rb and rb[0].data else None
        retained = sorted(x for x in d.one('nset', nset=rset).members() if isinstance(x, int)) \
            if rset else []
        print('  retained set %r -> %d nodes' % (rset, len(retained)))

        # couplings
        print('  couplings:')
        for c in d.find('coupling'):
            cname = c.param('constraint name')
            ref, surf = c.param('ref node'), c.param('surface')
            rad = c.param('influence radius')
            try:
                rn = [x for x in d.one('nset', nset=ref).members() if isinstance(x, int)]
            except KeyError:
                rn = []
            kind = c.data[0].split(',')[0].strip() if c.data else '?'
            loc = ' '.join('%s(%s)' % (n, ','.join('%.3f' % v for v in nodes[n])) for n in rn
                           if n in nodes)
            extra = ''
            if cname.startswith('AN-') and surf:
                try:
                    labs, planes, insts = surface_geometry(d, nodes, elems, inst_of, surf)
                    extra = '  | %d faces on %s, plane %s' % (
                        len(labs), sorted(insts),
                        ', '.join('%s=%.3f' % (AXIS[a], v) for a, v in sorted(planes)))
                except KeyError:
                    extra = '  | surface %r not found' % surf
            print('    %-16s %-10s rad=%-6s ref=%s%s' % (cname, kind.lstrip('*'), rad, loc, extra))

        # stub-like instances and their extents
        print('  instance extents (timber segments only):')
        for name, (ns, es) in sorted(inst.items()):
            if not ns or not any(k in name.upper() for k in ('B1', 'B2')):
                continue
            pts = [nodes[n] for n in ns if n in nodes]
            lo = [min(q[a] for q in pts) for a in range(3)]
            hi = [max(q[a] for q in pts) for a in range(3)]
            print('    %-16s %5d nodes %5d elems   X %9.3f..%9.3f  Y %7.3f..%7.3f  '
                  'Z %9.3f..%9.3f' % (name, len(ns), len(es), lo[0], hi[0], lo[1], hi[1],
                                      lo[2], hi[2]))


if __name__ == '__main__':
    main(sys.argv[1:])
