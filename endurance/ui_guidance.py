"""Feeling, telemetry and combined guidance; all three share evidence boundaries."""
from __future__ import annotations

import streamlit as st

from endurance.analysis import pace_summary
from endurance.knowledge import (compare_examples, knowledge, suggest_symptoms)
from endurance.rules import load_rules, recommend, trial_guide
from endurance.automatic import automatic_plan, choose_setup, settings_fingerprint
from endurance.live_setup import read_live_setup
from endurance.ui_baseline import file_baseline
from endurance.snapshot_files import export_candidate
import os
import hashlib
import json


@st.cache_data(ttl=2, show_spinner=False)
def current_game_setup():
    if os.environ.get("ENDURANCE_NO_LIVE") == "1":
        return None, "测试环境未连接模拟器"
    return read_live_setup()


def trial_lines(guide, mode):
    details = [("主测弯段", guide["primary"]), ("复核弯段", guide["cross_check"]),
               ("驾驶时留意", guide["observe"]), ("怎样选回自己的设置", guide["decision"])]
    if mode != "凭感觉":
        details.append(("有遥测时", guide["with_data"]))
    return details


def render_trial_guide(guide, mode, *, expanded=False):
    with st.expander("试跑指南 · 在哪试、怎么判断", expanded=expanded):
        if guide["reported_corner"]:
            st.text("你反馈的位置 · " + guide["reported_corner"])
            st.caption("如果那里能稳定复现，也可以用相同方法复测。")
        for label, advice in trial_lines(guide, mode):
            st.markdown(f"**{label}** · {advice}")
        st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(guide["steps"], start=1)))
        st.markdown(" · ".join(f"[{label}]({url})" for label, url in guide["sources"]))


