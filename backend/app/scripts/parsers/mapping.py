"""Evaluate compact mapping expressions against raw source payloads.

Supported expression forms (no third-party JSONPath dependency):

- dot/bracket path:      ``server.packages[0].identifier``
- equality filter:       ``server.packages[?(@.registryType=='npm')].identifier``
- default fallback:      ``server.title || 'Untitled'``
- literal value:         ``'free'``
- transform filter:      ``server.repository.url | extract_github_avatar``
"""

import re
from typing import Any

_FILTER_RE = re.compile(
    r"^(?P<base>[^\[]+)\[\?\(@\.(?P<key>[A-Za-z0-9_]+)\s*"
    r"(?P<op>==|!=)\s*'(?P<value>[^']*)'\)\]$"
)
_INDEX_RE = re.compile(r"^(?P<base>[^\[]+)\[(?P<index>\d+)\]$")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def evaluate_mappings(raw: dict, mappings: dict) -> dict:
    """Return ``{field: value}`` with each mapping expression evaluated."""
    return {field: _evaluate(expr, raw) for field, expr in mappings.items()}


def _evaluate(expr: Any, raw: dict) -> Any:
    if not isinstance(expr, str):
        return expr

    expr = expr.strip()
    if len(expr) >= 2 and expr[0] == expr[-1] == "'":
        return expr[1:-1]

    if " || " in expr:
        left, right = expr.split(" || ", 1)
        value = _evaluate(left, raw)
        if value is None or value == "" or value == []:
            return _evaluate(right, raw)
        return value

    if " | " in expr:
        path, function = expr.split(" | ", 1)
        return _apply_filter(function.strip(), _evaluate(path, raw))

    if expr in ("true", "false"):
        return expr == "true"
    if expr in ("null", "None"):
        return None
    if _NUMBER_RE.match(expr):
        return float(expr) if "." in expr else int(expr)

    return _resolve_path(raw, expr)


def _tokenize(path: str) -> list[str]:
    """Split on dots that are outside ``[...]`` brackets."""
    tokens: list[str] = []
    buffer: list[str] = []
    depth = 0
    for char in path.replace("?.", "."):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if char == "." and depth == 0:
            tokens.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    if buffer:
        tokens.append("".join(buffer))
    return [token for token in tokens if token]


def _resolve_path(raw: dict, path: str) -> Any:
    current: Any = raw
    for token in _tokenize(path):
        if not isinstance(current, dict):
            return None

        filter_match = _FILTER_RE.match(token)
        if filter_match:
            current = current.get(filter_match.group("base"))
            if not isinstance(current, list):
                return None
            key = filter_match.group("key")
            expected = filter_match.group("value")
            negate = filter_match.group("op") == "!="
            current = next(
                (
                    item
                    for item in current
                    if isinstance(item, dict)
                    and ((item.get(key) != expected) if negate else (item.get(key) == expected))
                ),
                None,
            )
            continue

        index_match = _INDEX_RE.match(token)
        if index_match:
            current = current.get(index_match.group("base"))
            index = int(index_match.group("index"))
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
            continue

        current = current.get(token)

    return current


def _apply_filter(function: str, value: Any) -> Any:
    if function == "extract_github_avatar":
        match = re.search(r"github\.com/([^/]+)", value or "")
        if not match:
            return None
        return f"https://github.com/{match.group(1)}.png?size=200"
    if function == "scope_from_remotes":
        return "cloud" if value else "local"
    raise ValueError(f"Unknown mapping filter: {function}")
