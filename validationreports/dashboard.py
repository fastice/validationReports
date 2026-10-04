"""Dashboard HTML and dated markdown report.

The dashboard (dashboard/index.html in the validationReports repo) is a single
self-contained page: status cards for the three requirements, the result
figures per region, the GPS section, and run information. Figures are inlined
as base64 PNG so the same file publishes as a claude.ai artifact unchanged.
The dated report (reports/YYYY-MM-DD/<region>.md) follows the
mosaickingDocuments convention: Quarto front matter, a blockquote summary,
bold "Figure N." captions, renders on GitHub as-is.
"""
import base64
import json
import os
import shutil

import numpy as np
import pandas as pd

from validationreports import cycles, gpsSeries, obsDump, plots, requirements
from validationreports import referencePoints
from validationreports.config import REPO_DIR
DASHBOARD_DIR = os.path.join(REPO_DIR, 'dashboard')
REPORTS_DIR = os.path.join(REPO_DIR, 'reports')

STATUS_CHIP = {'met': ('ok', 'met'), 'projected': ('warn', 'projected'),
               'notMet': ('fail', 'not met'), 'insufficient': ('na', 'insufficient data')}
REQ_TITLES = {'slow': 'Slow flow (< 50 m/yr), 3%·V + 1 m/yr',
              'fast': 'Fast flow (> 50 m/yr), 3%·V + 5 m/yr',
              'seasonal': 'Seasonal sampling, 12-day pairs, 3%·V + 10 m/yr'}

CSS = """
:root{
  --bg:#F6F8FA; --panel:#FFFFFF; --ink:#1B222B; --muted:#5A6672; --line:#D8DFE6;
  --accent:#2E6F9E; --accent-soft:#E4EDF4;
  --ok:#3E7A5C; --ok-soft:#E3EFE8; --warn:#A8762A; --warn-soft:#F6EEDD;
  --fail:#B03A2E; --fail-soft:#F7E4E1; --na:#6B7580; --na-soft:#ECEFF2;
  --serif:Georgia,"Iowan Old Style","Times New Roman",serif;
  --sans:system-ui,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#141A21; --panel:#1B232C; --ink:#E4EAF0; --muted:#95A3B1; --line:#2E3944;
    --accent:#6FAED8; --accent-soft:#1E2C38;
    --ok:#79B694; --ok-soft:#1B2A22; --warn:#D5A65A; --warn-soft:#2C2418;
    --fail:#E08A80; --fail-soft:#31201E; --na:#9AA6B2; --na-soft:#222A33;
  }
}
:root[data-theme="dark"]{
  --bg:#141A21; --panel:#1B232C; --ink:#E4EAF0; --muted:#95A3B1; --line:#2E3944;
  --accent:#6FAED8; --accent-soft:#1E2C38;
  --ok:#79B694; --ok-soft:#1B2A22; --warn:#D5A65A; --warn-soft:#2C2418;
  --fail:#E08A80; --fail-soft:#31201E; --na:#9AA6B2; --na-soft:#222A33;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);
  line-height:1.6;margin:0;padding:48px 24px 96px;font-size:16px}
.wrap{max-width:1180px;margin:0 auto;display:flex;flex-direction:column;gap:40px}
.prose{max-width:75ch}
h1{font-family:var(--serif);font-size:2.3rem;line-height:1.15;margin:0;font-weight:600}
h2{font-family:var(--serif);font-size:1.4rem;margin:0 0 14px;font-weight:600;
  padding-bottom:8px;border-bottom:2px solid var(--accent)}
h3{font-family:var(--sans);font-size:.82rem;text-transform:uppercase;
  letter-spacing:.1em;color:var(--muted);margin:22px 0 10px;font-weight:600}
p{margin:0 0 14px}
.eyebrow{font-family:var(--mono);font-size:.76rem;letter-spacing:.16em;
  text-transform:uppercase;color:var(--accent);margin:0 0 12px}
.sub{color:var(--muted);font-size:1.02rem;max-width:75ch;margin:14px 0 0}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:4px;
  padding:18px 20px;display:flex;flex-direction:column;gap:8px}
.card .lab{font-size:.95rem;font-weight:600}
.card .id{font-family:var(--mono);font-size:.76rem;color:var(--accent);letter-spacing:.08em}
.card .note{font-size:.85rem;color:var(--muted);line-height:1.5}
.region{display:grid;grid-template-columns:96px 1fr;gap:10px;align-items:start;
  padding:8px 0;border-top:1px solid var(--line)}
.region .name{font-weight:600;font-size:.9rem;padding-top:2px}
.region .num{font-family:var(--mono);font-size:.82rem;color:var(--muted);line-height:1.6}
.chip{display:inline-block;font-family:var(--mono);font-size:.72rem;padding:2px 8px;
  border-radius:3px;white-space:nowrap;font-weight:600;margin-bottom:4px}
.chip.ok{background:var(--ok-soft);color:var(--ok)}
.chip.warn{background:var(--warn-soft);color:var(--warn)}
.chip.fail{background:var(--fail-soft);color:var(--fail)}
.chip.na{background:var(--na-soft);color:var(--na)}
figure{margin:0 0 24px;display:flex;flex-direction:column;gap:10px}
figure img{width:100%;height:auto;border:1px solid var(--line);border-radius:4px;background:#fff}
figcaption{font-size:.87rem;color:var(--muted);max-width:90ch}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:4px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:.86rem;min-width:640px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
  font-weight:600;background:var(--accent-soft)}
tbody tr:last-child td{border-bottom:none}
td.num{font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}
code{font-family:var(--mono);font-size:.87em;background:var(--accent-soft);padding:1px 5px;border-radius:3px}
.foot{color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);padding-top:18px}
"""


