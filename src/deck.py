"""Line-preserving reader/editor for the flattened Abaqus .inp decks of this project.

The substructure decks here carry no *Part/*Instance blocks: part sections are delimited by
'** PART INSTANCE: <name>' comments and every node/element label is global and unique. That is what
makes coordinate-driven surgery safe -- nothing has to be renumbered.

Blocks the caller does not touch keep their original bytes, so a diff against the template shows
exactly the intended edit and nothing else.
"""
import re

TOL = 1e-3

# Abaqus C3D8 face -> local node numbers (1-based). Verified against M52B1.inp: for element 11963 of
# B1B-43, S3 is the face tied to B1A (Z=1350.046) and S5 the opposite one, exactly as this gives.
FACES = {'S1': (1, 2, 3, 4), 'S2': (5, 8, 7, 6), 'S3': (1, 5, 6, 2),
         'S4': (2, 6, 7, 3), 'S5': (3, 7, 8, 4), 'S6': (4, 8, 5, 1)}

_INT = re.compile(r'-?\d+')


def is_kw(l):
    return l.startswith('*') and not l.startswith('**')


def toks(line):
    """Tokens of a data line: ints where they are ints, otherwise the bare string."""
    out = []
    for t in line.split(','):
        t = t.strip()
        if t:
            out.append(int(t) if _INT.fullmatch(t) else t)
    return out


class Block:
    __slots__ = ('kw', 'data', 'trail')

    def __init__(self, kw, data=None, trail=None):
        self.kw = kw                                   # '*Keyword, ...', or None for the preamble
        self.data = data if data is not None else []
        self.trail = trail if trail is not None else []   # comments between this block and the next

    @property
    def name(self):
        return self.kw.split(',')[0].strip().lower() if self.kw else ''

    def param(self, key):
        if not self.kw:
            return None
        m = re.search(r'\b' + key + r'\s*=\s*([^,]+)', self.kw, re.I)
        return m.group(1).strip() if m else None

    @property
    def generate(self):
        return bool(self.kw) and 'generate' in self.kw.lower()

    # -- sets ----------------------------------------------------------------
    def members(self):
        """Expanded members of an *Nset/*Elset block (ints, plus any referenced set names)."""
        out = []
        for l in self.data:
            v = toks(l)
            if self.generate and len(v) >= 2 and all(isinstance(x, int) for x in v[:2]):
                step = v[2] if len(v) > 2 and isinstance(v[2], int) else 1
                out.extend(range(v[0], v[1] + 1, step))
            else:
                out.extend(v)
        return out

    def set_members(self, labels, per_line=16):
        """Replace a set block's contents with an explicit list (drops 'generate')."""
        labels = sorted(set(labels), key=lambda x: (isinstance(x, str), x))
        if self.generate:
            self.kw = re.sub(r',\s*generate', '', self.kw, flags=re.I)
        self.data = [','.join(str(x) for x in labels[i:i + per_line])
                     for i in range(0, len(labels), per_line)]


def _sub(u, v):
    return (u[0] - v[0], u[1] - v[1], u[2] - v[2])


def _dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _unit(u):
    n = _dot(u, u) ** 0.5
    if n < 1e-12:
        raise ValueError('degenerate *System axis')
    return (u[0] / n, u[1] / n, u[2] / n)


IDENT = ((0.0, 0.0, 0.0), ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))


