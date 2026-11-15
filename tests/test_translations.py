"""Every translation must have the same keys and placeholders as the English one."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest

TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / "apple_tv_output" / "translations"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten(value, path))
        else:
            result[path] = value
    return result


ENGLISH = flatten(json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", sorted(p for p in TRANSLATIONS.glob("*.json") if p.name != "en.json"), ids=str)
def test_translation_matches_english(path: Path) -> None:
    other = flatten(json.loads(path.read_text(encoding="utf-8")))
    assert other.keys() == ENGLISH.keys()
    for key, text in ENGLISH.items():
        assert set(PLACEHOLDER.findall(other[key])) == set(PLACEHOLDER.findall(text)), key
        assert other[key].strip(), key