def render_guidance(store, current, car, track, profile, mode):
    st.subheader("说说哪里不好开")
    feeling = st.text_area("保留我的原话", value=profile.get("feeling", ""),
                           placeholder="例如：带着速度转弯时车头总往外跑；或一给油车尾就滑。", height=90)
    hints = suggest_symptoms(feeling)
    plain = {"入弯时车头往外推": "入弯推头", "弯中车头往外推": "弯中推头", "刚转方向时反应慢": "入弯迟钝", "给油后车尾滑": "出弯不稳",
             "高速弯车头往外推": "高速推头", "高速弯车尾不稳": "高速车尾不稳", "高速不放心，说不清": "高速不放心"}
    selected = st.selectbox("最像哪一种（也可以只写上面的感受）", ["按我的描述判断"] + list(plain))
    symptom = plain.get(selected) or (hints[0] if len(hints) == 1 else None)
    if len(hints) > 1 and selected == "按我的描述判断":
        st.info("描述中有多个问题，先选这次最想解决的一项。")
    corner = st.text_input("发生在哪（可留空）", placeholder="弯名、快弯、连续弯都可以")
    config = load_rules()
    rule = next((r for r in config["rules"] if symptom in r["symptoms"]), None)
    source_mode = st.radio("设置来源", ["文件基准（无需启动游戏）", "游戏实时读取（可选）"], horizontal=True)
    if source_mode == "文件基准（无需启动游戏）":
        meta, source = file_baseline(store, current, car, track)
    else:
        live, connection = current_game_setup()
        meta, source = choose_setup(live, None, car, track)
        if st.button("重新读取游戏设置"):
            current_game_setup.clear()
            st.rerun()
        if meta is None:
            st.info(connection + "；也可以切换到文件基准，离线使用。")
        else:
            st.success("已读取游戏设置；车型、布局和版本已识别。")
    if meta is None:
        if rule and car == config["car"] and str(track[0]) == config["track_id"]:
            render_trial_guide(trial_guide(config, rule, corner), mode, expanded=True)
        return
    if source == "file":
        st.success(f"已读取文件基准：{meta.get('source_name', '设置快照')}。可离线使用。")
        if meta.get('source_kind') == 'historical_ibt':
            st.caption("使用记录中的设置快照作为起点，不代表当前车库，也未将它自动认定为官方设置。")
        else:
            st.caption(meta['track_context'] + "。按干地计划分析，不代表实际路面观测。")
    st.caption("凭感觉模式只使用设置快照，不要求你分析驾驶曲线。" if mode == "凭感觉" else "工具会同时查看设置与驾驶记录。")
    if not symptom:
        st.info("写下哪里不好开，或选择上面的现象。没有具体问题时，可以先保留官方基准试跑。")
        return
    st.caption("本轮要解决：" + symptom)
    facts = []
    before_ids = []
    if current and mode != "凭感觉":
        summary = pace_summary(current["laps"])
        facts = [f"所选历史记录有 {summary['valid']} 个有效完整圈、{summary['errors']} 个含失误片段；不代表当前车库设置的表现。"]
        before_ids = [current["id"]] if settings_fingerprint(meta) == settings_fingerprint(current['meta']) else []
        last = st.session_state.get("analysis_facts", {})
        if last.get("record_id") == current["id"] and last.get("corner") == corner:
            facts += last.get("facts", [])
    rec = recommend(meta, symptom, feeling, corner, facts=facts, mode=mode)
    if not rec["available"]:
        st.info(rec["reason"])
        return
    guide = rec["trial_guide"]
    if rule["sign"]:
        st.caption("试跑主测 · " + guide["primary"])
    render_trial_guide(guide, mode, expanded=not rule["sign"])
    if not rule["sign"]:
        st.info("先按指南跑官方基准，确认是哪种手感，再选对应的问题生成数值方案。")
        return
    signature = hashlib.sha256(json.dumps([settings_fingerprint(meta), symptom, feeling, corner, mode], ensure_ascii=False).encode()).hexdigest()
    key = "automatic_draft"
    if st.session_state.get(key, {}).get("signature") != signature:
        st.session_state.pop(key, None)
    if st.button("给我一个调整方案", type="primary", width="stretch"):
        st.session_state[key] = {"signature": signature, "plan": automatic_plan(meta, rule, store.list_records())}
    state = st.session_state.get(key)
    if not state:
        return
    plan = state["plan"]
    if not plan["ready"]:
        st.warning(plan["reason"])
        if plan.get('detail'):
            with st.expander('查看工具诊断'):
                st.caption(plan['detail'])
        return
    rec.update(current=plan["current"], target=plan["target"], build=plan["build"], numeric_plan_fingerprint=plan["fingerprint"],
               numeric_note='目标值有可追溯参数来源；未验证当前效果或整车 Tech', parameter_evidence=plan.get('parameter_evidence', 'same_build'))
    with st.container(border=True):
        st.markdown(f"### {plan['parameter']}：{plan['current']:g} → {plan['target']:g} {plan['unit']}")
        st.write(f"**目标输入值：`{plan['target']:g}` {plan['unit']}**")
        st.write("本次只动这一项。回退时：" + plan["rollback"])
        st.write("**预期变化：** " + rec['mechanism'])
        st.write("**可能的代价：** " + rec['risk'])
        st.write("**你试跑时留意：** " + rec["verification"])
        st.caption("已核对数值来源、单位与试调幅度。整车安全检查尚未自动接通，不能标为通过。")
        if plan.get('parameter_evidence') == 'reviewed_transfer':
            st.info('这是试调候选：历史参数经过兼容性复核，但当前版本的效果尚未验证。')
        if source == "file":
            st.caption("这是对所选文件基准的调整草案；应用时从这份基准出发。离线生成无需连接游戏。")
        with st.expander("为什么这样改，以及工具检查了什么"):
            st.write(rec["hypothesis"])
            st.write("可能的代价：" + rec["risk"])
            for check in plan["checks"]:
                st.write("• " + check)
            for evidence in plan['evidence']:
                if evidence.get('review_id'):
                    st.caption(evidence['compatibility_basis'])
                    st.caption(evidence['limitation'])
                    st.markdown(f"[本次版本兼容复核依据]({evidence['review_source']})")
                    break
            st.dataframe([{'参数值来源': e['source_name'], '记录版本': e['build'], '目标值': plan['target']} for e in plan['evidence']], hide_index=True)
            st.caption("实际出现过不等于完整合法范围；未推断不存在于资料中的新档位，也不声称是一档。")
            st.markdown(f"[官方作用说明 · 第 {rec['source_page']} 页]({rec['source']}#page={rec['source_page']})")
            for relation in rec["interactions"]:
                st.write(relation["name"] + "：" + relation["workflow"])
            for fact in facts:
                st.write(fact)
        card = (f"基准：{plan['baseline_name']}\n目标游戏版本：{plan['build']}\n"
                f"调整：{plan['parameter']} {plan['current']:g} → {plan['target']:g} {plan['unit']}\n"
                f"其他参数保持基准。\n回退：{plan['rollback']}\n观察：{rec['verification']}\n"
                "状态：试调候选；当前效果未验证；游戏 Tech 结果未自动接通。\n")
        card += "\n试跑指南\n"
        if guide["reported_corner"]:
            card += "你反馈的位置 · " + guide["reported_corner"] + "\n"
        card += "\n".join(f"{label} · {advice}" for label, advice in trial_lines(guide, mode)) + "\n"
        card += "\n".join(f"{i}. {step}" for i, step in enumerate(guide["steps"], start=1)) + "\n"
        card += "\n".join(f"{label} · {url}" for label, url in guide["sources"]) + "\n"
        st.download_button('下载本轮调整卡', card, file_name='setup-experiment.txt', mime='text/plain')
        try:
            snapshot = export_candidate(meta, plan)
        except (ValueError, TypeError) as exc:
            st.error(f"无法导出设置快照。{exc}")
        else:
            st.download_button('下载可重新导入的设置快照', snapshot,
                               file_name='setup-candidate.json', mime='application/json')
            st.caption("把 JSON 上传回工作台可恢复试调参数。要在 iRacing 加载，请在 Garage 应用调整并另存为 .sto。")
    if st.button("保存这个方案"):
        from endurance.storage import now
        saved_plan = dict(plan)
        saved_plan["created_at"] = now()
        from endurance.adjustment import fingerprint
        saved_plan["fingerprint"] = fingerprint(saved_plan)
        rec["numeric_plan_fingerprint"] = saved_plan["fingerprint"]
        store.save_experiment({"recommendation": rec, "before_records": before_ids, "car": car, "track_id": track[0],
                               "profile": store.get_setting("profile", profile), "status": "文件草案" if source == "file" else "待应用",
                               "mode": mode, "baseline_name": plan["baseline_name"], "workflow_version": 4, "numeric_plan": saved_plan,
                               "tech_status": "未接通游戏检查结果"})
        store.set_setting("profile", {**store.get_setting("profile", profile), "symptom": symptom, "feeling": feeling})
        st.success("已保存。之后只需记录好开了还是更难开；新记录出现后，工具会继续核对。")
        st.button("打开试跑验证", on_click=lambda: st.session_state.update(workspace_page="试跑验证"))


