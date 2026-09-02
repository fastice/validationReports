"""Rebuild every file in this directory from its sources.  Run from here.

    python buildReferencePoints.py

Nothing downstream depends on this script -- it exists so the culling is
reproducible and auditable, not so it runs routinely.  Sources:

  summitPoints.raw.txt   as supplied: station, lat, lon, then (year, speed, azimuth)
                         for 2022, 2023, 2024
  TIEFILE                /Users/ian/tiepoints/newSentinelTies/iceEquivalent/
                         tiepoints.2000.vz  (epoch ~2000)
  REFVRT                 the project velMap, sampled for context only
  ANNUAL                 the S1 annual mosaic stack used to detect real change
"""
import glob, os, re
import numpy as np, pandas as pd, rasterio, pyproj

TIEFILE = '/Users/ian/tiepoints/newSentinelTies/iceEquivalent/tiepoints.2000.vz'
REFVRT  = '/Volumes/insar1/ian/NISAR/realNISAR/newGreenlandProject/velocityMap.vrt'
ANNUAL  = '/Volumes/insar9/ian/Sentinel1/Release/annualMosaics/Vel-*/'
NISAR   = ('/Volumes/insar1/ian/NISAR/realNISAR/newGreenlandProject/Release/velocity/'
           'hopper2d-nosquint/Vel-2025-06-01.2026-11-30/release/'
           'GL-hop2d-nosq_vel_mosaic_multiYear_01Jun25_30Nov26')

MAXLAT   = 77.0   # north of this: no data, or geometry too poor to trust (user call)
TIE_EPOCH= 2000.0 # tie points are ~25 yr old
NIS_EPOCH= 2026.0 # NISAR mosaic centre
GAP      = NIS_EPOCH - TIE_EPOCH
TOLFRAC  = 0.5    # keep points whose projected change is under this x tolerance

TF = pyproj.Transformer.from_crs('EPSG:4326', 'EPSG:3413', always_xy=True)


def sampleRaster(path, x, y):
    '''Nearest-cell sample with nodata -> NaN.'''
    s = rasterio.open(path)
    v = np.array([p[0] for p in s.sample(list(zip(x, y)))], dtype=float)
    if s.nodata is not None:
        v[v <= s.nodata * 0.98] = np.nan
    v[~np.isfinite(v)] = np.nan
    return v


def tolerance(speed):
    '''L2-SCI-667 below 50 m/yr, L2-SCI-668 above.'''
    return np.where(speed < 50., 0.03 * speed + 1., 0.03 * speed + 5.)


def buildSummit():
    '''speed + azimuth per year -> vx, vy averaged over years.

    Azimuth is degrees clockwise from TRUE north (negative = west of north), so
    vE = v sin(az), vN = v cos(az).  EPSG:3413 has central meridian -45, and its
    x = rho sin(lon - lon0), so grid north at longitude lon is rotated by
    (lon + 45) and gridAzimuth = az - (lon + 45).  That rotation is 6-7 deg for
    these stations, which is far too large to skip.

    Checked against the surface gradient from the mosaic3d obsDump PIXEL records:
    flow sits 2.5-30 deg from downslope (mean +10), i.e. the ice flows downhill,
    which it would not under a wrong azimuth convention.
    '''
    rows = []
    for line in open('summitPoints.raw.txt'):
        p = line.split()
        if len(p) < 12:
            continue
        st, lat, lon = p[0], float(p[1]), float(p[2])
        for k in range(3):
            rows.append(dict(station='S' + str(int(float(st))), lat=lat, lon=lon,
                             year=int(p[3 + 3 * k]), v=float(p[4 + 3 * k]),
                             az=float(p[5 + 3 * k])))
    d = pd.DataFrame(rows)
    d['vE'] = d.v * np.sin(np.radians(d.az))
    d['vN'] = d.v * np.cos(np.radians(d.az))
    gaz = np.radians(d.az - (d.lon + 45.0))
    d['vx'] = d.v * np.sin(gaz)
    d['vy'] = d.v * np.cos(gaz)
    g = d.groupby('station').agg(lat=('lat', 'first'), lon=('lon', 'first'),
                                 speed=('v', 'mean'), speedSd=('v', 'std'),
                                 azimuth=('az', 'mean'), azimuthSd=('az', 'std'),
                                 vE=('vE', 'mean'), vN=('vN', 'mean'),
                                 vx=('vx', 'mean'), vy=('vy', 'mean'),
                                 n=('v', 'size')).reset_index()
    g.sort_values('speed', ascending=False).to_csv('summitPoints.csv', index=False)
    return g


