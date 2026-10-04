"""GPS station series: parquet -> cleaned epochs -> windowed velocities.

Three data regimes coexist in the cal/val parquet files:
  dense     continuous 30 s epochs (~2880/day), x_sigma ~9 mm
  daily     one winter fix per day, replicated onto the 30 s grid (239x or
            2880x) with x_sigma < 0.001 m; collapsed here to one epoch/day
  degraded  Antarctic winter solutions flagged with x_sigma = 10 m and
            metre-level scatter; excluded from the position series

Velocities follow nisargps.nisarStation.computeVelocityRegression: linear
regression of the polar-stereographic x(t), y(t) over the window, divided by the
projection's parallel scale so the result is a true ground velocity in m/yr.
"""
import os
import glob
from datetime import timedelta

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyproj
from scipy.stats import linregress

REPLICATED_SIGMA = 0.001   # x_sigma below this marks a replicated daily fix
DEGRADED_SIGMA = 1.0       # x_sigma at or above this marks a degraded solution
SECONDS_PER_YEAR = 365.25 * 86400.
STATION_COLUMNS = ['time_utc', 'lat', 'lon', 'x_sigma']
REGIMES = ['dense', 'daily', 'degraded']


class GpsStation:
    '''Cleaned position series for one station with windowed regression.'''

    def __init__(self, parquetPath, epsg, denseEpochsPerDay=1000,
                 stepMaxAngle=30., excludeAfter=None, splitGaps=None):
        self.name = os.path.basename(parquetPath).split('.')[0]
        self.parquetPath = parquetPath
        self.epsg = epsg
        raw = pq.read_table(parquetPath, columns=STATION_COLUMNS).to_pandas()
        raw = raw.sort_values('time_utc').reset_index(drop=True)
        if excludeAfter is not None:   # config gps.excludeAfter: record not yet usable
            raw = raw[raw['time_utc'] < pd.Timestamp(excludeAfter)].reset_index(drop=True)
        # config gps.splitGaps: [start, end) of a known disturbance (service visit, fallen
        # pole). Its epochs are dropped and the record is fit as two pieces with a common
        # velocity and separate offsets (a known step at `end`).
        self.knownSteps = []
        for g0, g1 in (splitGaps or []):
            g0, g1 = pd.Timestamp(g0), pd.Timestamp(g1)
            raw = raw[(raw['time_utc'] < g0) | (raw['time_utc'] >= g1)].reset_index(drop=True)
            self.knownSteps.append(g1)
        raw['regime'] = self._epochRegime(raw)
        self.coverage = self._coverageTable(raw, denseEpochsPerDay)
        self.data = self._cleanEpochs(raw)
        self._project()
        self.t0 = self.data['time_utc'].iloc[0]
        self.t1 = self.data['time_utc'].iloc[-1]
        self.daily = self._dailySeries()
        # detect every discontinuity, then keep those that cannot be motion
        candidates = detectSteps(self.daily)
        self.steps = []
        prelim = self.longTermVelocity()
        self.steps = classifySteps(candidates, prelim['vx'], prelim['vy'],
                                   maxAngle=stepMaxAngle)
        # known steps replace any detected step within 3 days of them
        for k in self.knownSteps:
            self.steps = [st for st in self.steps if abs(st['day'] - k) > timedelta(days=3)]
            self.steps.append(dict(day=k, magnitude=np.nan, known=True))
        self.steps.sort(key=lambda st: st['day'])

    def _dailySeries(self):
        '''Daily median positions (m) and time (days since 1970).'''
        day = self.data['time_utc'].dt.floor('D')
        d = self.data.groupby(day).agg(x=('x', 'median'), y=('y', 'median'),
                                       n=('x', 'size'))
        d = d.reset_index().rename(columns={'time_utc': 'day'})
        d['t'] = (d['day'] - pd.Timestamp('1970-01-01')).dt.total_seconds() / 86400.
        return d

    def stepsWithin(self, date0, date1):
        '''Detected position steps inside (date0, date1].'''
        return [s for s in self.steps
                if pd.Timestamp(date0) < s['day'] <= pd.Timestamp(date1)]

    # ------------------------------------------------------------------
    @staticmethod
    def _epochRegime(raw):
        sig = raw['x_sigma']
        return np.where(sig >= DEGRADED_SIGMA, 'degraded',
                        np.where(sig < REPLICATED_SIGMA, 'daily', 'dense'))

    @staticmethod
    def _coverageTable(raw, denseEpochsPerDay):
        '''Per-day epoch counts and the dominant regime.'''
        day = raw['time_utc'].dt.floor('D')
        counts = pd.crosstab(day, raw['regime'])
        for r in REGIMES:
            if r not in counts:
                counts[r] = 0
        cov = counts[REGIMES].reset_index().rename(columns={'time_utc': 'day'})
        cov['nEpochs'] = cov[REGIMES].sum(axis=1)
        cov['regime'] = cov[REGIMES].idxmax(axis=1)
        # a thin dense day (e.g. a partial day) still counts as dense
        return cov

    @staticmethod
    def _cleanEpochs(raw):
        '''Drop degraded epochs; collapse daily fixes to one row per day.'''
        dense = raw[raw['regime'] == 'dense']
        daily = raw[raw['regime'] == 'daily']
        parts = [dense]
        if len(daily) > 0:
            dayKey = daily['time_utc'].dt.floor('D')
            d = daily.groupby(dayKey).agg(time_utc=('time_utc', 'median'),
                                          lat=('lat', 'first'),
                                          lon=('lon', 'first'),
                                          x_sigma=('x_sigma', 'first'))
            d['regime'] = 'daily'
            parts.append(d.reset_index(drop=True))
        out = pd.concat(parts, ignore_index=True)
        return out.sort_values('time_utc').reset_index(drop=True)

    def _project(self):
        '''Add polar-stereographic x, y (m) and decimal time (years).'''
        transformer = pyproj.Transformer.from_crs('EPSG:4326',
                                                  f'EPSG:{self.epsg}',
                                                  always_xy=True)
        lon = self.data['lon'].to_numpy()
        lat = self.data['lat'].to_numpy()
        x, y = transformer.transform(lon, lat)
        self.data['x'] = x
        self.data['y'] = y
        self.lat = float(np.median(lat))
        self.lon = float(np.median(lon))
        self.x = float(np.median(x))
        self.y = float(np.median(y))
        # projected metres -> ground metres (nisarStation.projLengthScale)
        proj = pyproj.Proj(f'EPSG:{self.epsg}')
        self.scale = proj.get_factors(self.lon, self.lat).parallel_scale
        # parquet timestamps are microsecond resolution; go via total_seconds
        t = (self.data['time_utc'] - pd.Timestamp('1970-01-01')
             ).dt.total_seconds().to_numpy()
        self.tSeconds = t
        self.tYears = t / SECONDS_PER_YEAR
        self.isDaily = (self.data['regime'] == 'daily').to_numpy()

    # ------------------------------------------------------------------
    def _select(self, date0, date1):
        '''Index slice for epochs in [date0, date1).'''
        t0 = pd.Timestamp(date0).value / 1e9
        t1 = pd.Timestamp(date1).value / 1e9
        i0 = np.searchsorted(self.tSeconds, t0, side='left')
        i1 = np.searchsorted(self.tSeconds, t1, side='left')
        return i0, i1

    def windowCoverage(self, date0, date1):
        '''dict(dayFrac, spanFrac, dailyFrac, regime) for a window.'''
        i0, i1 = self._select(date0, date1)
        nDays = (pd.Timestamp(date1) - pd.Timestamp(date0)).total_seconds() \
            / 86400.
        out = dict(dayFrac=0., spanFrac=0., dailyFrac=np.nan, regime='none')
        if i1 <= i0 or nDays <= 0:
            return out
        days = self.data['time_utc'].iloc[i0:i1].dt.floor('D')
        span = (self.tSeconds[i1 - 1] - self.tSeconds[i0]) / 86400.
        dailyDays = days[self.isDaily[i0:i1]].nunique()
        nUnique = days.nunique()
        dailyFrac = dailyDays / nUnique
        if dailyDays == 0:
            regime = 'dense'
        elif dailyDays == nUnique:
            regime = 'daily'
        else:
            regime = 'mixed'
        out.update(dayFrac=min(nUnique / nDays, 1.), spanFrac=min(span / nDays, 1.),
                   dailyFrac=dailyFrac, regime=regime)
        return out

    def windowVelocity(self, date0, date1, minCoverageFrac=0.5, minPoints=10,
                       sigmaMultiple=3, maxSigma=np.inf):
        '''Regression velocity over [date0, date1).

        Returns a dict with vx, vy (m/yr), sigVx, sigVy (formal, m/yr),
        nEpochs, dayFrac, spanFrac, dailyFrac, regime and ok. Velocities are
        NaN unless ok; ok requires coverage, minPoints and formal sigma
        below maxSigma on both components.
        '''
        i0, i1 = self._select(date0, date1)
        cov = self.windowCoverage(date0, date1)
        result = dict(vx=np.nan, vy=np.nan, sigVx=np.nan, sigVy=np.nan,
                      nEpochs=int(i1 - i0), ok=False, **cov)
        if i1 - i0 < minPoints or \
                min(cov['dayFrac'], cov['spanFrac']) < minCoverageFrac:
            return result
        inside = self.stepsWithin(date0, date1)
        if any(not st.get('known', False) for st in inside):
            result['regime'] = 'step'
            return result
        t = self.tYears[i0:i1]
        x = self.data['x'].to_numpy()[i0:i1]
        y = self.data['y'].to_numpy()[i0:i1]
        # known steps: two pieces with a common slope; a piece too short to anchor its own
        # offset is dropped rather than fit
        stepT = []
        for st in inside:
            ts = (st['day'] - pd.Timestamp('1970-01-01')).total_seconds() / SECONDS_PER_YEAR
            nBefore, nAfter = int((t < ts).sum()), int((t >= ts).sum())
            if nAfter < minPoints:
                keep = t < ts
            elif nBefore < minPoints:
                keep = t >= ts
            else:
                stepT.append(ts)
                continue
            t, x, y = t[keep], x[keep], y[keep]
        if stepT:
            return self._piecewiseVelocity(result, t, x, y, stepT, minPoints,
                                           sigmaMultiple, maxSigma)
        if sigmaMultiple is not None:
            good = np.ones(len(t), dtype=bool)
            for d in [x, y]:
                fit = linregress(t, d)
                resid = d - (fit.slope * t + fit.intercept)
                sigma = np.std(resid)
                if sigma > 0:
                    good &= np.abs(resid) < sigmaMultiple * sigma
            t, x, y = t[good], x[good], y[good]
            if len(t) < minPoints:
                return result
        fx = linregress(t, x)
        fy = linregress(t, y)
        sigVx, sigVy = fx.stderr / self.scale, fy.stderr / self.scale
        ok = bool(max(sigVx, sigVy) <= maxSigma)
        result.update(sigVx=sigVx, sigVy=sigVy, nEpochs=int(len(t)), ok=ok)
        if ok:
            result.update(vx=fx.slope / self.scale, vy=fy.slope / self.scale)
        return result

    def _piecewiseVelocity(self, result, t, x, y, stepT, minPoints, sigmaMultiple, maxSigma):
        '''Common-slope fit with an offset after each known step (same gates as above).'''
        A = np.column_stack([t, np.ones_like(t)] + [(t >= s).astype(float) for s in stepT])
        good = np.ones(len(t), dtype=bool)
        for _ in range(2 if sigmaMultiple is not None else 1):
            fits = []
            for d in (x, y):
                coef = np.linalg.lstsq(A[good], d[good], rcond=None)[0]
                fits.append((coef, d - A @ coef))
            if sigmaMultiple is not None:
                keep = np.ones(len(t), dtype=bool)
                for _, resid in fits:
                    sd = np.std(resid[good])
                    if sd > 0:
                        keep &= np.abs(resid) < sigmaMultiple * sd
                good = keep
            if good.sum() < minPoints:
                return result
        AtA = np.linalg.inv(A[good].T @ A[good])
        dof = max(int(good.sum()) - A.shape[1], 1)
        out = []
        for coef, resid in fits:
            s2 = float((resid[good] ** 2).sum()) / dof
            out.append((coef[0] / self.scale, np.sqrt(s2 * AtA[0, 0]) / self.scale))
        (vx, sigVx), (vy, sigVy) = out
        ok = bool(max(sigVx, sigVy) <= maxSigma)
        result.update(sigVx=sigVx, sigVy=sigVy, nEpochs=int(good.sum()), ok=ok,
                      regime=result['regime'] if result['regime'] != 'none' else 'dense')
        if ok:
            result.update(vx=vx, vy=vy)
        return result

    def slidingWindows(self, windowDays=12, stepDays=3, **kwargs):
        '''Window velocities every stepDays over the record (DataFrame).'''
        rows = []
        start = self.t0.floor('D')
        while start + timedelta(days=windowDays) <= self.t1:
            end = start + timedelta(days=windowDays)
            r = self.windowVelocity(start, end, **kwargs)
            r['date0'] = start
            r['date1'] = end
            r['mid'] = start + timedelta(days=windowDays / 2.)
            rows.append(r)
            start += timedelta(days=stepDays)
        df = pd.DataFrame(rows)
        df['speed'] = np.hypot(df['vx'], df['vy'])
        df['station'] = self.name
        return df

    def longTermVelocity(self, minPoints=10, sigmaMultiple=3, **kwargs):
        '''Regression over the full record with an offset at each step.

        Design matrix [t, 1, H(t - s_1), ...]; the shared slope is the velocity,
        so antenna resets do not leak into the long-term mean.
        '''
        t = self.tYears
        x = self.data['x'].to_numpy()
        y = self.data['y'].to_numpy()
        stepT = [(s['day'] - pd.Timestamp('1970-01-01')).total_seconds()
                 / SECONDS_PER_YEAR for s in self.steps]
        cols = [t, np.ones_like(t)] + [(t >= s).astype(float) for s in stepT]
        A = np.column_stack(cols)
        good = np.ones(len(t), dtype=bool)
        result = dict(vx=np.nan, vy=np.nan, sigVx=np.nan, sigVy=np.nan,
                      nEpochs=int(len(t)), nSteps=len(self.steps), ok=False)
        for _ in range(2 if sigmaMultiple is not None else 1):
            fits = {}
            for name, d in [('x', x), ('y', y)]:
                coef, res, _, _ = np.linalg.lstsq(A[good], d[good], rcond=None)
                resid = d - A @ coef
                fits[name] = (coef, resid)
            if sigmaMultiple is not None:
                for name in fits:
                    sigma = np.std(fits[name][1][good])
                    if sigma > 0:
                        good &= np.abs(fits[name][1]) < sigmaMultiple * sigma
        n = int(good.sum())
        if n < minPoints:
            return result
        for name in fits:
            coef, resid = fits[name]
            dof = max(n - A.shape[1], 1)
            s2 = np.sum(resid[good] ** 2) / dof
            cov = s2 * np.linalg.inv(A[good].T @ A[good])
            v, sig = coef[0] / self.scale, np.sqrt(cov[0, 0]) / self.scale
            result[f'v{name}'] = v
            result[f'sigV{name}'] = sig
        result.update(nEpochs=n, ok=True)
        return result


