"""Match recorded setup snapshots to a saved trial and find comparable runs."""
import re

from endurance.analysis import compatibility
from endurance.automatic import same_context
from endurance.rules import parameter_number
from endurance.ibt import is_simulated


# These values describe a measurement, the setup editor, or the aero calculator.
# Keep fuel, starting pressures, springs, ARB specifications and unknown fields.
SNAPSHOT_ONLY = re.compile(
    r"UpdateCount|TiresAero\.AeroBalanceCalc\..+|"
    r"TiresAero\.(LeftFront|RightFront|LeftRear|RightRear)\.(LastHotPressure|LastTempsOMI|LastTempsIMO|TreadRemaining)(?:\..+)?|"
    r"Chassis\.(LeftFront|RightFront|LeftRear|RightRear)\.(CornerWeight|RideHeight)|"
    r"Chassis\.FrontBrakesLights\.CenterFrontSplitterHeight|Chassis\.InCarAdjustments\.(FWtdist|CrossWeight)"
)


def snapshot_values(settings):
    return {key: value for key, value in settings.items() if not SNAPSHOT_ONLY.fullmatch(key)}


def same_value(a, b):
    if a == b:
        return True
    # A display precision change (104.0 L vs 104 L) is not a setting change.
    pattern = r"\s*([+-]?\d+(?:\.\d+)?)\s*(\S.*)?"
    ma, mb = re.fullmatch(pattern, str(a)), re.fullmatch(pattern, str(b))
    return bool(ma and mb and float(ma[1]) == float(mb[1]) and (ma[2] or '').lower() == (mb[2] or '').lower())


def snapshot_differences(expected, actual, parameter_path, *, partial=False):
    a, b = snapshot_values(expected), snapshot_values(actual)
    keys = a.keys() if partial else a.keys() | b.keys()
    return sorted(key for key in keys if key != parameter_path and not same_value(a.get(key), b.get(key)))


def trial_role(plan, record):
    """The export constrains its recorded fields only. Missing fields are not matches."""
    meta = record['meta']
    if not same_context(plan, meta):
        return None
    settings = meta.get('setup_flat', {})
    key = plan['parameter_path']
    value = parameter_number(settings.get(key), plan['parameter'])
    if snapshot_differences(plan['baseline_setup'], settings, key, partial=True):
        return None
    if value == plan['current']:
        return 'before'
    created = plan.get('created_at')
    if value == plan['target'] and created and meta.get('start_utc', '') > created:
        return 'after'
    return None


def trial_defaults(plan, records):
    """Prefer a matching pair. Keep whole runs and order them by real recording time."""
    matches = {'before': [], 'after': []}
    for record in sorted(records, key=lambda r: r['meta'].get('start_utc', ''), reverse=True):
        role = trial_role(plan, record)
        if role:
            matches[role].append(record)
    for after in matches['after']:
        for before in matches['before']:
            if before['meta']['start_utc'] >= after['meta']['start_utc']:
                continue
            if compatibility(before['meta'], after['meta']):
                continue
            if is_simulated(before['meta']) != is_simulated(after['meta']):
                continue
            if snapshot_differences(before['meta']['setup_flat'], after['meta']['setup_flat'], plan['parameter_path']):
                continue
            return before, after
    # Keep a single side as a starting point, but don't preselect an incompatible pair.
    if matches['before']:
        return matches['before'][0], None
    return None, next(iter(matches['after']), None)
