# offset_parameter_study — how large must the joint substructure be?

Part of the `portalframe_model_fix` study (`railgnam/portalframe_fix`). There, `B1` and `B2` differ in
whether the three 300 mm timber **stubs** just outside the corner block belong to the *joint*
substructure or to the *main* substructure:

| | post below | post above | beam end | stub kept in the joint substructure |
|---|---|---|---|---|
| **B2** | — | — | — | **0 mm** |
| **B1** | `B1B-43` | `B1E-42` | `B2_2B-44` | **300 mm** |

Two models are two samples of a question that wants a curve: *how far from the joint must the
substructure's coupling boundary sit before it stops polluting the joint stresses?* This study builds
a ladder of seven specimens across that range from one generator, with one load case and one
coupling convention, so the answer can be read off a trend.

| case | offset t | stub layers joint / main | what it is |
|---|---|---|---|
| **D0** | 0 mm | 0 / 10 | B2's partition |
| **D1** | 30 mm | 1 / 9 | |
| **D2** | 90 mm | 3 / 7 | |
| **D3** | 150 mm | 5 / 5 | every wall and slab load point lands exactly on the cut |
| **D4** | 210 mm | 7 / 3 | |
| **D5** | 270 mm | 9 / 1 | |
| **D6** | 300 mm | 10 / 0 | B1's partition |
| **D3K** | 150 mm | 5 / 5 | D3 with **kinematic** interface couplings (probe) |

All rungs are wind-only and use distributing mid-joint interfaces. The same offset is applied to all
three stubs at once, in the mid joint, the top joint and the base joint simultaneously.

The reference is **C25** = job `C_GLOBAL_R25`: the full model `C-GLOBAL-1` with `EMB-TIMBER`
`influence radius` changed from 50 to 25, the value every substructure case uses. One line differs.

## Result (export `compare/exports/2026-10-07_zone_offset_c25`)

Deviation from C25 in per cent, joint-region statistics from table T2. Figures:
`figures/F9_zone_offset_J3.png`, `F9_zone_offset_J6.png`; the numbers behind them are in
`tables/T10_zone_offset_trend.csv`.

**Joint-6, timber S11**

| stat | D0 | D1 | D2 | D3 | D4 | D5 | D6 | D3K |
|---|---|---|---|---|---|---|---|---|
| peak | -19.1 | -15.0 | -9.9 | -7.2 | -5.7 | -4.8 | -4.5 | -2.5 |
| p95 | -13.3 | -11.1 | -7.7 | -6.3 | -5.4 | -4.8 | -4.7 | -1.3 |
| mean | 14.8 | 11.4 | 7.3 | 5.2 | 4.0 | 3.3 | 3.0 | 1.6 |

**Joint-3, timber S11**

| stat | D0 | D1 | D2 | D3 | D4 | D5 | D6 | D3K |
|---|---|---|---|---|---|---|---|---|
| peak | -9.4 | -12.2 | -5.9 | -2.7 | -1.4 | -0.7 | -0.5 | 0.9 |
| p95 | 3.0 | 3.5 | 4.0 | 3.8 | 2.5 | 1.7 | 1.6 | 5.5 |
| mean | 3.4 | 1.7 | -0.0 | -1.4 | -2.0 | -2.2 | -2.3 | -1.5 |

**Dowels, von Mises**

| | stat | D0 | D1 | D2 | D3 | D4 | D5 | D6 | D3K |
|---|---|---|---|---|---|---|---|---|---|
| J3 | peak | 30.5 | 24.9 | 18.6 | 16.3 | 14.2 | 12.9 | 12.4 | 10.5 |
| J3 | mean | -6.2 | -8.5 | -10.5 | -11.3 | -12.0 | -12.4 | -12.5 | -13.9 |
| J6 | peak | -14.7 | -10.5 | -6.3 | -4.7 | -4.0 | -3.7 | -3.6 | -3.2 |
| J6 | mean | -9.6 | -8.9 | -8.2 | -7.8 | -7.6 | -7.5 | -7.5 | -8.3 |

What to read off it:

1. **At Joint-6 the boundary error shrinks monotonically with the offset and has flattened by
   about 210 mm.** All three timber S11 statistics and the dowel peak and mean fall at every step;
   the timber error falls by half or more between t=0 and t=150, and past D4 it moves by about a
   percentage point. Judge with p95 and mean; the peaks sit next to dowel holes and are
   mesh-sensitive (`compare/GENERIC_WORKFLOW.md`, rule 2).
2. **At Joint-3 the offset is not the dominant error.** The timber peak drops from 12 % (D1) to
   0.5 % (D6), but the timber p95 and mean are within 4 % at every offset and not monotonic, and the
   dowel mean and p95 deviations *grow* as the boundary moves out (mean 6.2 % at D0 to 12.5 % at D6).
   The small zones are not more accurate there: their boundary error partly cancels a residual that
   is present whatever the offset.
