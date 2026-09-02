# validationReports

Continuous validation of the NISAR ice-velocity requirements (L2-SCI-667 slow flow,
L2-SCI-668 fast flow, L2-SCI-738 seasonal sampling) against the cal/val GPS networks in
Greenland (NIU, NIL) and Antarctica (NIT). One command rebuilds everything from the current
GPS parquet files and mosaic3d master inputs, writes a self-contained HTML dashboard
(`dashboard/index.html`) and a dated markdown report (`reports/YYYY-MM-DD/<region>.md`).

```
runValidation --region all --stage all        # gps -> dump -> eval -> report
runValidation --region greenland --stage eval  # one region, one stage
runValidation --stage dump --force             # re-run mosaic3d even if the dump is current
```

**gpsSeries** reads each station parquet, separates the three sampling regimes (30 s,
one winter fix per day, degraded), detects antenna resets, and builds 12-day sliding-window
velocities plus the station classification (slow/fast, stable/variable).

**pointMode** writes a boxed copy of the master input around each station group and runs
`mosaic3d -obsDump`, which dumps every observation ($\mathbf a_i, d_i, \sigma_i, w_i$) at
the GPS pixels.

**forwardModel** computes the GPS velocity over each observation's own window and pushes it
through the solver's weights, so temporal sampling cancels exactly.

**requirements** solves cumulative-cycle and per-cycle estimates, scores speed, $v_x$ and
$v_y$ against $0.03\,V + c$, and projects the error curve to a full year of cycles.

**plots** and **dashboard** produce the figures, the dashboard and the dated report.

Configuration lives in `validationreports/config/<region>.yaml`; intermediate products go to
`<project>/validation/`. See `Documents/` for each module.
