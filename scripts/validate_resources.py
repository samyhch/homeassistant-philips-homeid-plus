"""Validate JSON uniqueness, translated placeholders and example YAML syntax."""
import json
from pathlib import Path
from string import Formatter

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/philips_homeid_plus"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def strings(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from strings(child, (*path, key))
    elif isinstance(value, str):
        yield path, value


def placeholders(value):
    return {name for _, name, _, _ in Formatter().parse(value) if name}


def main():
    source = dict(strings(json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)))
    count = 0
    for path in COMPONENT.rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
        if path.parent == COMPONENT / "translations":
            for key, value in strings(data):
                if key in source and placeholders(value) != placeholders(source[key]):
                    raise ValueError(f"{path.name}: placeholder mismatch at {'.'.join(key)}")
        count += 1
    for folder in (".github", "examples", "blueprints"):
        for path in (ROOT / folder).rglob("*.yaml"):
            # HA's !input is a scalar reference, not executable YAML.
            loader = type("HALoader", (yaml.SafeLoader,), {})
            loader.add_constructor("!input", lambda loader, node: loader.construct_scalar(node))
            yaml.load(path.read_text(encoding="utf-8-sig"), Loader=loader)
            count += 1
        for path in (ROOT / folder).rglob("*.yml"):
            yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            count += 1
    print(f"Validated {count} resource files and translated placeholders")


if __name__ == "__main__":
    main()
