# zone_offset — append-only log

## 2026-10-06 / 07 — set up and first rungs

**Goal.** B1 and B2 differ only in whether the three 300 mm stubs belong to the joint or the main
substructure (300 mm vs 0 mm). Two points cannot show a trend, so add siblings of B1 at intermediate
offsets and read the joint-zone error off a curve. Offsets D1..D5 = 30/90/150/210/270 mm (equal 60 mm
steps), plus D0 = 300 mm as a generator check.

**Approach chosen.** Generate the decks by transforming the frozen B1/B2 decks as text; no CAE. Each
stub turned out to be a uniform 10-layer extrusion of 30 mm, so every chosen offset splits existing
element layers and the mesh stays bit-identical to B1's and B2's. This removes mesh density as a
confound and avoids the partition-after-mesh traps in `GOTCHAS.md`.

Templates: joint/top/foundation from B1 (they carry the stubs), **main from B2** (its main already
has the stubs, the `AN-*` couplings on their free faces and the `TIE-GLM*` ties to `B1C`/`B1D`/`B2_C`),
global from B1-GLOBAL.

**Things found while building, in the order they bit.**

1. `AN-1` is the post **above** and `AN-3` the post **below** — the opposite of what the planning
   note assumed. The code derives this from coordinates, so nothing depended on the assumption, but
   the write-up did and was corrected.
2. The interface surfaces sit on element face code `S3`/`S5`, and the C3D8 face convention was
   confirmed empirically against element 11963 of `B1B-43` (`S3` is the face tied to `B1A`) rather
   than assumed from the manual.
3. `*System` blocks place every part instance, and the first reader ignored them — which showed up as
   a foundation interface apparently 3570 mm (one storey) away from its own reference node.
4. `backcalc/README.md` says the only placements in this model are translation and 180 degrees about
   z. **Not true**: the foundation deck places dowel instances with a 90 degree rotation (`*System`
   with local x along (0,-1,0)). `src/deck.py` implements the general orthogonal placement. A guard
   that rejected the unsupported case is what surfaced this.
5. CAE writes **duplicate-named `*Elset` blocks, one per instance**, so rewriting only the first left
   stale siblings that the label purge then emptied — and a `*Surface` pointing at an empty `*Elset`
   is an input error. Cut surfaces are now rebuilt for all their instances at once.
6. Instance bounding boxes were being computed from the instance's node block, which includes the
   assembly-level coupling reference nodes written after the last part section. That inflated the box
   until every point looked "inside" it, so no load point ever migrated. Boxes now come from the
   nodes the instance's **elements** actually use.
7. A load coupling whose reference node migrates leaves an empty reference set. The real t=0 model
   does the equivalent thing — `M52B2top` keeps a vestigial `AN-5-WALL` coupling but leaves its
   reference node out of the retained set — so such a coupling is now deleted outright.
8. `abaqus job=... interactive` writes no `<job>.log`, and the comparison pipeline gates on that file
   (`compare/src/snapshot.py: job_completed`). The driver now keeps the captured console output there.

**The hazard this study had to be built around.** Every wall and slab reference point sits exactly
150 mm from its stub's inner face (all five, measured). They therefore change owner as the offset
crosses 150 mm, and at D3 they land exactly on the cut plane. Since `*Cload LOADSET-WIND, 1, -4000.`
is a force **per node**, a point counted twice or lost rescales the total load while the results still
look plausible. Guarded by a tie-break (a point on the cut belongs to the joint) and by V1.

**Verification status.** V0..V3 pass for all six rungs. At t=300 the generator is a provable no-op:
D0's four substructure decks are **byte-identical** to B1's and its global deck numerically identical,
so D0 is a regression test and is not solved. Abaqus accepts every deck with zero errors, and each
generated deck's warning profile is identical to its template's. D3 solved end to end (5 jobs, 11
recovery ODBs) and V4 gives `sum RF = [60000, 0, 0]`, identical to B1.

**Open issue, not caused here: the cases are not loaded alike.** `B1-GLOBAL` and `C-GLOBAL-1` apply
wind only; `B2-GLOBAL` and `A-GLOBAL` also apply `LOADSET-USER, 3, -9000.` and
`LOADSET-SNOW, 3, -4500.`, which is exactly B2's extra 202 500 N vertical reaction. The D rungs
inherit B1's wind-only load, so they are comparable with B1 and C but **B2 is not a comparable t=0
endpoint**. Remedy (not done): re-run only B2's global job wind-only as a new case — the `.sim` files
already exist — and never overwrite `B2-GLOBAL.*` in the repo root.

