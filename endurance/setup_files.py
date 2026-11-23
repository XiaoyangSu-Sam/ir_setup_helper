"""Offline garage exports; parse text only, never execute uploaded HTML."""
from html.parser import HTMLParser
import hashlib
from pathlib import Path
import re

from endurance.paths import documents_dir
from endurance.snapshot_files import parse_snapshot

MANUAL = "https://s100.iracing.com/wp-content/uploads/2024/06/Ferrari-296-GT3-V4.pdf"
LIMIT = 2_000_000
PARSER_VERSION = 3


def clean_line(text):
    return re.sub(r"\s+", " ", text).strip()


def section_key(text):
    return clean_line(re.sub(r"[,/]", " ", text.rstrip(':'))).lower()


class ExportText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0
        self.heading_parts, self.headings, self.in_heading = [], set(), False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if not self.hidden and tag in {"h1", "h2", "h3"}:
            self.in_heading, self.heading_parts = True, []
        if not self.hidden and tag == 'br' and self.in_heading:
            self.heading_parts.append('\n')
        if not self.hidden and tag in {"br", "p", "div", "tr", "h1", "h2", "h3", "title"}:
            self.parts.append("\n")
        if not self.hidden and tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3"} and self.in_heading:
            self.headings.update(clean_line(s) for s in ''.join(self.heading_parts).splitlines())
            self.in_heading = False
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "tr", "h1", "h2", "h3", "title"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
            if self.in_heading:
                self.heading_parts.append(data)


