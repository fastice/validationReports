# CLAUDE.md — validationReports

NISAR velocity-requirement validation against GPS. Entry point `runValidation`
(`validationreports/runValidation.py`), stages `gps -> dump -> eval -> report`, regions
`greenland` / `antarctica` from `validationreports/config/<region>.yaml`.

## Rules that shape the code

- **Rebuild from scratch every run.** Nothing GPS-derived is cached; the only skip is the
  mosaic3d dump when `mosaicOffsets.obsDump` is newer than the master input (`--force`
  overrides). When new GPS data arrive, windows previously `extrap`/`interp` become `real`
  with no config change.
- **No squint anywhere** (`useSquint: false` in both configs, decision 2026-09-02).
- **Strict 50 m/yr split** between slow and fast by long-term GPS speed (NIU1 and NIT1 sit
  just above it and count as fast).
- **Never reimplement mosaic3d's $\mathbf a_i$, $w_i$ in Python** — they come from the dump
  (`obsDump.solve2D` reproduces the product to 1e-4 m/yr; keep that check passing).
- The obsDump row order is OpenMP-dependent; everything sorts by station/date0/obsType.

## GPS handling (gpsSeries.py)

Three epoch regimes from `x_sigma`: `< 0.001` = one winter fix replicated 239x or 2880x per
day (collapsed to one epoch/day, regime `daily`); `>= 1.0` = Antarctic winter placeholder
(metre-level scatter, regime `degraded`, excluded); else `dense` 30 s data. A window is `ok`
only if coverage >= `minCoverageFrac`, `minPoints` epochs, formal sigma <= the station's
requirement tolerance, and no position step inside it.

Position steps: two-sided detector on daily medians (`detectSteps`, ported from
`errCal/report/scripts/gpsLoad.detectJumps2`), then `classifySteps` keeps only jumps more
than `stepMaxAngle` (30 deg) off the flow direction. Forward along-flow jumps are melt-season
motion (NIL Jul-Sep 2025) and are NOT steps; off-axis/backward jumps are antenna resets (NIT
late Jan 2025, NIL 7-9 Aug 2025) or regime offsets. The long-term velocity is fit with an
offset at each kept step.

Stability: peak-to-peak of the 36-day-smoothed 12-day speed from dense windows only, against
`stableTolFrac` x tolerance. Stable stations get `extrap` (long-term mean) where a window has
no data; variable stations get `interp` within one window length, else the row is skipped
from BOTH solves.

## Static reference sets (referencePoints.py)

`referenceSets` in a region config (Greenland: `referencePoints/summitPoints.csv` and
`tiePoints2000_validation.csv`) are single velocities with no time series: forward model =
constant velocity (quality `static`), always stable. The 2000 m points are named `T<row>` by 0-based
row in the validation CSV; Summit uses its `station` column. Each set is clustered in table
order (`maxClusterKm`) for the point-mode runs; **an existing dump directory whose point set
matches a cluster is reused** (matching by lat/lon, not by name), so the other session's
TIE01..TIE33 / SUMMIT runs are not repeated, and clusters that must run get a directory name
no run has used (`_assignFreeNames`) and run `maxParallel` (8) at a time. The mapping is
written to `pointMode/groups.json` and read by the eval stage. Status for slow/fast is
judged on ALL points (`group = all`); per-group RMS(r) (gps / summit / points2000) is reported
alongside. Seasonal uses GPS stations only.

## Evaluation (requirements.py)

Residual r = (NISAR - GPS) / T with T = 0.03 |v_GPS| + c, evaluated for speed, vx, vy.
Cumulative estimate k uses all rows with cycle <= the k-th cycle present in the master
(x-axis = cycles in the master, not calendar time). Met: RMS(r) over stations <= 1 for all
three. Projection: non-negative LSQ fit of e^2 = a^2 + b^2/N on steps k >= 4, evaluated at
`projectionCycles` (30). Seasonal: per (station, cycle) solve from the 12-day pairs, gated on
formal sigma < `maxSigma`, met when >= 68% of gated intervals have |r| <= 1 for all three and
gated/total >= `minCoverage`; status uses fast stations only.

## Known data facts (2026-09-02)

- Antarctic masters (`Antarctica2026/Release/track-all/inputFile`, Antarctica40/80) all start
  at cycle 15 (2026-03-10); NIT GPS end Feb/Mar 2026 -> no overlap yet; NIT comparisons are
  `extrap` until the stations come back up.
- Greenland: consistent ~10% NISAR deficit at NIU2/NIU3 makes L2-SCI-667 `notMet` with a
  bias floor; fast and seasonal are met.
- The dump box header is `x0 y0 xSize ySize dx dy` in km (extent, not pixel count);
  GeoTIFF origin = x0 - dx/2.

## Outputs

`<project>/validation/{gps,pointMode/<group>,results,figures}`; repo `dashboard/index.html`
(figures inlined base64, publishable as an artifact) and `reports/<date>/<region>.md` +
`figures/`. Committing the dated report is the user's call.
