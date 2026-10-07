"""Kinematic-coupling variant of a solved rung: <case>K.

The substructure interfaces AN-1/2/3 (and AN-1-Copy..AN-3-Copy in the main deck) are distributing
couplings, which let the cut face warp. This variant makes them kinematic -- the cut face moves as a
rigid body -- and changes nothing else. Load and embedding couplings (AN-4-SLAB, AN-5-WALL*,
EMB-STEEL, EMB-TIMBER, BASE-BC-CPL) stay distributing: making them rigid would change the physics
being compared, not the boundary idealisation.

'influence radius' is KEPT. In the main deck one coupling carries two reference nodes, one per
frame line 8 m apart, and the radius is what limits each reference node to its own cut face --
without it both faces would be tied to both reference nodes. It applies to kinematic coupling as
much as to distributing.

A coupling that is already kinematic in the parent (the free post top AN-1 in the top deck) is left
alone and reported.

The script refuses to write anything if the variant differs from its parent in any line other than
the converted coupling keywords and their sub-option lines.

usage: python make_kinematic.py --case D3        # -> work/D3K/
"""
import argparse
import os
import re

from deck import Deck

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
INTERFACES = {'AN-1', 'AN-2', 'AN-3', 'AN-1-COPY', 'AN-2-COPY', 'AN-3-COPY'}
SUFFIXES = ('', 'main', 'top', 'foundation')


def convert(src, dst):
    d = Deck(src)
    converted, already = [], []
    for i, b in enumerate(d.blocks):
        if b.name != '*coupling':
            continue
        name = (b.param('constraint name') or '').upper()
        if name not in INTERFACES:
            continue
        sub = d.blocks[i + 1]
        if sub.name == '*kinematic':
            already.append(name)
            continue
        if sub.name != '*distributing':
            raise SystemExit('%s: coupling %s is followed by %s, expected *Distributing'
                             % (src, name, sub.name))
        sub.kw = '*Kinematic'
        sub.data = []                       # no DOF list: all six DOFs are constrained
        converted.append(name)
    d.write(dst)

    old = open(src, errors='replace').read().split('\n')
    new = open(dst, errors='replace').read().split('\n')
    diff = [(a, b) for a, b in zip(old, new) if a != b]
    allowed = all(a.startswith('*Distributing') and b == '*Kinematic' for a, b in diff)
    if len(old) != len(new) or not allowed or len(diff) != len(converted):
        os.remove(dst)
        raise SystemExit('%s: the variant touches more than the interface couplings -- refused'
                         % os.path.basename(dst))
    return converted, already, len(diff)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    a = ap.parse_args()
    base, var = a.case, a.case + 'K'
    sdir = os.path.join(ROOT, 'zone_offset', 'work', base)
    vdir = os.path.join(ROOT, 'zone_offset', 'work', var)
    os.makedirs(vdir, exist_ok=True)

    for s in SUFFIXES:
        conv, already, nd = convert(os.path.join(sdir, 'M52%s%s.inp' % (base, s)),
                           os.path.join(vdir, 'M52%s%s.inp' % (var, s)))
        print('M52%s%-11s %d made kinematic (%s), %d lines changed%s'
              % (var, s, len(conv), ', '.join(conv), nd,
                 '; already kinematic, left alone: %s' % ', '.join(already) if already else ''))

    g = open(os.path.join(sdir, '%s-GLOBAL.inp' % base), errors='replace').read()
    g2, n = re.subn(r'file=M52%s(\w*)' % base, r'file=M52%s\1' % var, g)
    with open(os.path.join(vdir, '%s-GLOBAL.inp' % var), 'w', newline='\n') as fh:
        fh.write(g2)
    print('%s-GLOBAL.inp  %d substructure references renamed, nothing else changed' % (var, n))


if __name__ == '__main__':
    main()
