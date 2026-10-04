# Reference velocity points for validation

Four point sets for validating ice-velocity products where the GPS network does not
reach. All coordinates are EPSG:3413; `x`,`y` are metres, velocities m/yr.

## `summitPoints.csv` — 9 stations, Summit area

72.58–72.64 N, −37.75 to −38.79 E, ~3200 m. Annual solutions for 2022, 2023, 2024
averaged. `speed`/`azimuth` are the supplied polar form (azimuth = degrees clockwise
from TRUE north, negative = west of north); `vE`/`vN` are east/north; `vx`/`vy` are
EPSG:3413, rotated by the meridian convergence `lon + 45` (6–7° here — it matters).
Year-to-year repeatability: speed spread 0.016–0.113 m/yr, azimuth 0.45–8.25°.

**Do not use these to test a scale.** Speeds are 0.55–2.26 m/yr, so an ordinary
NISAR error of ~0.9 m/yr reads as a 60 % deficit. Measured NISAR scale here is
0.379 with a residual of 0.92 m/yr — a deficit-to-noise ratio of 0.95, i.e. not
distinguishable from unity. The nine points sit in a 35 km box and share frames, so
the effective sample size is closer to one than nine. They are useful for bounding
an *additive* offset, not a multiplicative one.

## `tiePoints2000_all.csv` — 152 points, 2000 m contour

From `/Users/ian/tiepoints/newSentinelTies/iceEquivalent/tiepoints.2000.vz`,
epoch ~2000, 1638–2977 m elevation, 0.8–198 m/yr. Column 6 of the source file is an
old SMB vertical correction and is deliberately **not** carried over. `refVx`/`refVy`
are the project `velocityMap.vrt` sampled at each point, with `refOverTie` the speed
ratio and `refDirDiff` the flow-direction difference in degrees.

Note the reference these are compared against is itself suspect — see the caveat below.

## `tiePoints2000_validation.csv` — 45 points, validation grade

The subset south of 77 N (32 dropped: no data or poor geometry beyond that) whose
projected change between the tie-point epoch and now is **below half the requirement
tolerance**, where T = 0.03·v + 1 below 50 m/yr and 0.03·v + 5 above. Change is the
S1 annual-stack trend (9 epochs, 2014-15 … 2022-23) extrapolated over a 26-year gap.

Columns: `cls`/`tol` are the requirement class and tolerance; `s1StackMean`,
`s1StackSd`, `s1FormalErr` summarise the annual stack; `trend`/`trendSE` are m/yr per
year; `projChange26yr` is the extrapolated drift in m/yr. `nisarVx`/`nisarVy` are the
no-squint NISAR release mosaic; `refVx`/`refVy` the S1 reference.

24 slow (1.1–50 m/yr) and 21 fast (54–152). Measured 2026-09-02, NISAR no-squint:
scale 0.995 ± 0.009 overall, 1.017 slow, 0.993 fast. Cumulative-cycle curves give
RMS(residual/tolerance) 0.766 slow and 0.425 fast — both requirements met.

**Screen on the trend, not the scatter.** Year-to-year scatter and trend are close to
independent: of the 91 points with scatter ≤5 % of mean, 24 still project to >10 %
change over the gap. Only 2 of the 45 are below 6 m/yr, so this set does **not**
constrain the very slow regime.

## `negisPoints.csv` — 63 points, NEGIS / EastGRIP strain net

From `/home/ian/NISAR/nisarCryoCalValNotebooks/GPSpoints/NEGIS-GPS.txt`: Hvidberg, C. S. et al.
(2020), Surface velocity of the Northeast Greenland Ice Stream (NEGIS): assessment of interior
velocities derived from satellite data by GPS, *The Cryosphere* 14, 3487–3502,
doi:10.5194/tc-14-3487-2020. A 63-pole strain net observed 2015–2019, 75.5–75.9 N,
~2700 m, 9.7–58.4 m/yr (52 slow, 11 fast). Source columns are lat, lon, elev, vx, vy, flag
(all 0); `vx`/`vy` are already EPSG:3413 components.

**No cull.** The GPS epoch sits inside the S1 annual stack, and the stack mean reads 1.0007
of the GPS speed (median over the 63), so the 2000 m trend screen is not applied. The
`s1Stack*`/`trend*` columns are kept for reference. All 63 fall in one point-mode box (NEGIS01).

Not used: `NEGIS{1,2,3}_velocity.corrected.txt` in the same directory (daily 2016–2019
series from Abbas Khan) — the source README requires his permission to use them.

## Caveat that applies to every comparison here

`velocityMap.vrt` (the `velMap` in `greenland.yaml`, and the assumed-motion field for
tie-point corrections) resolves to the S1 `multiYear` `v01.0` product written
2021-12-10 — four versions behind the `v05.0` annuals. At the NIU GPS sites it reads
0.72–0.90 of GPS, while all nine annual mosaics, and an average of them, read
0.99–1.00. The stored multi-year composite is biased on slow interior ice; the annuals
are not. Treat `refVx`/`refVy` accordingly.

## Reproducing the cull

`buildReferencePoints.py` regenerates all three CSVs from their sources. Run it from
this directory. It is not part of any pipeline — it exists so the culling is auditable.

The cull is two independent steps, reported separately:

1. **`lat < 77`** — 152 → 120. North of that there is either no data or the geometry
   is too poor to trust. A judgement call, not a measurement.
2. **projected change < 0.5 × tolerance** — 120 → 45. The S1 annual stack (9 epochs,
   2014-15 … 2022-23) gives a per-point OLS trend of speed against epoch year; that
   slope is extrapolated linearly over the 26-year gap from the tie epoch (~2000) to
   the NISAR mosaic centre (~2026) and compared against T = 0.03·v + 1 (slow) or
   0.03·v + 5 (fast), classified by tie-point speed.

No outlier rejection, no speed cut, no nodata losses — every one of the 152 data lines
parses and every point has both reference and NISAR coverage. The source file's
trailing `&` terminator is the only line skipped.

## Solver settings, and how they compare to the GPS runs

The tie-point `obsDump`s were produced with **the same `cfg['mosaic3d']['flags']` as
the GPS point-mode runs** — `mosaic3d`'s own logged settings block diffs clean between
`pointMode/NIU/run.log` and `pointMode/TIE01/run.log`:

    ; SOLVER: hopper3D (forced 2D)  rows: phase range azimuth

so the per-observation sigmas and weights come from an identical chain. Two differences
that do exist:

- **Thread count is not uniform**: 8 of the 33 clusters ran at `-ompThreads 8` and 25 at
  `-ompThreads 2`. The hopper is deterministic single-threaded but not bit-reproducible
  across thread counts (~50 of 33,812 px, max 4.4e-3 m/yr, from `llToImageNew`'s
  `lastTime` warm-start). Far below anything that matters here, but it is not a
  bit-identical configuration.
- **The forward model is not the same, and cannot be.** GPS validation pushes the GPS
  through each observation's own window, so temporal sampling cancels exactly. The tie
  points have no time series — truth is one constant velocity — so `dGps = a · v_tie`
  with the surface-parallel vertical, and every row is labelled `quality='real'`. That
  label is generous: the tie epoch does not overlap the NISAR window at all, and by the
  GPS convention these rows would be `extrap`. The screening in step 2 is what justifies
  treating them as valid, not the label.