# ----------------------------------------------------------------------
def detectSteps(daily, fitWin=16, buf=2, nSigma=6.0, minJump=0.10):
    '''Two-sided position-step detector on a daily median series.

    Independent lines are fitted either side of each candidate day and the
    discontinuity at the break is tested against its propagated uncertainty,
    so a velocity change (kink) is not flagged, only a genuine offset (antenna
    reset / re-deployment). Returns [{day, magnitude, nSigma}], merged so the
    largest candidate within fitWin days is kept. Ported from
    errCal/report/scripts/gpsLoad.detectJumps2.
    '''
    t = daily['t'].to_numpy()
    xs = {c: daily[c].to_numpy() for c in ('x', 'y')}
    found = []
    for i in range(fitWin + buf, len(daily) - fitWin - buf):
        pre = slice(i - buf - fitWin, i - buf)
        post = slice(i + buf, i + buf + fitWin)
        # require the fit windows to be reasonably contiguous in time
        if t[i] - t[pre.start] > 3 * fitWin or t[post.stop - 1] - t[i] > 3 * fitWin:
            continue
        step2, var2, offs = 0., 0., {}
        for c in ('x', 'y'):
            v = xs[c]
            cp, covp = np.polyfit(t[pre], v[pre], 1, cov=True)
            cq, covq = np.polyfit(t[post], v[post], 1, cov=True)
            ti = t[i]
            d = np.polyval(cq, ti) - np.polyval(cp, ti)
            g = np.array([ti, 1.])
            step2 += d * d
            var2 += g @ covp @ g + g @ covq @ g
            offs[c] = float(d)
        mag, sig = np.sqrt(step2), np.sqrt(max(var2, 1e-18))
        if mag > minJump and mag > nSigma * sig:
            found.append((i, mag, mag / sig, offs['x'], offs['y']))
    merged = []
    for item in found:
        if merged and item[0] - merged[-1][0] < fitWin:
            if item[1] > merged[-1][1]:
                merged[-1] = item
        else:
            merged.append(item)
    return [dict(day=daily['day'].iloc[i], magnitude=float(m), nSigma=float(s),
                 dx=dx, dy=dy)
            for i, m, s, dx, dy in merged]


