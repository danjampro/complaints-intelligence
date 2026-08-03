"""The statistics below the trust boundary.

These are the numbers that reach the report, and they are testable without
invoking a model — which is exactly what a model validator will ask for.
"""

from __future__ import annotations

import math

import pytest

from complaints_intelligence.metrics.statistics import (
    benjamini_hochberg,
    minimum_detectable_effect,
    run_mean_shift_tests,
    run_velocity_tests,
)


class TestBenjaminiHochberg:
    def test_empty(self):
        assert benjamini_hochberg([], alpha=0.1) == []

    def test_single_value_is_unchanged(self):
        assert benjamini_hochberg([0.03], alpha=0.1) == pytest.approx([0.03])

    def test_adjusted_values_are_never_smaller_than_raw(self):
        raw = [0.001, 0.01, 0.02, 0.04, 0.2, 0.5]
        adjusted = benjamini_hochberg(raw, alpha=0.1)
        assert all(a >= r for a, r in zip(adjusted, raw, strict=True))

    def test_adjusted_values_are_monotone_in_rank(self):
        """A larger raw p-value must not adjust to a smaller q-value.

        The step-up procedure enforces this explicitly; without it the
        ordering of flagged categories could invert.
        """
        raw = [0.001, 0.01, 0.02, 0.04, 0.2, 0.5]
        adjusted = benjamini_hochberg(raw, alpha=0.1)
        by_raw = [a for _, a in sorted(zip(raw, adjusted, strict=True))]
        assert by_raw == sorted(by_raw)

    def test_capped_at_one(self):
        adjusted = benjamini_hochberg([0.9, 0.95, 0.99], alpha=0.1)
        assert all(a <= 1.0 for a in adjusted)

    def test_controls_false_discoveries_under_the_null(self):
        """With every null true, almost nothing should be flagged.

        This is the property the whole correction exists for: testing ~40
        categories weekly at an uncorrected 5% produces roughly two false
        alarms a week, indefinitely.
        """
        uniform = [(i + 0.5) / 40 for i in range(40)]
        adjusted = benjamini_hochberg(uniform, alpha=0.1)
        assert sum(1 for a in adjusted if a <= 0.1) == 0


class TestVelocity:
    def test_flat_counts_are_not_significant(self):
        counts = {f"cat_{i}": (40, 41) for i in range(12)}
        results = run_velocity_tests(counts, alpha=0.1)
        assert not any(r.significant for r in results)

    def test_large_rise_is_significant(self):
        counts = {f"cat_{i}": (40, 41) for i in range(11)}
        counts["spiked"] = (48, 131)
        results = {r.category: r for r in run_velocity_tests(counts, alpha=0.1)}
        assert results["spiked"].significant
        assert results["spiked"].change == pytest.approx((131 - 48) / 48)

    def test_large_fall_is_significant(self):
        counts = {f"cat_{i}": (40, 41) for i in range(11)}
        counts["fell"] = (54, 18)
        results = {r.category: r for r in run_velocity_tests(counts, alpha=0.1)}
        assert results["fell"].significant
        assert results["fell"].change < 0

    def test_significance_depends_on_the_size_of_the_family(self):
        """The same movement can pass alone and fail among many tests.

        Not a defect — it is what multiplicity control means. Pinned as a test
        because it is the behaviour most likely to be mistaken for one when a
        category drops off the flagged list between weeks.
        """
        borderline = (54, 29)
        alone = run_velocity_tests({"fell": borderline}, alpha=0.1)[0]

        crowded_counts: dict[str, tuple[int, int]] = {
            f"cat_{i}": (40, 40) for i in range(11)
        }
        crowded_counts["fell"] = borderline
        crowded = {
            r.category: r for r in run_velocity_tests(crowded_counts, alpha=0.1)
        }["fell"]

        assert alone.p_value == pytest.approx(crowded.p_value)
        assert alone.significant
        assert not crowded.significant

    def test_small_movement_on_a_small_base_is_not_significant(self):
        """The noise decoy. Clears a naive threshold, fails the test."""
        counts = {f"cat_{i}": (40, 41) for i in range(11)}
        counts["noisy"] = (19, 24)
        results = {r.category: r for r in run_velocity_tests(counts, alpha=0.1)}
        assert results["noisy"].change > 0.2
        assert not results["noisy"].significant

    def test_zero_baseline_yields_infinite_change(self):
        results = {
            r.category: r for r in run_velocity_tests({"new": (0, 12)}, alpha=0.1)
        }
        assert math.isinf(results["new"].change)

    def test_every_category_is_tested(self):
        """Correction is only valid over the whole family.

        Testing only the interesting ones and correcting for that count gets
        the arithmetic right and the inference wrong.
        """
        counts = {f"cat_{i}": (40, 40) for i in range(7)}
        assert len(run_velocity_tests(counts, alpha=0.1)) == 7


class TestMinimumDetectableEffect:
    def test_improves_with_volume(self):
        small = minimum_detectable_effect(20, alpha=0.1)
        large = minimum_detectable_effect(500, alpha=0.1)
        assert large < small

    def test_zero_baseline_is_undetectable(self):
        assert math.isinf(minimum_detectable_effect(0, alpha=0.1))

    def test_is_a_positive_proportion(self):
        assert minimum_detectable_effect(100, alpha=0.1) > 0


class TestMeanShifts:
    def test_a_noise_sized_shift_in_a_tiny_cell_is_not_significant(self):
        """The failure mode this test exists to prevent.

        A four-complaint cell will show a shift of roughly one standard
        deviation from sampling alone. That clears any fixed threshold worth
        setting, which is why the brief tests the shift rather than
        thresholding it.
        """
        cells = {("cat", "branch"): (-0.55, 0.20, 4, -0.73, 0.20, 4)}
        assert not run_mean_shift_tests(cells, alpha=0.1)[0].significant

    def test_the_same_shift_is_significant_in_a_well_powered_cell(self):
        """Sample size is what separates the two, and nothing else.

        Identical means and dispersion; only the cell sizes differ.
        """
        shift = (-0.55, 0.20, 4, -0.73, 0.20, 4)
        powered = (-0.55, 0.20, 90, -0.73, 0.20, 160)

        assert not run_mean_shift_tests({("c", "a"): shift}, alpha=0.1)[0].significant
        assert run_mean_shift_tests({("c", "a"): powered}, alpha=0.1)[0].significant

    def test_large_well_powered_shift_is_significant(self):
        cells = {("cat", "app"): (-0.55, 0.18, 60, -0.80, 0.18, 120)}
        results = run_mean_shift_tests(cells, alpha=0.1)
        assert results[0].significant
        assert results[0].shift < 0

    def test_a_single_observation_cell_cannot_be_tested(self):
        cells = {("cat", "fos"): (-0.55, 0.0, 1, -0.90, 0.0, 1)}
        assert run_mean_shift_tests(cells, alpha=0.1)[0].p_value == 1.0

    def test_no_shift_is_not_significant(self):
        cells = {
            (f"cat{i}", "app"): (-0.55, 0.18, 100, -0.55, 0.18, 100) for i in range(10)
        }
        assert not any(r.significant for r in run_mean_shift_tests(cells, alpha=0.1))
