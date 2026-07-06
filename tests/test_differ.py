from nodrift import differ, serializer


def _diff(expected_value, actual_value, tolerance=0.0):
    return differ.diff_output(
        {"type": "return", "value": serializer.encode(expected_value)},
        {"type": "return", "value": serializer.encode(actual_value)},
        boundary="mod.fn", trace_id="t1", input_preview="(1)",
        float_tolerance=tolerance)


def _kinds(divs):
    return [d.kind for d in divs]


class TestValues:
    def test_identical_values_match(self):
        divs, weak = _diff({"a": [1, "x", (2.5,)]}, {"a": [1, "x", (2.5,)]})
        assert divs == [] and weak == 0

    def test_value_mismatch_with_path(self):
        divs, _ = _diff({"total": 10.0}, {"total": 10.5})
        assert _kinds(divs) == [differ.KIND_VALUE]
        assert divs[0].path == "output.total"
        assert divs[0].expected == 10.0 and divs[0].actual == 10.5
        assert "output.total" in divs[0].hint

    def test_float_tolerance_suppresses_noise(self):
        divs, _ = _diff(1.0, 1.0 + 1e-12, tolerance=1e-9)
        assert divs == []

    def test_float_tolerance_does_not_hide_real_change(self):
        divs, _ = _diff(1.0, 1.1, tolerance=1e-9)
        assert _kinds(divs) == [differ.KIND_VALUE]

    def test_nan_matches_nan(self):
        divs, _ = _diff(float("nan"), float("nan"))
        assert divs == []

    def test_list_length_change(self):
        divs, _ = _diff([1, 2, 3], [1, 2])
        assert any(d.path == "output.length" for d in divs)


class TestTypes:
    def test_tuple_vs_list_is_type_mismatch(self):
        divs, _ = _diff((1, 2), [1, 2])
        assert _kinds(divs) == [differ.KIND_TYPE]

    def test_int_vs_str_is_type_mismatch(self):
        divs, _ = _diff(5, "5")
        assert _kinds(divs) == [differ.KIND_TYPE]

    def test_missing_dict_key(self):
        divs, _ = _diff({"a": 1, "b": 2}, {"a": 1})
        assert _kinds(divs) == [differ.KIND_TYPE]
        assert divs[0].path == "output.b"

    def test_added_dict_key(self):
        divs, _ = _diff({"a": 1}, {"a": 1, "extra": True})
        assert _kinds(divs) == [differ.KIND_TYPE]
        assert divs[0].path == "output.extra"


class TestExceptions:
    def _diff_outputs(self, expected, actual):
        return differ.diff_output(expected, actual, boundary="mod.fn",
                                  trace_id="t1", input_preview="(1)")

    def test_same_exception_matches(self):
        exc = {"type": "exception",
               "exception": {"type": "ValueError", "message": "bad"}}
        divs, _ = self._diff_outputs(exc, dict(exc))
        assert divs == []

    def test_raised_vs_returned(self):
        divs, _ = self._diff_outputs(
            {"type": "exception",
             "exception": {"type": "ValueError", "message": "bad"}},
            {"type": "return", "value": 0})
        assert _kinds(divs) == [differ.KIND_EXCEPTION]
        assert "silently accepts" in divs[0].hint

    def test_returned_vs_raised(self):
        divs, _ = self._diff_outputs(
            {"type": "return", "value": 0},
            {"type": "exception",
             "exception": {"type": "TypeError", "message": "boom"}})
        assert _kinds(divs) == [differ.KIND_EXCEPTION]

    def test_different_exception_type(self):
        divs, _ = self._diff_outputs(
            {"type": "exception",
             "exception": {"type": "ValueError", "message": "bad"}},
            {"type": "exception",
             "exception": {"type": "KeyError", "message": "bad"}})
        assert divs[0].path == "output.exception.type"

    def test_different_exception_message(self):
        divs, _ = self._diff_outputs(
            {"type": "exception",
             "exception": {"type": "ValueError", "message": "unknown coupon"}},
            {"type": "exception",
             "exception": {"type": "ValueError", "message": "bad coupon"}})
        assert divs[0].path == "output.exception.message"


class TestWeakComparison:
    def test_matching_digests_count_as_weak_match(self):
        class Widget:
            pass

        divs, weak = _diff(Widget(), Widget())
        assert divs == [] and weak == 1

    def test_differing_digests_are_weak_divergence(self):
        class A:
            pass

        class B:
            pass

        divs, _ = _diff(A(), B())
        assert _kinds(divs) == [differ.KIND_WEAK]


class TestLimits:
    def test_divergences_capped_per_trace(self):
        expected = {"k%d" % i: i for i in range(100)}
        actual = {"k%d" % i: i + 1 for i in range(100)}
        divs, _ = _diff(expected, actual)
        assert len(divs) == differ.MAX_DIVERGENCES_PER_TRACE
