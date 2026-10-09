import re
from typing import Any

PATTERNS = {
    "api_key": re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AGDEMO_[A-Za-z0-9]{16,})\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
}


def redact(value: Any) -> tuple[Any, dict[str, int]]:
    """Recursively redact supported patterns. Counts include repeated occurrences."""
    counts: dict[str, int] = {}

    def visit(item):
        if isinstance(item, str):
            for label, pattern in PATTERNS.items():
                item, n = pattern.subn(f"[REDACTED:{label}]", item)
                if n:
                    counts[label] = counts.get(label, 0) + n
            return item
        if isinstance(item, list):
            return [visit(x) for x in item]
        if isinstance(item, dict):
            return {visit(str(k)): visit(v) for k, v in item.items()}
        return item

    return visit(value), counts