# ----------------------------------------------------------------------
def _img64(path):
    with open(path, 'rb') as fp:
        return 'data:image/png;base64,' + base64.b64encode(fp.read()).decode()


def _fmt(v, nd=2):
    return '—' if v is None or (isinstance(v, float) and not np.isfinite(v)) else f'{v:.{nd}f}'


def _chip(st):
    '''Status chip; a result resting on extrapolated GPS is shown grey, not green.'''
    cls, text = STATUS_CHIP.get(st['status'], ('na', st['status']))
    if st.get('gpsMode') == 'extrapolated' and st['status'] != 'insufficient':
        cls, text = 'na', f'{text} (extrapolated GPS)'
    return f'<span class="chip {cls}">{text}</span>'


def _statusNumbers(st, key):
    '''Short numeric summary lines for a status dict.'''
    if st['status'] == 'insufficient':
        return st.get('reason', 'insufficient data')
    if key == 'seasonal':
        w = st['within']
        return (f"within envelope: speed {w['speed']:.0%}, vx {w['vx']:.0%}, vy {w['vy']:.0%}<br>"
                f"{st['nGated']}/{st['nIntervals']} intervals gated (coverage {st['coverage']:.0%}), "
                f"{st['nStations']} stations<br>RMS speed error {st['rmsSpeedMPerYr']:.1f} m/yr")
    r, p = st['rms'], st['projected']
    need = st.get('cyclesToMeet', {})

    def cyc(qn):
        v = need.get(qn, np.nan)
        if v is None or not np.isfinite(v):
            return 'never at this bias'
        return f'{int(v)}'
    byGroup = st.get('byGroup', {})
    groupText = ''
    if len(byGroup) > 1:
        parts = []
        for g, bg in byGroup.items():
            if bg.get('nStations', 0) == 0:
                continue
            parts.append(f"{g} ({bg['nStations']}): "
                         + ', '.join(f"{q} {v:.2f}" for q, v in bg['rms'].items()))
        groupText = 'by group: ' + '; '.join(parts) + '<br>'
    return (f"RMS residual/tolerance now: speed {r['speed']:.2f}, vx {r['vx']:.2f}, vy {r['vy']:.2f}<br>"
            f"{groupText}"
            f"projected at {st['projectionCycles']} cycles: speed {_fmt(p['speed'])}, "
            f"vx {_fmt(p['vx'])}, vy {_fmt(p['vy'])}<br>"
            f"cycles needed: speed {cyc('speed')}, vx {cyc('vx')}, vy {cyc('vy')}<br>"
            f"{st['nCycles']} cycles, {st['nStations']} points, GPS {st['gpsMode']}")


