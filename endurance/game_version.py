"""Read installed simulator build without UI navigation or user input."""
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import re


def normalize_build(value):
    text = str(value).strip()
    match = re.fullmatch(r'(\d{4}\.\d{2}\.\d{2}\.\d{2})(?:\s+RELEASE)?', text, re.I)
    if not match:
        return None
    try:
        datetime.strptime(match[1][:10], '%Y.%m.%d')
    except ValueError:
        return None
    return match[1]


def service_directory(image_path):
    expanded = os.path.expandvars(str(image_path)).strip()
    match = re.fullmatch(r'"?(.+[\\/]iRacingService(?:64)?\.exe)"?(?:\s+.*)?', expanded, re.I)
    return Path(match[1]).parent if match else None


def installation_candidates():
    found = []
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Services\iRacingService') as key:
                root = service_directory(winreg.QueryValueEx(key, 'ImagePath')[0])
                if root:
                    found.append(root)
        except OSError:
            pass
        for subkey in (r'SOFTWARE\iRacing.com\iRacing', r'SOFTWARE\WOW6432Node\iRacing.com\iRacing'):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
                    for name in ('InstallDir', 'InstallPath'):
                        try:
                            value = winreg.QueryValueEx(key, name)[0]
                            if isinstance(value, str) and value:
                                found.append(Path(os.path.expandvars(value)))
                        except OSError:
                            pass
            except OSError:
                pass
    for name in ('ProgramFiles(x86)', 'ProgramFiles'):
        if os.environ.get(name):
            found.append(Path(os.environ[name]) / 'iRacing')
    return list(dict.fromkeys(found))


def read_installed_build(roots=None):
    """Use simulator's own version_system.txt, not UI/app or Windows FileVersion."""
    for root in installation_candidates() if roots is None else roots:
        path = Path(root) / 'version_system.txt'
        try:
            with path.open('rb') as f:
                raw = f.read(257)
            if len(raw) > 256:
                continue
            build = normalize_build(raw.decode('utf-8-sig'))
            if build:
                result = {'build': build, 'source': '本机 iRacing 安装版本', 'path': str(path),
                          'checked_at': datetime.now(timezone.utc).isoformat(), 'car_components': {}}
                component = Path(root) / 'cars' / 'ferrari296gt3' / 'version.txt'
                try:
                    with component.open('rb') as f:
                        component_raw = f.read(257)
                    component_build = normalize_build(component_raw.decode('utf-8-sig')) if len(component_raw) <= 256 else None
                    if component_build:
                        result['car_components']['ferrari296gt3'] = {'build': component_build, 'path': str(component)}
                except (OSError, UnicodeError):
                    pass
                return result
        except (OSError, UnicodeError):
            continue
    return None


def detect_current_build():
    installed = read_installed_build()
    if installed:
        return installed
    # Optional fallback only; file mode never needs a live setup or driving session.
    if os.environ.get('ENDURANCE_NO_LIVE') != '1':
        from endurance.live_setup import read_live_setup
        meta, _ = read_live_setup()
        build = normalize_build(meta.get('build')) if meta else None
        if build:
            return {'build': build, 'source': '运行中模拟器 SDK', 'path': '',
                    'checked_at': datetime.now(timezone.utc).isoformat()}
    return None


def resolve_file_build(meta, detected):
    result = deepcopy(meta)
    component = (detected or {}).get('car_components', {}).get(meta.get('car'), {})
    if normalize_build(component.get('build')) and meta.get('build') in ('unknown', (detected or {}).get('build')):
        result['car_component_build'] = component['build']
        result['car_component_source'] = component.get('path')
    if meta.get('build') and meta['build'] != 'unknown':
        # Known old versions are never silently relabelled as current.
        return result
    if meta.get('source_kind') not in {'setup_html', 'assistant_snapshot'}:
        return result
    result['file_build'] = meta.get('build', 'unknown')
    if detected and normalize_build(detected.get('build')):
        result.update(build=normalize_build(detected['build']), build_source=detected['source'],
                      build_detection=deepcopy(detected), build_assumption='未标版本的导出按当前安装版本使用（用户偏好）；不是文件自带版本证明')
    return result
