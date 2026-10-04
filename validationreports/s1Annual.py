"""Sentinel-1 annual mosaics (NSIDC-0725 v05.0) against the validation points.

Samples the nine annual Greenland mosaics (Dec 2014 - Nov 2023) at the GPS
stations, the Summit points, the 2000 m points and the NEGIS points, scores each year and each
cumulative average (years 1..k) against the same tolerances as the NISAR
dashboard, and writes the figures plus a markdown note for mosaickingDocuments.

The GPS stations have no temporal overlap with the S1 annuals (records start
2024), so their reference is the long-term mean; the static sets are single
velocities anyway. Every reference is therefore constant in time here.

    python -m validationreports.s1Annual [--resample] [--docDir DIR]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from validationreports import config as vcfg
from validationreports import referencePoints, requirements, plots
from validationreports.plots import SERIES, INK, MUTED, GRID, STATUS, DPI, GROUP_STYLE

URL_BASE = ('https://data.nsidc.earthdatacloud.nasa.gov/nsidc-cumulus-prod-protected/'
            'MEASURES/NSIDC-0725/5')
YEARS = list(range(2014, 2023))          # Dec YEAR -> Nov YEAR+1
BANDS = ['vx', 'vy', 'ex', 'ey']
NODATA_MIN = -1e9
DOC_DIR = '/home/ian/PycharmProjects/packages/mosaickingDocuments/biasInvestigation'
COOKIE = os.path.expanduser('~/.grimp_download_cookiejar.txt')


def yearLabel(y):
    return f'{y + 1}'          # season Dec y -> Nov y+1 labelled by its end year


def mosaicUrl(year, band):
    yy, yy1 = year % 100, (year + 1) % 100
    return (f'{URL_BASE}/{year}/12/01/GL_vel_mosaic_Annual_01Dec{yy:02d}_30Nov{yy1:02d}_'
            f'{band}_v05.0.tif')


def setupGdal():
    os.environ['GDAL_HTTP_COOKIEFILE'] = COOKIE
    os.environ['GDAL_HTTP_COOKIEJAR'] = COOKIE
    os.environ['GDAL_DISABLE_READDIR_ON_OPEN'] = 'EMPTY_DIR'
    os.environ['CPL_VSIL_CURL_ALLOWED_EXTENSIONS'] = '.tif'


def _bilinear(band, gt, x, y):
    '''Bilinear sample of a GDAL band at map coordinates (NaN over nodata).'''
    fc = (x - gt[0]) / gt[1] - 0.5
    fr = (y - gt[3]) / gt[5] - 0.5
    c0, r0 = int(np.floor(fc)), int(np.floor(fr))
    a = band.ReadAsArray(c0, r0, 2, 2).astype(float)
    a[a < NODATA_MIN] = np.nan
    wc, wr = fc - c0, fr - r0
    w = np.array([[(1 - wr) * (1 - wc), (1 - wr) * wc], [wr * (1 - wc), wr * wc]])
    good = np.isfinite(a)
    if good.sum() == 0:
        return np.nan
    return float(np.nansum(a * w) / w[good].sum())


def samplePoints(points, verbose=True):
    '''Sample vx, vy, ex, ey of every annual mosaic at the points (long DataFrame).'''
    from osgeo import gdal
    gdal.UseExceptions()
    setupGdal()
    rows = []
    for year in YEARS:
        vals = {}
        for band in BANDS:
            ds = gdal.Open('/vsicurl/' + mosaicUrl(year, band))
            gt = ds.GetGeoTransform()
            b = ds.GetRasterBand(1)
            vals[band] = [_bilinear(b, gt, x, y) for x, y in zip(points['x'], points['y'])]
            ds = None
        for i, (_, p) in enumerate(points.iterrows()):
            rows.append(dict(station=p['station'], group=p['group'], year=year,
                             season=yearLabel(year), vx=vals['vx'][i], vy=vals['vy'][i],
                             ex=vals['ex'][i], ey=vals['ey'][i]))
        if verbose:
            print(f'  sampled {yearLabel(year)}')
    return pd.DataFrame(rows)


def loadPoints(cfg):
    '''GPS stations (long-term mean) plus the static sets.'''
    pts = referencePoints.allReference(cfg)
    return pts[['station', 'group', 'kind', 'x', 'y', 'vx', 'vy', 'speed', 'reqClass',
                'tolerance']].rename(columns={'vx': 'vxG', 'vy': 'vyG', 'speed': 'speedG'})


# ----------------------------------------------------------------------
def _residuals(df, pts, cfg):
    '''Attach reference, tolerance and residuals to sampled rows.'''
    d = df.merge(pts, on=['station', 'group'], how='left')
    reqs = cfg['requirements']
    d['speed'] = np.hypot(d['vx'], d['vy'])
    d['sigSpeed'] = np.hypot(d['vx'] * d['ex'], d['vy'] * d['ey']) / d['speed'].clip(lower=1e-6)
    d['tol'] = [reqs[c]['pct'] * s + reqs[c]['absErr'] for c, s in zip(d['reqClass'], d['speedG'])]
    d['dvx'] = d['vx'] - d['vxG']
    d['dvy'] = d['vy'] - d['vyG']
    d['dspeed'] = d['speed'] - d['speedG']
    for qn in requirements.QUANTITIES:
        d[f'r{qn}'] = d[f'd{qn}'] / d['tol']
    return d


def byYear(samples, pts, cfg):
    return _residuals(samples, pts, cfg)


def cumulativeYears(samples, pts, cfg):
    '''Mean of years 1..k per point (unweighted over valid years), k = 1..9.'''
    out = []
    for k in range(1, len(YEARS) + 1):
        sub = samples[samples['year'].isin(YEARS[:k])]
        g = sub.groupby(['station', 'group'])
        m = g[['vx', 'vy']].mean()
        n = g['vx'].count().rename('nYears')
        # formal error of the mean from the per-year errors
        e = g[['ex', 'ey']].apply(lambda f: np.sqrt((f ** 2).sum()) / max(f.count().min(), 1))
        m = m.join(n).join(e.rename(columns={'ex': 'ex', 'ey': 'ey'})).reset_index()
        m['k'] = k
        m['season'] = f'{yearLabel(YEARS[0])}–{yearLabel(YEARS[k - 1])}' if k > 1 else yearLabel(YEARS[0])
        out.append(m)
    d = pd.concat(out, ignore_index=True)
    return _residuals(d, pts, cfg)


def summarize(d, reqClass, key):
    '''RMS(r) per group and over all points, per value of `key` (year or k).'''
    sub = d[(d['reqClass'] == reqClass) & np.isfinite(d['rspeed'])]
    recs = []
    groups = [requirements.ALL_GROUP] + sorted(sub['group'].unique())
    for g in groups:
        part = sub if g == requirements.ALL_GROUP else sub[sub['group'] == g]
        for kv, p in part.groupby(key):
            rec = dict(group=g, n=int(len(p)), meanTol=float(p['tol'].mean()))
            rec[key] = kv
            for qn in requirements.QUANTITIES:
                r = p[f'r{qn}'].to_numpy()
                rec[f'rms_{qn}'] = float(np.sqrt(np.mean(r ** 2)))
                rec[f'rmsMPerYr_{qn}'] = float(np.sqrt(np.mean(p[f'd{qn}'] ** 2)))
            recs.append(rec)
    return pd.DataFrame(recs)


# ----------------------------------------------------------------------
def figure(d, summary, reqClass, key, xlabels, outPath, title, cfg):
    '''3x3 panel: GPS station residuals, r per group, RMS(r) per group.

    Row 3 has the fraction of tolerance on the left axis and the equivalent
    error in m/yr (fraction x mean tolerance of all points) on the right.
    '''
    sub = d[d['reqClass'] == reqClass]
    gpsSub = sub[sub['group'] == 'gps']
    names = sorted(gpsSub['station'].unique())
    colors = plots._stationColors(names)
    staticGroups = [g for g in sub['group'].unique() if g != 'gps']
    xs = sorted(sub[key].unique())
    fig, axes = plt.subplots(3, 3, figsize=(12.5, 9.2), sharex='col')
    allTol = float(sub['tol'].mean()) if len(sub) else 1.
    for j, qn in enumerate(['speed', 'vx', 'vy']):
        axD, axR, axS = axes[0, j], axes[1, j], axes[2, j]
        sigCol = 'sigSpeed' if qn == 'speed' else f'e{qn[1]}'
        for name in names:
            s = gpsSub[gpsSub['station'] == name].set_index(key).reindex(xs)
            axD.errorbar(xs, s[f'd{qn}'], yerr=s[sigCol], fmt='o-', ms=3.5, lw=1.2,
                         capsize=2, color=colors[name], label=name)
            axR.plot(xs, s[f'r{qn}'], 'o-', ms=3.5, lw=1.2, color=colors[name], label=name)
        for g in staticGroups:
            lab, color = GROUP_STYLE.get(g, (g, SERIES['green']))
            q = sub[sub['group'] == g].groupby(key)[f'r{qn}'].quantile([0.16, 0.5, 0.84])
            q = q.unstack().reindex(xs)
            axR.fill_between(xs, q[0.16], q[0.84], color=color, alpha=0.15, lw=0)
            axR.plot(xs, q[0.5], '-', lw=1.6, color=color, label=f'{lab} median, 16–84%')
        axD.axhline(0, color=INK, lw=0.8)
        axR.axhspan(-1, 1, color=SERIES['blue'], alpha=0.08, lw=0)
        axR.axhline(0, color=INK, lw=0.8)
        axD.set_title(f'{qn}: S1 − reference (m/yr), GPS stations', loc='left', fontsize=9.5)
        axR.set_title(f'{qn}: residual / tolerance', loc='left', fontsize=9.5)
        for g in [requirements.ALL_GROUP, 'gps'] + staticGroups:
            sm = summary[summary['group'] == g].set_index(key).reindex(xs)
            if sm[f'rms_{qn}'].notna().sum() == 0:
                continue
            lab, color = GROUP_STYLE.get(g, ('all points', INK))
            axS.plot(xs, sm[f'rms_{qn}'], 'o-', ms=3.5,
                     lw=1.8 if g == requirements.ALL_GROUP else 1.2, color=color,
                     label=f'RMS(r) {lab}')
        axS.axhline(1, color=STATUS['critical'], lw=1, ls=':', label='requirement (r = 1)')
        rLim = 4.
        axD.set_ylim(-rLim * allTol, rLim * allTol)
        axR.set_ylim(-rLim, rLim)
        axS.set_ylim(0, rLim)
        axS.set_title(f'{qn}: RMS residual / tolerance', loc='left', fontsize=9.5)
        right = axS.secondary_yaxis('right', functions=(lambda r, t=allTol: r * t,
                                                        lambda e, t=allTol: e / t))
        right.set_ylabel(f'RMS error (m/yr) at mean tolerance {allTol:.1f}', fontsize=8,
                         color=MUTED)
        right.tick_params(labelsize=8, colors=MUTED)
        axS.set_xticks(xs)
        axS.set_xticklabels([xlabels[x] for x in xs], fontsize=8, rotation=0)
        axS.legend(fontsize=7.5, loc='upper right')
    axes[0, 0].legend(fontsize=7.5, ncol=2)
    if staticGroups:
        axes[1, 2].legend(fontsize=7, loc='upper right')
    fig.suptitle(title, x=0.01, ha='left', fontsize=11, fontweight='semibold')
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    fig.savefig(outPath, dpi=DPI)
    plt.close(fig)
    return outPath


# ----------------------------------------------------------------------
def writeDoc(docPath, figDir, tables, notes):
    lines = ['---', 'title: "Sentinel-1 annual mosaics against the validation points"',
             'subtitle: "NSIDC-0725 v05.0, nine seasons Dec 2014 – Nov 2023, scored like the NISAR dashboard"',
             f'date: {pd.Timestamp.now():%Y-%m-%d}', '---', '',
             '## Purpose', '',
             'How the individual Sentinel-1 annual mosaics, and their running average, compare with the '
             'same reference points the NISAR dashboard uses (GPS stations, Summit points, 2000 m points, NEGIS points), '
             'with the same tolerances (0.03·V + 1 m/yr slow, + 5 m/yr fast) and the same residual / '
             'tolerance statistic. Year by year first, then years 1..k averaged to show the gain from '
             'more data, as in the NISAR cumulative-cycle figures. Local note, not a deliverable.', '',
             '> **Summary**', '>']
    lines += [f'> {n}' for n in notes]
    lines += ['', '## Data', '',
              'Mosaics: `GL_vel_mosaic_Annual_01DecYY_30NovYY+1_{vx,vy,ex,ey}_v05.0.tif` from NSIDC-0725 '
              'sampled bilinearly (velocity) at each point. References: the GPS stations\' long-term mean '
              '(their records start 2024, after the last S1 season, so no epoch match is possible), the '
              'Summit points (2022–2024 mean), the 2000 m points (1993–1997, screened for trend) and the '
              'NEGIS points (2015–2019, inside the S1 span). '
              'Every reference is therefore a single constant velocity. The cumulative average is the '
              'unweighted mean of the available seasons at each point.', '']
    n = 1
    for cap, fn in tables['figures']:
        lines += [f'![{cap}](figures/{fn})', '', f'**Figure {n}.** {cap}', '']
        n += 1
    for head, df in tables['tables']:
        lines += [f'### {head}', '', df.to_markdown(index=False, floatfmt='.2f'), '']
    with open(docPath, 'w') as fp:
        fp.write('\n'.join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description='S1 annual mosaics vs validation points')
    parser.add_argument('--resample', action='store_true', help='re-read the mosaics')
    parser.add_argument('--docDir', default=DOC_DIR)
    args = parser.parse_args(argv)
    cfg = vcfg.loadConfig('greenland')
    cacheDir = os.path.join(cfg['paths']['validationDir'], 's1Annual')
    os.makedirs(cacheDir, exist_ok=True)
    cache = os.path.join(cacheDir, 'samples.parquet')
    pts = loadPoints(cfg)
    if args.resample or not os.path.exists(cache):
        print(f'sampling {len(pts)} points in {len(YEARS)} annual mosaics')
        samples = samplePoints(pts)
        samples.to_parquet(cache)
    else:
        samples = pd.read_parquet(cache)
    dYear = byYear(samples, pts, cfg)
    dCum = cumulativeYears(samples, pts, cfg)
    figDir = os.path.join(args.docDir, 'figures')
    os.makedirs(figDir, exist_ok=True)
    yearLabels = {y: yearLabel(y) for y in YEARS}
    kLabels = {k: f'{k}' for k in range(1, len(YEARS) + 1)}
    figures, tables, notes = [], [], []
    for reqClass in ['slow', 'fast']:
        rid = cfg['requirements'][reqClass]['id']
        sYear = summarize(dYear, reqClass, 'year')
        sCum = summarize(dCum, reqClass, 'k')
        fn = f's1Annual_byYear_{reqClass}.png'
        figure(dYear, sYear, reqClass, 'year', yearLabels, os.path.join(figDir, fn),
               f'S1 annual mosaics, {rid} ({reqClass}): season by season', cfg)
        figures.append((f'{rid} ({reqClass} flow), each S1 season on its own. Row 1: S1 − reference '
                        f'at the GPS stations with the mosaic formal error; row 2: residual over '
                        f'tolerance per station and per static group (median, 16–84%); row 3: RMS '
                        f'over points per group, left axis in tolerances, right axis in m/yr.', fn))
        fn = f's1Annual_cumulative_{reqClass}.png'
        figure(dCum, sCum, reqClass, 'k', kLabels, os.path.join(figDir, fn),
               f'S1 annual mosaics, {rid} ({reqClass}): average of seasons 1..k', cfg)
        figures.append((f'{rid} ({reqClass} flow), average of the first k seasons (2015 first). '
                        f'Same rows as the previous figure; compare with the NISAR cumulative-cycle '
                        f'figure in the dashboard.', fn))
        allYear = sYear[sYear['group'] == requirements.ALL_GROUP]
        allCum = sCum[sCum['group'] == requirements.ALL_GROUP]
        tables.append((f'{rid} ({reqClass}): season by season, all points',
                       allYear.assign(season=[yearLabel(y) for y in allYear['year']])[
                           ['season', 'n', 'rms_speed', 'rms_vx', 'rms_vy', 'rmsMPerYr_speed', 'meanTol']]))
        tables.append((f'{rid} ({reqClass}): average of seasons 1..k, all points',
                       allCum[['k', 'n', 'rms_speed', 'rms_vx', 'rms_vy', 'rmsMPerYr_speed', 'meanTol']]))
        byGroup = sCum[sCum['k'] == len(YEARS)]
        notes.append(f"**{rid} ({reqClass})**, nine-season average: RMS(r) speed "
                     f"{allCum['rms_speed'].iloc[-1]:.2f}, vx {allCum['rms_vx'].iloc[-1]:.2f}, "
                     f"vy {allCum['rms_vy'].iloc[-1]:.2f} over {int(allCum['n'].iloc[-1])} points "
                     f"({allCum['rmsMPerYr_speed'].iloc[-1]:.1f} m/yr RMS speed error); by group: "
                     + ', '.join(f"{g['group']} {g['rms_speed']:.2f} (n={g['n']})"
                                 for _, g in byGroup.iterrows() if g['group'] != requirements.ALL_GROUP)
                     + f". Single seasons: RMS(r) speed {allYear['rms_speed'].min():.2f}–"
                     f"{allYear['rms_speed'].max():.2f}.")
    docPath = os.path.join(args.docDir, 's1AnnualComparison.md')
    writeDoc(docPath, figDir, dict(figures=figures, tables=tables), notes)
    dYear.to_parquet(os.path.join(cacheDir, 'byYear.parquet'))
    dCum.to_parquet(os.path.join(cacheDir, 'cumulative.parquet'))
    print(f'wrote {docPath}')
    for n in notes:
        print(' ', n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