class RegionResults:
    '''Everything the report needs for one region.'''

    def __init__(self, cfg):
        self.cfg = cfg
        self.stations, self.windows, self.coverage = gpsSeries.loadGpsStage(cfg)
        self.reference = referencePoints.allReference(cfg)
        res = cfg['paths']['results']
        self.rows = pd.read_parquet(os.path.join(res, 'rows.parquet'))
        self.cum = pd.read_parquet(os.path.join(res, 'cumulative.parquet'))
        self.seas = pd.read_parquet(os.path.join(res, 'seasonal.parquet'))
        with open(os.path.join(res, 'status.json')) as fp:
            self.status = json.load(fp)
        groups = [requirements.ALL_GROUP] + self.status.get('groups', ['gps'])
        self.summaries = {k: {g: pd.read_parquet(os.path.join(res, f'summary_{k}_{g}.parquet'))
                              for g in groups} for k in ['slow', 'fast']}
        self.figures = {}

    def referenceTable(self):
        '''One row per static reference group: count, speeds, RMS(r) at the last step.'''
        out = []
        for g in self.status.get('groups', []):
            if g == 'gps':
                continue
            pts = self.reference[self.reference['group'] == g]
            rec = dict(group=g, nPoints=int(len(pts)),
                       nSlow=int((pts['reqClass'] == 'slow').sum()),
                       nFast=int((pts['reqClass'] == 'fast').sum()),
                       speedMin=float(pts['speed'].min()), speedMax=float(pts['speed'].max()))
            for k in ['slow', 'fast']:
                bg = self.status[k].get('byGroup', {}).get(g, {})
                rms = bg.get('rms', {})
                rec[f'{k}Rms'] = ', '.join(f"{q} {v:.2f}" for q, v in rms.items()) if rms else '—'
            out.append(rec)
        return pd.DataFrame(out)

    def makeFigures(self):
        self.figures.update(plots.gpsFigures(self.cfg, self.stations, self.windows,
                                             self.coverage))
        self.figures.update(plots.resultFigures(self.cfg, self.cum, self.summaries,
                                                self.seas, self.stations))
        return self.figures

    def stationTable(self):
        '''Station rows with the forward-model quality counts.'''
        q = self.rows.groupby('station')['quality'].value_counts().unstack(fill_value=0)
        t = self.stations.set_index('station')
        for k in ['real', 'interp', 'extrap', 'skip']:
            t[k] = q[k] if k in q else 0
        t['nRows'] = self.rows.groupby('station').size()
        t['cycles'] = self.rows.groupby('station')['cycle'].nunique()
        return t.fillna(0).reset_index()

    def runInfo(self):
        m = self.cfg['paths']['masterInput']
        return dict(master=m, masterTime=pd.Timestamp(os.path.getmtime(m), unit='s'),
                    cycles=self.status['masterCycles'], nRows=int(len(self.rows)),
                    flags=self.cfg['mosaic3d']['flags'],
                    squint=self.cfg['mosaic3d'].get('useSquint', False),
                    generated=self.status['generated'])


# ----------------------------------------------------------------------
def _stationTableHtml(t):
    head = ['station', 'class', 'stable', 'speed m/yr', 'lat', 'lon', 'record', 'steps',
            'cycles', 'rows', 'real', 'interp', 'extrap', 'skip']
    out = ['<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in head)
           + '</tr></thead><tbody>']
    for _, r in t.iterrows():
        rec = (f"{pd.Timestamp(r['recordStart']).date()} → {pd.Timestamp(r['recordEnd']).date()}")
        cells = [r['station'], r['reqClass'], 'yes' if r['stable'] else 'no',
                 f"{r['speed']:.1f}", f"{r['lat']:.4f}", f"{r['lon']:.4f}", rec,
                 str(int(r['nSteps'])), str(int(r['cycles'])), str(int(r['nRows'])),
                 str(int(r['real'])), str(int(r['interp'])), str(int(r['extrap'])),
                 str(int(r['skip']))]
        out.append('<tr>' + ''.join(
            f'<td class="num">{c}</td>' if i not in (0, 1, 2, 6) else f'<td>{c}</td>'
            for i, c in enumerate(cells)) + '</tr>')
    out.append('</tbody></table></div>')
    return '\n'.join(out)


