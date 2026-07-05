"""Loading ``retrace.toml``.

Uses the stdlib ``tomllib`` on Python 3.11+, and falls back to a minimal
built-in reader for the subset of TOML that retrace configs use (sections,
string/number/bool values, flat arrays, quoted keys) so that Python 3.8
works with zero dependencies.
"""

import os
import re
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_NAME = "retrace.toml"


class Config:
    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        self.data = data or {}

    # -- mapping ---------------------------------------------------------
    def mappings(self) -> Dict[str, str]:
        """old module/target prefix -> new prefix"""
        return dict(self.data.get("map", {}))

    # -- scrubbing -------------------------------------------------------
    def float_tolerance(self, boundary: str) -> float:
        per = self._boundary_scrub(boundary).get("float_tolerance")
        if per is not None:
            return float(per)
        return float(self._scrub().get("float_tolerance", 0.0))

    def ignore_fields(self, boundary: str) -> List[str]:
        fields = list(self._scrub().get("ignore_fields", []))
        fields.extend(self._boundary_scrub(boundary).get("ignore_fields", []))
        return fields

    def redact_fields(self, boundary: str) -> List[str]:
        fields = list(self._scrub().get("redact_fields", []))
        fields.extend(self._boundary_scrub(boundary).get("redact_fields", []))
        return fields

    def builtin_scrubbers(self, boundary: str) -> List[str]:
        names = list(self._scrub().get("builtin", []))
        names.extend(self._boundary_scrub(boundary).get("builtin", []))
        return names

    def regex_scrubs(self, boundary: str) -> List[Dict[str, str]]:
        entries = list(self._scrub().get("regex", []))
        entries.extend(self._boundary_scrub(boundary).get("regex", []))
        return entries

    # -- recording ---------------------------------------------------------
    def record_mutations(self) -> bool:
        record = self.data.get("record", {})
        if not isinstance(record, dict):
            return True
        return bool(record.get("mutations", True))

    # -- built-in agent ----------------------------------------------------
    def _agent(self) -> Dict[str, Any]:
        agent = self.data.get("agent", {})
        return agent if isinstance(agent, dict) else {}

    def agent_llm(self) -> Optional[str]:
        return self._agent().get("llm")

    def agent_base_url(self) -> Optional[str]:
        return self._agent().get("base_url")

    def agent_max_tokens(self) -> int:
        return int(self._agent().get("max_tokens", 8000))

    def agent_api_key_env(self) -> Optional[str]:
        return self._agent().get("api_key_env")

    # -- quality gate ------------------------------------------------------
    def quality_budgets(self) -> Dict[str, int]:
        quality = self.data.get("quality", {})
        return {k: v for k, v in quality.items()
                if k in ("max_function_lines", "max_complexity",
                         "max_nesting")}

    def quality_disabled(self) -> List[str]:
        quality = self.data.get("quality", {})
        disabled = quality.get("disable", [])
        return list(disabled) if isinstance(disabled, list) else []

    def _scrub(self) -> Dict[str, Any]:
        scrub = self.data.get("scrub", {})
        return scrub if isinstance(scrub, dict) else {}

    def _boundary_scrub(self, boundary: str) -> Dict[str, Any]:
        boundaries = self._scrub().get("boundaries", {})
        if not isinstance(boundaries, dict):
            return {}
        # longest-prefix match lets a rule for a module apply to its functions
        best = {}
        best_len = -1
        for prefix, rules in boundaries.items():
            if (boundary == prefix or boundary.startswith(prefix + ".")) \
                    and len(prefix) > best_len:
                best, best_len = rules, len(prefix)
        return best if isinstance(best, dict) else {}


def load_config(path: Optional[str] = None) -> Config:
    if path is None:
        if os.path.exists(DEFAULT_CONFIG_NAME):
            path = DEFAULT_CONFIG_NAME
        else:
            return Config()
    with open(path, "rb") as f:
        raw = f.read()
    try:
        import tomllib  # Python 3.11+
        return Config(tomllib.loads(raw.decode("utf-8")))
    except ImportError:
        return Config(_parse_toml_subset(raw.decode("utf-8"), path))


# ---------------------------------------------------------------------------
# Minimal TOML-subset reader (fallback for Python < 3.11).
# Supports: [section], [a.b."quoted.key"], key = value where value is a
# string, int, float, bool, or a flat array of those. Comments and blank
# lines are ignored. Anything else raises with a clear message.
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^\[(.+)\]$")


def _split_dotted(key_path: str) -> List[str]:
    parts = []
    buf = ""
    in_quote = None
    for ch in key_path:
        if in_quote:
            if ch == in_quote:
                in_quote = None
            else:
                buf += ch
        elif ch in ("'", '"'):
            in_quote = ch
        elif ch == ".":
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    parts.append(buf.strip())
    return [p for p in parts if p != ""]


def _parse_value(text: str, where: str) -> Any:
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        items = []
        buf = ""
        in_quote = None
        for ch in inner:
            if in_quote:
                buf += ch
                if ch == in_quote:
                    in_quote = None
            elif ch in ("'", '"'):
                in_quote = ch
                buf += ch
            elif ch == ",":
                items.append(_parse_value(buf, where))
                buf = ""
            else:
                buf += ch
        if buf.strip():
            items.append(_parse_value(buf, where))
        return items
    if (text.startswith('"') and text.endswith('"') and len(text) >= 2) or \
       (text.startswith("'") and text.endswith("'") and len(text) >= 2):
        return text[1:-1]
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        if re.fullmatch(r"[+-]?\d+", text):
            return int(text)
        return float(text)
    except ValueError:
        raise ValueError(
            "retrace.toml: cannot parse value %r (%s). The built-in reader "
            "supports strings, numbers, booleans and flat arrays." % (text, where)
        )


def _parse_toml_subset(text: str, path: str) -> Dict[str, Any]:
    root = {}  # type: Dict[str, Any]
    current = root
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        where = "%s:%d" % (path, lineno)
        m = _SECTION_RE.match(line)
        if m:
            current = root
            for part in _split_dotted(m.group(1)):
                current = current.setdefault(part, {})
                if not isinstance(current, dict):
                    raise ValueError("retrace.toml: section conflicts with "
                                     "existing key (%s)" % where)
            continue
        if "=" not in line:
            raise ValueError("retrace.toml: expected 'key = value' (%s)" % where)
        key_text, _, value_text = line.partition("=")
        # strip trailing comments outside quotes
        value_text = _strip_comment(value_text)
        keys = _split_dotted(key_text)
        target = current
        for part in keys[:-1]:
            target = target.setdefault(part, {})
        target[keys[-1]] = _parse_value(value_text, where)
    return root


def _strip_comment(value_text: str) -> str:
    out = ""
    in_quote = None
    for ch in value_text:
        if in_quote:
            out += ch
            if ch == in_quote:
                in_quote = None
        elif ch in ("'", '"'):
            in_quote = ch
            out += ch
        elif ch == "#":
            break
        else:
            out += ch
    return out
