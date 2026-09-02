"""NISAR 12-day cycle bookkeeping and date conversions.

Cycle 1 started 2025-09-23 (mosaicworkflow.makeimagemosaics.NISAR_CYCLE_EPOCH);
cycle k covers [epoch + 12(k-1) d, epoch + 12k d). Frame directories are named
<absoluteOrbit>_<frame>; orbit = 173*cycle + track + 618
(nisargrimpworkflow.FileNISARProducts.orbitFromCycleTrack).
"""
import re
from datetime import datetime, timedelta

import numpy as np

try:
    from mosaicworkflow.makeimagemosaics import NISAR_CYCLE_EPOCH
except Exception:  # keep this package importable without mosaicworkflow
    NISAR_CYCLE_EPOCH = datetime(2025, 9, 23)

CYCLE_DAYS = 12
ORBITS_PER_CYCLE = 173
ORBIT_OFFSET = 618
MJD_EPOCH = datetime(1858, 11, 17)
MJD_OFFSET = 2400000.5


def cycleStart(cycle):
    '''Datetime at which a 1-based cycle starts.'''
    return NISAR_CYCLE_EPOCH + timedelta(days=(cycle - 1) * CYCLE_DAYS)


def cycleDates(cycle):
    '''(start, end) datetimes of a cycle; end is exclusive (= next start).'''
    start = cycleStart(cycle)
    return start, start + timedelta(days=CYCLE_DAYS)


def cycleOfDate(date):
    '''1-based cycle containing a datetime (vectorised over arrays).'''
    if isinstance(date, (list, np.ndarray)):
        days = np.array([(d - NISAR_CYCLE_EPOCH).total_seconds() / 86400.
                         for d in date])
        return (np.floor(days / CYCLE_DAYS) + 1).astype(int)
    days = (date - NISAR_CYCLE_EPOCH).total_seconds() / 86400.
    return int(np.floor(days / CYCLE_DAYS)) + 1


def julDayToDatetime(julDay):
    '''Fractional Julian day (as written by mosaic3d) to datetime.'''
    return MJD_EPOCH + timedelta(days=julDay - MJD_OFFSET)


def datetimeToJulDay(date):
    '''Datetime to fractional Julian day.'''
    return (date - MJD_EPOCH).total_seconds() / 86400. + MJD_OFFSET


def cycleFromOrbit(orbit, track):
    '''Cycle number from absolute orbit and track number.'''
    return (orbit - track - ORBIT_OFFSET) // ORBITS_PER_CYCLE


_frameRe = re.compile(r'track-(\d+)/(\d+)_(\d+)')


def trackFrameFromPath(path):
    '''(track, orbit, frame) parsed from a product path, or None.'''
    m = _frameRe.search(path)
    if m is None:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def masterCycles(masterInput):
    '''Sorted cycles present in a mosaic3d master input file.'''
    cycles = set()
    with open(masterInput) as fp:
        for line in fp:
            if line.startswith(';') or len(line.split()) < 5:
                continue
            parsed = trackFrameFromPath(line.split()[0])
            if parsed is None:
                continue
            track, orbit, _ = parsed
            cycles.add(int(cycleFromOrbit(orbit, track)))
    return sorted(cycles)