def _referenceTableHtml(ref):
    head = ['group', 'points', 'slow', 'fast', 'speed range m/yr',
            'slow RMS(r) at last step', 'fast RMS(r) at last step']
    out = ['<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in head)
           + '</tr></thead><tbody>']
    for _, r in ref.iterrows():
        out.append(f"<tr><td>{r['group']}</td><td class=\"num\">{r['nPoints']}</td>"
                   f"<td class=\"num\">{r['nSlow']}</td><td class=\"num\">{r['nFast']}</td>"
                   f"<td class=\"num\">{r['speedMin']:.1f} – {r['speedMax']:.1f}</td>"
                   f"<td class=\"num\">{r['slowRms']}</td><td class=\"num\">{r['fastRms']}</td></tr>")
    out.append('</tbody></table></div>')
    return '\n'.join(out)


def overallStatus(results, key):
    '''Both regions together: RMS speed error, mean tolerance, fraction, status.

    slow/fast use every point's latest cumulative estimate; seasonal uses the
    gated 12-day intervals at fast stations. Status is met when RMS(r) <= 1
    for speed, vx and vy.
    '''
    parts = []
    for r in results:
        if key == 'seasonal':
            s = r.seas[r.seas['gated'] & (r.seas['reqClass'] == 'fast')]
        else:
            c = r.cum[r.cum['reqClass'] == key]
            s = c.sort_values('k').groupby('station').tail(1)
        parts.append(s)
    s = pd.concat(parts) if parts else pd.DataFrame()
    if len(s) == 0:
        return None
    rms = lambda v: float(np.sqrt(np.mean(np.asarray(v, dtype=float) ** 2)))
    achieved = rms(s['dspeed'])
    tol = float(s['tol'].mean())
    rmsR = {qn: rms(s[f'r{qn}']) for qn in requirements.QUANTITIES}
    met = all(v <= 1 for v in rmsR.values())
    # fraction = RMS of the per-point speed residual / tolerance, the same
    # statistic the status is judged on (achieved / mean tolerance differs
    # slightly because the tolerance varies point to point)
    return dict(status='met' if met else 'notMet', achieved=achieved, tolerance=tol,
                fraction=rmsR['speed'], n=int(len(s)), rms=rmsR)


def _overallHtml(ov):
    if ov is None:
        return ('<div class="region"><div class="name">Overall</div>'
                '<div><span class="chip na">insufficient data</span></div></div>')
    return (f'<div class="region"><div class="name">Overall</div><div>{_chip(ov)}'
            f'<div class="num">achieved 1-σ {ov["achieved"]:.1f} m/yr · tolerance '
            f'{ov["tolerance"]:.1f} m/yr · fraction {ov["fraction"]:.2f} · n = {ov["n"]}'
            f'</div></div></div>')


def _stationList(r):
    names = list(r.stations['station'])
    span = (pd.Timestamp(r.stations['recordStart'].min()).strftime('%b %Y'),
            pd.Timestamp(r.stations['recordEnd'].max()).strftime('%b %Y'))
    return names, span


