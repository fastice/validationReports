"""GPS forward model: the GPS velocity over each observation's own window.

For every unique (station, date0, nDays) in the dump the GPS reference is
  real    regression over exactly that window (coverage and sigma gates pass)
  extrap  the station's long-term mean, when the station is classed stable
  interp  linear interpolation between the nearest usable 12-day windows on
          either side, within one window length, for variable stations
  skip    none of the above; the row is dropped from both solves
The synthetic observable is d_gps = a . C v_gps with C the surface-parallel
projection, so pushing d_gps through the same a_i, w_i cancels temporal
sampling identically (mosaickingDocuments/biasInvestigation/gpsComparison.md).
"""
import numpy as np
import pandas as pd

from validationreports import gpsSeries

QUALITIES = ['real', 'interp', 'extrap', 'skip']


def _interpolate(windows, mid, nDays):
    '''Linear interpolation of ok windows bracketing mid within nDays.'''
    ok = windows[windows['ok']]
    before = ok[(ok['mid'] <= mid) & (ok['mid'] >= mid - pd.Timedelta(days=nDays))]
    after = ok[(ok['mid'] >= mid) & (ok['mid'] <= mid + pd.Timedelta(days=nDays))]
    if len(before) == 0 or len(after) == 0:
        return None
    b = before.iloc[-1]
    a = after.iloc[0]
    span = (a['mid'] - b['mid']).total_seconds()
    f = 0.5 if span == 0 else (mid - b['mid']).total_seconds() / span
    return (b['vx'] + f * (a['vx'] - b['vx']), b['vy'] + f * (a['vy'] - b['vy']))


def windowReferences(station, info, windows, rows, gpsCfg):
    '''GPS reference per unique window for one station.

    station : gpsSeries.GpsStation; info : its row of stations.csv;
    windows : its sliding-window table; rows : its dump rows.
    Returns a DataFrame keyed by (date0, nDays) with vxG, vyG, quality.
    '''
    tol = float(info['tolerance'])
    kw = gpsSeries.windowKwargs(gpsCfg, maxSigma=tol)
    out = []
    keys = rows[['date0', 'nDays']].drop_duplicates()
    for date0, nDays in zip(keys['date0'], keys['nDays']):
        date1 = date0 + pd.Timedelta(days=nDays)
        r = station.windowVelocity(date0, date1, **kw)
        if r['ok']:
            vx, vy, quality = r['vx'], r['vy'], 'real'
        elif bool(info['stable']):
            vx, vy, quality = float(info['vx']), float(info['vy']), 'extrap'
        else:
            mid = date0 + pd.Timedelta(days=nDays / 2.)
            v = _interpolate(windows, mid, nDays)
            if v is None:
                vx, vy, quality = np.nan, np.nan, 'skip'
            else:
                vx, vy, quality = v[0], v[1], 'interp'
        out.append(dict(date0=date0, nDays=nDays, vxG=vx, vyG=vy,
                        quality=quality, gpsRegime=r['regime'],
                        gpsSigVx=r['sigVx'], gpsSigVy=r['sigVy']))
    return pd.DataFrame(out)


def addForwardModel(rows, cfg, stations, windows, verbose=True):
    '''Attach vxG, vyG, quality and dGps to every dump row.'''
    parts = []
    for name, sub in rows.groupby('station', sort=True):
        if name not in set(stations['station']):
            raise ValueError(f'{name} in dump but not in stations.csv')
        info = stations[stations['station'] == name].iloc[0]
        station = gpsSeries.loadStation(cfg, name)
        refs = windowReferences(station, info, windows[name], sub, cfg['gps'])
        merged = sub.merge(refs, on=['date0', 'nDays'], how='left')
        parts.append(merged)
        if verbose:
            q = merged['quality'].value_counts()
            print(f"  {name}: rows {len(merged)} "
                  + ' '.join(f'{k}={int(q.get(k, 0))}' for k in QUALITIES))
    out = pd.concat(parts, ignore_index=True)
    vz = out['sx'] * out['vxG'] + out['sy'] * out['vyG']
    out['dGps'] = out['ax'] * out['vxG'] + out['ay'] * out['vyG'] + out['az'] * vz
    return out
