"""Local Streamlit UI. Run with: python -m streamlit run app.py."""
from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import polars as pl
import streamlit as st

from endurance.analysis import (compare_corner, compare_runs, compatibility, default_segments, endurance_coverage, repeated_corner,
                                lap_frame, pace_summary, validate_corners)
from endurance.ibt import IBTError, is_simulated
from endurance.paths import data_dir, setup_files, telemetry_dir
from endurance.rules import setup_difference
from endurance.service import Watcher
from endurance.storage import Store
from endurance.snapshot_files import export_snapshot
from endurance.trial import trial_defaults
from endurance.knowledge import initial_baseline
from endurance.ui_guidance import render_guidance, render_knowledge, subjective_validation
from endurance.ui_adjustment import render_automatic_checks
from endurance.ui_timing_wall import render_timing_wall

st.set_page_config(page_title="耐力调教 · Endurance Lab", page_icon="🏁", layout="wide")
st.markdown("""
<style>
.block-container {max-width:1440px;padding-top:2.0rem;padding-bottom:4rem;}
h1,h2,h3 {letter-spacing:-.035em;}
[data-testid="stMetric"] {background:#15222b;border:1px solid #283942;border-radius:12px;padding:16px;}
[data-testid="stMetricLabel"] {color:#93a8b1;}
[data-testid="stSidebar"] {border-right:1px solid #283942;}
.eyebrow {font-size:12px;letter-spacing:.19em;color:#a9e86c;font-weight:700;margin-bottom:12px;}
.hero {padding:24px 28px;border:1px solid #31434a;border-radius:16px;background:linear-gradient(110deg,#1c3037,#15222b);margin-bottom:24px;}
.hero h1 {font-size:32px;margin:0 0 8px;}
.hero p {color:#b7c7cd;margin:0;line-height:1.8;}
.small-note {color:#91a6ae;font-size:13px;}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def services(root: str):
    store = Store(Path(root))
    watcher = Watcher(store)
    if os.environ.get("ENDURANCE_NO_WATCHER") != "1":
        watcher.start()
    return store, watcher


store, watcher = services(str(data_dir().resolve()))


def local_date(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(ZoneInfo("America/Toronto")).strftime("%m/%d %H:%M")


def seconds(value: float | None) -> str:
    return "待采集" if value is None else f"{int(value // 60)}:{value % 60:06.3f}"


def record_label(r: dict) -> str:
    summary = pace_summary(r["laps"])
    return f"{local_date(r['meta']['start_utc'])} · {summary['valid']} 有效圈 · {r['meta']['source_name']}"


@st.cache_data(max_entries=6, show_spinner=False)
def read_samples(root: str, record_id: str):
    return pl.read_parquet(Path(root) / "recordings" / f"{record_id}.parquet")


def samples(r):
    return read_samples(str(store.root), r["id"])


def lap_table(laps):
    return [{"片段": l["lap_id"], "游戏圈号": l["lap_number"], "驾驶段": l["run_id"],
             "圈时／片段时长": seconds(l["duration_s"]), "有效圈": "是" if l["valid"] else "否",
             "说明": "、".join(l["reasons"]) or "完整且记录内未发现失误",
             "起始燃油 L": l["fuel_start_l"], "赛道温度 °C": l["track_temp_c"],
             "失误增量": l["incident_delta"], "方向输入变化次数": l["steering_changes"]} for l in laps]


def render_metrics(record):
    summary = pace_summary(record["laps"]) if record else {"valid": 0, "total": 0, "median_s": None, "errors": 0, "iqr_s": None}
    for col, title, value, helptext in zip(st.columns(4),
          ["有效完整圈", "代表性圈速", "圈速波动 · IQR", "含失误的圈／片段"],
          [f"{summary['valid']} / {summary['total']}", seconds(summary["median_s"]),
           f"{summary['iqr_s']:.3f} s" if summary["iqr_s"] is not None else "待采集", str(summary["errors"])],
          ["完整且质量通道可核验的圈。其余片段仍保留。", "有效圈的中位数，不采用最快圈。", "有效圈的四分位距，越小表示圈时越集中。", "失误记录保留用于稳定性评价。"]):
        col.metric(title, value, help=helptext)


records = store.list_records()
by_id = {r["id"]: r for r in records}
profile = store.get_setting("profile", {"race_hours": 4.0, "stint_minutes": 60,
    "preference": "车头响应积极、弯中愿意转向；保留可控车尾与有竞争力的长距离稳定性。", "symptom": "弯中推头", "feeling": ""})

with st.sidebar:
    st.markdown('<div class="eyebrow">ENDURANCE LAB / PERSONAL</div>', unsafe_allow_html=True)
    st.title("耐力调教")
    st.caption("更愿意转向，也能稳定跑下去。")
    page = st.radio("工作区", ["赛前工作台", "驾驶记录", "弯道与参考圈", "试跑验证", "设置档案", "参数与搭配"],
                    label_visibility="collapsed", key="workspace_page")
    st.divider()
    cars = list(dict.fromkeys(["ferrari296gt3"] + [r["meta"]["car"] for r in records]))
    car = st.selectbox("车辆", cars, format_func=lambda x: "Ferrari 296 GT3" if x == "ferrari296gt3" else x)
    tracks = list(dict.fromkeys([("262", "nurburgring combinedshortb")] +
                                [(r["meta"]["track_id"], r["meta"]["track"]) for r in records if r["meta"]["car"] == car]))
    selected_track = st.selectbox("赛道布局", tracks, format_func=lambda x: "纽博格林 · Gesamtstrecke VLN" if x == ("262", "nurburgring combinedshortb") else x[1])
    available = [r for r in records if r["meta"]["car"] == car and (r["meta"]["track_id"], r["meta"]["track"]) == selected_track]
    if available:
        record_id = st.selectbox("当前驾驶记录", [r["id"] for r in available], format_func=lambda x: record_label(by_id[x]), key=f"current_record:{car}:{selected_track[0]}")
        current = by_id[record_id]
    else:
        current = None
        st.caption("该组合暂无本机记录")
    st.divider()
    st.caption("本机处理 · 只读游戏数据\n\n比赛时长和单段时长分别记录")
    if st.button("刷新记录与状态", width="stretch"):
        st.rerun()


def show_plan():
    st.markdown('<div class="hero"><div class="eyebrow">RACE PREPARATION</div><h1>把车调成你愿意一直开的样子。</h1><p>从一套基准出发，一次验证一个改变。灵敏的车头、可控的车尾、稳定的比赛节奏。</p></div>', unsafe_allow_html=True)
    mode = st.radio("推荐依据", ["凭感觉", "凭数据", "感觉 + 数据"], index=0, horizontal=True)
    render_guidance(store, current, car, selected_track, profile, mode)
    if mode != "凭感觉":
        with st.expander("驾驶记录摘要"):
            render_metrics(current)
    with st.expander("比赛目标与基准（可选）"):
        st.subheader("01 · 本次比赛")
        with st.form("race_profile"):
            c1, c2 = st.columns(2)
            race = c1.number_input("比赛总时长（小时）", 3.0, 48.0, float(profile["race_hours"]), .5)
            stint = c2.number_input("预计单次驾驶／燃油段（分钟）", 10, 240, int(profile["stint_minutes"]), 5)
            preference = st.text_area("我的驾驶偏好", profile["preference"], height=100)
            if st.form_submit_button("保存赛前目标", width="stretch"):
                if stint > race * 60:
                    st.error("单段时长不能超过比赛总时长。")
                else:
                    store.set_setting("profile", {**profile, "race_hours": race, "stint_minutes": stint, "preference": preference})
                    st.success("目标已保存，下次打开会继续使用。")
        st.subheader("02 · 选好基准")
        with st.expander("还没有数据或设置：先从这里开始", expanded=not current or mode == "凭感觉"):
            for step in initial_baseline(car, selected_track[1]):
                st.write("• " + step)
            st.markdown("[官方设置选择说明 · 第 21 页](https://s100.iracing.com/wp-content/uploads/2024/06/Ferrari-296-GT3-V4.pdf#page=21)")
        versions = store.versions(car, selected_track[0])
        active = store.get_setting(f"active_baseline:{car}:{selected_track[0]}")
        # Do not silently use a validated setup from another simulator build.
        preferred = next((v for v in versions if v["id"] == active), None)
        validated = [v for v in versions if v.get("locally_validated") and current and v.get("build") == current["meta"]["build"]]
        if preferred:
            st.info(f"当前基准档案：{preferred['name']}。请在游戏中手动加载对应设置。")
        if validated:
            st.success(f"本机有初步验证记录：{validated[0]['name']}。仍需检查本次燃油与环境条件。")
        else:
            st.info("尚无适用的个人验证设置。先在 Garage → iRacing Setups 选择本布局的 endurance 基准，记为“未验证个人适配”。")
        if current and mode != "凭感觉":
            st.caption(f"当前分析快照来自 {local_date(current['meta']['start_utc'])} · 游戏版本 {current['meta']['build']}。不代表游戏现在加载的设置。")
            with st.expander("查看已有设置文件"):
                files = setup_files(car)
                st.write("\n".join(f"• {p.name}" for p in files) if files else "没有找到本车型的个人 .sto 文件。")
                st.caption("文件名仅供查找，不据此宣称设置适用于当前版本或赛道。")


def show_data():
    st.title("驾驶记录")
    st.write("本机自动发现，原始文件保持不变。没有完整圈也会保留练习片段。")
    @st.fragment(run_every="10s")
    def monitor():
        st.info(watcher.status)
        st.caption("应用进程运行时持续监测；关闭浏览器不停止后台扫描。重新打开或点击刷新载入新增记录。")
    monitor()
    with st.expander("采集与目录设置", expanded=not records):
        with st.form("data_settings"):
            folder = st.text_input("遥测目录", store.get_setting("telemetry_path", str(telemetry_dir())))
            enabled = st.checkbox("自动发现新记录", store.get_setting("watch_enabled", True))
            if st.form_submit_button("保存目录设置"):
                if not Path(folder).is_dir():
                    st.error("目录不存在，请选择实际的 telemetry 文件夹。")
                else:
                    store.set_setting("telemetry_path", folder)
                    store.set_setting("watch_enabled", enabled)
                    st.success("已保存；下一轮扫描使用新设置。")
        st.markdown("没有记录时：进入 iRacing，按 **Alt + L** 开启遥测记录，确认游戏出现 Telemetry 指示；完成试跑后退回车库结束记录。这里只根据实际文件确认采集，不把目录存在当作正在录制。")
        st.markdown("[iRacing 官方录制说明](https://ir-core-sites.iracing.com/dev/atlas/atlas_quickstart.pdf)")
    uploads = st.file_uploader("也可以导入自己的记录或参考圈", type=["ibt"], accept_multiple_files=True)
    if uploads and st.button("导入选中的 IBT", type="primary"):
        upload_dir = store.root / "uploads"
        upload_dir.mkdir(exist_ok=True)
        for upload in uploads:
            payload = upload.getvalue()
            dest = upload_dir / (hashlib.sha256(payload).hexdigest() + ".ibt")
            if not dest.exists():
                dest.write_bytes(payload)
            try:
                with st.spinner(f"解析 {upload.name}"):
                    identifier, fresh = store.import_file(dest, source_name=upload.name)
                    if fresh:
                        watcher.associate_experiments(identifier)
                st.success(f"{upload.name}：{'导入完成' if fresh else '已有同内容记录，未重复导入'}")
            except (IBTError, OSError, ValueError) as exc:
                st.error(f"{upload.name}：{exc}")
        st.button("更新记录列表")
    if records:
        st.dataframe([{"时间（多伦多）": local_date(r["meta"]["start_utc"]), "车辆": r["meta"]["car"],
                       "布局": r["meta"]["track"], "有效圈": pace_summary(r["laps"])["valid"],
                       "总圈／片段": len(r["laps"]), "游戏版本": r["meta"]["build"], "源文件": r["meta"]["source_name"]} for r in records],
                     hide_index=True, width="stretch")
    if current:
        st.subheader("当前记录 · 圈与质量")
        render_metrics(current)
        st.dataframe(lap_table(current["laps"]), hide_index=True, width="stretch")
        with st.expander("数据来源、缺失项与原始通道"):
            st.write(current["meta"]["source_path"])
            st.write(f"采样率 {current['meta']['tick_rate']} Hz · {current['meta']['record_count']:,} 个样本")
            st.write("缺失标准通道：" + ("、".join(current["meta"]["missing_channels"]) or "无"))
            for warning in current["meta"]["warnings"]:
                st.warning(warning)
            st.dataframe(current["meta"]["channels"], hide_index=True, width="stretch")
    with st.expander("文件扫描详情"):
        st.dataframe([{"文件": Path(p).name, "状态": msg} for p, msg in list(watcher.messages.items())], hide_index=True)


def chart_trace(result):
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=.045,
                        subplot_titles=("速度 · km/h", "踏板输入 · 0–1", "方向盘 · °", "相对参考耗时 · s"))
    for label, trace, color in (("本圈", result["trace"], "#a9e86c"), ("参考", result["reference"], "#70b9ec")):
        if trace is None:
            continue
        for channel, row, title, dash in (("speed_kph", 1, "速度", None), ("throttle", 2, "油门", None),
                                          ("brake", 2, "刹车", "dot"), ("steering_deg", 3, "方向", None)):
            if channel in trace:
                fig.add_trace(go.Scatter(x=trace["distance_m"], y=trace[channel], name=f"{label} {title}",
                                        line=dict(color=color, dash=dash)), row=row, col=1)
    if result["reference"] is not None:
        fig.add_trace(go.Scatter(x=result["trace"]["distance_m"], y=result["trace"]["elapsed_s"] - result["reference"]["elapsed_s"],
                                name="正值：本圈更慢", line=dict(color="#f5bc73")), row=4, col=1)
    fig.update_layout(height=730, template="plotly_dark", paper_bgcolor="#0c1419", plot_bgcolor="#15222b",
                      margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h"))
    fig.update_xaxes(title_text="本布局距离 · m", row=4, col=1)
    return fig


def show_corners():
    st.title("弯道与参考圈")
    if not current:
        st.info("先导入一份遥测记录。")
        return
    meta, df = current["meta"], samples(current)
    key = f"corners:{meta['track_id']}:{meta['track']}"
    saved = store.get_setting(key)
    initial_corners, map_note = default_segments(meta)
    corners = saved["corners"] if saved else initial_corners
    st.caption(f"布局 ID {meta['track_id']} · {meta['track_length_m'] / 1000:.4f} km · 不与其他布局合并")
    if not saved:
        st.info(map_note)
    with st.expander("校准弯道／连续弯分段"):
        st.write("先查看下方全圈速度与距离，再新增或修改分段。verified 仅在你核对本布局弯道位置后勾选。")
        edited = st.data_editor(corners, num_rows="dynamic", width="stretch", key=f"corner_editor:{key}")
        if st.button("保存本布局分段"):
            try:
                checked = validate_corners(edited, meta["track_length_m"])
                store.set_setting(key, {"track_id": meta["track_id"], "track": meta["track"], "corners": checked,
                                       "source_record": current["id"]})
                st.success("分段已保存；重新打开本页即可使用。")
            except (ValueError, KeyError, TypeError) as exc:
                st.error(str(exc))
    lap_ids = [l["lap_id"] for l in current["laps"] if l["sample_stop"] - l["sample_start"] > 30]
    if not lap_ids:
        st.warning("没有足够样本进行分段分析。")
        return
    def label_lap(identifier):
        l = next(l for l in current["laps"] if l["lap_id"] == identifier)
        return f"片段 {identifier} / 游戏圈 {l['lap_number']} · {seconds(l['duration_s'])} · {'有效' if l['valid'] else '、'.join(l['reasons'])}"
    default_lap = max(lap_ids, key=lambda i: (next(l for l in current["laps"] if l["lap_id"] == i)["valid"], next(l for l in current["laps"] if l["lap_id"] == i)["duration_s"]))
    chosen = st.selectbox("分析哪一圈／片段", lap_ids, index=lap_ids.index(default_lap), format_func=label_lap)
    user_lap = lap_frame(df, chosen)
    overview = go.Figure(go.Scatter(x=user_lap["distance_m"].to_list()[::6], y=user_lap["speed_kph"].to_list()[::6],
                                   line_color="#a9e86c", name="速度"))
    overview.update_layout(height=220, xaxis_title="本布局距离 · m", yaxis_title="km/h", margin=dict(l=15,r=15,t=10,b=10))
    st.plotly_chart(overview, width="stretch")
    selected = st.selectbox("弯道／连续弯分段", range(len(corners)), format_func=lambda i: corners[i]["name"])
    corner = corners[selected]
    references = [r for r in records if r["meta"]["car"] == car and r["meta"]["track_id"] == meta["track_id"] and r["meta"]["track"] == meta["track"]]
    ref_id = st.selectbox("参考记录（可选）", [None] + [r["id"] for r in references],
                         format_func=lambda x: "不使用参考圈" if x is None else record_label(by_id[x]))
    ref_lap = None
    if ref_id:
        reference = by_id[ref_id]
        ids = [l["lap_id"] for l in reference["laps"] if l["valid"] and (ref_id != current["id"] or l["lap_id"] != chosen)]
        if ids:
            rid = st.selectbox("参考有效圈", ids)
            ref_lap = lap_frame(samples(reference), rid)
            differences = compatibility(meta, reference["meta"])
            st.caption("参考圈用于描述差异，不自动认定其为最佳驾驶。燃油、温度及路面条件需另行核对。")
            if differences:
                st.warning("参考条件不同：" + "、".join(differences) + "；以下仅描述曲线差异。")
        else:
            st.warning("该记录没有其他有效完整圈；继续进行无参考分析。")
    try:
        result = compare_corner(user_lap, ref_lap, corner)
    except ValueError as exc:
        st.warning(f"{exc} 请改选覆盖此分段的圈，或校准分段。")
        return
    if not corner.get("verified"):
        result["phases"] = []
        result["facts"] = [f for f in result["facts"] if "开始刹车" not in f and "出弯达到" not in f]
        st.warning("此分段阶段边界尚未核对：仅显示整体曲线，不把草稿阶段解释为真实入弯／弯中／出弯。")
    st.plotly_chart(chart_trace(result), width="stretch")
    if result["phases"]:
        st.dataframe(result["phases"], hide_index=True, width="stretch")
    st.markdown("**观测事实**")
    for fact in result["facts"]:
        st.write("• " + fact)
    st.markdown("**待验证解释**")
    st.write(result["hypotheses"][0])
    st.caption("本版不诊断赛车走线是否最优，不把方向盘角度直接当作轮胎滑移角。")
    st.session_state["analysis_facts"] = {"record_id": current["id"], "corner": corner["name"], "facts": result["facts"]}
    with st.expander("同一弯道的重复行为（无需参考圈）"):
        repeated = repeated_corner(df, current["laps"], corner)
        st.write(repeated["message"])
        if repeated["rows"]:
            st.dataframe(repeated["rows"], hide_index=True, width="stretch")
        st.caption("保留失误片段；这里只描述重复输入及其范围，不据此诊断调教原因。燃油和温度差异需核对。")
    if "Lat" in user_lap.columns and "Lon" in user_lap.columns:
        with st.expander("查看本圈位置轨迹（用于人工定位）"):
            pts = user_lap.select("Lon", "Lat", "distance_m").gather_every(12).drop_nulls()
            if pts.height and pts["Lat"].std() and pts["Lon"].std():
                origin_lat = float(pts["Lat"].mean())
                x = (pts["Lon"].to_numpy() - float(pts["Lon"].mean())) * 111320 * np.cos(np.radians(origin_lat))
                y = (pts["Lat"].to_numpy() - origin_lat) * 111320
                fig = go.Figure(go.Scatter(x=x, y=y, mode="markers", marker=dict(size=3,color=pts["distance_m"].to_numpy(),colorscale="Viridis",showscale=True),
                                          customdata=pts["distance_m"].to_numpy(), hovertemplate="距离 %{customdata:.0f} m<extra></extra>"))
                fig.update_layout(height=520, yaxis=dict(scaleanchor="x"), xaxis_title="相对东西位置 · m", yaxis_title="相对南北位置 · m")
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("没有可用位置变化。")


def show_validation():
    st.title("试跑验证")
    experiments = [e for e in store.experiments()
                   if e["car"] == car and e["track_id"] == selected_track[0]
                   and (e.get("numeric_plan") or {}).get("track", selected_track[1]) == selected_track[1]]
    if not experiments:
        st.info("先在赛前工作台保存一个实验，再完成调整前后的试跑。")
        return
    exp_index = st.selectbox("待验证实验", range(len(experiments)), format_func=lambda i: f"{local_date(experiments[i]['created_at'])} · {experiments[i]['recommendation']['parameter']} · {experiments[i]['status']}")
    exp = experiments[exp_index]
    plan = exp.get("numeric_plan") or {}
    matched_before, matched_after = trial_defaults(plan, available) if plan.get("schema") == 2 else (None, None)
    st.write(f"**问题：** {exp['recommendation']['symptom']} · {exp['recommendation']['corner'] or '尚未指定弯道'}")
    st.write(f"**你的原话：** {exp['recommendation']['feeling'] or '未填写'}")
    st.caption("推荐依据：" + exp.get("mode", "感觉 + 数据"))
    with st.expander("回看本轮实验和起点"):
        st.write(f"**{exp['recommendation']['parameter']}** · 原值：{exp['recommendation']['current']}")
        st.write(exp["recommendation"]["direction"])
        st.write("基准：" + (exp.get("baseline_name") or "查看调整前记录／快照"))
        st.write(exp["recommendation"]["verification"])
    render_automatic_checks(store, exp)
    if plan.get("schema") == 2:
        missing = []
        if not matched_before:
            missing.append(f"原设置 {plan['current']:g} {plan['unit']}")
        if not matched_after:
            missing.append(f"调整后 {plan['target']:g} {plan['unit']}")
        if missing:
            st.info("等待可配对的记录：" + "、".join(missing) + "。同版本、同布局分别试跑并保存遥测后，工具会尝试自动匹配。")
        else:
            st.success("已自动配对调整前后记录。两份记录在可比对的设置快照中仅目标参数不同。")
    subjective_validation(store, exp)
    if not available:
        st.info("没有遥测也可以在上面保存手感反馈；之后导入前后记录即可补充数据验证。")
        return
    # Units are disjoint whole runs, preserving all error laps within each run.
    units = {}
    for r in available:
        for run_id in sorted({l["run_id"] for l in r["laps"]}):
            laps = [l for l in r["laps"] if l["run_id"] == run_id]
            units[f"{r['id']}:{run_id}"] = (r, laps)
    labels = lambda k: f"{record_label(units[k][0])} · 驾驶段 {units[k][1][0]['run_id']} · {pace_summary(units[k][1])['valid']} 有效 / {len(units[k][1])} 圈或片段"
    def preferred_run(record):
        keys = [k for k, (r, _) in units.items() if record and r["id"] == record["id"]]
        return [max(keys, key=lambda k: (pace_summary(units[k][1])["valid"], len(units[k][1])))] if keys else []

    if plan.get("schema") == 2:
        default_before, default_after = preferred_run(matched_before), preferred_run(matched_after)
    else:
        default_before = [k for k, (r, _) in units.items() if r["id"] in exp.get("before_records", [])]
        default_after = [k for k, (r, _) in units.items() if r["id"] in exp.get("candidate_after_records", [])]
    with st.expander("查看或更换对比的驾驶段"):
        selection_key = f"{exp['id']}:{','.join(default_before)}:{','.join(default_after)}"
        before_keys = st.multiselect("调整前驾驶段", list(units), default=default_before, format_func=labels, key=f"before:{selection_key}")
        after_keys = st.multiselect("调整后驾驶段", list(units), default=default_after, format_func=labels, key=f"after:{selection_key}")
    # Snapshots cannot establish per-lap settings or traffic/tyre history.
    # Do not replace missing machine evidence with a novice's checkbox.
    confirmed = conditions = False
    if not before_keys or not after_keys:
        st.caption("计时墙会在选定调整前后的遥测后显示。")
        if plan.get("schema") != 2:
            st.info("在上方选择两组驾驶段。各可比条件组前后均需至少三圈有效圈。")
        return
    if set(before_keys) & set(after_keys):
        st.error("同一个驾驶段不能同时作为调整前与调整后。")
        return
    before, after = [l for k in before_keys for l in units[k][1]], [l for k in after_keys for l in units[k][1]]
    ma, mb = units[before_keys[0]][0]["meta"], units[after_keys[0]][0]["meta"]
    inner = []
    for group_keys, base in ((before_keys, ma), (after_keys, mb)):
        for k in group_keys:
            inner.extend(compatibility(base, units[k][0]["meta"]))
    if inner:
        st.error("选中的同组驾驶段并不一致：" + "、".join(sorted(set(inner))))
        return
    sources = {is_simulated(units[k][0]["meta"]) for k in before_keys + after_keys}
    if len(sources) > 1:
        st.info("请分别比较模拟试跑和真实试跑。")
        return
    if True in sources:
        st.info("当前对比使用模拟遥测，供检查图表和流程。")
    render_timing_wall(store, exp, before, after, by_id, samples)
    result = compare_runs(ma, mb, before, after, confirmed, conditions)
    comparable = [group for group in result["groups"] if group["eligible"]]
    st.subheader("试跑观测" if comparable else result["status"])
    if len(comparable) == 1:
        st.metric("可比条件下，代表圈速变化", f"{comparable[0]['delta_s']:+.2f} 秒／圈",
                  help="负数表示调整后记录圈速更短。")
    elif comparable:
        st.write(f"找到 {len(comparable)} 组配速可对照的条件，详见下表。")
    else:
        st.write(result["conclusion"])
    st.caption("效果判断仍需更多证据。记录可以对照圈速和失误，逐圈设置、轮胎使用和交通尚未完整核实。")
    with st.expander("查看数据核对详情"):
        for blocker in result["blockers"]:
            st.write("• " + blocker)
    if result["groups"]:
        st.dataframe(result["groups"], hide_index=True, width="stretch")
    st.caption("条件组：燃油每 10 L、赛道／气温每 3°C；路面湿润等级、胎种、配重和动力限制分别匹配。边界附近可能需要更多数据，这些分组不代表环境差异已被完全消除。")
    a, b = result["before"], result["after"]
    st.dataframe([{"组别": title, "有效圈": v["valid"], "全部圈／片段": v["total"], "含失误圈／片段": v["errors"],
                   "代表圈速": seconds(v["median_s"]), "波动 IQR 秒": v["iqr_s"],
                   "方向输入变化中位数": v["steering_changes_median"]} for title, v in (("调整前", a), ("调整后", b))], hide_index=True)
    st.caption("方向输入变化包含正常转弯修正，不能直接解释为失控次数。")
    coverage = endurance_coverage(after, mb.get("fuel_capacity_l"), float(profile["stint_minutes"]))
    c1, c2, c3 = st.columns(3)
    c1.metric("高油量有效圈", coverage["high_fuel_laps"])
    c2.metric("低油量有效圈", coverage["low_fuel_laps"])
    c3.metric("最长已记录驾驶段", f"{coverage['longest_run_minutes']:.1f} 分钟")
    st.caption(coverage["message"])
    st.info("当前结果不等同于完整耐力赛验证。长段配速变化还可能来自燃油、温度、交通和驾驶状态，不能直接称为胎衰。")
    trend = [{"组别": group, "记录": l["recording_id"][:6], "驾驶段": l["run_id"], "圈号": l["lap_number"],
              "圈时秒": l["duration_s"], "起始燃油 L": l["fuel_start_l"], "有效": l["valid"]}
             for group, rows in (("前", before), ("后", after)) for l in rows]
    with st.expander("驾驶段趋势与设置差异"):
        st.dataframe(trend, hide_index=True)
        st.dataframe(setup_difference(ma, mb), hide_index=True)
        st.caption("这是文件快照差异，包含燃油和测量值；并非逐圈设置变更证明。")
    if st.button("保存本次数据对比", type="primary"):
        payload = {k: v for k, v in exp.items() if k not in {"id", "created_at"}}
        payload.update(status=result["status"], result=result,
                       before_units=before_keys, after_units=after_keys, coverage=coverage,
                       setup_confirmed=confirmed, conditions_confirmed=conditions)
        if exp.get("workflow_version") == 3:
            # Preserve legacy safety state while allowing additional observations.
            payload["status"] = exp["status"]
        store.save_experiment(payload, exp["id"])
        st.success("数据对比已保存。")


def show_archive():
    st.title("设置档案")
    st.write("保存调教快照、验证记录和你的偏好。切换基准只影响助手里的比较起点。")
    if current:
        with st.form("snapshot"):
            name = st.text_input("给当前快照取个名字", placeholder="例如：纽北 · 满油基准 · 先保留贴地感")
            st.caption(current["meta"]["setup_scope"])
            if st.form_submit_button("保存为未验证基准"):
                if not name.strip():
                    st.error("请输入名称。")
                else:
                    m = current["meta"]
                    identifier = store.save_version({"name": name.strip(), "car": car, "track_id": selected_track[0],
                       "track": m["track"], "build": m["build"], "record_id": current["id"], "setup": m["setup"],
                       "setup_flat": m["setup_flat"], "locally_validated": False, "validation_level": "尚未验证个人适配",
                       "observed_wetness": m.get("observed_wetness", []),
                       "parent_id": store.get_setting(f"active_baseline:{car}:{selected_track[0]}")})
                    store.set_setting(f"active_baseline:{car}:{selected_track[0]}", identifier)
                    st.success("基准快照已保存。")
    versions = store.versions(car, selected_track[0])
    if versions:
        selected = st.selectbox("历史版本", range(len(versions)), format_func=lambda i: f"{versions[i]['name']} · {versions[i]['validation_level']}")
        v = versions[selected]
        st.caption(f"游戏版本 {v['build']} · {local_date(v['created_at'])}")
        st.dataframe([{"参数": k, "值": str(value)} for k, value in v["setup_flat"].items()], hide_index=True, width="stretch")
        if st.button("设为当前基准／回退到此版本"):
            store.set_setting(f"active_baseline:{car}:{selected_track[0]}", v["id"])
            st.success("助手基准已切换。请在游戏内加载相应设置，助手不会覆盖 .sto。")
        try:
            snapshot = export_snapshot(v)
        except (ValueError, TypeError) as exc:
            st.error(f"无法导出设置快照。{exc}")
        else:
            st.download_button("下载可重新导入的设置快照", snapshot, "setup-snapshot.json", "application/json")
    else:
        st.info("尚无设置档案。先保存当前记录中的设置作为基准。")
    st.caption("参数资料和检查由工具处理；这里保留你的设置历史。")
    with st.expander("实验历史"):
        for e in store.experiments():
            if e["car"] == car and e["track_id"] == selected_track[0]:
                st.markdown(f"**{local_date(e['created_at'])} · {e['recommendation']['parameter']} · {e['status']}**")
                st.write(e.get("feedback") or e["recommendation"]["feeling"] or "未填写反馈")


{"赛前工作台": show_plan, "驾驶记录": show_data, "弯道与参考圈": show_corners,
 "试跑验证": show_validation, "设置档案": show_archive,
 "参数与搭配": lambda: render_knowledge(store, current, car, selected_track)}[page]()
