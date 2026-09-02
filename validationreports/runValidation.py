"""runValidation: NISAR velocity-requirement validation against GPS.

Stages (all rebuild from the current parquet and master input files):
  gps     GPS window series, coverage and station classification
  dump    mosaic3d -obsDump point-mode runs (skipped when current unless --force)
  eval    forward model, cumulative-cycle and seasonal evaluation, status
  report  figures, dashboard HTML and the dated markdown report
"""
import argparse
import sys

from validationreports import config as vcfg
from validationreports import gpsSeries, plots

STAGES = ['gps', 'dump', 'eval', 'report']


def parseArgs(argv=None):
    parser = argparse.ArgumentParser(
        description='\033[1mNISAR velocity requirement validation\033[0m')
    parser.add_argument('--region', default='all',
                        choices=vcfg.REGIONS + ['all'],
                        help='Region to process (default all)')
    parser.add_argument('--stage', default='all', choices=STAGES + ['all'],
                        help='Stage to run (default all)')
    parser.add_argument('--config', default=None,
                        help='Explicit region yaml (overrides --region)')
    parser.add_argument('--force', action='store_true',
                        help='Re-run mosaic3d even if the dump is current')
    parser.add_argument('--quiet', action='store_true')
    return parser.parse_args(argv)


def regionConfigs(args):
    if args.config is not None:
        return [vcfg.loadConfig(args.config)]
    regions = vcfg.REGIONS if args.region == 'all' else [args.region]
    return [vcfg.loadConfig(r) for r in regions]


def stageGps(cfg, verbose=True):
    stations, windows, coverage = gpsSeries.runGpsStage(cfg, verbose=verbose)
    figs = plots.gpsFigures(cfg, stations, windows, coverage)
    if verbose:
        for k, p in figs.items():
            print(f'  wrote {p}')
    return stations


def stageDump(cfg, force=False, verbose=True):
    from validationreports import pointMode
    return pointMode.runDumpStage(cfg, force=force, verbose=verbose)


def stageEval(cfg, verbose=True):
    from validationreports import requirements
    return requirements.runEvalStage(cfg, verbose=verbose)


def stageReport(cfgs, verbose=True):
    from validationreports import dashboard
    return dashboard.runReportStage(cfgs, verbose=verbose)


def main(argv=None):
    args = parseArgs(argv)
    verbose = not args.quiet
    cfgs = regionConfigs(args)
    stages = STAGES if args.stage == 'all' else [args.stage]
    for cfg in cfgs:
        vcfg.ensureDirs(cfg)
        if verbose:
            print(f"\n=== {cfg['label']} ({cfg['paths']['validationDir']}) ===")
        if 'gps' in stages:
            stageGps(cfg, verbose=verbose)
        if 'dump' in stages:
            stageDump(cfg, force=args.force, verbose=verbose)
        if 'eval' in stages:
            stageEval(cfg, verbose=verbose)
    if 'report' in stages:
        stageReport(cfgs, verbose=verbose)
    return 0


if __name__ == '__main__':
    sys.exit(main())
