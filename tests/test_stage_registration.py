import hashlib
import json
from zipfile import ZipFile

import pytest

from scripts.stage_registration import PROJECT_OVERRIDES, REQUIRED, export_runtime, stage


def registration_archive(path, private_file=False, corrupted=False):
    files = dict.fromkeys(REQUIRED, b"fixture")
    files["runtime.json"] = json.dumps({"nodePath": r"runtime\node\node.exe"}).encode()
    files["practice-validation.json"] = b'{"method":"driver-specific data"}'
    if private_file:
        files["data/tasks.sqlite"] = b"must stay local"
    manifest = [{"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                for name, payload in files.items()]
    if corrupted:
        files["NativeBridge.exe"] = b"changed"
    with ZipFile(path, "w") as archive:
        for name, payload in files.items():
            archive.writestr(f"share/{name}", payload)
        archive.writestr("share/manifest.json", json.dumps(manifest))


def test_registration_package_keeps_only_runtime_files(tmp_path):
    package = tmp_path / "share.zip"
    registration_archive(package)
    result = stage(package, tmp_path / "build")
    assert (result / "NativeBridge.exe").read_bytes() == b"fixture"
    assert not (result / "data").exists()
    assert "driver-specific" not in (result / "practice-validation.json").read_text()
    public = tmp_path / "runtime.zip"
    export_runtime(result, public)
    with ZipFile(public) as archive:
        assert set(archive.namelist()) == {f"registration/{file}" for file in REQUIRED | {"manifest.json"}}
    reinstalled = stage(public, tmp_path / "public-install")
    assert (reinstalled / "NativeBridge.exe").read_bytes() == b"fixture"
    assert not (reinstalled / "data").exists()


@pytest.mark.parametrize(("private_file", "corrupted", "message"), [
    (True, False, "clean registration assistant share ZIP"),
    (False, True, "verification failed"),
])
def test_registration_package_rejects_private_or_changed_files(tmp_path, private_file, corrupted, message):
    package = tmp_path / "share.zip"
    registration_archive(package, private_file=private_file, corrupted=corrupted)
    with pytest.raises(ValueError, match=message):
        stage(package, tmp_path / "build")


def test_project_registration_overrides_are_allowlisted(tmp_path):
    package = tmp_path / "share.zip"
    registration_archive(package)
    overrides = tmp_path / "overrides"
    for name in PROJECT_OVERRIDES:
        file = overrides / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"project version")
    (overrides / "endurance.mjs").write_bytes(b"unexpected override")
    (overrides / "access-token.txt").write_bytes(b"unrelated file")
    result = stage(package, tmp_path / "build", overrides)
    for name in PROJECT_OVERRIDES:
        assert (result / name).read_bytes() == b"project version"
    assert (result / "endurance.mjs").read_bytes() == b"fixture"
    assert not (result / "access-token.txt").exists()
