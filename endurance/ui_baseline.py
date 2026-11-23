"""File-first baseline selection; live simulator access is optional."""
from copy import deepcopy
import streamlit as st

from endurance.ibt import IBTError
from endurance.paths import setup_files
from endurance.setup_files import discover_exports, import_baseline, refresh_baseline, MANUAL, LIMIT
from endurance.game_version import detect_current_build, resolve_file_build


@st.cache_data(ttl=5, show_spinner=False)
def current_installation():
    return detect_current_build()


def file_baseline(store, current, car, track):
    st.subheader("从哪套设置开始")
    st.caption("优先使用适合本布局的官方基准；读入文件后可离线分析，不需要连接游戏。")
    with st.expander("读取本机文件或上传设置", expanded=current is None):
        exports = discover_exports(car)
        st.caption(f"已发现 {len(exports)} 个可读设置导出、{len(setup_files(car))} 个游戏 .sto 文件。")
        if exports:
            selected = st.selectbox("本机设置导出", exports, format_func=lambda p: p.name)
            if st.button("读取并用作基准"):
                try:
                    if selected.stat().st_size > LIMIT:
                        raise ValueError("设置导出超过 2 MB。")
                    import_baseline(store, selected.read_bytes(), selected.name, car, *track)
                    st.rerun()
                except (ValueError, OSError, IBTError) as exc:
                    st.error(str(exc))
        upload = st.file_uploader("上传设置导出或驾驶记录", type=['htm', 'html', 'ibt', 'json', 'sto'],
                                  help="支持 Garage 导出 .htm/.html、助手快照 .json 和驾驶记录 .ibt。游戏 .sto 请在 Garage 中打开。")
        if upload and st.button("导入并用作基准"):
            try:
                import_baseline(store, upload.getvalue(), upload.name, car, *track)
                st.rerun()
            except (ValueError, OSError, IBTError) as exc:
                st.error(str(exc))
        st.markdown("**只有 `.sto`？** 在游戏 Garage 加载想用的官方设置，点击 **Export** 导出 `.htm`。随后工具可直接读取本机导出，或在这里上传；不需要跑圈，也无需逐项抄参数。")
        st.markdown(f"[官方基准选择依据 · 第 5、6、21 页]({MANUAL}#page=21)")
        st.caption("文件名不会自动证明官方来源。保留所选官方设置的完整搭配，个人适配与改动后的检查结果另行验证。")
    versions = [v for v in store.versions(car, track[0]) if v.get('kind') == 'file_baseline' and v.get('track') == track[1]]
    active_key = f'file_baseline:{car}:{track[0]}:{track[1]}'
    active = store.get_setting(active_key)
    options = {v['id']: v for v in versions}
    if versions:
        keys = ['record'] + list(options)
        picked = st.selectbox("本次基准文件", keys, index=keys.index(active) if active in keys else 0,
                              format_func=lambda k: '侧栏所选记录中的设置' if k == 'record' else options[k]['name'],
                              key=f'file-picker:{car}:{track[0]}:{active}')
        if picked != 'record':
            try:
                version = refresh_baseline(store, options[picked])
            except (ValueError, OSError) as exc:
                st.error(str(exc))
                return None, 'file'
            meta = deepcopy(version['meta'])
            if meta.get('source_kind') == 'assistant_snapshot':
                st.caption("已读取助手快照。游戏设置请在 Garage 保存为 .sto 后加载。")
                if meta['build'] != 'unknown':
                    meta = resolve_file_build(meta, current_installation())
            with st.expander("查看文件中的设置参数"):
                st.dataframe([{'参数路径': k, '文件值': v} for k, v in meta['setup_flat'].items()], hide_index=True)
                st.caption("显示原始单位；未识别的数值格式不会用于自动计算。")
            if meta['build'] == 'unknown':
                meta = resolve_file_build(meta, current_installation())
                if meta['build'] != 'unknown':
                    st.caption(f"已自动识别游戏版本：{meta['build']} · {meta['build_source']}。")
                    st.caption("文件未标注版本，按当前安装版本使用；更新游戏后自动重新识别。")
                else:
                    st.caption("工具暂未读到本机游戏版本，仍可查看文件参数；无需手工填写。")
                if st.button('重新识别游戏版本'):
                    current_installation.clear()
                    st.rerun()
            return meta, 'file'
    if current:
        return {**deepcopy(current['meta']), 'source_kind': 'historical_ibt'}, 'file'
    st.info("还没有读到设置文件。可以读取本机导出或上传文件；不需要连接模拟器。")
    return None, 'file'
