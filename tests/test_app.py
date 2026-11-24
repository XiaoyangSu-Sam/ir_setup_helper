from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from endurance.storage import Store


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ENDURANCE_NO_LIVE", "1")
    monkeypatch.setenv("ENDURANCE_NO_WATCHER", "1")
    from endurance.ui_guidance import current_game_setup
    current_game_setup.clear()
    monkeypatch.setattr('endurance.ui_baseline.current_installation', lambda: {'build': '2026.11.02.01', 'source': '测试安装版本', 'path': 'test/version_system.txt'})


def open_app(root, monkeypatch):
    monkeypatch.setenv("ENDURANCE_DATA_DIR", str(root))
    return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()


def test_source_edition_can_open_registration_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr("endurance.ui_tools.registration_exe", lambda: tmp_path / "missing" / "NativeBridge.exe")
    app = open_app(tmp_path / "data", monkeypatch)
    next(widget for widget in app.radio if widget.key == "workspace_page").set_value("赛事报名").run()
    assert not app.exception
    assert any(title.value == "赛事报名" for title in app.title)
    assert any("安装 Windows 合装版" in note.value for note in app.info)
    assert any("当前 源码版" in note.value for note in app.caption)


def no_engineering_form(app):
    labels = [w.label for kind in (app.text_input, app.checkbox, app.selectbox) for w in kind]
    for forbidden in ("最小值", "最大值", "每档步长", "完整可选值", "Passed Tech", "实际参数值", "本次 Tech", "我已核实", "这份设置的游戏版本"):
        assert not any(forbidden in label for label in labels), labels