def discover_exports(car):
    if car != Path(car).name or car in {".", ".."}:
        return []
    root = documents_dir() / "iRacing" / "setups" / car
    return sorted((p for p in root.rglob("*") if p.suffix.lower() in {".htm", ".html"}), key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []


def parse_export(payload, name, car, track_id, track):
    if not payload or len(payload) > LIMIT:
        raise ValueError("设置导出文件为空或超过 2 MB。")
    if Path(name).suffix.lower() not in {".htm", ".html"}:
        raise ValueError("请选择 Garage Export 导出的 .htm／.html；.sto 当前只能由游戏加载，助手尚不能解码其参数。")
    if payload[:2] in (b'\xff\xfe', b'\xfe\xff'):
        source = payload.decode("utf-16")
    else:
        try:
            source = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            source = payload.decode("cp1252")
    parser = ExportText()
    parser.feed(source)
    lines = [clean_line(line) for line in ''.join(parser.parts).splitlines()]
    lines = [line for line in lines if line]
    text = '\n'.join(lines)
    if car != "ferrari296gt3" or not re.search(r"Ferrari\s*296\s*GT3", '\n'.join(lines[:8]), re.I):
        raise ValueError("文件内未识别到 Ferrari 296 GT3，不能仅凭文件名套用车型规则。")
    # Preserve every field; map only unambiguous, section-scoped labels.
    sections = {"front": "FrontBrakesLights", "front brakes lights": "FrontBrakesLights",
                "rear": "Rear", "in-car dials": "InCarAdjustments", "in-car adjustments": "InCarAdjustments",
                "left front": "LeftFront", "right front": "RightFront", "left rear": "LeftRear", "right rear": "RightRear",
                "gears differential": "GearsDifferential", "aero balance calc": "AeroBalanceCalc"}
    fields = {"arb blades": "ArbBlades", "arb options": "ArbOptions", "total toe-in": "TotalToeIn", "rear wing angle": "RearWingAngle",
              "fuel level": "FuelLevel", "traction control setting": "TcSetting", "tc setting": "TcSetting", "ride height": "RideHeight",
              "spring rate": "SpringRate", "diff preload": "DiffPreload"}
    section, flat, raw = "", {}, []
    for line in lines:
        label = section_key(line)
        if label in sections:
            section = sections[label]
            continue
        if line in parser.headings:
            section = ''  # Never leak the previous wheel/axle into a new unknown heading.
        if label in {'notes', 'setup notes', 'tires', 'tires / aero', 'tires and aero', 'aero calculator'}:
            section = ''
        if ':' not in line:
            continue
        key, value = (s.strip() for s in line.split(':', 1))
        raw.append({"section": section, "label": key, "value": value})
        key = key.lower()
        if key in {"tire type", "tyre type"}:
            flat["TiresAero.TireType.TireType"] = value
        elif key in fields and section:
            path = f"TiresAero.AeroBalanceCalc.{fields[key]}" if section == 'AeroBalanceCalc' else f"Chassis.{section}.{fields[key]}"
            if key == 'arb blades':
                ordinal = re.fullmatch(r'\d+\s*\(([+-]?\d+(?:\.\d+)?)\s*(?:degrees|deg|°)\)', value, re.I)
                if ordinal:
                    value = ordinal[1] + ' degrees'
            if path in flat and flat[path] != value:
                raise ValueError(f"文件内 {key} 存在冲突数值，暂不生成方案。")
            flat[path] = value
    if not flat:
        raise ValueError("已识别车型，但没有识别到支持的参数字段；请使用 Garage 的 Export 原始文件。")
    build = re.search(r"(?:Build(?: Version)?|Game Version)\s*:\s*(\d{4}\.\d{2}\.\d{2}\.\d+)", text, re.I)
    exported_track = next((r['value'] for r in raw if r['label'].lower() in {'track', 'track name'}), '')
    # A generic setup has an intended track chosen in the app, not a claimed observed layout.
    if exported_track and exported_track.lower() not in {track.lower(), 'nürburgring gesamtstrecke vln', 'nurburgring gesamtstrecke vln', 'nürburgring combined - gesamtstrecke vln'}:
        raise ValueError(f"文件布局“{exported_track}”尚未匹配所选布局；保留文件，不跨布局套用建议。")
    return {"car": car, "track_id": track_id, "track": track, "build": build[1] if build else "unknown",
            "setup_flat": flat, "setup": {}, "source_name": Path(name).name, "source_kind": "setup_html",
            "context_source": "Garage 文件基准", "setup_scope": "导出文件中的参数；不证明当前车库、实际驾驶条件或 Tech 结果",
            "raw_fields": raw, "exported_track": exported_track,
            "track_context": "文件注明布局" if exported_track else "使用侧栏选择的目标布局；文件未注明适用布局",
            "planned_conditions": "dry", "observed_wetness": [], "official_verified": False,
            "official_status": "文件来源尚未独立鉴定；文件名不作为官方身份凭据",
            "file_hash": hashlib.sha256(payload).hexdigest(), "source_document": MANUAL,
            "parser_version": PARSER_VERSION}


def refresh_baseline(store, version):
    """Repair derived metadata from retained bytes without replacing the user's file/id."""
    old = version.get('meta', {})
    if version.get('kind') != 'file_baseline' or old.get('source_kind') != 'setup_html' or old.get('parser_version', 0) >= PARSER_VERSION:
        return version
    digest = version.get('file_hash', '')
    if not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('已存文件的校验标识异常，不能自动重读。')
    path = next((p for suffix in ('.htm', '.html') if (p := store.root / 'setup_exports' / (digest + suffix)).is_file()), None)
    if path is None:
        raise ValueError('保存的原始导出文件缺失，无法自动修复解析。')
    if path.stat().st_size > LIMIT:
        raise ValueError('保存的导出文件超过读取上限。')
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('保存的导出文件校验不符，未覆盖已有基准。')
    meta = parse_export(content, old['source_name'], version['car'], version['track_id'], version['track'])
    payload = {k: v for k, v in version.items() if k not in {'id', 'created_at'}}
    payload.update(meta=meta, setup=meta['setup'], setup_flat=meta['setup_flat'], build=meta['build'])
    store.refresh_file_baseline(version['id'], payload)
    return {**version, **payload}


def import_baseline(store, payload, name, car, track_id, track):
    """Persist an offline source without requiring a running simulator."""
    suffix = Path(name).suffix.lower()
    digest = hashlib.sha256(payload).hexdigest()
    if suffix == '.ibt':
        folder = store.root / 'uploads'
        folder.mkdir(exist_ok=True)
        path = folder / (digest + '.ibt')
        if not path.exists():
            path.write_bytes(payload)
        rid, _ = store.import_file(path, source_name=name)
        meta = store.record(rid)['meta']
        if (meta['car'], meta['track_id'], meta['track']) != (car, track_id, track):
            raise ValueError("记录已导入数据页，但车型或布局不同，未设为本次基准。")
        meta = {**meta, 'source_kind': 'historical_ibt'}
    else:
        parser = parse_snapshot if suffix == '.json' else parse_export
        meta = parser(payload, name, car, track_id, track)
        folder = store.root / 'setup_exports'
        folder.mkdir(exist_ok=True)
        path = folder / (digest + suffix)
        if not path.exists():
            path.write_bytes(payload)
    existing = next((v for v in store.versions(car, track_id) if v.get('file_hash') == digest and v.get('track') == track), None)
    if existing:
        existing = refresh_baseline(store, existing)
    identifier = existing['id'] if existing else store.save_version({
        'kind': 'file_baseline', 'name': Path(name).name, 'car': car, 'track_id': track_id, 'track': track,
        'build': meta['build'], 'meta': meta, 'setup': meta.get('setup', {}), 'setup_flat': meta['setup_flat'],
        'file_hash': digest, 'locally_validated': False, 'validation_level': '文件基准／个人适配未验证', 'parent_id': None})
    store.set_setting(f'file_baseline:{car}:{track_id}:{track}', identifier)
    return identifier
