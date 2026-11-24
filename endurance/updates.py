"""Check and download the matching installer from the project's GitHub release."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import tomllib
from urllib.request import Request, urlopen

from endurance.paths import ROOT


REPOSITORY = "XiaoyangSu-Sam/ir_setup_helper"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_INSTALLER = 512 * 1024 * 1024


@dataclass(frozen=True)
class Installer:
    version: str
    name: str
    url: str
    checksum: str
    size: int


def current_version():
    with (ROOT / "pyproject.toml").open("rb") as source:
        return tomllib.load(source)["project"]["version"]


def _version(value):
    if not re.fullmatch(r"\d{1,6}\.\d{1,6}\.\d{1,6}", value):
        raise ValueError("版本号格式无效。")
    return tuple(map(int, value.split(".")))


def release_offer(release, installed, *, combined):
    tag = release.get("tag_name", "")
    if release.get("draft") or release.get("prerelease") or not isinstance(tag, str) or not tag.startswith("v"):
        raise ValueError("未找到可用的正式版本。")
    version = tag[1:]
    if _version(version) <= _version(installed):
        return None
    product = "IRacingTools" if combined else "IRSetupHelper"
    name = f"{product}-{version}-windows-x64-setup.exe"
    assets = [asset for asset in release.get("assets", []) if asset.get("name") == name]
    if len(assets) != 1:
        raise ValueError("该版本缺少对应的安装包。")
    digest, size = assets[0].get("digest"), assets[0].get("size")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        raise ValueError("该版本没有可用的 SHA-256 校验值。")
    if type(size) is not int or not 0 < size <= MAX_INSTALLER:
        raise ValueError("安装包大小无效。")
    return Installer(version, name, f"{RELEASES}/download/{tag}/{name}", digest[7:].lower(), size)


def check_for_update(installed, *, combined):
    request = Request(API, headers={"User-Agent": "IRacingTools", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=15) as response:
        release = json.loads(response.read(1024 * 1024))
    return release_offer(release, installed, combined=combined)


def download(offer, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    checksum, count = sha256(), 0
    temp = None
    try:
        with NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as stream:
            temp = Path(stream.name)
            with urlopen(offer.url, timeout=30) as response:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > offer.size:
                        raise ValueError("安装包大小校验失败。")
                    stream.write(chunk)
                    checksum.update(chunk)
        if count != offer.size or checksum.hexdigest() != offer.checksum:
            raise ValueError("安装包 SHA-256 或大小校验失败。")
        target = directory / offer.name
        os.replace(temp, target)
        return target
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
