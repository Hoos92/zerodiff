import datetime
import decimal
import math

import pytest

from nodrift import serializer


class TestRoundTrip:
    @pytest.mark.parametrize("value", [
        None, True, False, 0, -17, 3.5, "hello", "",
        [1, 2, [3, "x"]],
        (1, 2, (3,)),
        {"a": 1, "b": {"c": [1.5]}},
        {1: "one", (2, 3): "pair"},
        {1, 2, 3},
        frozenset({"a", "b"}),
        b"\x00\xffbytes",
        bytearray(b"mut"),
        datetime.datetime(2026, 7, 3, 12, 30, 15),
        datetime.date(1999, 12, 31),
        datetime.time(23, 59, 59),
        decimal.Decimal("10.250"),
    ])
    def test_round_trip(self, value):
        decoded = serializer.decode(serializer.encode(value))
        assert decoded == value
        assert type(decoded) is type(value)

    def test_nan_round_trips(self):
        decoded = serializer.decode(serializer.encode(float("nan")))
        assert math.isnan(decoded)

    def test_inf_round_trips(self):
        assert serializer.decode(serializer.encode(float("inf"))) == \
            float("inf")
        assert serializer.decode(serializer.encode(float("-inf"))) == \
            float("-inf")

    def test_tuple_and_list_encode_differently(self):
        assert serializer.encode((1, 2)) != serializer.encode([1, 2])


class TestOpaque:
    def test_arbitrary_object_becomes_opaque(self):
        class Widget:
            pass

        tree = serializer.encode(Widget())
        assert "__opaque__" in tree
        assert "Widget" in tree["__opaque__"]["type"]
        assert tree["__opaque__"]["digest"]

    def test_opaque_digest_is_stable_across_instances(self):
        # reprs contain memory addresses; digests must not
        class Widget:
            pass

        d1 = serializer.encode(Widget())["__opaque__"]["digest"]
        d2 = serializer.encode(Widget())["__opaque__"]["digest"]
        assert d1 == d2

    def test_decode_opaque_raises(self):
        tree = serializer.encode(object())
        with pytest.raises(serializer.OpaqueValueError):
            serializer.decode(tree)

    def test_contains_opaque(self):
        tree = serializer.encode({"ok": 1, "bad": object()})
        assert serializer.contains_opaque(tree)
        assert not serializer.contains_opaque(serializer.encode({"ok": 1}))

    def test_cycle_degrades_instead_of_crashing(self):
        loop = []
        loop.append(loop)
        tree = serializer.encode(loop)
        assert tree == [{"__cycle__": True}]

    def test_repr_failure_does_not_crash(self):
        class Evil:
            def __repr__(self):
                raise RuntimeError("no repr for you")

        tree = serializer.encode(Evil())
        assert tree["__opaque__"]["repr"] == "<repr failed>"


class TestCanonical:
    def test_dict_key_order_is_irrelevant(self):
        a = serializer.canonical_json(serializer.encode({"x": 1, "y": 2}))
        b = serializer.canonical_json(serializer.encode({"y": 2, "x": 1}))
        assert a == b

    def test_set_order_is_irrelevant(self):
        a = serializer.canonical_json(serializer.encode({3, 1, 2}))
        b = serializer.canonical_json(serializer.encode({2, 3, 1}))
        assert a == b