def dataSourceItems(results):
    '''[(heading, text)] describing each validation data set (HTML-free text).'''
    items = []
    for r in results:
        names, (t0, t1) = _stationList(r)
        items.append((
            f"{r.cfg['label']} GPS stations ({', '.join(names)})",
            f"Continuous GNSS stations deployed for NISAR cal/val ({t0} to {t1}). "
            "Positions come from the NISAR cal/val database: 30 s solutions through the sunlit "
            "season and a single daily session in winter (Antarctic winter solutions are flagged "
            "degraded and excluded). Velocities are least-squares slopes of position over each "
            "observation's own window; antenna resets are detected as off-flow position steps and "
            "removed. Slow (< 50 m/yr) and fast classes are set by the long-term GPS speed."))
    static = [s for r in results for s in r.cfg.get('referenceSets', [])]
    if any(s['name'] == 'points2000' for s in static):
        items.append((
            '2000 m points (45 of 152)',
            "In-situ GPS velocities measured along the 2000 m elevation contour of the Greenland "
            "ice sheet in 1993 to 1997 (NSIDC-0615, https://nsidc.org/data/nsidc-0615/versions/1). "
            "Because these are single epochs roughly a quarter century old, "
            "each point was screened for change since it was measured: the Sentinel-1 annual "
            "velocity stack (2014-15 to 2022-23) gives a linear trend at every point, and only "
            "points south of 77 N whose trend projected over the gap is less than half the "
            "requirement tolerance (0.03·V + 1 or + 5 m/yr) are kept. The screen is on trend, not "
            "year-to-year scatter, which is nearly independent of it. The retained 45 span 1 to "
            "150 m/yr (24 slow, 21 fast); only two are below 6 m/yr, so the set does not test the "
            "slowest ice. Each point is a single velocity, so its reference is constant in time."))
    if any(s['name'] == 'negis' for s in static):
        items.append((
            'NEGIS points (63)',
            "GPS velocities of the 63-pole strain net around the EastGRIP drill site on the "
            "Northeast Greenland Ice Stream, observed 2015 to 2019 (Hvidberg, C. S. et al. "
            "(2020). Surface velocity of the Northeast Greenland Ice Stream (NEGIS): assessment "
            "of interior velocities derived from satellite data by GPS. The Cryosphere 14, "
            "3487-3502. doi:10.5194/tc-14-3487-2020). The poles span 10 to 58 m/yr (52 slow, "
            "11 fast) across the stream and its shear margin. No point was culled: the GPS epoch "
            "falls inside the Sentinel-1 annual stack (2014-15 to 2022-23), whose mean reads "
            "1.001 of the GPS speed (median over the 63), so the ice has not measurably changed. "
            "Each point is a single velocity, so its reference is constant in time."))
    if any(s['name'] == 'summit' for s in static):
        items.append((
            'Summit points (9)',
            "Nine GNSS stations within about 35 km of Summit, Greenland, at 0.5 to 2.3 m/yr, from "
            "annual solutions for 2022, 2023 and 2024 averaged ("
            "Pickell, D. & Hawley, R. (2024). An East-West Network of Twelve Global Navigation "
            "Satellite System (GNSS) Stations in the Summit Region of Greenland: RINEX Data, "
            "2022-2025. Arctic Data Center. doi:10.18739/A2183446Q). Because the speeds are "
            "comparable to the 1 m/yr floor of the slow requirement they bound an additive error "
            "rather than a scale, and because they share frames the effective sample size is "
            "nearer one than nine. Each is a single velocity, constant in time."))
    return items


def _dataSourcesHtml(results):
    parts = ['<section><h2>Validation data sources</h2><div class="prose">']
    for head, text in dataSourceItems(results):
        text = text.replace('https://nsidc.org/data/nsidc-0615/versions/1',
                            '<a href="https://nsidc.org/data/nsidc-0615/versions/1">NSIDC-0615</a>')
        text = text.replace('doi:10.5194/tc-14-3487-2020',
                            '<a href="https://doi.org/10.5194/tc-14-3487-2020">doi:10.5194/tc-14-3487-2020</a>')
        text = text.replace('doi:10.18739/A2183446Q',
                            '<a href="https://doi.org/10.18739/A2183446Q">doi:10.18739/A2183446Q</a>')
        parts.append(f'<p><b>{head}.</b> {text}</p>')
    parts.append('</div></section>')
    return '\n'.join(parts)


def _figureHtml(path, caption):
    return f'<figure><img src="{_img64(path)}" alt="{caption}"><figcaption>{caption}</figcaption></figure>'