3. **The error does not shrink to zero.** At D6 it is still about -4.5 % in the J6 timber and about
   12 % in the J3 dowels. That part does not move with the offset, so it is not boundary pollution
   but the residual error of joint-wise substructuring itself — the separation two endpoints could
   not give.
4. **Kinematic interfaces (D3K) are not uniformly worse — for the J6 timber they are clearly
   better.** At t=150 they beat every distributing rung there, D6 included (timber p95 -1.3 % against
   -6.3 % for D3 and -4.7 % for D6). Elsewhere it is mixed: the J3 timber peak and both dowel peaks
   improve; the J3 timber p95 and the dowel means get worse. One rung cannot say how this behaves
   across the range, but the expectation that a rigid cut face simply over-stiffens is not borne out.
5. **The published B2 was optimistic as a t=0 endpoint.** D0 has B2's partition but B1's wind-only
   load and B1's distributing mid joint, and it is markedly worse than B2 (J6 timber peak -19.1 %
   against -0.6 %, J3 dowel peak 30.5 % against 8.4 %). See *Known limits* for why the two differ.

## How it is built

No CAE. The decks are generated by transforming the frozen decks of `portalframe_model_fix` as text,
which keeps the mesh exact and makes every rung reproducible from `params.csv`.

Each stub is a uniform **10-layer extrusion of 30 mm** along its member axis (`B1B-43` and `B1E-42`
are 13x6x11 node planes, `B2_2B-44` is 11x6x16). A cut at a multiple of 30 mm only **splits existing
element layers** — no geometry, no remeshing, no partitioning — so the mesh of every rung is identical
to B1's and B2's and mesh density cannot confound the comparison.

| deck | template |
|---|---|
| `M52Dn` (mid joint) | `M52B1`, cut. D0: `M5B2` with its three interface couplings made distributing. D6: `M52B1` unchanged |
| `M52Dntop` | `M52B1top`, cut. D0: `M52B2top`. D6: unchanged |
| `M52Dnfoundation` | `M52B1foundation`, cut. D0: `M52B2foundation`. D6: unchanged |
| `M52Dnmain` | `M52B2main`, cut (it already has the stubs, their interface couplings and the ties to `B1C`/`B1D`/`B2_C`). D0: unchanged. D6: `M52B1main` |
| `Dn-GLOBAL` | `B1-GLOBAL` for every rung: same 11 Z1 instances, wind-only load, BCs, stack tie, output requests |

Nothing is hard-coded per rung: the cut plane, its axis, its instance, the reference node riding on it
and the other surfaces sharing that face are all read out of the deck.

### Reproducing

The generated decks and solver output (`work/`, several GB) are not in this repository. They
regenerate from the decks in `portalframe_model_fix`, so check this repository out as
`portalframe_model_fix/zone_offset/`:

```
python src/make_specimen.py   --case D3     # four substructure decks, from params.csv
python src/make_global.py     --case D3     # the global deck
python src/verify_specimen.py --case D3     # V0..V3b -- before any solver time is spent
python src/run_specimens.py   --case D3     # generate + verify + solve (or --datacheck)
python src/make_kinematic.py  --case D3     # -> D3K, interfaces kinematic, nothing else changed
python src/make_cases.py                    # register solved cases for the comparison
cd compare
python src/run_study.py --cases D3 --snapshot --extract
python src/run_study.py --compare --tag zone_offset_c25
cd .. && python src/trend.py --tag zone_offset_c25
```

The comparison writes `comparison.xlsx` with `xlsxwriter`; use the ecosystem `.venv`
(`C:\Users\au686008\Claude\.venv`), the system python lacks it.

## The thing that could quietly ruin this study

Every wall-pressure and slab reference point sits **exactly 150 mm from its stub's inner face** — all
five of them. So those points change owner as the offset crosses 150 mm, and at D3 they land exactly
on the cut. `*Cload LOADSET-WIND, 1, -4000.` is a force **per node**, so a point counted twice or lost
rescales the load while every result still looks plausible. Guarded by a tie-break (a point on the cut
belongs to the joint substructure) and by V1 and V4. The retained topology confirms the threshold:

| | joint | top | foundation | main |
|---|---|---|---|---|
| D0, D1, D2 (B2 topology) | 4 | 3 | 2 | 23 |
| D3, D4, D5, D6 (B1 topology) | 7 | 5 | 3 | 17 |

## Verification

All pass for every case, D3K included.