def classifySteps(steps, vx, vy, maxAngle=30.):
    '''Keep steps that cannot be ice motion.

    A melt-season speed-up moves the antenna forward along the flow direction;
    an antenna reset or a processing-regime offset is off-axis or backward.
    Returns the steps whose offset vector is more than maxAngle degrees from
    the flow direction, each with its angle added.
    '''
    speed = np.hypot(vx, vy)
    if not np.isfinite(speed) or speed == 0:
        return steps
    kept = []
    for s in steps:
        cosA = (s['dx'] * vx + s['dy'] * vy) / (s['magnitude'] * speed)
        angle = float(np.degrees(np.arccos(np.clip(cosA, -1., 1.))))
        if angle > maxAngle:
            kept.append(dict(s, angleToFlow=angle))
    return kept


# ----------------------------------------------------------------------
def requirementClass(speed, requirements):
    '''slow or fast by GPS speed.'''
    return 'slow' if speed < requirements['slow']['maxSpeed'] else 'fast'


def requirementTolerance(speed, reqClass, requirements):
    '''3%·V + absErr for a class.'''
    r = requirements[reqClass]
    return r['pct'] * abs(speed) + r['absErr']


def stabilityMetrics(windows, gpsCfg):
    '''Smoothed peak-to-peak and std of the 12-day speeds (dense windows only).'''
    ok = windows[windows['ok'] & (windows['regime'] == 'dense')].sort_values('mid')
    if len(ok) < 3:
        return dict(speedStd=np.nan, speedP2P=np.nan, nWindows=int(len(ok)))
    nSmooth = max(1, int(round(gpsCfg['smoothDays'] / gpsCfg['stepDays'])))
    smoothed = ok['speed'].rolling(nSmooth, center=True, min_periods=1).median()
    return dict(speedStd=float(ok['speed'].std()),
                speedP2P=float(smoothed.max() - smoothed.min()),
                nWindows=int(len(ok)))


