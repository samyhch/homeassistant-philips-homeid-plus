"""Build a HACS-compatible archive only when tag and manifest version match."""

import argparse
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "philips_homeid_plus"


def build_release(tag, destination):
    version = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))["version"]
    if tag != f"v{version}":
        raise ValueError(f"Tag {tag!r} must match manifest version v{version}")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(COMPONENT.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, path.relative_to(COMPONENT).as_posix())
        for notice in ("LICENSE", "NOTICE.md"):
            archive.write(ROOT / notice, notice)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--output", default="dist/philips_homeid_plus.zip")
    args = parser.parse_args()
    print(build_release(args.tag, args.output))
