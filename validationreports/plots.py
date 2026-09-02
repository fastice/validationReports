"""Figures for the validation dashboard and reports (matplotlib, PNG).

Colour roles (fixed order, never cycled):
  series 1 blue   - NISAR / dense GPS
  series 2 orange - GPS forward model / sparse-winter GPS
  series 3 aqua   - interpolated GPS
  series 7 violet - extrapolated GPS
Status colours (good / warning / critical) are reserved for status only.
"""
import os
from datetime import timedelta

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402

from validationreports import cycles  # noqa: E402

SERIES = {'blue': '#2a78d6', 'orange': '#eb6834', 'aqua': '#1baf7a',
          'yellow': '#eda100', 'magenta': '#e87ba4', 'green': '#008300',
          'violet': '#4a3aa7', 'red': '#e34948'}
QUALITY_COLOR = {'real': SERIES['blue'], 'sparse': SERIES['orange'],
                 'interp': SERIES['aqua'], 'extrap': SERIES['violet']}
STATUS = {'good': '#0ca30c', 'warning': '#fab219', 'critical': '#d03b3b',
          'na': '#9a9a96'}
INK = '#1B222B'
MUTED = '#5A6672'
GRID = '#D8DFE6'
CYCLE_SHADE = '#EEF2F6'
DPI = 140

plt.rcParams.update({
    'font.size': 9, 'axes.edgecolor': GRID, 'axes.labelcolor': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.titlecolor': INK,
    'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.6,
    'axes.spines.top': False, 'axes.spines.right': False,
    'legend.frameon': False, 'lines.linewidth': 1.6, 'figure.facecolor': 'white',
    'axes.facecolor': 'white', 'savefig.facecolor': 'white',
})


def _shadeCycles(ax, cycleList, label=True):
    '''Shade the span of each NISAR cycle present in the master input.'''
    first = True
    for c in cycleList:
        start, end = cycles.cycleDates(c)
        ax.axvspan(start, end, color=CYCLE_SHADE, lw=0, zorder=0,
                   label='NISAR cycles in master' if (first and label) else None)
        first = False


