"""Narrow reviewed transfer of observed PARAMETER VALUES, never lap comparisons."""
import json
from endurance.paths import ROOT


def parameter_review(meta, source_build, parameter):
    reviews = json.loads((ROOT / 'config' / 'parameter_compatibility.json').read_text(encoding='utf-8'))['reviews']
    return next((r for r in reviews if r['car'] == meta.get('car')
                 and r['from_build'] == source_build and r['to_build'] == meta.get('build')
                 and r['required_installed_car_component'] == meta.get('car_component_build')
                 and meta.get('car_component_source') and parameter in r['parameters']), None)


def source_review(meta, other, parameter):
    if not all(meta.get(k) and meta[k] != 'unknown' and meta[k] == other.get(k) for k in ('car', 'track_id', 'track')):
        return None
    review = parameter_review(meta, other.get('build'), parameter)
    if review:
        for path in review.get('matching_settings', {}).get(parameter, []):
            value = meta.get('setup_flat', {}).get(path)
            if value is None or value != other.get('setup_flat', {}).get(path):
                return None
    return review
