"""Region configuration for the validation pipeline.

A region config (config/greenland.yaml, config/antarctica.yaml) names the project
directory, the master mosaic3d input, the GPS parquet directory, the station groups
for the point-mode runs, and the requirement thresholds. loadConfig resolves the
relative paths against projectDir and returns a plain dict.
"""
import os
import yaml

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIONS = ['greenland', 'antarctica']


def configPath(region):
    '''Path of the packaged config for a region name.'''
    return os.path.join(CONFIG_DIR, f'{region}.yaml')


def loadConfig(regionOrPath):
    '''Load a region config by name or explicit yaml path and resolve paths.'''
    path = regionOrPath if regionOrPath.endswith('.yaml') \
        else configPath(regionOrPath)
    with open(path) as fp:
        cfg = yaml.safe_load(fp)
    projectDir = cfg['projectDir']

    def resolve(p):
        return p if os.path.isabs(p) else os.path.join(projectDir, p)
    cfg['paths'] = {
        'masterInput': resolve(cfg['masterInput']),
        'gpsDir': resolve(cfg['gpsDir']),
        'validationDir': resolve(cfg['validationDir']),
    }
    v = cfg['paths']['validationDir']
    for sub in ['gps', 'pointMode', 'results', 'figures']:
        cfg['paths'][sub] = os.path.join(v, sub)
    cfg['configFile'] = path
    return cfg


def ensureDirs(cfg):
    '''Create the validation directory tree (idempotent).'''
    for key in ['validationDir', 'gps', 'pointMode', 'results', 'figures']:
        os.makedirs(cfg['paths'][key], exist_ok=True)


def stationNames(cfg):
    '''All stations named in the config groups, in group order.'''
    names = []
    for group in cfg['groups']:
        names.extend(group['stations'])
    return names