def test_candidate_download_reimports_through_uploader(make_ibt, tmp_path, monkeypatch):
    import json
    import streamlit as st

    from endurance.setup_files import parse_export

    source = (Path(__file__).parent / "fixtures" / "ferrari296_real_export.htm").read_bytes()
    root = tmp_path / "export-source"
    db = Store(root)
    db.import_file(make_ibt(front_arb=30, build="2026.11.02.01"))
    db.close()
    app = open_app(root, monkeypatch)
    uploaded = next(w for w in app.file_uploader if ".json" in w.allowed_type)
    uploaded.upload("ir_suggest.htm", source, "text/html").run()
    next(b for b in app.button if b.label == "导入并用作基准").click().run()
    next(t for t in app.text_area if t.label == "保留我的原话").set_value("入弯推头").run()
    downloads = {}
    original = st.download_button

    def capture(label, data, *args, **kwargs):
        if kwargs.get("file_name") == "setup-candidate.json":
            downloads["candidate"] = data
        return original(label, data, *args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    next(b for b in app.button if b.label == "给我一个调整方案").click().run()
    assert not app.exception, app.exception
    assert any(b.proto.label == "下载可重新导入的设置快照" for b in app.download_button)
    exported = json.loads(downloads["candidate"])
    baseline = parse_export(source, "ir_suggest.htm", exported["car"], exported["track_id"], exported["track"])
    expected = {**baseline["setup_flat"], "Chassis.FrontBrakesLights.ArbBlades": "30 degrees"}
    assert exported["setup_flat"] == expected

    destination = tmp_path / "clean-import"
    clean = open_app(destination, monkeypatch)
    next(w for w in clean.file_uploader if ".json" in w.allowed_type).upload(
        "setup-candidate.json", downloads["candidate"], "application/json"
    ).run()
    next(b for b in clean.button if b.label == "导入并用作基准").click().run()
    assert not clean.exception, clean.exception
    assert any("已读取助手快照" in c.value for c in clean.caption)
    db = Store(destination)
    version, = db.versions()
    assert version["setup_flat"] == expected and version["build"] == "2026.11.02.01"
    assert version["meta"]["adjustment"]["before"] == "45 degrees"
    assert not version["locally_validated"] and not db.list_records()
    db.close()


def test_trial_page_compares_matching_runs_without_manual_selection(make_ibt, tmp_path, monkeypatch):
    from endurance.adjustment import fingerprint
    from endurance.automatic import automatic_plan
    from endurance.rules import load_rules

    root = tmp_path / "automatic-trial-ui"
    db = Store(root)
    before, _ = db.import_file(make_ibt(front_arb=45))
    after, _ = db.import_file(make_ibt(name="faster.ibt", lap_seconds=58, front_arb=30, epoch=1893457000))
    plan = automatic_plan(db.record(before)["meta"], load_rules()["rules"][0], db.list_records())
    plan["created_at"] = "2026-01-01T00:00:00+00:00"
    plan["fingerprint"] = fingerprint(plan)
    db.save_experiment({"workflow_version": 4, "numeric_plan": plan, "tech_status": plan["tech_status"],
                        "status": "文件草案", "car": plan["car"], "track_id": plan["track_id"], "before_records": [],
                        "recommendation": {"symptom": "入弯推头", "corner": "", "feeling": "", "parameter": plan["parameter"],
                                           "current": 45, "direction": "降低前防倾杆角度", "verification": "试跑观察"}})
    db.close()

    app = open_app(root, monkeypatch)
    next(r for r in app.radio if r.label == "工作区").set_value("试跑验证").run()
    assert not app.exception
    assert any("已自动配对" in entry.value for entry in app.success)
    assert next(m for m in app.multiselect if m.label == "调整前驾驶段").value == [f"{before}:1"]
    assert next(m for m in app.multiselect if m.label == "调整后驾驶段").value == [f"{after}:1"]
    assert next(m for m in app.metric if m.label == "可比条件下，代表圈速变化").value == "-2.00 秒／圈"
    next(b for b in app.button if b.label == "保存本次数据对比").click().run()
    assert not app.exception
    db = Store(root)
    saved = db.experiments()[0]
    assert saved["result"]["groups"][0]["delta_s"] == -2
    assert saved["status"] == "证据不足" and saved["tech_status"] == "未接通游戏检查结果"
    db.close()


def test_empty_library_is_usable(tmp_path, monkeypatch):
    app = open_app(tmp_path / "empty", monkeypatch)
    assert not app.exception
    assert next(r for r in app.radio if r.label == "推荐依据").value == "凭感觉"
    assert any("还没有读到设置" in w.value for w in app.info)
    no_engineering_form(app)
    for page in ("驾驶记录", "弯道与参考圈", "试跑验证", "设置档案", "参数与搭配"):
        next(r for r in app.radio if r.label == "工作区").set_value(page).run()
        assert not app.exception
        no_engineering_form(app)


def test_feeling_plan_automatically_reads_settings_and_feedback(make_ibt, tmp_path, monkeypatch):
    root = tmp_path / "feelings"
    db = Store(root)
    before, _ = db.import_file(make_ibt(front_arb=45))
    db.import_file(make_ibt(name="after.ibt", front_arb=30))
    db.close()
    app = open_app(root, monkeypatch)
    next(s for s in app.selectbox if s.label == "当前驾驶记录").set_value(before).run()
    next(t for t in app.text_area if t.label == "保留我的原话").set_value("弯中推头").run()
    next(b for b in app.button if b.label == "给我一个调整方案").click().run()
    assert not app.exception
    assert any("45 → 30 deg" in m.value for m in app.markdown)
    no_engineering_form(app)
    next(b for b in app.button if b.label == "保存这个方案").click().run()
    assert not app.exception
    next(r for r in app.radio if r.label == "工作区").set_value("试跑验证").run()
    no_engineering_form(app)
    next(s for s in app.selectbox if s.label == "这次主观感觉").set_value("感觉改善")
    next(b for b in app.button if b.label == "保存手感反馈").click().run()
    assert not app.exception
    db = Store(root)
    exp = db.experiments()[0]
    assert exp["before_records"] == [] and exp["mode"] == "凭感觉"
    assert exp["subjective_status"] == "感觉改善"
    assert exp["tech_status"] == "未接通游戏检查结果"
    assert not db.versions()
    db.close()


def test_tool_owns_missing_parameter_knowledge(make_ibt, tmp_path, monkeypatch):
    root = tmp_path / "incomplete"
    db = Store(root)
    db.import_file(make_ibt(front_arb=30))
    db.close()
    app = open_app(root, monkeypatch)
    next(t for t in app.text_area if t.label == "保留我的原话").set_value("弯中推头").run()
    next(b for b in app.button if b.label == "给我一个调整方案").click().run()
    assert not app.exception
    assert any("无需你操作" in w.value for w in app.warning)
    assert not any(b.label == "保存这个方案" for b in app.button)
    no_engineering_form(app)


def test_changing_problem_invalidates_draft(make_ibt, tmp_path, monkeypatch):
    root = tmp_path / "invalidate"
    db = Store(root)
    before, _ = db.import_file(make_ibt(front_arb=45))
    db.import_file(make_ibt(name="after.ibt", front_arb=30))
    db.close()
    app = open_app(root, monkeypatch)
    next(s for s in app.selectbox if s.label == "当前驾驶记录").set_value(before).run()
    next(t for t in app.text_area if t.label == "保留我的原话").set_value("弯中推头").run()
    next(b for b in app.button if b.label == "给我一个调整方案").click().run()
    assert any(b.label == "保存这个方案" for b in app.button)
    next(t for t in app.text_area if t.label == "保留我的原话").set_value("高速车尾滑").run()
    assert not app.exception
    assert not any(b.label == "保存这个方案" for b in app.button)


def test_uploaded_baseline_never_requires_live_game(make_ibt, tmp_path, monkeypatch):
    from endurance.setup_files import import_baseline
    root = tmp_path / 'offline-file-ui'
    db = Store(root)
    db.import_file(make_ibt(front_arb=30, build='2026.11.02.01'))
    content = b'<html><title>Ferrari 296 GT3 setup</title><h2>FRONT:</h2>ARB blades: 45 degrees<br></html>'
    import_baseline(db, content, 'official-endurance.htm', 'ferrari296gt3', '262', 'nurburgring combinedshortb')
    db.close()
    def no_live():
        raise AssertionError('File mode must never request the simulator')
    monkeypatch.setattr('endurance.ui_guidance.current_game_setup', no_live)
    app = open_app(root, monkeypatch)
    assert not app.exception
    assert next(r for r in app.radio if r.label == '设置来源').value == '文件基准（无需启动游戏）'
    assert any('已读取文件基准' in x.value for x in app.success)
    assert not any('未连接游戏' in x.value for x in app.info)
    assert any('已自动识别游戏版本：2026.11.02.01' in x.value for x in app.caption)
    next(t for t in app.text_area if t.label == '保留我的原话').set_value('弯中推头').run()
    next(b for b in app.button if b.label == '给我一个调整方案').click().run()
    assert not app.exception
    assert any('45 → 30 deg' in m.value for m in app.markdown)
    no_engineering_form(app)


def test_existing_real_export_is_repaired_without_reupload(make_ibt, tmp_path, monkeypatch):
    from copy import deepcopy
    from endurance.setup_files import import_baseline
    root = tmp_path / 'existing-export-ui'
    db = Store(root)
    db.import_file(make_ibt(front_arb=30, build='2026.11.02.01'))
    content = (Path(__file__).parent / 'fixtures' / 'ferrari296_real_export.htm').read_bytes()
    rid = import_baseline(db, content, 'ir_suggest.htm', 'ferrari296gt3', '262', 'nurburgring combinedshortb')
    broken = deepcopy(db.versions()[0])
    broken['meta'].pop('parser_version')
    broken['meta']['setup_flat'].pop('Chassis.FrontBrakesLights.ArbBlades')
    broken['setup_flat'] = broken['meta']['setup_flat']
    db.refresh_file_baseline(rid, {k: v for k, v in broken.items() if k not in {'id', 'created_at'}})
    db.close()

    app = open_app(root, monkeypatch)
    next(t for t in app.text_area if t.label == '保留我的原话').set_value('弯中推头').run()
    next(b for b in app.button if b.label == '给我一个调整方案').click().run()
    assert not any('没有这个参数' in w.value for w in app.warning)
    assert not app.exception
    assert any('45 → 30 deg' in m.value for m in app.markdown)
    db = Store(root)
    assert len(db.versions()) == 1 and db.versions()[0]['id'] == rid
    assert db.versions()[0]['meta']['parser_version'] == 3
    db.close()


def test_reviewed_historical_candidate_can_be_saved_with_honest_status(make_ibt, tmp_path, monkeypatch):
    from endurance.setup_files import import_baseline
    root = tmp_path / 'reviewed-candidate-ui'
    db = Store(root)
    db.import_file(make_ibt(front_arb=30, build='2026.10.01.01'))
    content = (Path(__file__).parent / 'fixtures' / 'ferrari296_real_export.htm').read_bytes()
    import_baseline(db, content, 'ir_suggest.htm', 'ferrari296gt3', '262', 'nurburgring combinedshortb')
    db.close()
    monkeypatch.setattr('endurance.ui_baseline.current_installation', lambda: {
        'build': '2026.11.02.01', 'source': '测试安装版本', 'car_components': {
            'ferrari296gt3': {'build': '2026.09.25.02', 'path': 'cars/ferrari296gt3/version.txt'}}})
    app = open_app(root, monkeypatch)
    next(t for t in app.text_area if t.label == '保留我的原话').set_value('带着速度入弯都会推头').run()
    assert any('本轮要解决：入弯推头' in c.value for c in app.caption)
    next(b for b in app.button if b.label == '给我一个调整方案').click().run()
    assert not app.exception
    assert any('45 → 30 deg' in m.value for m in app.markdown)
    assert any('历史参数经过兼容性复核' in m.value for m in app.info)
    next(b for b in app.button if b.label == '保存这个方案').click().run()
    assert not app.exception
    db = Store(root)
    exp = db.experiments()[0]
    assert exp['numeric_plan']['parameter_evidence'] == 'reviewed_transfer'
    assert exp['tech_status'] == '未接通游戏检查结果'
    db.close()
