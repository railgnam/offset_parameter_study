# Generic workflow: retain and compare FE results across model variants

Reusable for any comparative Abaqus study (several variants of one core model, one reference). The portalframe study
(`A` module-wise, `B1`/`B2` joint-wise substructures, `C` full model) is the worked example; everything study-specific lives
in `study/*.json`, the code in `src/` is generic.

## The seven steps

| # | Step | What you do | Tool / file |
|---|------|-------------|-------------|
| 1 | **Register cases** | One entry per variant: label, role (`reference`/`test`), status, solver step, jobs, and the files that make the case (ODBs, inputs/logs, optional `.sim`/`.cae`). Cases that are not solved yet stay `pending` and are skipped everywhere. | `study/cases.json` |
| 2 | **Define regions once, on the reference** | Boxes in global coordinates + part-name rules, derived from the reference (full) model, then applied unchanged to every case. Regions are physical features (joint, segment, plate, dowels, section series), never ad-hoc selections. | `src/abq/discover_odb.py` -> `src/make_regions.py` -> `study/regions.json` |
| 3 | **Snapshot (retain)** | When a job has COMPLETED, copy its ODBs + inputs/logs into the store with SHA-256 checksums (identical files are hard-linked, nothing is stored twice). Snapshots are immutable and indexed in `store/manifest.csv`. Later steps read the *copy*, so re-runs, overwrites, deleted ODBs and open Viewer sessions cannot change a result. | `src/snapshot.py` |
| 4 | **Extract to tidy CSV** | Read the snapshot ODBs (read-only) and write long-format CSVs for the regions: element stresses, nodal U/UR, probe nodes. | `src/abq/extract_case.py` -> `store/<case>/<run>/extract/` |
| 5 | **Compare** | Tables per quantity: probe displacements, region stress statistics (peak, mean, p95), per-part and per-dowel values, section series, element-wise error vs the reference, model size and solver time. Deviation = (case - ref)/|ref|. | `src/compare.py` -> `exports/<date>_<tag>/` |
| 6 | **Images** | Fixed colour limits and identical views for all cases; free edges only; section views; assembled into side-by-side montages. | `src/abq/render_contours.py`, `src/montage.py` |
| 7 | **Export for the presentation** | `comparison.xlsx` (one sheet per table, native charts), the tables as CSV, and the image pool. | `exports/<date>_<tag>/` |

Run the whole chain: `python src/run_study.py --all` (incremental; `--force` redoes a step).

## Data layout

```
study/                cases.json, regions.json, discovery/*.json   (the only study-specific files)
store/<case>/<run>/   odb/  inputs/  extract/  SHA256SUMS  meta.json      <- retained, never overwritten
store/manifest.csv    one line per snapshot (case, run id, date, hash, size, complete?)
exports/<date>_<tag>/ comparison.xlsx, tables/*.csv, images/*.png, README.txt
```

## Tidy schema (one row per measurement, so any tool can pivot it)

`elem_stress.csv`: `case, odb, instance, joint, part, class, element, etype, ip, sp, x, y, z, S11, S22, S33, S12, S13, S23, MISES`
- `x,y,z` = element centroid in global coordinates; `class` in `timber | steel_corner | steel_inter | dowel`;
  `ip`/`sp` = integration/section point (dowel beam elements have 4 section points).

`nodal.csv` / `probes.csv`: `case, odb, [probe,] instance, joint, node, x, y, z, U1, U2, U3, UR1, UR2, UR3`

Units: mm, N, tonne, s (stress MPa, displacement mm).

## Rules that keep comparisons honest

1. **Same regions for every case** (boxes from the reference), same step and last frame, same limits in every figure.
2. **Report peak, mean and p95** (p05 for signed stresses). Peaks next to dowel holes depend on the mesh; judge with p95/mean.
3. **Never compare against an unfinished job** (`snapshot` refuses unless the log says COMPLETED).
4. **Quote the run id** that every table and figure came from (printed in `comparison.xlsx` -> README sheet).
5. Region membership is by element-centroid coordinates + part names, so it survives the flattening of substructure ODBs
   into `PART-1-1`.

## Reusing it for another study

1. Copy `compare/` (without `store/`, `exports/`, `work/`).
2. Edit `study/cases.json` (cases, jobs, file patterns, step name, reference).
3. Run `discover_odb.py` on the reference ODB; adapt `make_regions.py` (joint names, segments, section series) -> `regions.json`.
4. If part names follow another pattern, change the two regexes in `extract_case.py` (`part_map_from_sets`) and the class rules in `regions.json`.
5. `python src/run_study.py --all`.

## Adding a case later (e.g. B2 once its global job completes)

Set `"status": "available"` for `B2` in `study/cases.json`, then `python src/run_study.py --cases B2 --snapshot --extract` and
`python src/run_study.py --compare`. Nothing else changes; the new column appears in all tables.

## Gotchas found while building this

- Launch Abaqus from a script with stdin closed (`stdin=DEVNULL`) and one pre-quoted `cmd /c "..."` string; launched from a
  Git-Bash `cmd.exe /c` the Abaqus wrapper can hang silently.
- ODB `steps`, `nodeSets` etc. are `Repository` objects: no `.get()`, use `in obj.keys()`.
- Looping over every node/element in Python is slow for big models; use `bulkDataBlocks` and numpy.
- Recovery ODBs are flattened (`PART-1-1`); parts are identified by the element sets `<part>_MAT-GLM`, `<part>_S235`,
  `DWL_*__PICKEDSET*`.
- Main-beam substructures cannot be recovered by Abaqus (see `backcalc/README.md`); their recovery ODBs have no frames. Back-calculated ODBs
  have no element sets and name their steps `BC-<step>`: parts are assigned by matching element centroids to the reference model.
- **View cuts (`odbDisplay.ViewCut`)**: Abaqus puts a new plane at the CENTRE of the displayed model whatever `origin` you pass (`position` is
  auto-set). Call `cut.setValues(position=0.0)` after creating it, and give every cut a unique name (names are session-wide).
  Symptom of forgetting: all cuts look identical and differ between ODBs with different extents.
- `Viewport.view.setProjection(PARALLEL)` must be called after setting the camera, otherwise the projection can silently revert.
- A node lies in the global ODB only if it is a retained node; look it up by coordinate in the recovery and back-calculated ODBs instead of by set name.
- Excel files opened in Excel are locked: write exports under a time-stamped name instead of failing.