def buildHtml(results, today):
    regions = [r.cfg['label'] for r in results]
    parts = [f'<title>NISAR Velocity Validation</title>\n<style>{CSS}</style>\n<div class="wrap">']
    parts.append(f'''<header class="prose">
  <p class="eyebrow">{' · '.join(regions)} · no-squint hopper · updated {today}</p>
  <h1>NISAR velocity requirement validation</h1>
  <p class="sub">Each requirement is evaluated against GPS three ways (speed, vx, vy) using
  <code>mosaic3d -obsDump</code> rows at the GPS pixels, with the GPS forward-modelled through
  the solver's own weights and windows. Status is green when the RMS residual over stations is
  within the 1-σ tolerance now, amber when the fitted error curve reaches it at
  {results[0].cfg['projectionCycles']} cycles, red otherwise, grey when the data cannot test it.</p>
</header>''')
    # status cards
    parts.append('<section><h2>Status</h2><div class="grid3">')
    for key in ['slow', 'fast', 'seasonal']:
        rid = results[0].cfg['requirements'][key]['id']
        parts.append(f'<div class="card"><div class="id">{rid}</div><div class="lab">{REQ_TITLES[key]}</div>')
        for r in results:
            st = r.status[key]
            parts.append(f'<div class="region"><div class="name">{r.cfg["label"]}</div>'
                         f'<div>{_chip(st)}<div class="num">{_statusNumbers(st, key)}</div></div></div>')
        parts.append(_overallHtml(overallStatus(results, key)))
        parts.append('</div>')
    parts.append('</div>')
    parts.append('<p class="note" style="font-size:.85rem;color:var(--muted);margin:12px 0 0">'
                 'Fraction = RMS over points of (speed error / that point\'s tolerance 0.03·V + c), '
                 'the per-point statistic the status is judged on; it is not achieved ÷ tolerance, '
                 'which divides pooled averages and differs when the tolerance varies across points.</p>')
    parts.append('</section>')
    parts.append(_dataSourcesHtml(results))
    # results per region
    for r in results:
        L = r.cfg['label']
        parts.append(f'<section><h2>{L}: results</h2>')
        for key in ['slow', 'fast']:
            rid = r.cfg['requirements'][key]['id']
            parts.append(_figureHtml(r.figures[f'cumulative_{key}'],
                f'{L} {rid}. Row 1: NISAR − GPS per station with formal σ, as data accumulate cycle by cycle. '
                f'Row 2: residual divided by the station tolerance (band = ±1). Row 3: RMS over stations '
                f'with the fitted a² + b²/N projection to {r.cfg["projectionCycles"]} cycles.'))
        parts.append(_figureHtml(r.figures['seasonal'],
            f"{L} {r.cfg['requirements']['seasonal']['id']}. Each 12-day cycle solved on its own from the "
            f"12-day pairs; GPS forward-modelled over the same windows; intervals with formal σ ≥ "
            f"{r.cfg['requirements']['seasonal']['maxSigma']} m/yr rejected."))
        parts.append('</section>')
    # GPS section
    for r in results:
        L = r.cfg['label']
        parts.append(f'<section><h2>{L}: GPS</h2>')
        parts.append(_figureHtml(r.figures['gpsSpeed'],
            f'{L} GPS 12-day speeds over the full record (colour = sampling regime; dotted red = '
            f'position step treated as an antenna reset; shaded = NISAR cycles in the master input).'))
        parts.append(_figureHtml(r.figures['gpsCoverage'], f'{L} GPS daily coverage and regime.'))
        parts.append('<h3>Stations</h3>')
        parts.append(_stationTableHtml(r.stationTable()))
        ref = r.referenceTable()
        if len(ref):
            parts.append('<h3>Static reference point sets</h3>')
            parts.append(_referenceTableHtml(ref))
        parts.append('</section>')
    # run info
    parts.append('<section><h2>Run information</h2><div class="scroll"><table><thead><tr>'
                 '<th>region</th><th>master input</th><th>master updated</th><th>cycles</th>'
                 '<th>rows</th><th>mosaic3d flags</th></tr></thead><tbody>')
    for r in results:
        info = r.runInfo()
        parts.append(f"<tr><td>{r.cfg['label']}</td><td><code>{info['master']}</code></td>"
                     f"<td class=\"num\">{info['masterTime'].strftime('%Y-%m-%d %H:%M')}</td>"
                     f"<td class=\"num\">{cyclesText(info['cycles'])}</td><td class=\"num\">{info['nRows']}</td>"
                     f"<td><code>{info['flags']}{' -useSquint' if info['squint'] else ''}</code></td></tr>")
    parts.append('</tbody></table></div></section>')
    parts.append(f'<p class="foot">Generated {today} by <code>runValidation</code> '
                 f'(validationReports). Every product is rebuilt from the current GPS parquet '
                 f'files and master inputs on each run.</p></div>')
    return '\n'.join(parts)


