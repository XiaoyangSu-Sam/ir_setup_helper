"""Read-only checks. Users never certify engineering facts for the tool."""
import streamlit as st
from endurance.automatic import observe_plan, validate_automatic_plan


def render_automatic_checks(store, exp):
    plan = exp.get("numeric_plan")
    if not plan:
        st.info("旧版方向记录仍可查看和填写感受。具体数值请在工作台重新生成。")
        return
    st.markdown(f"### 本轮方案：{plan['parameter']} → {plan['target']:g} {plan['unit']}")
    st.caption(f"原值 {plan['current']:g} {plan['unit']} · 版本 {plan['build']}")
    if plan.get("schema") == 2:
        try:
            validate_automatic_plan(plan)
        except ValueError as exc:
            st.error(str(exc))
            return
        observation = observe_plan(plan, store.list_records())
        st.info(observation["message"])
        if observation.get("other_differences"):
            with st.expander("工具发现的其他快照差异"):
                st.write(observation["other_differences"])
    st.caption("游戏安全检查：尚未自动接通。这里不会要求你填写 Passed Tech，也不会将试跑或手感改善当作通过检查。")
