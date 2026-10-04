"""Static reference point sets (Summit stations, 2000 m tie points, NEGIS poles).

These are single velocity measurements with no time series, so their forward
model is a constant velocity (quality `static`). Each set is clustered into
small boxes for the mosaic3d point-mode runs; an existing dump directory whose
point set matches a cluster is reused, so the other session's TIE01..TIE33 and
SUMMIT runs are not repeated.

Point names: the Summit set carries a `station` column; tie points are named
T<row> by 0-based row in their CSV (the convention of the existing dumps).
"""
import glob
import json
import os

import numpy as np
import pandas as pd
import pyproj

from validationreports import gpsSeries
from validationreports.config import REPO_DIR

GROUPS_FILE = 'groups.json'


def _resolve(path):
    return path if os.path.isabs(path) else os.path.join(REPO_DIR, path)


def loadSet(cfg, refSet):
    '''DataFrame of one static set in the stations.csv layout.'''
    df = pd.read_csv(_resolve(refSet['file']))
    if 'station' in df:
        names = df['station'].astype(str)
    else:
        names = [f"{refSet.get('namePrefix', 'T')}{i:03d}" for i in range(len(df))]
    if 'x' not in df or 'y' not in df:
        tr = pyproj.Transformer.from_crs('EPSG:4326', f"EPSG:{cfg['epsg']}",
                                         always_xy=True)
        x, y = tr.transform(df['lon'].to_numpy(), df['lat'].to_numpy())
        df['x'], df['y'] = x, y
    speed = np.hypot(df['vx'], df['vy'])
    reqs = cfg['requirements']
    reqClass = [gpsSeries.requirementClass(s, reqs) for s in speed]
    tol = [gpsSeries.requirementTolerance(s, c, reqs) for s, c in zip(speed, reqClass)]
    return pd.DataFrame(dict(
        station=list(names), group=refSet['name'], kind='static',
        lat=df['lat'], lon=df['lon'], x=df['x'], y=df['y'],
        vx=df['vx'], vy=df['vy'], speed=speed, reqClass=reqClass, tolerance=tol,
        stable=True))


def loadAllSets(cfg):
    '''All static sets for a region (empty frame if none configured).'''
    sets = cfg.get('referenceSets', [])
    if not sets:
        return pd.DataFrame(columns=['station', 'group', 'kind', 'lat', 'lon', 'x', 'y',
                                     'vx', 'vy', 'speed', 'reqClass', 'tolerance', 'stable'])
    return pd.concat([loadSet(cfg, s) for s in sets], ignore_index=True)


def allReference(cfg):
    '''GPS stations (group gps) plus static sets, one table.'''
    stations, _, _ = gpsSeries.loadGpsStage(cfg)
    stations = stations.copy()
    stations['group'] = 'gps'
    stations['kind'] = 'gps'
    static = loadAllSets(cfg)
    if len(static) == 0:
        return stations
    return pd.concat([stations, static], ignore_index=True, sort=False)


# ----------------------------------------------------------------------
def clusterPoints(points, maxKm=45.):
    '''Greedy clusters in table order: a point joins the first cluster whose
    members are all within maxKm, else starts a new one. Returns a list of
    index lists.'''
    x = points['x'].to_numpy() / 1000.
    y = points['y'].to_numpy() / 1000.
    clusters = []
    for i in range(len(points)):
        for c in clusters:
            if all(np.hypot(x[i] - x[j], y[i] - y[j]) <= maxKm for j in c):
                c.append(i)
                break
        else:
            clusters.append([i])
    return clusters


def staticGroups(cfg, static):
    '''Point-mode groups for the static sets: [{name, set, stations, marginKm}].'''
    groups = []
    for refSet in cfg.get('referenceSets', []):
        pts = static[static['group'] == refSet['name']].reset_index(drop=True)
        maxKm = refSet.get('maxClusterKm', 45.)
        for n, idx in enumerate(clusterPoints(pts, maxKm), start=1):
            groups.append(dict(name=f"{refSet.get('groupPrefix', refSet['name'].upper())}{n:02d}",
                               set=refSet['name'],
                               stations=list(pts['station'].iloc[idx]),
                               marginKm=refSet.get('marginKm', 5), kind='static'))
    return groups


def _pointKey(lat, lon):
    return f'{lat:.4f},{lon:.4f}'


def _dumpPointKeys(dirPath):
    keys = set()
    path = os.path.join(dirPath, 'gpsPoints.txt')
    if not os.path.exists(path):
        return keys
    with open(path) as fp:
        for line in fp:
            if line.startswith('#') or len(line.split()) < 2:
                continue
            p = line.split()
            keys.add(_pointKey(float(p[0]), float(p[1])))
    return keys


def findExistingDir(cfg, group, static):
    '''An existing point-mode dir whose point set equals this group's, or None.'''
    pts = static[static['station'].isin(group['stations'])]
    want = {_pointKey(la, lo) for la, lo in zip(pts['lat'], pts['lon'])}
    master = os.path.getmtime(cfg['paths']['masterInput'])
    for d in sorted(glob.glob(os.path.join(cfg['paths']['pointMode'], '*'))):
        dump = os.path.join(d, 'mosaicOffsets.obsDump')
        if not os.path.exists(dump) or os.path.getmtime(dump) < master:
            continue
        if _dumpPointKeys(d) == want:
            return d
    return None


def groupsPath(cfg):
    return os.path.join(cfg['paths']['pointMode'], GROUPS_FILE)


def saveGroups(cfg, mapping):
    '''{groupName: {dir, set, stations, kind}} -> groups.json.'''
    with open(groupsPath(cfg), 'w') as fp:
        json.dump(mapping, fp, indent=2)


def loadGroups(cfg):
    path = groupsPath(cfg)
    if not os.path.exists(path):
        return {}
    with open(path) as fp:
        return json.load(fp)
