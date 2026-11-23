"""Render the timing wall with telemetry from one comparable condition group."""
import json
from pathlib import Path

import streamlit as st
from polars.exceptions import PolarsError

from endurance.analysis import default_segments
from endurance.timing_wall import build_wall, common_conditions


ASSETS = Path(__file__).with_name("ui_assets")


def wall_html(model):
    # Do not allow strings from the imported files to terminate the JSON script.
    payload = json.dumps(model, ensure_ascii=True, allow_nan=False).replace("<", r"\u003c")
    template = (ASSETS / "timing-wall.html").read_text(encoding="utf-8")
    script = (ASSETS / "timing-wall.js").read_text(encoding="utf-8")
    return f'{template}<script id="timing-wall-data" type="application/json">{payload}</script><script>{script}</script>'


def render_timing_wall(store, exp, before, after, records, load_samples):
    groups = common_conditions(before, after)
    if not groups:
        st.info("调校计时墙需要相同燃油和环境分组下的调整前后有效圈。")
        return
    selected = next(iter(groups))
    if len(groups) > 1:
        def group_label(key):
            a, b = groups[key]
            return (f"燃油 {key[0]*10}–{(key[0]+1)*10} L · 地温 {key[1]*3}–{(key[1]+1)*3}°C · "
                    f"气温 {key[2]*3}–{(key[2]+1)*3}°C · 湿度级 {key[3]} · 胎种 {key[4]} · "
                    f"配重 {key[5]:g} kg · 动力调整 {key[6]:g} · A {len(a)} 圈 / B {len(b)} 圈")
        selected = st.selectbox("计时墙条件组", list(groups), format_func=group_label, key=f"wall-bin:{exp['id']}")
    a, b = groups[selected]
    meta = records[a[0]["recording_id"]]["meta"]
    saved = store.get_setting(f"corners:{meta['track_id']}:{meta['track']}")
    corners = saved["corners"] if saved else default_segments(meta)[0]
    try:
        model = build_wall(a, b, records, load_samples, corners)
    except ValueError as exc:
        st.info(f"计时墙暂时无法对齐这两组记录。{exc}")
        return
    except (OSError, PolarsError):
        st.info("计时墙无法读取本机采样。可在「驾驶记录」检查对应遥测。")
        return
    plan = exp.get("numeric_plan") or {}
    model["change"] = (f"本轮目标 · {plan['parameter']} {plan['current']:g} → {plan['target']:g} {plan['unit']}"
                       if plan else "A 调整前 · B 调整后")
    st.iframe(wall_html(model), height="content", alt="调校计时墙：圈速、分段和按距离对齐的遥测")
    counts = model["counts"]
    st.caption(f"A {counts[0]} 圈 / B {counts[1]} 圈 · 默认各选一条最接近中位数的完整圈。下方试跑观测使用各组实际中位数。"
               "绿色按同条件下较早的 A、B 有效圈判断个人最佳。紫色整圈取自游戏正式会话结果；分段及速度暂无全场参照。")
    if model["best"] is None:
        st.caption("遥测没有报告中间计时线，仅可比较整圈。")
    else:
        st.caption("理论最佳圈按各自最快赛段相加，赛段来源随选择显示；合计不参加实跑最快圈排名。")
    if model["rejected"]:
        st.caption(f"有 {model['rejected']} 圈因计时线附近缺采样或数据断续未进入计时墙。")
