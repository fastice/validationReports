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

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    return (f"RMS residual/tolerance now: speed {r['speed']:.2f}, vx {r['vx']:.2f}, vy {r['vy']:.2f}<br>"
            f"projected at {st['projectionCycles']} cycles: speed {_fmt(p['speed'])}, "
            f"vx {_fmt(p['vx'])}, vy {_fmt(p['vy'])}<br>"
            f"cycles needed: speed {cyc('speed')}, vx {cyc('vx')}, vy {cyc('vy')}<br>"
            f"{st['nCycles']} cycles, {st['nStations']} stations, GPS {st['gpsMode']}")


class RegionResults:
    '''Everything the report needs for one region.'''

    def __init__(self, cfg):
        self.cfg = cfg
        self.stations, self.windows, self.coverage = gpsSeries.loadGpsStage(cfg)
        res = cfg['paths']['results']
        self.rows = pd.read_parquet(os.path.join(res, 'rows.parquet'))
        self.cum = pd.read_parquet(os.path.join(res, 'cumulative.parquet'))
        self.seas = pd.read_parquet(os.path.join(res, 'seasonal.parquet'))
        self.summaries = {k: pd.read_parquet(os.path.join(res, f'summary_{k}.parquet'))
                          for k in ['slow', 'fast']}
        with open(os.path.join(res, 'status.json')) as fp:
            self.status = json.load(fp)
        self.figures = {}

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
        parts.append('</div>')
    parts.append('</div></section>')
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
    lines += ['', '## Method', '',
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