def system_of(data_lines):
    """(origin, (e1, e2, e3)) of a *System block, as global-frame basis vectors.

    Handles the general orthogonal placement: 'a, b' (origin + a point on the local x axis) and the
    optional 'c' line (a point in the local x-y plane). With c omitted Abaqus takes the shortest
    rotation carrying global X onto the local x axis; the antiparallel case is resolved about z,
    which is the convention backcalc/inpparse.py already relies on.

    This model does use more than translation and 180deg-about-z -- the foundation deck places dowel
    instances with a 90deg rotation -- so the general form is needed, not the two-case shortcut.
    """
    fl = []
    for l in data_lines:
        fl += [float(x) for x in l.split(',') if x.strip()]
    if not fl:
        return IDENT                                   # bare *System resets to global
    a, b = tuple(fl[0:3]), tuple(fl[3:6])
    e1 = _unit(_sub(b, a))
    if len(fl) >= 9:
        v = _sub(tuple(fl[6:9]), a)
        e2 = _unit(_sub(v, tuple(e1[i] * _dot(v, e1) for i in range(3))))
    else:
        X, Y = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
        k = _cross(X, e1)
        if _dot(k, k) ** 0.5 < 1e-12:                  # parallel or antiparallel to global X
            e2 = Y if _dot(X, e1) > 0 else (-Y[0], -Y[1], -Y[2])
        else:                                          # Rodrigues about k by the angle X->e1
            k = _unit(k)
            c_, s_ = _dot(X, e1), (1 - _dot(X, e1) ** 2) ** 0.5
            kv = _cross(k, Y)
            e2 = tuple(Y[i] * c_ + kv[i] * s_ + k[i] * _dot(k, Y) * (1 - c_) for i in range(3))
            e2 = _unit(_sub(e2, tuple(e1[i] * _dot(e2, e1) for i in range(3))))
    return a, (e1, e2, _cross(e1, e2))


def to_global(raw, sys):
    o, e = sys
    return tuple(o[i] + e[0][i] * raw[0] + e[1][i] * raw[1] + e[2][i] * raw[2] for i in range(3))


def to_local(glob, sys):
    o, e = sys
    d = _sub(glob, o)
    return (_dot(d, e[0]), _dot(d, e[1]), _dot(d, e[2]))


