"""In-app access to the registration companion and released Windows updates."""
import os
from pathlib import Path
import socket
import subprocess
import sys

import streamlit as st

from endurance.paths import ROOT
from endurance.updates import RELEASES, check_for_update, current_version, download


def registration_exe():
    install = ROOT.parent if getattr(sys, "frozen", False) else Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "IRSetupHelper"
    return install / "registration" / "NativeBridge.exe"


def show_registration():
    st.title("赛事报名")
    st.write("用报名助手选择场次、保存个人预约，或准备耐力赛车队资料。")
    bridge = registration_exe()
    if not bridge.is_file():
        st.info("安装 Windows 合装版后，就可以从这里启动报名助手。")
        st.link_button("获取合装版", RELEASES + "/latest")
        return
    try:
        with socket.create_connection(("127.0.0.1", 19390), timeout=.25):
            running = True
    except OSError:
        running = False
    if running:
        st.link_button("打开报名控制台", "http://127.0.0.1:19390/", type="primary")
    elif st.button("启动报名助手", type="primary"):
        try:
            subprocess.Popen([str(bridge)], cwd=bridge.parent)
            st.success("报名助手已启动，请在它的小窗口点击「打开控制台」。")
        except OSError as exc:
            st.error(f"启动失败：{exc}")
    st.caption("现有组件支持 Mazda 个人预约。耐力赛支持选赛事、准备名单及打开 iRacing 报名页。")


def show_updates(library):
    with st.expander("版本与更新"):
        version = current_version()
        installed = getattr(sys, "frozen", False)
        combined = registration_exe().is_file()
        edition = ("合装版" if combined else "调教版") if installed else "源码版"
        st.caption(f"当前 {edition} · v{version}")
        if os.name != "nt":
            st.link_button("查看版本", RELEASES + "/latest")
            return
        if not installed:
            st.caption("安装版可在此检查更新并打开安装程序。")
            st.link_button("下载 Windows 安装包", RELEASES + "/latest")
            return
        if st.button("检查更新", key="check-installed-update"):
            st.session_state.pop("installer_offer", None)
            try:
                with st.spinner("正在检查 GitHub Release…"):
                    st.session_state["installer_offer"] = check_for_update(version, combined=combined)
            except (OSError, ValueError) as exc:
                st.error(f"检查更新失败：{exc}")
        if "installer_offer" in st.session_state:
            offer = st.session_state["installer_offer"]
            if offer is None:
                st.success("已是最新版本。")
            else:
                st.write(f"可更新到 v{offer.version}")
                if st.button("下载并打开安装程序", key="install-update"):
                    try:
                        with st.spinner("正在下载并校验安装包…"):
                            path = download(offer, library / "updates")
                        os.startfile(str(path))
                        st.success("安装程序已打开。正在运行的报名助手须先从托盘退出。")
                    except (OSError, ValueError) as exc:
                        st.error(f"更新未完成：{exc}")
