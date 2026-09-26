from pathlib import Path
import re
import sys

import yaml

root = Path(__file__).resolve().parents[1]
errors = []
skills = list((root / ".agents" / "skills").glob("*/SKILL.md"))
if not skills:
    errors.append("No discoverable project skills")
names = set()
for path in skills:
    text = path.read_text(encoding="utf-8")
    try:
        metadata = yaml.safe_load(text.split("---", 2)[1])
        name = metadata["name"]
        if not re.fullmatch(r"[a-z0-9-]{1,64}", name) or name != path.parent.name:
            errors.append(f"Invalid name: {path}")
        if name in names:
            errors.append(f"Duplicate skill: {name}")
        names.add(name)
        if not isinstance(metadata["description"], str) or not metadata["description"].strip():
            errors.append(f"Missing description: {path}")
        for reference in re.findall(r"`((?:docs|examples)/[^`]+)`", text):
            if not (root / reference).exists():
                errors.append(f"Missing resource {reference} in {path}")
    except (IndexError, KeyError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"Invalid skill {path}: {exc}")
if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(f"Validated {len(skills)} discoverable skills and their resources")
