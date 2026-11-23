"""Stage only the files needed to run the registration assistant."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from tempfile import mkdtemp
from zipfile import ZIP_DEFLATED, ZipFile


SERVER_FILES = {
    "bridge-client.mjs", "endurance.mjs", "maintenance.mjs", "phone.mjs",
    "race-details.mjs", "racing.mjs", "recovery-bridge.mjs", "recovery.mjs",
    "scheduler.mjs", "season-catalog.mjs", "server.mjs", "special-events.mjs",
    "store.mjs", "team-directory.mjs", "team-plan.mjs", "team-progress.mjs",
    "verification.mjs",
}
REQUIRED = SERVER_FILES | {
    "NativeBridge.exe", "runtime.json", "practice-validation.json",
    "web/app.js", "web/index.html", "web/style.css", "web/support.js", "web/team.js",
    "runtime/node/node.exe", "runtime/node/LICENSE.txt",
    "runtime/pdfjs/LICENSE", "runtime/pdfjs/package.json",
    "runtime/pdfjs/legacy/build/pdf.mjs", "runtime/pdfjs/legacy/build/pdf.worker.mjs",
}
OPTIONAL = {
    f"runtime/node/{name}.dll" for name in (
        "concrt140", "msvcp140", "msvcp140_1", "msvcp140_2", "msvcp140_atomic_wait",
        "msvcp140_codecvt_ids", "vccorlib140", "vcruntime140", "vcruntime140_1",
        "vcruntime140_threads",
    )
}
NON_RUNTIME = {"NativeBridge.cs", "启动报名助手.cmd", "新手使用说明.md"}


def stage(package: Path, build: Path) -> Path:
    sidecar = package.with_suffix(package.suffix + ".sha256")
    if sidecar.exists():
        with package.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != sidecar.read_text(encoding="utf-8-sig").split()[0].lower():
            raise ValueError("Registration ZIP checksum does not match.")

    with ZipFile(package) as archive:
        files = {}
        roots = set()
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            parts = PurePosixPath(entry.filename).parts
            if len(parts) < 2 or parts[0] in {"/", "..", "."} or ".." in parts or "\\" in entry.filename:
                raise ValueError("Unexpected path in the registration ZIP.")
            roots.add(parts[0])
            relative = "/".join(parts[1:])
            if relative in files:
                raise ValueError("Duplicate path in the registration ZIP.")
            files[relative] = entry
        allowed = REQUIRED | OPTIONAL | NON_RUNTIME | {"manifest.json"}
        if len(roots) != 1 or not REQUIRED | {"manifest.json"} <= files.keys() or files.keys() - allowed:
            raise ValueError("Use the clean registration assistant share ZIP with its bundled runtimes.")

        manifest = {record["path"]: record for record in json.loads(archive.read(files["manifest.json"]))}
        build.mkdir(parents=True, exist_ok=True)
        dest = Path(mkdtemp(prefix="registration-", dir=build)).resolve()
        for relative in sorted(files.keys() & (REQUIRED | OPTIONAL)):
            data = archive.read(files[relative])
            record = manifest[relative]
            if record["bytes"] != len(data) or record["sha256"].lower() != hashlib.sha256(data).hexdigest():
                raise ValueError(f"Registration package verification failed for {relative}.")
            if relative == "runtime.json" and json.loads(data)["nodePath"] != r"runtime\node\node.exe":
                raise ValueError("The registration assistant must use its bundled Node runtime.")
            if relative == "practice-validation.json":
                # Do not carry the original driver's observations into a clean install.
                data = json.dumps({"checks": [], "method": "本机尚无车队实测记录。"}).encode()
            file = dest / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        return dest


def export_runtime(staged: Path, output: Path):
    """Publish the staged runtime without the original ZIP's development files."""
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(staged.rglob("*")):
            if not file.is_file():
                continue
            relative = file.relative_to(staged).as_posix()
            if relative not in REQUIRED | OPTIONAL:
                raise ValueError(f"Unexpected file in the staged runtime: {relative}")
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            manifest.append({"path": relative, "sha256": digest, "bytes": file.stat().st_size})
            archive.write(file, f"registration/{relative}")
        archive.writestr("registration/manifest.json", json.dumps(manifest))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("package", type=Path)
    cli.add_argument("build", type=Path)
    cli.add_argument("--export-runtime", type=Path)
    args = cli.parse_args()
    staged = stage(args.package, args.build)
    if args.export_runtime:
        export_runtime(staged, args.export_runtime)
        print(args.export_runtime)
    else:
        print(staged)
