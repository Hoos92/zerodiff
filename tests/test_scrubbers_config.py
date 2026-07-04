import pytest

from retrace import scrubbers
from retrace.config import Config, _parse_toml_subset


class TestScrub:
    def test_ignore_field_by_key_anywhere(self):
        tree = {"data": {"generated_at": "now", "value": 1}}
        out = scrubbers.scrub(tree, ["*.generated_at"], [])
        assert out["data"]["generated_at"] == scrubbers.SCRUBBED
        assert out["data"]["value"] == 1

    def test_ignore_field_by_exact_path(self):
        tree = {"a": {"id": 1}, "b": {"id": 2}}
        out = scrubbers.scrub(tree, ["output.a.id"], [])
        assert out["a"]["id"] == scrubbers.SCRUBBED
        assert out["b"]["id"] == 2

    def test_uuid_builtin_scrubs_inside_strings(self):
        rx = scrubbers.BUILTIN_PATTERNS["uuid"]
        out = scrubbers.scrub(
            "id=123e4567-e89b-12d3-a456-426614174000 ok", [], [rx])
        assert "123e4567" not in out and "ok" in out

    def test_timestamp_builtin(self):
        rx = scrubbers.BUILTIN_PATTERNS["timestamp"]
        out = scrubbers.scrub("at 2026-07-03T10:00:00Z done", [], [rx])
        assert "2026" not in out and "done" in out

    def test_marker_nodes_are_not_treated_as_fields(self):
        # a __tuple__ marker key must never match an ignore pattern
        tree = {"__tuple__": [1, 2]}
        out = scrubbers.scrub(tree, ["*.__tuple__"], [])
        assert out == {"__tuple__": [1, 2]}

    def test_unknown_builtin_raises(self):
        cfg = Config({"scrub": {"builtin": ["nope"]}})
        with pytest.raises(ValueError):
            scrubbers.compile_scrubbers(cfg, "mod.fn")


class TestConfig:
    TOML = """
# comment
[map]
"billing.pricing" = "billing_v2.pricing"

[scrub]
float_tolerance = 1e-9
builtin = ["uuid", "timestamp"]
ignore_fields = ["*.request_id"]

[scrub.boundaries."billing.pricing.make_receipt"]
ignore_fields = ["generated_at"]
float_tolerance = 0.01
"""

    def _cfg(self):
        return Config(_parse_toml_subset(self.TOML, "test.toml"))

    def test_mappings(self):
        assert self._cfg().mappings() == {
            "billing.pricing": "billing_v2.pricing"}

    def test_global_scrub(self):
        cfg = self._cfg()
        assert cfg.float_tolerance("other.fn") == 1e-9
        assert cfg.builtin_scrubbers("other.fn") == ["uuid", "timestamp"]

    def test_boundary_scrub_merges_and_overrides(self):
        cfg = self._cfg()
        assert cfg.float_tolerance("billing.pricing.make_receipt") == 0.01
        assert cfg.ignore_fields("billing.pricing.make_receipt") == [
            "*.request_id", "generated_at"]

    def test_longest_prefix_wins(self):
        cfg = Config({"scrub": {"boundaries": {
            "a": {"float_tolerance": 1.0},
            "a.b": {"float_tolerance": 2.0},
        }}})
        assert cfg.float_tolerance("a.b.fn") == 2.0
        assert cfg.float_tolerance("a.other") == 1.0

    def test_parse_values(self):
        data = _parse_toml_subset(
            'x = 5\ny = true\nz = "s"\narr = [1, "two"]\nf = 1.5\n', "t")
        assert data == {"x": 5, "y": True, "z": "s", "arr": [1, "two"],
                        "f": 1.5}

    def test_parse_rejects_garbage_with_location(self):
        with pytest.raises(ValueError) as exc:
            _parse_toml_subset("x = {inline = 1}\n", "bad.toml")
        assert "bad.toml:1" in str(exc.value)

    def test_trailing_comment_stripped_outside_quotes(self):
        data = _parse_toml_subset('x = "a # b"  # real comment\n', "t")
        assert data == {"x": "a # b"}
