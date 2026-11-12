"""Package current nonignored source and the documentation PDF with verified bytes.

From the root: python submission/package_submission.py
Use --output NAME.zip to select a different new archive; existing archives are preserved.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def ignored(paths):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=ROOT, input=b"\0".join(paths) + b"\0", stdout=subprocess.PIPE, check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("Git ignore check failed")
    return set(p for p in result.stdout.split(b"\0") if p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="Resolve_Submission_With_Documentation.zip")
    args = parser.parse_args()
    destination = ROOT / args.output
    if not destination.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Output must remain inside the source directory")
    if destination.exists():
        raise FileExistsError("Existing archive preserved; choose a new --output")
    raw = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
    )
    candidates = sorted(set(p for p in raw.split(b"\0") if p))
    excluded = ignored(candidates)
    selected = []
    for candidate in candidates:
        name = candidate.decode("utf-8")
        relative = PurePosixPath(name)
        source = ROOT / name
        if candidate in excluded or relative.parts[0] in (".git", ".agents", ".codex"):
            continue
        if relative.suffix.lower() in (".zip", ".7z", ".tar", ".gz") or not source.is_file():
            continue
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f"Unsafe source path: {name}")
        selected.append(name)
    required = {
        "output/pdf/Resolve_Technical_Documentation.pdf", "SUBMISSION_README.md",
        "submission/Resolve_Technical_Documentation.md", "postman/contracts/resolve.openapi.json",
    }
    if not required.issubset(selected):
        raise ValueError(f"Missing required deliverables: {required - set(selected)}")
    expected = {}
    uncompressed = 0
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in selected:
            data = (ROOT / name).read_bytes()
            member = "Resolve/" + name
            expected[member] = hashlib.sha256(data).hexdigest()
            uncompressed += len(data)
            archive.writestr(member, data)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC failure")
        if len(archive.infolist()) != len(expected) or set(archive.namelist()) != set(expected):
            raise ValueError("Archive member set mismatch")
        for item in archive.infolist():
            rel = PurePosixPath(item.filename)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("Unsafe archive member")
            if hashlib.sha256(archive.read(item)).hexdigest() != expected[item.filename]:
                raise ValueError(f"Content mismatch: {item.filename}")
    if ignored([name.encode("utf-8") for name in selected]):
        raise ValueError("Archive includes an ignored path")
    if destination.stat().st_size >= 35_000_000:
        raise ValueError("Archive exceeds the 35 MB submission limit")
    result = {
        "file": str(destination), "files": len(selected), "bytes": destination.stat().st_size,
        "source_bytes": uncompressed, "postman_files": sum(n.startswith("postman/") for n in selected),
        "ignored_members": 0, "crc": "passed", "content_hashes": "all match",
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }
    qa = ROOT / "tmp/pdfs"
    qa.mkdir(parents=True, exist_ok=True)
    (qa / "archive_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