**Deferred.** The kinematic-coupling variant series; see README "Possible extension". Back-calculation
of the D main substructures, on demand.

## 2026-10-07 — all five rungs solved, first curve

All of D1..D5 solved (5 jobs each, 11 recovery ODBs each). V4 gives `sum RF = [60000, 0, 0]` for
every rung, identical to B1 — including D1 and D2, where four load couplings are deleted because
their reference nodes move into the main substructure. Load conservation therefore holds across the
whole ladder, which was the main thing that could have invalidated the study silently.

One real bug was caught by the sweep rather than by D3: `*Distributing` is a keyword block of its
own, not data of `*Coupling`, so deleting a dead coupling orphaned its sub-option, which then
attached to the preceding coupling. D3/D4/D5 passed because no coupling is deleted above the 150 mm
threshold; D1 and D2 failed with errors naming couplings that had never been touched. Fixed, and
`verify_specimen.py` now asserts that every coupling has exactly one sub-option (V3b). Confirmed the
fix is a no-op for D3/D4/D5 — only D1 and D2 remove couplings — so their earlier results stand.

Comparison export `2026-10-07_zone_offset` (8 cases: C, B1, B2, D1..D5). The error decays
monotonically with the offset and flattens by roughly 210–270 mm; most of the benefit is taken by
150 mm. It does not decay to zero: a residual that does not move with the offset remains (about
-4.5 % at J6, and the J3 dowel statistics), which separates inherent substructuring error from
boundary pollution — the thing two endpoints could not show.

Gotchas logged to the canonical `C:\Users\au686008\Claude\GOTCHAS.md` (6 entries): the `*Coupling`
sub-option block, duplicate-named `*Elset` blocks in flattened decks, reference nodes inflating the
last instance's bounding box, `interactive` writing no `.log`, the unsupported `*System` rotation,
and checking that two "comparable" cases are actually loaded alike.

Not done: the wind-only B2 needed to make t=0 a comparable endpoint; back-calculation of the D main
substructures; the kinematic-coupling series.

## 2026-10-07 (afternoon) — canonical ends, C25 reference, kinematic probe, repository

**Reference.** C fixed as job `C_GLOBAL_R25` (`EMB-TIMBER` influence radius 50 -> 25), one asserted
line, line-identical to the other session's `C-r25.inp`. Result: **numerically identical to C** —
largest element von Mises difference 1e-6 MPa. Probably every hole-surface node is within 25 mm of
its reference node, so both radii pick the same nodes (not checked). Kept as reference for
consistency; no deviation in the study changes because of it.

**Ladder redefined.** D0 = t=0 (B2 partition), D6 = t=300 (B1 partition), both through the same
generator and the wind-only B1-GLOBAL template. The earlier "D0 = t=300 verification twin" is now D6;
the 600 mm idea is dropped.

**Found: the originals mix coupling types.** Mid joint distributing in B1 but kinematic in B2; top
and foundation kinematic in both; main distributing in both. D0 copies `M5B2` with its three mid-joint
interfaces switched to distributing so the whole ladder shares B1's convention. Published B2 thus
differs from D0 by load *and* mid-joint coupling; not separated.

**Found: my earlier advice to drop `influence radius` for kinematic coupling was wrong.** The main
deck's interface couplings each carry two reference nodes, one per frame line, and the radius keeps
each on its own face. `make_kinematic.py` keeps it; README corrected; gotcha logged.

**Found: "byte-identical" was overstated.** The CAE templates are CRLF, the generator writes LF.
Content is line-identical; wording corrected everywhere rather than changing the writer mid-study.

**D3K** (D3 with kinematic mid-joint and main interfaces): all jobs completed, no new warnings, sum RF
unchanged. Clearly better than every distributing rung for the J6 timber; mixed elsewhere.

**Results vs C25** (export `2026-10-07_zone_offset_c25`). V5 holds: D6 equals B1 in all 102 T2 rows.
J6: error falls monotonically with the offset and flattens by ~210 mm. J3: not monotonic — the dowel
mean and p95 deviations grow as the boundary moves out, so small zones partly cancel a residual rather
than being more accurate. A residual independent of the offset remains (about -4.5 % J6 timber, about
12 % J3 dowels). An earlier draft of the README claimed steady decay at both joints; corrected after
checking monotonicity per statistic.

**Repository.** This directory is now its own git repository, pushed to
`railgnam/offset_parameter_study`. `work/` and the snapshot store are not committed.