def _dateAxis(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b\n%Y'))


WINDOW_REGIME = {
    'dense': ('GPS 12-day speed (30 s data)', SERIES['blue']),
    'daily': ('GPS 12-day speed (winter daily fixes)', SERIES['orange']),
    'mixed': ('GPS 12-day speed (regime transition)', SERIES['yellow']),
}
DAY_REGIME = {
    'dense': ('30 s epochs', SERIES['blue']),
    'daily': ('one winter fix per day', SERIES['orange']),
    'degraded': ('degraded solutions (excluded)', SERIES['magenta']),
}


# ----------------------------------------------------------------------
def figGpsSpeed(stations, windows, cycleList, outPath, title):
    '''Per-station 12-day speed over the full GPS record.'''
    names = list(stations['station'])
    n = len(names)
    fig, axes = plt.subplots(n, 1, figsize=(11, 1.55 * n + 1.2), sharex=True)
    axes = np.atleast_1d(axes)
    handles = {}
    for ax, name in zip(axes, names):
        w = windows[name]
        ok = w[w['ok']]
        row = stations[stations['station'] == name].iloc[0]
        _shadeCycles(ax, cycleList, label=False)
        for regime, (lab, color) in WINDOW_REGIME.items():
            sub = ok[ok['regime'] == regime]
            if len(sub) == 0:
                continue
            h = ax.plot(sub['mid'], sub['speed'], '.', ms=4, color=color,
                        label=lab)[0]
            handles[lab] = h
        h = ax.axhline(row['speed'], color=MUTED, lw=1, ls='--',
                       label='long-term mean')
        handles['long-term mean'] = h
        steps = row.get('steps', '')
        if isinstance(steps, str) and steps:
            for s in steps.split(';'):
                h = ax.axvline(pd.Timestamp(s.split(':')[0]), color=SERIES['red'],
                               lw=1, ls=':', label='position step (reset / regime offset)')
            handles['position step (reset / regime offset)'] = h
        tol = row['tolerance']
        ax.axhspan(row['speed'] - tol, row['speed'] + tol, color=SERIES['blue'],
                   alpha=0.07, lw=0)
        cls = f"{row['reqClass']} · {'stable' if row['stable'] else 'variable'}"
        ax.set_ylabel(f"{name}\n{row['speed']:.0f} m/yr", fontsize=8.5)
        ax.text(0.995, 0.93, cls, transform=ax.transAxes, ha='right', va='top',
                fontsize=8, color=MUTED)
        ax.tick_params(axis='y', labelsize=8)
        ax.margins(y=0.25)
    _dateAxis(axes[-1])
    handles['NISAR cycles in master'] = plt.Rectangle((0, 0), 1, 1, color=CYCLE_SHADE)
    fig.legend(handles.values(), handles.keys(), loc='lower center', ncol=4,
               fontsize=8, bbox_to_anchor=(0.5, 0.0))
    fig.suptitle(title, x=0.01, ha='left', fontsize=11, fontweight='semibold')
    fig.text(0.01, 0.955, 'Band = requirement tolerance about the mean; '
             'shaded columns = NISAR cycles in the master input',
             fontsize=8, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(outPath, dpi=DPI)
    plt.close(fig)
    return outPath


def figGpsCoverage(stations, coverage, cycleList, outPath, title):
    '''Station rows vs time, shaded by daily regime.'''
    names = list(stations['station'])
    n = len(names)
    fig, ax = plt.subplots(figsize=(11, 0.42 * n + 1.6))
    present = set()
    for i, name in enumerate(names):
        cov = coverage[name]
        for regime, (lab, color) in DAY_REGIME.items():
            days = cov.loc[cov['regime'] == regime, 'day']
            if len(days) == 0:
                continue
            present.add(regime)
            ax.bar(days, 0.7, width=1.0, bottom=i - 0.35, color=color, lw=0,
                   align='edge')
    for c in cycleList:
        start, end = cycles.cycleDates(c)
        ax.axvspan(start, end, ymin=0.985, ymax=1.0, color=INK, lw=0)
    ax.set_yticks(range(n))
    ax.set_yticklabels(names, fontsize=8.5)
    ax.set_ylim(-0.6, n - 0.4 + 0.3)
    ax.invert_yaxis()
    ax.grid(axis='y', visible=False)
    _dateAxis(ax)
    handles = [plt.Rectangle((0, 0), 1, 1, color=DAY_REGIME[r][1])
               for r in DAY_REGIME if r in present]
    labels = [DAY_REGIME[r][0] for r in DAY_REGIME if r in present]
    handles.append(plt.Rectangle((0, 0), 1, 1, color=INK))
    labels.append('NISAR cycles in master (top ticks)')
    ax.legend(handles, labels, loc='lower center', ncol=4, fontsize=8,
              bbox_to_anchor=(0.5, -0.42 - 0.9 / max(n, 1)))
    ax.set_title(title, loc='left', fontsize=11, fontweight='semibold')
    fig.tight_layout()
    fig.savefig(outPath, dpi=DPI, bbox_inches='tight')
    plt.close(fig)
    return outPath


def gpsFigures(cfg, stations, windows, coverage, outDir=None):
    '''Write the two GPS figures for a region; returns {key: path}.'''
    outDir = outDir or cfg['paths']['figures']
    os.makedirs(outDir, exist_ok=True)
    cycleList = cycles.masterCycles(cfg['paths']['masterInput'])
    label = cfg['label']
    paths = {}
    paths['gpsSpeed'] = figGpsSpeed(
        stations, windows, cycleList, os.path.join(outDir, 'gpsSpeed.png'),
        f'{label} GPS: 12-day speeds over the full record')
    paths['gpsCoverage'] = figGpsCoverage(
        stations, coverage, cycleList, os.path.join(outDir, 'gpsCoverage.png'),
        f'{label} GPS: daily coverage and sampling regime')
    return paths


# ----------------------------------------------------------------------
STATION_SLOTS = ['blue', 'orange', 'aqua', 'yellow', 'magenta', 'green', 'violet', 'red']
QUANTITY_LABEL = {'speed': 'speed', 'vx': 'vx', 'vy': 'vy'}


def _stationColors(names):
    return {n: SERIES[STATION_SLOTS[i % len(STATION_SLOTS)]] for i, n in enumerate(names)}


def figCumulative(cum, summary, reqClass, cfg, outPath, title):
    '''Cumulative-cycle panels for one requirement class.

    Row 1: NISAR - GPS in m/yr per station with formal sigma bars.
    Row 2: normalised residual r = delta / T per station with the +-1 band.
    Row 3: RMS(r) over stations with the fitted projection to projectionCycles.
    '''
    sub = cum[cum['reqClass'] == reqClass]
    names = sorted(sub['station'].unique())
    colors = _stationColors(names)
    nTarget = cfg['projectionCycles']
    fig, axes = plt.subplots(3, 3, figsize=(12.5, 9.2), sharex='col')
    for j, qn in enumerate(['speed', 'vx', 'vy']):
        axD, axR, axS = axes[0, j], axes[1, j], axes[2, j]
        for name in names:
            s = sub[sub['station'] == name].sort_values('k')
            sig = s['sigSpeed'] if qn == 'speed' else s[f'sig{qn[0].upper()}{qn[1:]}']
            axD.errorbar(s['k'], s[f'd{qn}'], yerr=sig, fmt='o-', ms=3.5, lw=1.2,
                         capsize=2, color=colors[name], label=name)
            axR.plot(s['k'], s[f'r{qn}'], 'o-', ms=3.5, lw=1.2, color=colors[name],
                     label=name)
        axD.axhline(0, color=INK, lw=0.8)
        axR.axhspan(-1, 1, color=SERIES['blue'], alpha=0.08, lw=0)
        axR.axhline(0, color=INK, lw=0.8)
        axD.set_title(f'{QUANTITY_LABEL[qn]}: NISAR − GPS (m/yr)', loc='left', fontsize=9.5)
        axR.set_title(f'{QUANTITY_LABEL[qn]}: residual / tolerance', loc='left', fontsize=9.5)
        if len(summary):
            k = summary['k'].to_numpy()
            rms = summary[f'rms_{qn}'].to_numpy()
            axS.plot(k, rms, 'o-', ms=4, color=SERIES['blue'], label='RMS(r) over stations')
            from validationreports.requirements import projectSeries
            p = projectSeries(k, rms, nTarget)
            if np.isfinite(p['projected']):
                kk = np.arange(k[-1], nTarget + 1)
                if p['method'] == 'fit':
                    curve = np.sqrt(p['floor'] ** 2 + p['random'] ** 2 / kk)
                else:
                    curve = rms[-1] * np.sqrt(k[-1] / kk)
                axS.plot(kk, curve, '--', color=SERIES['orange'], lw=1.4,
                         label=f'projection ({p["method"]}) → {p["projected"]:.2f} at {nTarget}')
                axS.plot([nTarget], [p['projected']], 's', color=SERIES['orange'], ms=5)
        axS.axhline(1, color=STATUS['critical'], lw=1, ls=':', label='requirement (r = 1)')
        # the first cycles are geometry-starved and off-scale; clamp so the
        # steady state is legible (points beyond the limits sit on the edge)
        rLim = 4.
        meanTol = float(sub['tol'].mean()) if len(sub) else 1.
        axD.set_ylim(-rLim * meanTol, rLim * meanTol)
        axR.set_ylim(-rLim, rLim)
        axS.set_ylim(0, rLim)
        axS.set_title(f'{QUANTITY_LABEL[qn]}: RMS residual / tolerance', loc='left', fontsize=9.5)
        axS.set_xlabel('cumulative NISAR cycles in the master input')
        axS.legend(fontsize=7.5, loc='upper right')
        axS.set_xlim(0.5, nTarget + 0.5)
    axes[0, 0].legend(fontsize=7.5, ncol=2)
    fig.suptitle(title, x=0.01, ha='left', fontsize=11, fontweight='semibold')
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    fig.savefig(outPath, dpi=DPI)
    plt.close(fig)
    return outPath


def figSeasonal(seas, stations, cfg, outPath, title):
    '''Per fast station: 12-day NISAR vs GPS speed, and the residuals vs the envelope.'''
    s = cfg['requirements']['seasonal']
    fast = seas[seas['reqClass'] == 'fast']
    names = [n for n in sorted(fast['station'].unique()) if fast[fast['station'] == n]['gated'].any()]
    if len(names) == 0:
        fig, ax = plt.subplots(figsize=(11, 2.2))
        ax.text(0.5, 0.5, 'no gated 12-day intervals at fast stations', ha='center',
                va='center', color=MUTED, transform=ax.transAxes)
        ax.set_axis_off()
        fig.savefig(outPath, dpi=DPI)
        plt.close(fig)
        return outPath
    n = len(names)
    fig, axes = plt.subplots(n, 2, figsize=(12.5, 2.3 * n + 1), sharex=True, squeeze=False)
    qualColor = {'real': SERIES['orange'], 'interp': SERIES['aqua'], 'extrap': SERIES['violet']}
    for i, name in enumerate(names):
        sub = fast[fast['station'] == name].sort_values('date')
        ok = sub[sub['gated']]
        bad = sub[~sub['gated']]
        axL, axR = axes[i]
        axL.errorbar(ok['date'], ok['speed'], yerr=ok['sigSpeed'], fmt='o-', ms=3.5,
                     lw=1.2, capsize=2, color=SERIES['blue'], label='NISAR 12-day')
        dom = ok[['qReal', 'qInterp', 'qExtrap']].idxmax(axis=1).str[1:].str.lower()
        for q, c in qualColor.items():
            m = dom == q
            if m.any():
                axL.plot(ok['date'][m], ok['speedG'][m], 's', ms=4, color=c,
                         label=f'GPS forward model ({q})')
        axL.plot(ok['date'], ok['speedG'], '--', lw=1, color=SERIES['orange'])
        if len(bad):
            # rejected solves can be wildly off; pin them to the top edge
            lo = min(ok['speed'].min() - 2 * ok['sigSpeed'].max(), ok['speedG'].min())
            hi = max(ok['speed'].max() + 2 * ok['sigSpeed'].max(), ok['speedG'].max())
            pad = 0.1 * (hi - lo + 1)
            axL.set_ylim(lo - pad, hi + 2 * pad)
            axL.plot(bad['date'], np.full(len(bad), hi + 1.5 * pad), 'x',
                     color=STATUS['critical'], ms=6,
                     label=f'rejected (σ ≥ {s["maxSigma"]} m/yr), off scale')
        axL.set_ylabel(f'{name}\nspeed (m/yr)', fontsize=8.5)
        axL.legend(fontsize=7, ncol=2)
        axR.fill_between(ok['date'], -ok['tol'], ok['tol'], color=SERIES['blue'], alpha=0.1,
                         lw=0, label='3% + 10 m/yr envelope')
        axR.axhline(0, color=INK, lw=0.8)
        axR.errorbar(ok['date'], ok['dvx'], yerr=ok['sigVx'], fmt='o-', ms=3, lw=1,
                     capsize=2, color=SERIES['aqua'], label='Δvx')
        axR.errorbar(ok['date'], ok['dvy'], yerr=ok['sigVy'], fmt='s-', ms=3, lw=1,
                     capsize=2, color=SERIES['violet'], label='Δvy')
        axR.plot(ok['date'], ok['dspeed'], '^-', ms=4, lw=1.4, color=INK, label='Δspeed')
        axR.set_ylabel('NISAR − GPS (m/yr)', fontsize=8.5)
        axR.legend(fontsize=7, ncol=2)
    for ax in axes[-1]:
        _dateAxis(ax)
    axes[0, 0].set_title('12-day interval speed: NISAR vs GPS', loc='left', fontsize=9.5)
    axes[0, 1].set_title('Per-interval residuals vs L2-SCI-738 envelope', loc='left', fontsize=9.5)
    fig.suptitle(title, x=0.01, ha='left', fontsize=11, fontweight='semibold')
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(outPath, dpi=DPI)
    plt.close(fig)
    return outPath


def resultFigures(cfg, cum, summaries, seas, stations, outDir=None):
    '''Write the requirement figures for a region; returns {key: path}.'''
    outDir = outDir or cfg['paths']['figures']
    os.makedirs(outDir, exist_ok=True)
    label = cfg['label']
    paths = {}
    for reqClass in ['slow', 'fast']:
        rid = cfg['requirements'][reqClass]['id']
        paths[f'cumulative_{reqClass}'] = figCumulative(
            cum, summaries[reqClass], reqClass, cfg,
            os.path.join(outDir, f'cumulative_{reqClass}.png'),
            f'{label} {rid} ({reqClass} flow): estimate vs cumulative cycles')
    paths['seasonal'] = figSeasonal(
        seas, stations, cfg, os.path.join(outDir, 'seasonal.png'),
        f"{label} {cfg['requirements']['seasonal']['id']}: 12-day intervals")
    return paths