def windowKwargs(gpsCfg, maxSigma=np.inf):
    return dict(minCoverageFrac=gpsCfg['minCoverageFrac'],
                minPoints=gpsCfg['minPoints'],
                sigmaMultiple=gpsCfg['sigmaMultiple'], maxSigma=maxSigma)


def stationTolerance(station, cfg):
    '''(long-term velocity dict, speed, class, tolerance) for a station.'''
    gpsCfg = cfg['gps']
    lt = station.longTermVelocity(minPoints=gpsCfg['minPoints'],
                                  sigmaMultiple=gpsCfg['sigmaMultiple'])
    speed = float(np.hypot(lt['vx'], lt['vy']))
    reqClass = requirementClass(speed, cfg['requirements'])
    tol = requirementTolerance(speed, reqClass, cfg['requirements'])
    return lt, speed, reqClass, tol


def summarizeStation(station, windows, cfg, lt, speed, reqClass, tol):
    '''One row of the station table.'''
    gpsCfg = cfg['gps']
    stab = stabilityMetrics(windows, gpsCfg)
    stable = bool(np.isfinite(stab['speedP2P'])
                  and stab['speedP2P'] <= gpsCfg['stableTolFrac'] * tol)
    cov = station.coverage
    return dict(station=station.name, lat=station.lat, lon=station.lon,
                x=station.x, y=station.y, vx=lt['vx'], vy=lt['vy'],
                speed=speed, reqClass=reqClass, tolerance=tol,
                speedStd=stab['speedStd'], speedP2P=stab['speedP2P'],
                nWindows=stab['nWindows'], stable=stable,
                nSteps=len(station.steps),
                steps=';'.join(f"{s['day'].date()}:{s['magnitude']:.2f}m"
                               for s in station.steps),
                recordStart=station.t0.date(), recordEnd=station.t1.date(),
                daysWithData=int((cov['regime'] != 'degraded').sum()),
                daysDense=int((cov['regime'] == 'dense').sum()),
                daysDaily=int((cov['regime'] == 'daily').sum()),
                daysDegraded=int((cov['regime'] == 'degraded').sum()))