def render_knowledge(store, current, car, track):
    st.title("参数与搭配")
    if car != "ferrari296gt3":
        st.info("当前只核对了 Ferrari 296 GT3 的手册，不把它套用于其他车型。")
        return
    k = knowledge()
    st.caption(k["edition"])
    st.write("作用方向来自文档；本次问题原因属于假设；最终效果由你的试跑确认。")
    param = st.selectbox("想了解哪个参数", k["parameters"], format_func=lambda p: p["name"])
    st.write("**调大／增加：** " + param["up"])
    st.write("**调小／减少：** " + param["down"])
    st.markdown(f"[核对原文 · 第 {param['page']} 页]({k['source']}#page={param['page']})")
    for c in k["couplings"]:
        with st.expander(c["name"], expanded=c["group"] == param["group"]):
            st.write(c["document"])
            st.write("**建议验证顺序：** " + c["workflow"])
            for check in c["checks"]:
                st.write("• " + check)
            if c.get("historical_reference"):
                st.info(c["historical_reference"])
            for page in c["pages"]:
                st.markdown(f"[官方手册第 {page} 页]({k['source']}#page={page})")
    st.subheader("官方配置实例库")
    st.caption("官方配置的自动识别尚未接通；已有实例保留供查阅。日常使用不需要手工录入配置参数或声明来源。")
    examples = [v for v in store.versions(car, track[0]) if v.get("kind") == "official_example"]
    if not examples:
        st.info("尚未读取任何官方配置的实际数值。手册知识已可用，但不能声称已学会官方配置组合。")
    else:
        st.caption(f"已保存 {len(examples)} 个实际实例；这些不是已训练的模型，也不是验证过的个人设置。")
        a = st.selectbox("实例 A", range(len(examples)), format_func=lambda i: examples[i]["name"], key="example_a")
        st.write(examples[a]["source_note"])
        st.caption(examples[a]["source_verification"])
        st.dataframe([{"参数路径": key, "值": value} for key, value in examples[a]["setup_flat"].items()], hide_index=True)
        if len(examples) > 1:
            b = st.selectbox("实例 B", [i for i in range(len(examples)) if i != a], format_func=lambda i: examples[i]["name"])
            result = compare_examples(examples[a], examples[b])
            st.info(result["message"])
            if result["rows"]:
                st.dataframe(result["rows"], hide_index=True, width="stretch")
                st.caption("需要结合上方关系核对：" + "、".join(result["groups"]))


def subjective_validation(store, exp):
    """Subjective feedback never becomes telemetry-proven improvement."""
    guide = (exp.get("recommendation") or {}).get("trial_guide")
    if guide:
        render_trial_guide(guide, exp.get("mode", "感觉 + 数据"))
    with st.expander("只凭手感记录试跑（无需遥测）", expanded=not exp.get("before_records")):
        with st.form(f"subjective:{exp['id']}"):
            verdict = st.selectbox("这次主观感觉", ["还没试跑", "感觉改善", "感觉恶化", "没有明显差别", "说不清"])
            notes = st.text_area("还有什么感受（可留空）")
            if st.form_submit_button("保存手感反馈"):
                if verdict == "还没试跑":
                    st.info("试跑后选一下感觉即可，不需要填写参数或检查结果。")
                else:
                    payload = {key: val for key, val in exp.items() if key not in {"id", "created_at"}}
                    history = list(payload.get("subjective_history", []))
                    from endurance.storage import now
                    history.append({"at": now(), "verdict": verdict, "actual_change": "关联已保存方案；实际应用状态由工具观察", "notes": notes})
                    payload.update(subjective_history=history, subjective_status=verdict)
                    # Preserve telemetry verdicts and pending auto-discovery status.
                    store.save_experiment(payload, exp["id"])
                    st.success("手感反馈已保存，标为主观结论；不会升级为数据验证通过或耐力赛验证通过。")
        for feedback in exp.get("subjective_history", [])[-3:]:
            st.write(f"**{feedback['verdict']}** · {feedback['actual_change']} · {feedback['notes']}")
