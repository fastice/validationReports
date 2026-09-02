"""Requirement evaluation: cumulative-cycle and seasonal estimates, status.

Thresholds (1-sigma): slow 3%V + 1 m/yr (L2-SCI-667), fast 3%V + 5 m/yr
(L2-SCI-668), seasonal 3%V + 10 m/yr (L2-SCI-738), each tested against the
speed and the vx, vy components. The normalised residual r = delta / T is the
common currency; a requirement is met when RMS(r) over stations is <= 1 for
all three quantities. The projection fits e(N)^2 = a^2 + b^2 / N to the
cumulative series and evaluates it at projectionCycles.
"""
import json
import os

import numpy as np
import pandas as pd

from validationreports import cycles, gpsSeries, obsDump, forwardModel

QUANTITIES = ['vx', 'vy', 'speed']
USABLE = ['real', 'interp', 'extrap']


def thresholdFor(speedGps, reqClass, requirements):
    return gpsSeries.requirementTolerance(speedGps, reqClass, requirements)


def solveBoth(rows, sx, sy):
    '''NISAR and GPS-forward-model solves on the same rows and weights.'''
    vN, sN = obsDump.solve2D(rows, sx, sy, key='d')
    vG, _ = obsDump.solve2D(rows, sx, sy, key='dGps')
    if vN is None or vG is None:
        return None
    out = dict(vx=vN[0], vy=vN[1], sigVx=sN[0], sigVy=sN[1],
               vxG=vG[0], vyG=vG[1], nRows=int(len(rows)))
    out['speed'] = float(np.hypot(vN[0], vN[1]))
    out['speedG'] = float(np.hypot(vG[0], vG[1]))
    out['sigSpeed'] = float(np.hypot(vN[0] * sN[0], vN[1] * sN[1]) / max(out['speed'], 1e-6))
    out.update({f'n{t.capitalize()}': n for t, n in obsDump.typeCounts(rows).items()})
    q = rows['quality'].value_counts()
    out.update({f'q{k.capitalize()}': int(q.get(k, 0)) for k in forwardModel.QUALITIES})
    return out


def addResiduals(rec, reqClass, absErr, requirements):
    '''delta, threshold and normalised residual for vx, vy, speed.'''
    T = requirements[reqClass]['pct'] * abs(rec['speedG']) + absErr
    rec['tol'] = T
    rec['dvx'] = rec['vx'] - rec['vxG']
    rec['dvy'] = rec['vy'] - rec['vyG']
    rec['dspeed'] = rec['speed'] - rec['speedG']
    for qn in QUANTITIES:
        rec[f'r{qn}'] = rec[f'd{qn}'] / T
    return rec


def cumulativeEstimates(rows, stations, cfg):
    '''Per station, the estimate from all rows up to each cycle in the master.'''
    reqs = cfg['requirements']
    cycleList = cycles.masterCycles(cfg['paths']['masterInput'])
    usable = rows[rows['quality'].isin(USABLE)]
    out = []
    for name, sub in usable.groupby('station'):
        info = stations[stations['station'] == name].iloc[0]
        sx, sy = float(sub['sx'].iloc[0]), float(sub['sy'].iloc[0])
        for k, c in enumerate(cycleList, start=1):
            part = sub[sub['cycle'] <= c]
            if len(part) < 3:
                continue
            rec = solveBoth(part, sx, sy)
            if rec is None:
                continue
            rec.update(station=name, k=k, cycle=int(c), reqClass=info['reqClass'],
                       nCyclesStation=int(part['cycle'].nunique()))
            rec = addResiduals(rec, info['reqClass'], reqs[info['reqClass']]['absErr'], reqs)
            out.append(rec)
    return pd.DataFrame(out)


def seasonalEstimates(rows, stations, cfg):
    '''Per (station, cycle) estimate from the 12-day pairs of that cycle.'''
    reqs = cfg['requirements']
    s = reqs['seasonal']
    usable = rows[rows['quality'].isin(USABLE) & (rows['nDays'] == s['pairDays'])]
    out = []
    for (name, c), part in usable.groupby(['station', 'cycle']):
        info = stations[stations['station'] == name].iloc[0]
        sx, sy = float(part['sx'].iloc[0]), float(part['sy'].iloc[0])
        if len(part) < s['minRows']:
            continue
        rec = solveBoth(part, sx, sy)
        if rec is None:
            continue
        rec.update(station=name, cycle=int(c), reqClass=info['reqClass'],
                   gated=bool(max(rec['sigVx'], rec['sigVy']) < s['maxSigma']),
                   date=cycles.cycleStart(int(c)) + pd.Timedelta(days=6))
        rec = addResiduals(rec, 'seasonal', s['absErr'], reqs)
        # also score against the fast envelope, as tsplot.py did
        Tfast = reqs['fast']['pct'] * abs(rec['speedG']) + reqs['fast']['absErr']
        rec['rspeedFast'] = rec['dspeed'] / Tfast
        out.append(rec)
    return pd.DataFrame(out)


