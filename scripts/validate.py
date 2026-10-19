"""Validate source syntax and JSON without importing HA or writing bytecode."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    failures = []
    paths = list((ROOT / "custom_components").rglob("*.py"))
    paths += list((ROOT / "tests").rglob("*.py"))
    paths += list((ROOT / "scripts").rglob("*.py"))
    for path in paths:
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, UnicodeError) as err:
            failures.append(f"{path.relative_to(ROOT)}: {err}")
    json_paths = list((ROOT / "custom_components").rglob("*.json")) + [ROOT / "hacs.json"]
    for path in json_paths:
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError) as err:
            failures.append(f"{path.relative_to(ROOT)}: {err}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Validated {len(paths)} Python files and {len(json_paths)} JSON files.")


if __name__ == "__main__":
    main()