def readTiePoints():
    '''lat lon(0-360) elev vx vy vz -- vz is an old SMB correction, DROPPED.

    The file ends with a "&" terminator, and comments start with ";".
    '''
    r = []
    for line in open(TIEFILE):
        if line.lstrip().startswith(';'):
            continue
        p = line.split()
        if len(p) < 5:            # the "&" end-of-data marker
            continue
        r.append([float(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])])
    d = pd.DataFrame(r, columns=['lat', 'lon', 'elev', 'vx', 'vy'])
    d['lon'] = ((d.lon + 180) % 360) - 180
    d['x'], d['y'] = TF.transform(d.lon.values, d.lat.values)
    d['speed'] = np.hypot(d.vx, d.vy)
    return d


def addStack(d):
    '''Per-point mean, scatter and TREND from the S1 annual stack.

    The trend is what matters: these points are ~26 years older than the product
    under test, so a steady trend is a SYSTEMATIC error that accumulates over the
    gap, while year-to-year scatter is noise that averages down over many points.
    The two are close to independent -- of the 91 points with scatter <= 5% of
    mean, 24 still project to >10% change -- so a scatter cut does NOT control
    the systematic and must not be used as a proxy for one.

    Limitation: the trend is extrapolated LINEARLY from 2014-2023 back to the tie
    epoch.  It catches points that were trending during the S1 era; it cannot
    catch one that changed before 2014 and has been steady since.
    '''
    pts = list(zip(d.x, d.y))
    t, S, E = [], [], []
    for D in sorted(glob.glob(ANNUAL)):
        b = glob.glob(os.path.join(D, 'release', '*_vx_v*.tif'))
        if not b:
            continue
        base = b[0][:b[0].rfind('vx_')]
        ver = re.search(r'_vx_(v[\d.]+)\.tif', b[0]).group(1)
        g = {k: sampleRaster(f'{base}{k}_{ver}.tif', d.x, d.y)
             for k in ['vx', 'vy', 'ex', 'ey']}
        t.append(int(re.search(r'Vel-(\d{4})', D).group(1)) + 0.5)
        S.append(np.hypot(g['vx'], g['vy']))
        E.append(np.hypot(g['ex'], g['ey']))
    t, S, E = np.array(t), np.array(S), np.array(E)
    d['s1StackMean'] = np.nanmean(S, axis=0)
    d['s1StackSd'] = np.nanstd(S, axis=0, ddof=1)
    d['s1FormalErr'] = np.nanmedian(E, axis=0)
    slope = np.full(len(d), np.nan)
    se = np.full(len(d), np.nan)
    for i in range(S.shape[1]):
        m = np.isfinite(S[:, i])
        if m.sum() < 5:
            continue
        c = np.polyfit(t[m], S[m, i], 1)
        r = S[m, i] - np.polyval(c, t[m])
        slope[i] = c[0]
        se[i] = np.sqrt(np.sum(r ** 2) / (m.sum() - 2) / np.sum((t[m] - t[m].mean()) ** 2))
    d['trend'], d['trendSE'] = slope, se
    d['projChange26yr'] = np.abs(slope) * GAP
    return d


def main():
    print('Summit:', len(buildSummit()), 'stations')
    d = readTiePoints()
    d['refVx'] = sampleRaster(REFVRT, d.x, d.y)                     # band 1 = vx
    s = rasterio.open(REFVRT)
    rv = np.array(list(s.sample(list(zip(d.x, d.y)))), dtype=float)
    rv[rv <= s.nodata * 0.98] = np.nan
    d['refVx'], d['refVy'] = rv[:, 0], rv[:, 1]
    d['refSpeed'] = np.hypot(d.refVx, d.refVy)
    d['refOverTie'] = d.refSpeed / d.speed
    d['refDirDiff'] = (np.degrees(np.arctan2(d.refVy, d.refVx)
                                  - np.arctan2(d.vy, d.vx)) + 180) % 360 - 180
    d.to_csv('tiePoints2000_all.csv', index=False)
    print('2000 m, all:', len(d))

    #  CULL, in order.  Each step is independent and reported separately.
    v = d[d.lat < MAXLAT].copy()
    print(f'  lat < {MAXLAT}: keep {len(v)} of {len(d)}')
    v = addStack(v)
    v['nisarVx'] = sampleRaster(f'{NISAR}_vx_v01.0.tif', v.x, v.y)
    v['nisarVy'] = sampleRaster(f'{NISAR}_vy_v01.0.tif', v.x, v.y)
    v['cls'] = np.where(v.speed < 50., 'slow', 'fast')
    v['tol'] = tolerance(v.speed.values)
    keep = v.projChange26yr < TOLFRAC * v.tol
    print(f'  projected {GAP:.0f}-yr change < {TOLFRAC} x tolerance: keep {int(keep.sum())}')
    v[keep].to_csv('tiePoints2000_validation.csv', index=False)
    k = v[keep]
    sc = np.sum(k.nisarVx * k.vx + k.nisarVy * k.vy) / np.sum(k.vx ** 2 + k.vy ** 2)
    print(f'  NISAR scale on the kept set: {sc:.3f}  '
          f'(slow {int((k.cls == "slow").sum())}, fast {int((k.cls == "fast").sum())})')


if __name__ == '__main__':
    main()
