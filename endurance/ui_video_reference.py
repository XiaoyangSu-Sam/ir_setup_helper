"""Video annotation and comparison in the existing corner workspace."""
from pathlib import Path

import streamlit as st
from streamlit.components.v2 import component

from endurance.video_reference import compare_video, video_reference


LANDMARK_LABELS = {"start": "入段", "apex": "弯心", "end": "出段"}
EVENT_LABELS = {"brake": "开始刹车", "throttle": "出弯开油"}
ASSETS = Path(__file__).with_name("ui_assets")


@st.cache_resource
def marker_component():
    return component("endurance.video_marks", html=(ASSETS / "video-reference.html").read_text(encoding="utf-8"),
                     js=(ASSETS / "video-reference.js").read_text(encoding="utf-8"))


def choose_video_reference(store, meta, corner):
    scope = (meta["car"], meta["track_id"], meta["track"], corner["name"])
    key = "|".join(str(part) for part in scope)
    selection = f"video-pick:{key}"
    saved = store.video_references(*scope)
    with st.expander("添加教学视频参考", expanded=not bool(saved)):
        st.caption("选取视频里与本段对应的三个地标。画面没有显示的刹车、油门和速度可以留空。")
        start, apex, end = (float(corner[part]) for part in ("start_m", "apex_m", "end_m"))
        st.caption(f"本段地标 · 入段 {start:g} m · 弯心 {apex:g} m · 出段 {end:g} m")
        left, right = st.columns(2)
        title = left.text_input("视频参考名称", key=f"video-title:{key}", max_chars=120, placeholder="例如：296 GT3 干地教学圈")
        url = right.text_input("来源网页链接（可选）", key=f"video-url:{key}", max_chars=2048,
                               help="可在原网页观看并手填时间，也可打开已有的本机视频取帧。")
        lap_time = left.text_input("画面显示的整圈时间（可选）", key=f"video-lap:{key}", max_chars=20, placeholder="例如 8:03.250")
        conditions = right.text_input("画面已知的赛道条件（可选）", key=f"video-conditions:{key}", max_chars=240,
                                      placeholder="例如：干地，赛道 25 °C")
        line = st.text_area("从画面看到的走线（可选）", key=f"video-line:{key}", max_chars=600, height=88,
                            placeholder="例如：靠外侧刹车，过第一个弯心后让车向外靠。")
        continuous = st.checkbox("确认原视频在这段连续播放、速度为 1×", key=f"video-continuous:{key}",
                                 help="用于比较经过相同地标的分段用时，并估算踏板动作的位置。")
        result = marker_component()(key=f"video-marker:{key}", on_marks_change=lambda: None)
        if result.get("marks") is not None:
            try:
                marks = result["marks"]
                if not isinstance(marks, dict):
                    raise ValueError("视频标记格式无效，请重新保存。")
                ref = video_reference(meta, corner, title=title, url=url, conditions=conditions, line=line,
                                      continuous=continuous, lap_time=lap_time, marks=marks)
                identifier = store.save_video_reference(ref)
                saved[identifier] = ref
                st.session_state[selection] = identifier
                st.success("视频参考已保存。")
            except ValueError as exc:
                st.error(str(exc))
    if not saved:
        return None
    selected = st.selectbox("教学视频参考", list(saved), key=selection,
                            format_func=lambda x: f"{saved[x]['title']} · {stamp(saved[x]['times']['start'])} · "
                                                  f"{saved[x]['conditions'] or '条件未知'}")
    return saved[selected]


def stamp(value):
    if value is None:
        return "—"
    ms = round(value * 1000)
    return f"{ms // 60000}:{(ms % 60000) / 1000:06.3f}"


def reading(value, precision=".1f"):
    return "—" if value is None else format(value, precision)


def render_video_comparison(reference, meta, corner, trace, own_lap):
    compared = compare_video(reference, meta, corner, trace)
    st.subheader("视频观察")
    st.caption(f"{reference['title']} · 调教未知 · 赛道条件 {reference['conditions'] or '未知'}")
    if reference["url"]:
        st.link_button("打开来源网页", reference["url"])
    if reference["line"]:
        st.write("走线笔记", reference["line"])
    if reference["lap_time_s"] is not None:
        own = f" · 本机有效整圈 {stamp(own_lap['duration_s'])}" if own_lap["valid"] else ""
        st.write(f"画面圈时 **{stamp(reference['lap_time_s'])}**{own}")
    if not compared["aligned"]:
        st.info("先核对弯道地标。若分段距离已修改，请按新的地标重新保存视频标记。")
    elif not compared["timed"]:
        st.caption("确认视频分段连续且为 1× 后，可以比较用时并估算视频踏板位置。")
    else:
        st.caption("视频踏板位置由三个地标间的时间插值得出。用时按共同地标比较，路线和赛道条件仍可能有差异。")

    speed_rows = []
    for point in compared["speeds"]:
        own_speed, video_speed = point["own"], point["video"]
        speed_rows.append({"地标": LANDMARK_LABELS[point["key"]], "视频时刻": stamp(point["clock"]),
                           "视频速度 km/h": reading(video_speed), "本机速度 km/h": reading(own_speed),
                           "差值 km/h（本机减视频）": "—" if own_speed is None or video_speed is None else reading(own_speed - video_speed, "+.1f")})
    st.dataframe(speed_rows, hide_index=True, width="stretch")

    events = [{"操作": EVENT_LABELS[event["key"]], "视频时刻": stamp(event["clock"]),
               "视频估计位置 m": "—" if event["video_m"] is None else reading(round(event["video_m"] / 10) * 10, ".0f"),
               "本机位置 m": reading(event["own_m"])}
              for event in compared["events"]]
    st.dataframe(events, hide_index=True, width="stretch")
    if compared["aligned"]:
        st.caption("本机踏板点按输入初次达到 5% 统计。视频估计值取整到 10 米，实际误差取决于地标和区间内的速度变化。")
    if compared["phases"]:
        phases = [{"阶段": row["阶段"], "本机秒": reading(row["本机秒"], ".2f"), "视频秒": reading(row["视频秒"], ".2f"),
                   "差值秒（本机减视频）": "—" if row["本机秒"] is None else reading(row["本机秒"] - row["视频秒"], "+.2f")}
                  for row in compared["phases"]]
        st.dataframe(phases, hide_index=True, width="stretch")
    return compared
