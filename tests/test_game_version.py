from pathlib import Path
import pytest

from endurance.game_version import (normalize_build, service_directory, read_installed_build,
                                    detect_current_build, resolve_file_build)
from endurance.automatic import settings_fingerprint


def test_service_locator_and_build_validation():
    assert service_directory(r'"E:\iRacing\iRacingService64.exe" --service') == Path('E:/iRacing')
    assert service_directory('not a service') is None
    assert normalize_build('2026.11.02.01 RELEASE') == '2026.11.02.01'
    for invalid in ('latest', '2.61.5.31', '2026.99.02.01', '2026.11.02.01 junk'):
        assert normalize_build(invalid) is None


def test_install_file_update_and_invalid_sources(tmp_path):
    source = tmp_path / 'version_system.txt'
    assert read_installed_build([tmp_path]) is None
    source.write_text('2026.11.02.01\n', encoding='utf-8-sig')
    assert read_installed_build([tmp_path])['build'] == '2026.11.02.01'
    source.write_text('2026.11.10.01')
    assert read_installed_build([tmp_path])['build'] == '2026.11.10.01'
    for invalid in ('latest', 'a' * 257, '2026.99.01.01'):
        source.write_text(invalid)
        assert read_installed_build([tmp_path]) is None


def test_installed_source_does_not_need_running_game(monkeypatch):
    def unexpected():
        raise AssertionError('SDK should not be needed')
    monkeypatch.setattr('endurance.live_setup.read_live_setup', unexpected)
    monkeypatch.setattr('endurance.game_version.read_installed_build', lambda: {'build': '2026.11.02.01', 'source': 'install'})
    assert detect_current_build()['build'] == '2026.11.02.01'


def test_sdk_fallback_and_no_invented_version(monkeypatch):
    monkeypatch.delenv('ENDURANCE_NO_LIVE', raising=False)
    monkeypatch.setattr('endurance.game_version.read_installed_build', lambda: None)
    monkeypatch.setattr('endurance.live_setup.read_live_setup', lambda: ({'build': '2026.11.02.01'}, 'connected'))
    assert detect_current_build()['source'] == '运行中模拟器 SDK'
    monkeypatch.setattr('endurance.live_setup.read_live_setup', lambda: (None, 'offline'))
    assert detect_current_build() is None


def test_current_build_assumption_keeps_file_provenance_and_known_versions():
    unknown = {'build': 'unknown', 'source_kind': 'setup_html', 'setup_flat': {}}
    detected = {'build': '2026.11.02.01', 'source': 'install'}
    meta = resolve_file_build(unknown, detected)
    assert meta['build'] == detected['build'] and meta['file_build'] == 'unknown'
    assert '用户偏好' in meta['build_assumption']
    assert unknown['build'] == 'unknown'
    old = {**unknown, 'build': '2026.10.01.01'}
    assert resolve_file_build(old, detected)['build'] == old['build']
    assert resolve_file_build({**unknown, 'source_kind': 'historical_ibt'}, detected)['build'] == 'unknown'
    updated = resolve_file_build(unknown, {**detected, 'build': '2026.11.10.01'})
    assert settings_fingerprint(meta) != settings_fingerprint(updated)
