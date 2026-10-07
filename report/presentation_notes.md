# Joint-zone offset study: conclusions for the presentation

Side study to the portalframe partitioning comparison. Repo: railgnam/offset_parameter_study.
Numbers: `compare/exports/2026-10-07_zone_offset_c25/tables/T10_zone_offset_trend.csv`, figures F9.

## Objectives
- B1 and B2 differ in one thing: whether the 300 mm timber stubs next to each joint belong to the joint substructure (B1) or the main one (B2). Two points cannot show a trend.
- Question: how far from the joint must the substructure boundary sit before it stops disturbing the joint stresses?
- Answer it as a curve: 7 rungs D0..D6 at offset t = 0, 30, 90, 150, 210, 270, 300 mm, moved together at the mid, top and base joints.
- Keep everything else fixed: same mesh, same wind-only load, same coupling type, same reference.

## Method in one slide
- Decks generated from the B1/B2 decks by text transform, no CAE. Each stub is 10 layers of 30 mm, so cuts split existing element layers: the mesh is identical on every rung.
- Reference C25 = full model with dowel-embedding radius 25 mm (as in the substructures). It gives the same results as the old C to 1e-6 MPa.
- Checks: total reaction 60 kN on every rung; D6 reproduces B1 in all 102 region rows; wall/slab load points (150 mm from the joint) move between substructures without being lost or doubled.

## Results (deviation from C25)
- **Joint 6:** error shrinks steadily with offset and levels off by about 210 mm. Timber S11 peak −19 % (t=0) → −7 % (150) → −4.5 % (300); p95 −13 % → −4.7 %.
- **Joint 3 (load-carrying):** peaks shrink with offset (dowel Mises peak +31 % → +12 %, timber S11 peak −9 % → −0.5 %), but the dowel mean drifts the other way (−6 % → −12.5 %). Timber mean/p95 stays within ±3 % on every rung.
- **Floor:** about −4.5 % at J6 timber and −12 % at J3 dowel mean remain at t=300 and do not depend on the offset. That part comes from substructuring itself, not from the boundary position.
- **Practical rule:** about 150–210 mm (5–7 element layers of 30 mm) captures most of the gain; beyond 210 mm nothing changes.

## Kinematic coupling probe (D3K, t=150)
- Rigid interfaces at all cuts: solves cleanly, same reaction.
- Best of all rungs at J6 timber (p95 −1.3 % vs −4.7 % at D6). Mixed elsewhere: J3 dowel mean −13.9 % (worse), J3 dowel peak +10.5 % (better).
- Promising, one point only. Not a series yet.

## Finding about the published models
- Interface coupling types differ: mid joint is distributing in B1 but kinematic in B2; top and base joints kinematic in both.
- Published B2 also has user and snow loads; B1 and C are wind-only.
- So published B1 vs B2 mixes three effects: zone size, coupling type, load. This study isolates zone size. D0 (t=0, distributing) is much worse than published B2 at J6 (−19 % vs −0.6 % timber peak); load and coupling type are not separated yet.

## Likely questions
- *Why does J3 dowel mean get worse with a bigger zone?* Small zones add a boundary error that partly cancels the offset-independent error. Larger zones remove the cancellation. Cause of the floor not established.
- *Is J6 meaningful?* It is lightly loaded, so percentages amplify small stresses. Use it for the trend shape, quote absolute values if asked.
- *Inter-module plates?* About +82 % on every rung, same as published B1, independent of offset: the mesh-related edge effect from the main study.
- *Cost?* Same mesh and same global DOF count on every rung; not a runtime study.

## Open
- Separate B2's load vs coupling-type effect (D0 with kinematic mid joint).
- Back-calculation of the main substructures (deferred).
- Full kinematic ladder if D3K holds up.
