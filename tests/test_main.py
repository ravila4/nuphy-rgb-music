"""Tests for _CyclicIndex in main.py."""

import threading

import pytest

from nuphy_rgb.main import _CyclicIndex


# ---------------------------------------------------------------------------
# _CyclicIndex
# ---------------------------------------------------------------------------


class TestCyclicIndexNext:
    def test_starts_at_zero(self) -> None:
        idx = _CyclicIndex(3)
        assert idx.index == 0

    def test_next_increments(self) -> None:
        idx = _CyclicIndex(3)
        idx.next()
        assert idx.index == 1

    def test_next_wraps_around(self) -> None:
        idx = _CyclicIndex(3)
        idx.next()
        idx.next()
        idx.next()
        assert idx.index == 0

    def test_next_sets_changed(self) -> None:
        idx = _CyclicIndex(3)
        idx.next()
        assert idx.poll_changed() == 1


class TestCyclicIndexPrev:
    def test_prev_decrements(self) -> None:
        idx = _CyclicIndex(3)
        idx.next()
        idx.prev()
        assert idx.index == 0

    def test_prev_wraps_from_zero(self) -> None:
        idx = _CyclicIndex(3)
        idx.prev()
        assert idx.index == 2

    def test_prev_sets_changed(self) -> None:
        idx = _CyclicIndex(3)
        idx.prev()
        assert idx.poll_changed() == 2


class TestCyclicIndexSet:
    def test_set_jumps_to_index(self) -> None:
        idx = _CyclicIndex(5)
        idx.set(3)
        assert idx.index == 3

    def test_set_sets_changed(self) -> None:
        idx = _CyclicIndex(5)
        idx.set(3)
        assert idx.poll_changed() == 3

    def test_set_zero_is_valid(self) -> None:
        idx = _CyclicIndex(5)
        idx.next()
        idx.set(0)
        assert idx.index == 0

    def test_set_out_of_bounds_raises(self) -> None:
        idx = _CyclicIndex(3)
        with pytest.raises(ValueError):
            idx.set(3)

    def test_set_negative_raises(self) -> None:
        idx = _CyclicIndex(3)
        with pytest.raises(ValueError):
            idx.set(-1)


class TestCyclicIndexSetByName:
    def test_set_by_name_finds_exact_match(self) -> None:
        idx = _CyclicIndex(3, names=["Alpha", "Beta", "Gamma"])
        result = idx.set_by_name("Beta")
        assert result is True
        assert idx.index == 1

    def test_set_by_name_is_case_insensitive(self) -> None:
        idx = _CyclicIndex(3, names=["Alpha", "Beta", "Gamma"])
        result = idx.set_by_name("beta")
        assert result is True
        assert idx.index == 1

    def test_set_by_name_all_caps(self) -> None:
        idx = _CyclicIndex(3, names=["Alpha", "Beta", "Gamma"])
        result = idx.set_by_name("GAMMA")
        assert result is True
        assert idx.index == 2

    def test_set_by_name_returns_false_when_not_found(self) -> None:
        idx = _CyclicIndex(3, names=["Alpha", "Beta", "Gamma"])
        result = idx.set_by_name("Delta")
        assert result is False

    def test_set_by_name_does_not_change_index_on_miss(self) -> None:
        idx = _CyclicIndex(3, names=["Alpha", "Beta", "Gamma"])
        idx.set_by_name("Delta")
        assert idx.index == 0

    def test_set_by_name_sets_changed_on_hit(self) -> None:
        idx = _CyclicIndex(3, names=["Alpha", "Beta", "Gamma"])
        idx.set_by_name("Beta")
        assert idx.poll_changed() == 1

    def test_set_by_name_no_changed_on_miss(self) -> None:
        idx = _CyclicIndex(3, names=["Alpha", "Beta", "Gamma"])
        idx.set_by_name("Delta")
        assert idx.poll_changed() is None

    def test_set_by_name_without_names_raises(self) -> None:
        idx = _CyclicIndex(3)
        with pytest.raises(ValueError):
            idx.set_by_name("anything")


class TestCyclicIndexPollChanged:
    def test_initially_returns_none(self) -> None:
        idx = _CyclicIndex(3)
        assert idx.poll_changed() is None

    def test_returns_index_after_change(self) -> None:
        idx = _CyclicIndex(3)
        idx.next()
        assert idx.poll_changed() == 1

    def test_resets_flag_after_poll(self) -> None:
        idx = _CyclicIndex(3)
        idx.next()
        idx.poll_changed()
        assert idx.poll_changed() is None

    def test_multiple_changes_report_last(self) -> None:
        """Rapid next/next/next — poll sees current index, not intermediate."""
        idx = _CyclicIndex(5)
        idx.next()
        idx.next()
        idx.next()
        assert idx.poll_changed() == 3


class TestCyclicIndexIndependence:
    def test_two_instances_do_not_share_changed(self) -> None:
        a = _CyclicIndex(3)
        b = _CyclicIndex(3)
        a.next()
        assert a.poll_changed() == 1
        assert b.poll_changed() is None

    def test_two_instances_do_not_share_index(self) -> None:
        a = _CyclicIndex(4)
        b = _CyclicIndex(4)
        a.next()
        a.next()
        assert a.index == 2
        assert b.index == 0


class TestCyclicIndexThreadSafety:
    def test_concurrent_next_does_not_corrupt_index(self) -> None:
        count = 100
        idx = _CyclicIndex(count)
        threads = [threading.Thread(target=idx.next) for _ in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # After 100 nexts on a size-100 cyclic index, we're back to 0
        assert idx.index == 0


class TestCyclicIndexCountGuard:
    def test_zero_count_raises(self) -> None:
        with pytest.raises(ValueError):
            _CyclicIndex(0)

    def test_negative_count_raises(self) -> None:
        with pytest.raises(ValueError):
            _CyclicIndex(-1)