def stationFiles(cfg):
    '''{name: parquet path} for every station parquet in the GPS directory.'''
    files = sorted(glob.glob(os.path.join(cfg['paths']['gpsDir'], '*.parquet')))
    return {os.path.basename(f).split('.')[0]: f for f in files}


def loadStation(cfg, name):
    '''GpsStation for a named station in this region.'''
    files = stationFiles(cfg)
    if name not in files:
        raise FileNotFoundError(f'no parquet for {name} in {cfg["paths"]["gpsDir"]}')
    return GpsStation(files[name], cfg['epsg'],
                      denseEpochsPerDay=cfg['gps']['denseEpochsPerDay'],
                      stepMaxAngle=cfg['gps'].get('stepMaxAngle', 30.),
                      excludeAfter=(cfg['gps'].get('excludeAfter') or {}).get(name),
                      splitGaps=(cfg['gps'].get('splitGaps') or {}).get(name))


def runGpsStage(cfg, verbose=True):
    '''Build window series, coverage tables and the station summary.

    Writes <validation>/gps/<STATION>.windows.parquet, .coverage.parquet and
    stations.csv. Returns (stations DataFrame, {name: windows DataFrame},
    {name: coverage DataFrame}).
    '''
    gpsCfg = cfg['gps']
    outDir = cfg['paths']['gps']
    os.makedirs(outDir, exist_ok=True)
    summaries, allWindows, allCoverage = [], {}, {}
    for name, path in stationFiles(cfg).items():
        station = GpsStation(path, cfg['epsg'],
                             denseEpochsPerDay=gpsCfg['denseEpochsPerDay'],
                             stepMaxAngle=gpsCfg.get('stepMaxAngle', 30.),
                             excludeAfter=(gpsCfg.get('excludeAfter') or {}).get(name),
                             splitGaps=(gpsCfg.get('splitGaps') or {}).get(name))
        lt, speed, reqClass, tol = stationTolerance(station, cfg)
        windows = station.slidingWindows(
            windowDays=gpsCfg['windowDays'], stepDays=gpsCfg['stepDays'],
            **windowKwargs(gpsCfg, maxSigma=tol))
        windows.to_parquet(os.path.join(outDir, f'{name}.windows.parquet'))
        station.coverage.to_parquet(
            os.path.join(outDir, f'{name}.coverage.parquet'))
        summary = summarizeStation(station, windows, cfg, lt, speed, reqClass, tol)
        summaries.append(summary)
        allWindows[name] = windows
        allCoverage[name] = station.coverage
        if verbose:
            nOk = int(windows['ok'].sum())
            print(f"{name}: {summary['speed']:7.1f} m/yr {summary['reqClass']:4s} "
                  f"stable={summary['stable']!s:5s} p2p={summary['speedP2P']:6.2f} "
                  f"tol={summary['tolerance']:5.2f} windows ok {nOk}/{len(windows)} "
                  f"{summary['recordStart']}..{summary['recordEnd']}")
    stations = pd.DataFrame(summaries)
    stations.to_csv(os.path.join(outDir, 'stations.csv'), index=False)
    return stations, allWindows, allCoverage


def loadGpsStage(cfg):
    '''Read back what runGpsStage wrote.'''
    outDir = cfg['paths']['gps']
    stations = pd.read_csv(os.path.join(outDir, 'stations.csv'),
                           parse_dates=['recordStart', 'recordEnd'])
    windows = {n: pd.read_parquet(os.path.join(outDir, f'{n}.windows.parquet'))
               for n in stations['station']}
    coverage = {n: pd.read_parquet(os.path.join(outDir, f'{n}.coverage.parquet'))
                for n in stations['station']}
    return stations, windows, coverage