def cyclesText(cycleList):
    '''Compact "3-9, 15-22" text for a cycle list.'''
    if not cycleList:
        return '—'
    runs, start, prev = [], cycleList[0], cycleList[0]
    for c in cycleList[1:]:
        if c == prev + 1:
            prev = c
            continue
        runs.append((start, prev))
        start = prev = c
    runs.append((start, prev))
    return ', '.join(f'{a}' if a == b else f'{a}-{b}' for a, b in runs)


# ----------------------------------------------------------------------
def buildMarkdown(r, today, figDir, figPrefix):
    '''Dated report for one region in the mosaickingDocuments style.'''
    cfg, st = r.cfg, r.status
    L = cfg['label']
    lines = [f'---', f'title: "NISAR velocity validation — {L}"',
             f'subtitle: "Requirements L2-SCI-667/668/738 against GPS, no-squint hopper"',
             f'date: {today}', '---', '',
             '## Purpose', '',
             f'Automated validation of the NISAR ice-velocity requirements over {L} against the '
             f'cal/val GPS network, rebuilt from the current master input and GPS parquet files. '
             f'Observations come from `mosaic3d -obsDump` at the GPS pixels; the GPS is forward-modelled '
             f'through the solver\'s own weights and windows so temporal sampling cancels exactly.', '',
             '> **Status**', '>']
    for key in ['slow', 'fast', 'seasonal']:
        s = st[key]
        text = _statusNumbers(s, key).replace('<br>', '; ')
        lines.append(f"> - **{cfg['requirements'][key]['id']}** ({key}): **{STATUS_CHIP.get(s['status'], ('', s['status']))[1]}** — {text}")
    lines += ['', '## Validation data sources', '']
    for head, text in dataSourceItems([r]):
        lines += [f'**{head}.** {text}', '']
    lines += ['## Method', '',
              'For each station the per-observation rows $(\\mathbf a_i, d_i, \\sigma_i, w_i)$ are '
              'solved as $\\hat{\\mathbf v} = (\\sum_i w_i \\mathbf a_i \\mathbf a_i^{\\mathsf T})^{-1} '
              '\\sum_i w_i \\mathbf a_i d_i$ with the surface-parallel projection, and the GPS is pushed '
              'through the same weights as $d_i^{\\rm GPS} = \\mathbf a_i \\cdot \\bar{\\mathbf v}_{\\rm GPS}(t_i, \\Delta t_i)$. '
              'The residual $\\Delta$ for speed, $v_x$ and $v_y$ is divided by the tolerance '
              '$T = 0.03\\,|\\mathbf v_{\\rm GPS}| + c$ ($c$ = 1, 5, 10 m/yr). A requirement is met when '
              'the RMS of $\\Delta/T$ over stations is $\\le 1$; the projection fits $e^2(N) = a^2 + b^2/N$ '
              f"to the cumulative-cycle series and evaluates it at N = {cfg['projectionCycles']} cycles.", '',
              'GPS windows use every epoch inside the window (regression, not endpoint differencing); '
              'a window is `real` when it has data, `extrap` (long-term mean) at stations classed stable, '
              '`interp` between neighbouring windows otherwise, and rows without a reference are dropped '
              'from both solves.', '',
              '## Results', '']
    n = 1
    for key in ['slow', 'fast']:
        rid = cfg['requirements'][key]['id']
        fn = f'{figPrefix}_cumulative_{key}.png'
        lines += [f'![{rid}](figures/{fn})', '',
                  f'**Figure {n}.** {L} {rid} ({key} flow). NISAR − GPS per station with formal σ as '
                  f'cycles accumulate; residual over tolerance; RMS over stations with the projection to '
                  f"{cfg['projectionCycles']} cycles.", '']
        n += 1
    lines += [f"![seasonal](figures/{figPrefix}_seasonal.png)", '',
              f"**Figure {n}.** {L} {cfg['requirements']['seasonal']['id']}. Each 12-day cycle solved "
              f"from its 12-day pairs against the GPS forward model over the same windows.", '']
    n += 1
    lines += ['## GPS', '',
              f'![gps speed](figures/{figPrefix}_gpsSpeed.png)', '',
              f'**Figure {n}.** {L} GPS 12-day speeds over the full record.', '']
    n += 1
    lines += [f'![gps coverage](figures/{figPrefix}_gpsCoverage.png)', '',
              f'**Figure {n}.** {L} GPS daily coverage and sampling regime.', '',
              '### Stations', '',
              '| station | class | stable | speed (m/yr) | record | steps | cycles | rows | real | interp | extrap | skip |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for _, row in r.stationTable().iterrows():
        lines.append(f"| {row['station']} | {row['reqClass']} | {'yes' if row['stable'] else 'no'} | "
                     f"{row['speed']:.1f} | {pd.Timestamp(row['recordStart']).date()} → "
                     f"{pd.Timestamp(row['recordEnd']).date()} | {int(row['nSteps'])} | {int(row['cycles'])} | "
                     f"{int(row['nRows'])} | {int(row['real'])} | {int(row['interp'])} | "
                     f"{int(row['extrap'])} | {int(row['skip'])} |")
    ref = r.referenceTable()
    if len(ref):
        lines += ['', '### Static reference point sets', '',
                  '| group | points | slow | fast | speed (m/yr) | slow RMS(r) | fast RMS(r) |',
                  '|---|---|---|---|---|---|---|']
        for _, row in ref.iterrows():
            lines.append(f"| {row['group']} | {row['nPoints']} | {row['nSlow']} | {row['nFast']} | "
                         f"{row['speedMin']:.1f} – {row['speedMax']:.1f} | {row['slowRms']} | "
                         f"{row['fastRms']} |")
    info = r.runInfo()
    lines += ['', '## Run information', '',
              f"- master input: `{info['master']}` (updated {info['masterTime'].strftime('%Y-%m-%d %H:%M')})",
              f"- cycles: {cyclesText(info['cycles'])}; observation rows: {info['nRows']}",
              f"- mosaic3d: `{info['flags']}`, squint {'on' if info['squint'] else 'off'}",
              f"- generated: {info['generated']}", '']
    return '\n'.join(lines)


# ----------------------------------------------------------------------
def runReportStage(cfgs, verbose=True):
    '''Figures, dashboard/index.html and reports/<date>/<region>.md.'''
    today = pd.Timestamp.now().strftime('%Y-%m-%d')
    results = []
    for cfg in cfgs:
        r = RegionResults(cfg)
        r.makeFigures()
        results.append(r)
    os.makedirs(DASHBOARD_DIR, exist_ok=True)
    htmlPath = os.path.join(DASHBOARD_DIR, 'index.html')
    with open(htmlPath, 'w') as fp:
        fp.write(buildHtml(results, today))
    reportDir = os.path.join(REPORTS_DIR, today)
    figDir = os.path.join(reportDir, 'figures')
    os.makedirs(figDir, exist_ok=True)
    written = [htmlPath]
    for r in results:
        prefix = r.cfg['region']
        for key, path in r.figures.items():
            shutil.copy(path, os.path.join(figDir, f'{prefix}_{key}.png'))
        mdPath = os.path.join(reportDir, f'{prefix}.md')
        with open(mdPath, 'w') as fp:
            fp.write(buildMarkdown(r, today, figDir, prefix))
        written.append(mdPath)
    shutil.copy(htmlPath, os.path.join(reportDir, 'dashboard.html'))
    if verbose:
        for w in written:
            print(f'  wrote {w}')
    return written
