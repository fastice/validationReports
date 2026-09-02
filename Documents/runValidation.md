# runValidation

Rebuilds the NISAR velocity-requirement validation from the current GPS parquet files and
mosaic3d master inputs, then writes the dashboard and a dated report.

```
runValidation [--region greenland|antarctica|all] [--stage gps|dump|eval|report|all]
              [--config path.yaml] [--force] [--quiet]
```

| stage | module | reads | writes (`<project>/validation/`) |
|---|---|---|---|
| `gps` | `gpsSeries` | `GPS/*.parquet` | `gps/<STATION>.windows.parquet`, `.coverage.parquet`, `gps/stations.csv`, `figures/gps*.png` |
| `dump` | `pointMode` | master input, `stations.csv` | `pointMode/<group>/{gpsPoints.txt,inputFile,runOff,run.log,mosaicOffsets.*}` |
| `eval` | `forwardModel`, `requirements` | dumps, gps stage | `results/{rows,cumulative,seasonal,summary_slow,summary_fast}.parquet`, `results/status.json` |
| `report` | `plots`, `dashboard` | results of all regions | repo `dashboard/index.html`, `reports/<date>/<region>.md`, `reports/<date>/figures/` |

`--stage all` runs the four in order; `report` always covers every region requested so the
dashboard is complete. `mosaic3d` must be on PATH.

## Configuration (`validationreports/config/<region>.yaml`)

| key | meaning |
|---|---|
| `projectDir`, `masterInput`, `gpsDir`, `validationDir` | project paths (relative to `projectDir`) |
| `epsg`, `dem`, `shelfMask` | projection and mosaic3d inputs (follow the production region yaml) |
| `mosaic3d.flags`, `useSquint`, `dx`, `date1`, `date2`, `ompThreads` | the point-mode run; `dx` in km |
| `groups` | station groups; one mosaic3d run per group on a box = station bbox + `marginKm` |
| `requirements.slow/fast/seasonal` | `absErr`, `pct`, speed split, seasonal `pairDays`, `minRows`, `maxSigma`, `minCoverage` |
| `projectionCycles` | N for the projected status (30 = one year) |
| `gps.*` | window length/step, coverage and point gates, `stepMaxAngle`, stability smoothing |

## GPS stage

Each parquet is split into regimes by `x_sigma` (`< 0.001` replicated winter fix, collapsed to
one epoch per day; `>= 1` degraded, excluded; otherwise dense 30 s). Positions are projected to
polar stereographic and velocities are the regression slopes divided by the projection's
parallel scale (the `nisargps.nisarStation` convention). Position steps that are more than
`stepMaxAngle` off the flow direction are antenna resets or regime offsets: windows spanning
one are rejected and the long-term velocity is fit with an offset at each. Stations are
classed slow/fast by long-term speed against 50 m/yr and stable/variable by the smoothed
peak-to-peak of the dense 12-day speeds against `stableTolFrac` × tolerance.

## Forward model

For each unique (station, date0, nDays) in the dump the GPS reference is `real` (regression
over that window), `extrap` (long-term mean, stable stations), `interp` (between the nearest
usable windows within one window length, variable stations) or `skip` (row dropped from both
solves). `dGps = a·C·v_gps` with the surface-parallel projection from the PIXEL slopes.

## Evaluation and status

Residual r = (NISAR − GPS)/T, T = 0.03·|v_GPS| + c with c = 1 (slow), 5 (fast), 10
(seasonal), for speed, vx and vy. The cumulative estimate at step k uses all rows with cycle
≤ the k-th cycle in the master. Status per requirement: **met** when RMS(r) over stations ≤ 1
for all three quantities; **projected** when the non-negative fit e² = a² + b²/N (steps
k ≥ 4) reaches ≤ 1 at `projectionCycles`; **notMet** otherwise; **insufficient** below two
stations or, for seasonal, without measured GPS. Seasonal solves each (station, cycle) from
its 12-day pairs, gates on formal σ < `maxSigma`, and is met when ≥ 68% of gated intervals at
fast stations are within the envelope for all three quantities and gated/total ≥ `minCoverage`.

## Verification checks

- `obsDump.solve2D` on all rows of a station reproduces `mosaicOffsets.vx/vy.tif` at the
  station pixel (row `ny-1-r`) to < 1e-3 m/yr.
- A constant GPS velocity pushed through the forward model returns exactly.
- On `errCal/gpsDump/mosaicOffsets.obsDump` the seasonal evaluation gives 25 gated intervals,
  RMS speed error 8.9 m/yr, 25/25 within 3%+10 (tsplot.py: 27, 10.15, 26/27 with a different
  GPS estimator and no coverage gate).