| id | check |
|---|---|
| **V0** | D6's four substructure decks are line-identical to B1's and its global deck numerically identical to `B1-GLOBAL` (same labels, 0.000000 mm). D0's are line-identical to B2's, except the three mid-joint interface lines of `M5B2`. "Line-identical": the content matches line for line; CAE wrote the templates with CRLF endings and the generator writes LF, which Abaqus treats the same |
| **V1** | every `LOADSET-*`, `FO-*` and `BC-1-FIX` set holds the same physical points as `B1-GLOBAL` (15 wind / 9 snow / 18 user) |
| **V2** | per stub and frame line, joint elements + main elements = the template's count, and both cuts land on the same plane |
| **V3** | each Z1 element's nodes match its substructure's retained set, in label order, within 0.05 mm |
| **V3b** | every `*Coupling` is followed by exactly one sub-option block (see the gotcha below) |
| **V4** | summed reaction `[60000, 0, 0]` for every rung, D3K and C25 — identical to B1 |
| **V5** | D6 reproduces B1 in every row of T2 |

Abaqus accepts every deck with zero errors. Each generated deck's warning profile is identical to its
template's, except that removed couplings take their own warnings with them; D3K adds no warning (in
particular no over-constraint warning) and only loses the distributing-coupling notes.

## Known limits

- **The originals do not use one interface coupling type.** Read out of the decks:

  | deck | B1 | B2 |
  |---|---|---|
  | mid joint `AN-1/2/3` | distributing | **kinematic** |
  | top joint | kinematic | kinematic |
  | foundation | kinematic | kinematic |
  | main `AN-*` | distributing | distributing |

  The ladder keeps the B1 convention: distributing mid joint and main, kinematic top and foundation.
  D0 therefore has its three mid-joint lines switched from `M5B2`'s kinematic. It also means D3K
  ("kinematic interfaces") changes only the mid joint and the main; top and foundation already were.
- **The published B2 differs from D0 in two ways at once**: its global deck also applies
  `LOADSET-USER, 3, -9000.` and `LOADSET-SNOW, 3, -4500.` (summed reaction `[60000, 0, 202500]`, B1
  and C are wind-only), and its mid joint is kinematic. This study does not separate the two effects;
  a D0 variant with a kinematic mid joint would.
- **C and C25 give identical results.** Changing `EMB-TIMBER` from radius 50 to 25 moves no element
  stress by more than 1e-6 MPa (output rounding), so every deviation in this study is the same
  against either. Most likely every hole-surface node already lies within 25 mm of its dowel's
  reference node, so both radii select the same nodes — a hypothesis, not checked. C25 is kept as the
  reference because it is the consistent definition.
- Table T3's segment statistics for a rung cover only the **retained portion** of the stub — the
  quantity under study. `regions.json` needs no edit: its boxes come from C and the instance names
  are kept.
- The D main substructures are not back-calculated, so mid-span fields and whole-frame contours are
  blank for them. The joint-zone question does not need them.
- `backcalc/README.md` (in `portalframe_model_fix`) says the only instance placements are
  translation and 180 degrees about z. Not so: the foundation deck places dowels with a 90 degree
  rotation. `src/deck.py` implements the general orthogonal `*System`.

## The kinematic variant, and what to know before extending it

- Only `AN-1/2/3` (and `AN-1-Copy`..`AN-3-Copy` in a B1-type main deck) change, sub-option line only.
  `AN-4-SLAB`, `AN-5-WALL*`, `EMB-*` and `BASE-BC-CPL` stay as they are: they apply loads or model
  dowel embedment, so making them rigid would change the physics rather than the boundary.
- **Keep `influence radius`.** In the main deck one coupling carries two reference nodes, one per frame
  line 8 m apart, and the radius is what keeps each on its own cut face. It applies to kinematic
  coupling as well; an earlier note in this study said to drop it, which was wrong.
- `make_kinematic.py` refuses to write a variant whose decks differ from the parent anywhere except
  those sub-option lines.

## Gotchas found here (logged to the canonical `GOTCHAS.md`)

`*Distributing`/`*Kinematic` is its own keyword block, so deleting a `*Coupling` without it orphans
the line onto the previous coupling; CAE writes duplicate-named `*Elset` blocks, one per instance;
assembly-level reference nodes inflate the last instance's bounding box; `abaqus ... interactive`
writes no `<job>.log`; `*System` placements beyond the documented two; cases compared as alike that
are not loaded alike; and the influence-radius point above.

## Layout

```
params.csv            the ladder -- the only place an offset is set
plan.md               append-only log
src/deck.py           line-preserving .inp reader/editor, general *System placement
src/discover.py       a deck's interface anatomy -- the evidence for the transform
src/make_specimen.py  params.csv row -> the four substructure decks
src/make_global.py    -> the global deck
src/make_kinematic.py -> a kinematic-interface variant of a rung
src/verify_specimen.py V0..V3b
src/run_specimens.py  generate + verify + solve, or --datacheck
src/make_cases.py     -> compare/study/cases.json
src/trend.py          F9 and T10
compare/              study copy of the comparison pipeline; exports/2026-10-07_zone_offset_c25 is the result
work/                 (not in git) decks, .sim files, solver output
```