class Deck:
    def __init__(self, path):
        self.path = path
        raw = open(path, errors='replace').read()
        self._final_nl = raw.endswith('\n')
        lines = raw.split('\n')
        if self._final_nl:
            lines.pop()
        self.blocks = [Block(None)]
        for l in lines:
            if is_kw(l):
                self.blocks.append(Block(l))
            elif l.startswith('**'):
                self.blocks[-1].trail.append(l)
            else:
                b = self.blocks[-1]
                if b.trail:                 # data resumed after a comment: preserve original order
                    b.data.extend(b.trail)
                    b.trail = []
                b.data.append(l)

    # ---------------------------------------------------------------- output
    def text(self):
        out = []
        for b in self.blocks:
            if b.kw is not None:
                out.append(b.kw)
            out.extend(b.data)
            out.extend(b.trail)
        return '\n'.join(out) + ('\n' if self._final_nl else '')

    def write(self, path):
        with open(path, 'w', newline='\n') as fh:
            fh.write(self.text())

    # ---------------------------------------------------------------- lookup
    def find(self, kw=None, **params):
        hits = []
        want = '*' + kw.lower().lstrip('*') if kw else None
        for b in self.blocks:
            if want and b.name != want:
                continue
            if all((b.param(k) or '').upper() == v.upper() for k, v in params.items()):
                hits.append(b)
        return hits

    def one(self, kw=None, **params):
        hits = self.find(kw, **params)
        if len(hits) != 1:
            raise KeyError('expected exactly 1 %s %s, found %d' % (kw, params, len(hits)))
        return hits[0]

    # ---------------------------------------------------------------- model
    @staticmethod
    def _node_rows(b):
        for l in b.data:
            v = [t.strip() for t in l.split(',') if t.strip()]
            if len(v) >= 4 and _INT.fullmatch(v[0]):
                yield int(v[0]), (float(v[1]), float(v[2]), float(v[3]))

    @staticmethod
    def _elem_rows(b):
        """(label, [nodes]) joining continuation lines."""
        lab, conn = None, []
        for l in b.data:
            v = toks(l)
            if lab is None:
                if not v or not isinstance(v[0], int):
                    continue
                lab, conn = v[0], [x for x in v[1:] if isinstance(x, int)]
            else:
                conn += [x for x in v if isinstance(x, int)]
            if not l.rstrip().endswith(','):
                yield lab, conn
                lab, conn = None, []

    def node_systems(self):
        """{label: (origin, signs)} -- the *System in force where each node was written."""
        out, cur = {}, IDENT
        for b in self.blocks:
            if b.name == '*system':
                cur = system_of(b.data)
            elif b.name == '*node':
                for lab, _ in self._node_rows(b):
                    out[lab] = cur
        return out

    def raw_nodes(self):
        """Coordinates exactly as written, before the active *System is applied."""
        out = {}
        for b in self.blocks:
            if b.name == '*node':
                out.update(dict(self._node_rows(b)))
        return out

    def nodes(self):
        """True (global) coordinates, with each node's *System applied."""
        sysm = self.node_systems()
        return {lab: to_global(c, sysm[lab]) for lab, c in self.raw_nodes().items()}

    def elements(self):
        out = {}
        for b in self.blocks:
            if b.name == '*element':
                out.update(dict(self._elem_rows(b)))
        return out

    def instance_members(self):
        """{instance: (node labels, element labels)}.

        Assembly-level single-node *Node blocks (coupling reference nodes) follow the last part
        section and are attributed to it. Harmless: reference nodes are always reached by *Nset.
        """
        out, cur = {}, None
        for b in self.blocks:
            if cur:
                if b.name == '*node':
                    out[cur][0].update(lab for lab, _ in self._node_rows(b))
                elif b.name == '*element':
                    out[cur][1].update(lab for lab, _ in self._elem_rows(b))
            for t in b.trail:
                m = re.match(r'\*\*\s*PART INSTANCE:\s*(\S+)', t)
                if m:
                    cur = m.group(1)
                    out.setdefault(cur, (set(), set()))
        return out

    # ---------------------------------------------------------------- edits
    def drop(self, nodes=(), elems=()):
        """Delete node/element definitions and purge those labels from every set in the deck."""
        dn, de = set(nodes), set(elems)
        for b in self.blocks:
            if b.name == '*node' and dn:
                rows = [(lab, c) for lab, c in self._node_rows(b) if lab not in dn]
                if len(rows) != len(list(self._node_rows(b))):
                    b.data = ['%8d, %13.6f, %13.6f, %13.6f' % (lab, c[0], c[1], c[2])
                              for lab, c in rows]
            elif b.name == '*element' and de:
                rows = [(lab, conn) for lab, conn in self._elem_rows(b) if lab not in de]
                if len(rows) != len(list(self._elem_rows(b))):
                    b.data = [', '.join(str(x) for x in [lab] + conn) for lab, conn in rows]
            elif b.name in ('*nset', '*elset'):
                bad = dn if b.name == '*nset' else de
                mem = b.members()
                if any(isinstance(x, int) and x in bad for x in mem):
                    b.set_members([x for x in mem if not (isinstance(x, int) and x in bad)])

    def move_node(self, label, axis, value):
        """Set one global coordinate of a node, writing it back in that node's own *System."""
        sysm = self.node_systems()
        if label not in sysm:
            return False
        for b in self.blocks:
            if b.name != '*node':
                continue
            for i, l in enumerate(b.data):
                v = [t.strip() for t in l.split(',') if t.strip()]
                if len(v) >= 4 and _INT.fullmatch(v[0]) and int(v[0]) == label:
                    raw = (float(v[1]), float(v[2]), float(v[3]))
                    g = list(to_global(raw, sysm[label]))
                    g[axis] = value
                    c = to_local(tuple(g), sysm[label])
                    b.data[i] = '%8d, %13.6f, %13.6f, %13.6f' % (label, c[0], c[1], c[2])
                    return True
        return False

    def delete_block(self, blk):
        self.blocks = [b for b in self.blocks if b is not blk]

    def empty_sets(self):
        return [(b.name, b.param('nset') or b.param('elset'))
                for b in self.blocks if b.name in ('*nset', '*elset') and not b.members()]

    # ---------------------------------------------------------------- surfaces
    def surface_faces(self, name):
        """[(elset block, face code)] for an element-based *Surface."""
        s = self.one('surface', name=name)
        out = []
        for l in s.data:
            v = [t.strip() for t in l.split(',') if t.strip()]
            if len(v) == 2:
                out.append((v[0], v[1]))
        return s, out
