"""Read mosaic3d -obsDump files and rebuild the per-pixel solve.

Dump format (mosaicSource/Mosaic3d/obsDump.c):
  OBS   point row col obsType frame julDay nDays ax ay az d sigma w
  PIXEL point row col sx sy
The window of an observation is [julDay, julDay + nDays]; d and sigma are in
m/yr; w is the weight mosaic3d accumulated. The solve is
  v3 = (sum w a a^T)^-1 (sum w a d)
projected surface-parallel with C = [[1,0],[0,1],[sx,sy]]: N2 = C^T N3 C,
b2 = C^T b3 (checkDump.py:33-37). Row order is OpenMP-dependent; never rely
on it.

The `row` field is mosaic3d's INTERNAL bottom-up index (row 0 = southernmost).
The GeoTIFF/VRT products are north-up, so indexing a product with it reads the
wrong pixel, silently, with the error growing away from the grid centre --
measured at up to 397 m/yr on fast ice.  Use tifRow = nRows - 1 - row; col is
the same in both.  Nothing in this package indexes a raster, so `row`/`col` are
carried as metadata only; anything that does index one must apply the flip.
"""
import os
from datetime import timedelta

import numpy as np
import pandas as pd

from validationreports import cycles
from validationreports import pointMode

OBS_COLUMNS = ['station', 'row', 'col', 'obsType', 'frame', 'julDay', 'nDays',
               'ax', 'ay', 'az', 'd', 'sigma', 'w']


def readDump(path):
    '''(rows DataFrame, {station: (sx, sy)}) from one obsDump file.'''
    obs, pix = [], {}
    with open(path) as fp:
        for line in fp:
            if line.startswith('#') or not line.strip():
                continue
            p = line.split()
            if p[0] == 'PIXEL':
                pix[p[1]] = (float(p[4]), float(p[5]))
            elif p[0] == 'OBS':
                obs.append(p[1:14])
    rows = pd.DataFrame(obs, columns=OBS_COLUMNS)
    for c in ['row', 'col']:
        rows[c] = rows[c].astype(int)
    for c in ['julDay', 'nDays', 'ax', 'ay', 'az', 'd', 'sigma', 'w']:
        rows[c] = rows[c].astype(float)
    rows['date0'] = [cycles.julDayToDatetime(j) for j in rows['julDay']]
    rows['date1'] = [d + timedelta(days=n) for d, n in zip(rows['date0'], rows['nDays'])]
    rows['cycle'] = cycles.cycleOfDate(list(rows['date0'])) if len(rows) else []
    tf = [cycles.trackFrameFromPath(f) for f in rows['frame']]
    rows['track'] = [t[0] if t else -1 for t in tf]
    rows['orbit'] = [t[1] if t else -1 for t in tf]
    rows = rows.sort_values(['station', 'date0', 'obsType', 'track']).reset_index(drop=True)
    return rows, pix


def readAllDumps(cfg):
    '''Rows and pixel slopes for every group in a region.'''
    allRows, pixels = [], {}
    for group in cfg['groups']:
        path = pointMode.dumpPath(cfg, group)
        if not os.path.exists(path):
            raise FileNotFoundError(f'missing dump {path}; run the dump stage')
        rows, pix = readDump(path)
        rows['group'] = group['name']
        allRows.append(rows)
        pixels.update(pix)
    rows = pd.concat(allRows, ignore_index=True)
    rows['sx'] = rows['station'].map(lambda s: pixels.get(s, (0., 0.))[0])
    rows['sy'] = rows['station'].map(lambda s: pixels.get(s, (0., 0.))[1])
    return rows, pixels


def solve2D(rows, sx, sy, key='d'):
    '''Surface-parallel 2D solve from rows.

    Returns (v[2], sigma[2]) with the formal sigma from sqrt(diag(inv(N2))),
    or (None, None) when the normal matrix is not positive definite.
    '''
    a = rows[['ax', 'ay', 'az']].to_numpy(dtype=float)
    w = rows['w'].to_numpy(dtype=float)
    d = rows[key].to_numpy(dtype=float)
    aw = a * w[:, None]
    N = aw.T @ a
    b = aw.T @ d
    C = np.array([[1., 0.], [0., 1.], [sx, sy]])
    N2 = C.T @ N @ C
    b2 = C.T @ b
    if np.linalg.eigvalsh(N2).min() <= 0:
        return None, None
    inv = np.linalg.inv(N2)
    return inv @ b2, np.sqrt(np.diag(inv))


def typeCounts(rows):
    '''{'phase': n, 'range': n, 'azimuth': n}.'''
    c = rows['obsType'].value_counts()
    return {t: int(c.get(t, 0)) for t in ['phase', 'range', 'azimuth']}
