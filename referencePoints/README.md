# Reference velocity points for validation

Three point sets for validating ice-velocity products where the GPS network does not
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

## Caveat that applies to every comparison here

`velocityMap.vrt` (the `velMap` in `greenland.yaml`, and the assumed-motion field for
tie-point corrections) resolves to the S1 `multiYear` `v01.0` product written
2021-12-10 — four versions behind the `v05.0` annuals. At the NIU GPS sites it reads
0.72–0.90 of GPS, while all nine annual mosaics, and an average of them, read
0.99–1.00. The stored multi-year composite is biased on slow interior ice; the annuals
are not. Treat `refVx`/`refVy` accordingly.
