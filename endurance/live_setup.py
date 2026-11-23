"""Read only the published IRSDK shared-memory session block; never control the sim.

Protocol reference: iRacing's irsdk_defines.h (original publisher's header mirrored
at https://github.com/vipoo/irsdk/blob/master/irsdk_defines.h). No SDK code copied.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import struct
import time

import yaml

from endurance.ibt import _metadata


def session_bounds(header: bytes) -> tuple[int, int, int, int]:
    if len(header) < 112:
        raise ValueError("共享内存头不完整")
    version, status, rate, update, length, offset = struct.unpack_from("<6i", header)
    if version not in (1, 2) or not status & 1:
        raise ValueError("模拟器尚未连接")
    if not 1 <= rate <= 1000 or not 1 <= length <= 8_000_000 or not 112 <= offset <= 16_000_000:
        raise ValueError("共享内存范围异常")
    return offset, length, update, rate


def decode_session(header: bytes, session: bytes, after_header: bytes) -> dict:
    offset, length, update, rate = session_bounds(header)
    if session_bounds(after_header) != (offset, length, update, rate):
        raise ValueError("设置正在更新，稍后重新读取")
    if len(session) != length:
        raise ValueError("会话数据不完整")
    doc = yaml.safe_load(session.split(b"\0", 1)[0].decode("utf-8", errors="replace"))
    if not isinstance(doc, dict) or not isinstance(doc.get("CarSetup"), dict):
        raise ValueError("游戏尚未提供车辆设置")
    meta = _metadata(doc, int(time.time()), rate, [])
    if not meta.get("setup_flat") or meta["car"] == "unknown":
        raise ValueError("车辆设置尚未就绪")
    meta.update(context_source="模拟器 SDK 当前会话设置", source_kind="live_sdk",
                source_name="当前游戏设置", observed_at=datetime.now(timezone.utc).isoformat(),
                setup_scope="SDK 会话中的设置快照；尚未读取 Garage Tech 检查结果")
    return meta


def mapped_length(header):
    offset, length, _, _ = session_bounds(header)
    count, variables, buffers, row_size = struct.unpack_from("<4i", header, 24)
    if not 0 < count < 5000 or not 112 <= variables < 32_000_000 or not 1 <= buffers <= 4 or not 0 < row_size < 1_000_000:
        raise ValueError("变量区域异常")
    ends = [offset + length, variables + count * 144]
    for i in range(buffers):
        row = struct.unpack_from("<i", header, 52 + 16 * i)[0]
        if row < 112:
            raise ValueError("采样偏移异常")
        ends.append(row + row_size)
    size = max(ends)
    if size > 32_000_000:
        raise ValueError("共享内存长度异常")
    return size


def read_conditions(blob, header):
    """Only scalars needed to identify current conditions; not a streaming recorder."""
    if len(blob) < mapped_length(header):
        raise ValueError("共享内存采样不完整")
    count, variables, buffers, row_size = struct.unpack_from("<4i", header, 24)
    idx = max(range(buffers), key=lambda i: struct.unpack_from("<i", header, 48 + 16 * i)[0])
    row = struct.unpack_from("<i", header, 52 + 16 * idx)[0]
    result = {}
    formats = {1: "?", 2: "i", 3: "I", 4: "f", 5: "d"}
    wanted = {"TrackWetness": (2, "irsdk_TrackWetness"), "FuelLevel": (4, "l"), "IsOnTrack": (1, ""), "IsInGarage": (1, "")}
    for i in range(count):
        block = variables + 144 * i
        name = blob[block + 16:block + 48].split(b"\0")[0].decode("ascii", errors="replace")
        if name not in wanted:
            continue
        kind, off, n = struct.unpack_from("<iii", blob, block)
        unit = blob[block + 112:block + 144].split(b"\0")[0].decode("ascii", errors="replace")
        if (kind, unit) != wanted[name] or n != 1 or off < 0 or off + struct.calcsize("<" + formats[kind]) > row_size:
            continue
        result[name] = struct.unpack_from("<" + formats[kind], blob, row + off)[0]
    return result


def read_live_setup() -> tuple[dict | None, str]:
    if os.name != "nt":
        return None, "当前系统没有 Windows iRacing 共享内存"
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenFileMappingW.restype = wintypes.HANDLE
    kernel.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    kernel.MapViewOfFile.restype = ctypes.c_void_p
    kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenFileMappingW(4, False, "Local\\IRSDKMemMapFileName")  # FILE_MAP_READ only
    if not handle:
        return None, "尚未连接模拟器；进入练习并加载车辆后，可点击重新读取"
    pointer = None
    try:
        pointer = kernel.MapViewOfFile(handle, 4, 0, 0, 112)
        if not pointer:
            return None, "暂时无法读取游戏设置"
        header = ctypes.string_at(pointer, 112)
        offset, length, _, _ = session_bounds(header)
        size = mapped_length(header)
        kernel.UnmapViewOfFile(pointer)
        pointer = kernel.MapViewOfFile(handle, 4, 0, 0, size)
        if not pointer:
            return None, "游戏会话仍在初始化"
        blob = ctypes.string_at(pointer, size)
        after = ctypes.string_at(pointer, 112)
        meta = decode_session(header, blob[offset:offset + length], after)
        conditions = read_conditions(blob, header)
        meta["observed_wetness"] = [conditions["TrackWetness"]] if "TrackWetness" in conditions else []
        meta["live_conditions"] = conditions
        return meta, "已读取模拟器当前设置"
    except (ValueError, yaml.YAMLError, OSError, TypeError, KeyError) as exc:
        return None, f"暂未取得当前设置：{exc}"
    finally:
        if pointer:
            kernel.UnmapViewOfFile(pointer)
        kernel.CloseHandle(handle)
