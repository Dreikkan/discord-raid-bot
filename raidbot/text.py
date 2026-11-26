from __future__ import annotations

import re

_MARKDOWN_RE = re.compile(r"([\\*_~`|>])")


def escape_markdown(value: object) -> str:
    """Escape Discord markdown characters in user-controlled display text."""

    return _MARKDOWN_RE.sub(r"\\\1", str(value))
