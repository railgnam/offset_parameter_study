# Coupling-type study: plan for a new session

Written 2026-10-07 at the end of the zone-offset session, to be picked up in a fresh conversation.
Work lives in `portalframe_model_fix/zone_offset/` (its own git repo, `railgnam/offset_parameter_study`,
branch `main`). New code and docs for this study go under `zone_offset/coupling/` and `zone_offset/src/`;
generated decks and solver output under `zone_offset/work/<case>/` (git-ignored).

## Before starting

1. Read `C:\Users\au686008\Claude\GOTCHAS.md` and `abaqus_run/CLAUDE.md` (launch rules, "never invent a
   parameter silently", baseline before sweep).
2. Read `zone_offset/README.md` and the end of `zone_offset/plan.md` (append-only log of the zone-offset
   study). Results to date: `zone_offset/report/presentation_notes.md`, report artifact
   https://claude.ai/artifact/TRgUFTnwzSmAaA9KAxFb1S.
3. Check `git status` in `zone_offset/` and for running `abaqus`/`standard` processes: the user runs
   parallel sessions on these repos.
4. Python: `C:\Users\au686008\Claude\.venv\Scripts\python.exe` (system python lacks xlsxwriter).
   Abaqus: `cmd /c "call "C:\SIMULIA\Commands\abaqus.bat" ..."`, stdin=DEVNULL, cwd = the work dir.
   `interactive` writes no `.log`; `run_specimens.py` captures stdout into `<job>.log`.
   The user has several license seats: independent jobs can run in parallel.

## What is already known

**The original decks do not use one interface coupling type** (AN-1/2/3 = joint-to-substructure
interfaces; AN-4-SLAB, AN-5-WALL*, EMB-*, BASE-BC-CPL are loads/embedding and are out of scope):

| deck | B1 | B2 |
|---|---|---|
| mid joint AN-1/2/3 | distributing | **kinematic** |
| top joint AN-1/2/3 | kinematic | kinematic |
| foundation AN-1 | kinematic | kinematic |
| main AN-* (two ref nodes per coupling, `influence radius`) | distributing | distributing |

Also: published B2 and A carry `LOADSET-USER, 3, -9000.` and `LOADSET-SNOW, 3, -4500.` on top of wind;
B1, C and C25 are wind-only. So published B1 vs B2 mixes zone size, mid-joint coupling type and load.

**Zone-offset ladder D0..D6** (t = 0, 30, 90, 150, 210, 270, 300 mm): same mesh, wind-only, B1's coupling
convention (mid distributing, top/foundation kinematic, main distributing). D0 = B2 partition with its mid
joint switched to distributing (`make_specimen.py: to_distributing`). D6 reproduces B1 exactly.
Reference C25 = `C_GLOBAL_R25` (`zone_offset/work/C_GLOBAL_R25/`), identical to old C to 1e-6 MPa.

**D3K probe** (t=150, every AN interface kinematic, built by `src/make_kinematic.py --case D3`):
solved clean, same reaction. J6 timber S11 p95 −1.3 % vs −6.3 % (D3) and −4.7 % (D6). J3 mixed: dowel
Mises peak +10.5 % (better than D3 +16.3 %), dowel Mises mean −13.9 % (worse than D3 −11.3 %).

Numbers: `compare/exports/2026-10-07_zone_offset_c25/tables/T10_zone_offset_trend.csv` (and T2).

Rules already learned (all in GOTCHAS):
- Keep `influence radius` when converting a multi-reference-node coupling to kinematic, or both frame
  lines get tied to both reference nodes.
- Deleting a `*Coupling` must also delete its `*Distributing`/`*Kinematic` sub-option.
- A kinematic variant deck must differ from its parent only in the converted coupling lines
  (`make_kinematic.py` refuses otherwise). Coupling type lives in the substructure decks; the global
  deck only changes its `file=` names.

## Part 1: investigate the coupling-type anomaly

Goal: establish whether the mixed coupling types in the originals are deliberate, and what each one
does to the results.

1.1 **Audit.** Script `src/audit_couplings.py`: for every `.inp` in `portalframe_model_fix` (A, B1, B2,
    C decks, all substructure decks) list each `*Coupling`: name, deck, type, weighting, influence
    radius, number of reference nodes, surface size. Output `coupling/T_coupling_audit.csv` and a table
    in `coupling/README.md`. Check the `.cae` models too if a noGUI query is cheap (the decks are
    generated from them; a mismatch would mean the decks were hand-edited).
1.2 **Provenance.** Look in `portalframe_model_fix` git history, `report/`, journal files (`.jnl`) and
    the published texts in `report/examples/` for any stated reason for kinematic at top/foundation and
    at the B2 mid joint. Ask the user only if nothing is found. Record the answer.
1.3 **Linearity check.** Read the global and substructure decks for `nlgeom`, contact, plasticity.
    Substructures are linear by construction; if the global step is linear too, load effects superpose
    and the load confound can be removed by analysis instead of extra runs. State the result.
1.4 **Separate B2's confounds at t=0** (2×2):

    | | wind only | wind + user + snow |
    |---|---|---|
    | mid distributing | D0 (exists) | D0-L (new) |
    | mid kinematic | D0-Km (new) | B2 published (exists) |

    Each loaded case needs a reference with the same load: build `C25-L` = `C_GLOBAL_R25` plus the B2
    `LOADSET-USER`/`LOADSET-SNOW` cloads (confirm the node sets exist in C and carry the same total;
    V4: summed RF must equal B2's `[60000, 0, 202500]`). If 1.3 shows linearity, D0-L may be skipped
    and its effect computed by superposition; still run one loaded pair to confirm.
    D0-Km = M5B2 verbatim joint deck (kinematic mid) with the D0 top/foundation/main and wind-only global.
    Result: the effect of mid-joint coupling type and of load on B2's apparent accuracy, as separate
    numbers.
1.5 **Top/foundation convention.** D3K showed that "kinematic" in the ladder already meant mixed. Build
    one probe `D3D` = D3 with top and foundation AN-* switched to distributing (all interfaces
    distributing). Extend `make_kinematic.py` into a converter with a `--to kinematic|distributing` and
    `--decks mid,top,foundation,main` selector rather than a second script. Same refuse-on-extra-diff rule.

Gate: report Part 1 to the user before starting Part 2.

## Part 2: kinematic vs distributing over the ladder

Goal: the same zone-offset curve for each coupling convention, so the "safe" offset and the residual
floor can be compared between conventions.

2.1 **Conventions** (names are suffixes on the rung):

    | suffix | mid | top / foundation | main |
    |---|---|---|---|
    | (none) | distributing | kinematic | distributing | — existing D0..D6 (B1 convention) |
    | K | kinematic | kinematic | kinematic | — all rigid |
    | D | distributing | distributing | distributing | — all flexible |

    Run D only if the D3D probe from 1.5 differs materially from D3 (say > 1 percentage point on any
    J3/J6 p95 or mean); otherwise record that top/foundation type does not matter and skip it.
2.2 **Build and solve** `D0K..D6K` (and `D0D..D6D` if needed) with the converter; D3K already exists.
    Per rung: V0–V3b on the decks, datacheck, solve (substructures in parallel across seats), V4 summed
    RF `[60000,0,0]`. Each rung ≈ 30–50 min and ≈ 0.55 GB.
2.3 **Register and compare.** Extend `VARIANTS` in `src/make_cases.py` (currently only D3K), snapshot,
    extract, `compare/src/run_study.py --compare --tag coupling_c25`. Add palette entries in
    `compare/src/figures.py`.
2.4 **Figures.** Extend `src/trend.py` to draw one curve per convention (solid = B1 convention,
    dashed = K, dotted = D) instead of the single variant marker. Output F10 per joint. Judge with p95
    and mean; peaks are mesh sensitive.
2.5 **Mechanism (optional, if the curves disagree in an unexplained way).** At one cut plane, compare
    the interface reaction forces/moments at the substructure reference node with the section forces of
    C25 integrated over the same plane, and measure cut-face warping in C25. This tests whether the
    distributing or the kinematic idealisation is closer to how the real section deforms, and may
    explain the J3 dowel-mean drift (−6 % → −12.5 % with offset) and the offset-independent floor.

## Deliverables

- `coupling/README.md`: audit table, provenance answer, 2×2 result, convention curves, recommendation
  (which coupling type and minimum offset for a joint substructure).
- Update `zone_offset/README.md` and append to `zone_offset/plan.md`.
- New gotchas to canonical `GOTCHAS.md` (ask the user before backfilling the three repo copies).
- Commit and push to `railgnam/offset_parameter_study` when the user asks.
- Update the report artifact (https://claude.ai/artifact/TRgUFTnwzSmAaA9KAxFb1S) or publish a new one.

## Out of scope

Back-calculation of main substructures; the inter-module plate +82 % (mesh-related edge effect, main
study); any change to load, mesh or material other than the cases above; the load/embedding couplings
(AN-4-SLAB, AN-5-WALL*, EMB-*, BASE-BC-CPL).