def projectSeries(k, rms, nTarget, minCycles=4):
    '''Fit e^2 = a^2 + b^2/N (non-negative least squares) and evaluate at nTarget.

    Only steps with k >= minCycles enter the fit: the first few cycles are
    dominated by geometry-starved solves whose residuals are tens of
    tolerances and would swamp the fit. Falls back to 1/sqrt(N) scaling of
    the last value when fewer than three points remain.
    '''
    from scipy.optimize import nnls
    k = np.asarray(k, dtype=float)
    rms = np.asarray(rms, dtype=float)
    good = np.isfinite(rms) & (k > 0)
    k, rms = k[good], rms[good]
    if len(k) == 0:
        return dict(projected=np.nan, floor=np.nan, random=np.nan, method='none')
    fit = (k >= minCycles) & (rms > 0)
    #  A step whose solve is still geometry-starved lands anywhere -- k=4 was
    #  measured at 0.36 for phase and 28.21 for range on the same stations.
    #  Either wrecks the fit, and the relative weighting below cannot help:
    #  1/rms^2 SUPPRESSES a large outlier but AMPLIFIES a small one, handing a
    #  lucky-low early step 15x the weight of the converged steady state (that
    #  drove a flat 1.39 series to a projected 0.49).  Cut on distance from the
    #  converged level, which is blind to the direction of the excursion.
    if fit.sum() >= 6:
        level = np.median(rms[fit][len(rms[fit]) // 2:])
        if level > 0:
            fit &= (rms > level / 3.) & (rms < level * 3.)
    if fit.sum() >= 3:
        # relative weighting: otherwise the largest early value dominates e^2
        wgt = 1. / rms[fit] ** 2
        A = np.column_stack([np.ones(fit.sum()), 1. / k[fit]]) * wgt[:, None]
        coef, _ = nnls(A, rms[fit] ** 2 * wgt)
        a2, b2 = coef
        return dict(projected=float(np.sqrt(a2 + b2 / nTarget)),
                    floor=float(np.sqrt(a2)), random=float(np.sqrt(b2)),
                    method='fit')
    return dict(projected=float(rms[-1] * np.sqrt(k[-1] / nTarget)),
                floor=np.nan, random=np.nan, method='sqrtN')


def cyclesToMeet(proj, kLast, rmsLast):
    '''Cycles at which the fitted curve reaches r = 1; inf if the floor is above 1.'''
    a, b = proj.get('floor', np.nan), proj.get('random', np.nan)
    if proj['method'] == 'fit':
        if a >= 1:
            return float('inf')
        return float(np.ceil(b ** 2 / (1 - a ** 2))) if b > 0 else 1.
    if rmsLast <= 1:
        return float(kLast)
    return float(np.ceil(kLast * rmsLast ** 2))


def summarizeCumulative(cum, reqClass, cfg):
    '''Region-level RMS(r) per cumulative step for one requirement class.'''
    sub = cum[cum['reqClass'] == reqClass]
    out = []
    for k, part in sub.groupby('k'):
        rec = dict(k=int(k), cycle=int(part['cycle'].iloc[0]),
                   nStations=int(len(part)),
                   realFrac=float(part['qReal'].sum() / max(part['nRows'].sum(), 1)))
        for qn in QUANTITIES:
            r = part[f'r{qn}'].to_numpy()
            rec[f'rms_{qn}'] = float(np.sqrt(np.mean(r ** 2)))
            rec[f'within_{qn}'] = float(np.mean(np.abs(r) <= 1))
        rec['rmsMax'] = max(rec[f'rms_{qn}'] for qn in QUANTITIES)
        out.append(rec)
    return pd.DataFrame(out)


def requirementStatus(summary, cfg, minStations=2):
    '''Status dict for a slow/fast requirement from its cumulative summary.'''
    nTarget = cfg['projectionCycles']
    if len(summary) == 0 or summary['nStations'].iloc[-1] < minStations:
        return dict(status='insufficient', reason='fewer than two usable stations')
    last = summary.iloc[-1]
    proj = {qn: projectSeries(summary['k'], summary[f'rms_{qn}'], nTarget)
            for qn in QUANTITIES}
    projectedMax = max(p['projected'] for p in proj.values())
    met = bool(last['rmsMax'] <= 1.)
    if met:
        status = 'met'
    elif np.isfinite(projectedMax) and projectedMax <= 1.:
        status = 'projected'
    else:
        status = 'notMet'
    return dict(status=status, nCycles=int(last['k']), lastCycle=int(last['cycle']),
                nStations=int(last['nStations']), realFrac=float(last['realFrac']),
                rms={qn: float(last[f'rms_{qn}']) for qn in QUANTITIES},
                within={qn: float(last[f'within_{qn}']) for qn in QUANTITIES},
                projected={qn: proj[qn]['projected'] for qn in QUANTITIES},
                projectionMethod={qn: proj[qn]['method'] for qn in QUANTITIES},
                floor={qn: proj[qn]['floor'] for qn in QUANTITIES},
                cyclesToMeet={qn: cyclesToMeet(proj[qn], last['k'], last[f'rms_{qn}'])
                              for qn in QUANTITIES},
                projectionCycles=nTarget,
                gpsMode='extrapolated' if last['realFrac'] == 0 else 'measured')


def seasonalStatus(seas, cfg):
    '''Status for L2-SCI-738 from the gated seasonal intervals of fast stations.'''
    s = cfg['requirements']['seasonal']
    fast = seas[seas['reqClass'] == 'fast']
    if len(fast) == 0:
        return dict(status='insufficient', reason='no 12-day intervals at fast stations')
    gated = fast[fast['gated']]
    realRows = int(gated['qReal'].sum()) if len(gated) else 0
    if len(gated) == 0 or realRows == 0:
        return dict(status='insufficient', nIntervals=int(len(fast)), nGated=int(len(gated)),
                    reason='no gated intervals with measured GPS')
    within = {qn: float(np.mean(np.abs(gated[f'r{qn}']) <= 1)) for qn in QUANTITIES}
    rms = {qn: float(np.sqrt(np.mean(gated[f'r{qn}'] ** 2))) for qn in QUANTITIES}
    coverage = float(len(gated) / len(fast))
    met = all(v >= 0.68 for v in within.values()) and coverage >= s['minCoverage']
    return dict(status='met' if met else 'notMet', nIntervals=int(len(fast)),
                nGated=int(len(gated)), coverage=coverage, within=within, rms=rms,
                rmsSpeedMPerYr=float(np.sqrt(np.mean(gated['dspeed'] ** 2))),
                withinFastEnvelope=float(np.mean(np.abs(gated['rspeedFast']) <= 1)),
                nStations=int(gated['station'].nunique()),
                gpsMode='measured' if realRows > 0 else 'extrapolated')


def runEvalStage(cfg, verbose=True):
    '''Forward model, cumulative and seasonal tables, status.json.'''
    outDir = cfg['paths']['results']
    os.makedirs(outDir, exist_ok=True)
    stations, windows, _ = gpsSeries.loadGpsStage(cfg)
    rows, _ = obsDump.readAllDumps(cfg)
    if verbose:
        print(f'  {len(rows)} observation rows from {rows["station"].nunique()} stations')
    rows = forwardModel.addForwardModel(rows, cfg, stations, windows, verbose=verbose)
    rows.to_parquet(os.path.join(outDir, 'rows.parquet'))
    cum = cumulativeEstimates(rows, stations, cfg)
    cum.to_parquet(os.path.join(outDir, 'cumulative.parquet'))
    seas = seasonalEstimates(rows, stations, cfg)
    seas.to_parquet(os.path.join(outDir, 'seasonal.parquet'))
    status = {}
    for reqClass in ['slow', 'fast']:
        summary = summarizeCumulative(cum, reqClass, cfg)
        summary.to_parquet(os.path.join(outDir, f'summary_{reqClass}.parquet'))
        status[reqClass] = requirementStatus(summary, cfg)
        status[reqClass]['id'] = cfg['requirements'][reqClass]['id']
    status['seasonal'] = seasonalStatus(seas, cfg)
    status['seasonal']['id'] = cfg['requirements']['seasonal']['id']
    status['region'] = cfg['region']
    status['masterCycles'] = cycles.masterCycles(cfg['paths']['masterInput'])
    status['generated'] = pd.Timestamp.now().isoformat(timespec='seconds')
    with open(os.path.join(outDir, 'status.json'), 'w') as fp:
        json.dump(status, fp, indent=2, default=str)
    if verbose:
        for key in ['slow', 'fast', 'seasonal']:
            st = status[key]
            extra = ''
            if 'rms' in st:
                extra = ' rms(r) ' + ' '.join(f"{q}={v:.2f}" for q, v in st['rms'].items())
            if 'projected' in st:
                extra += ' proj ' + ' '.join(f"{q}={v:.2f}" for q, v in st['projected'].items())
            print(f"  {st['id']} {key:8s}: {st['status']}{extra}")
    return status
