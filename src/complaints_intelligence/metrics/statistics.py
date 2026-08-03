"""Statistics for the metrics layer.

Ordinary code, no model involved. This is below the trust boundary: everything
here is deterministic, independently testable without invoking an LLM, and
exactly what a model validator will ask to see.

The problem this addresses: with ~40 categories tested every week, comparing
each against last week at the 5% level produces roughly two false alarms a
week, indefinitely. A report that cries wolf twice a week is worse than no
report. So movements are tested, and the tests are corrected for multiplicity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import t as student_t

#: Dispersion for the negative-binomial model of weekly counts.
#:
#: Complaint counts are over-dispersed relative to Poisson — volume clusters
#: around incidents, campaigns and outages, so variance exceeds the mean.
#: Assuming Poisson would understate the variance and flag ordinary weeks as
#: significant.
#:
#: The parameterisation is ``variance = mean + dispersion * mean**2``, so the
#: second term sets a floor on the coefficient of variation of
#: ``sqrt(dispersion)`` — about 14% here. That floor is the reason the
#: minimum detectable effect stops improving with volume: past a few hundred
#: complaints a week, week-to-week variability, not sample size, is what
#: limits sensitivity. That is a real property of count data, and it is why
#: the MDE is reported rather than assumed away.
#:
#: In production this is estimated per category from the historical series.
#: A single value is used here and stated openly.
DISPERSION = 0.02


@dataclass(frozen=True)
class VelocityTest:
    """Result of testing one category's week-on-week movement."""

    category: str
    baseline: int
    current: int
    #: Proportional change. ``inf`` where the baseline was zero.
    change: float
    p_value: float
    adjusted_p_value: float
    significant: bool


def _log_gamma(x: float) -> float:
    return math.lgamma(x)


def _nb_log_pmf(k: int, mean: float, dispersion: float) -> float:
    """Log PMF of a negative binomial parameterised by mean and dispersion.

    Variance is ``mean + dispersion * mean**2``, so ``dispersion -> 0``
    recovers the Poisson.
    """
    if mean <= 0:
        return 0.0 if k == 0 else -math.inf
    size = 1.0 / dispersion
    log_p = (
        _log_gamma(k + size)
        - _log_gamma(size)
        - _log_gamma(k + 1.0)
        + size * math.log(size / (size + mean))
        + k * math.log(mean / (size + mean))
    )
    return log_p


def _nb_tail_p_value(observed: int, expected: float, dispersion: float) -> float:
    """Two-sided tail probability of ``observed`` under the null.

    The null is that this week's count comes from the same process as the
    baseline. Summed directly rather than via a normal approximation: counts
    here are small enough that the approximation is poor in exactly the tail
    that matters.
    """
    if expected <= 0:
        return 1.0 if observed == 0 else 0.0

    upper_limit = max(observed, int(expected * 6) + 20)
    if observed >= expected:
        tail = sum(
            math.exp(_nb_log_pmf(k, expected, dispersion))
            for k in range(observed, upper_limit + 1)
        )
    else:
        tail = sum(
            math.exp(_nb_log_pmf(k, expected, dispersion))
            for k in range(0, observed + 1)
        )
    return float(min(1.0, 2.0 * tail))


def benjamini_hochberg(p_values: list[float], alpha: float) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values).

    Controls the false discovery rate — the expected proportion of flagged
    categories that are not real — rather than the family-wise error rate.
    That is the right trade here: the cost of one spurious line in a report a
    human reviews is far lower than the cost of missing a genuine emerging
    problem, and Bonferroni at 40 tests would miss most real movements.

    ``alpha`` does not enter the adjustment itself; it is returned to the
    caller's threshold comparison. It is taken here so the call site reads as
    one decision rather than two.
    """
    del alpha  # Retained for call-site legibility; see docstring.
    n = len(p_values)
    if n == 0:
        return []

    order = sorted(range(n), key=lambda i: p_values[i])
    adjusted = [0.0] * n
    previous = 1.0
    # Walk from the largest p-value down, enforcing monotonicity as we go.
    for rank in range(n - 1, -1, -1):
        idx = order[rank]
        value = min(previous, p_values[idx] * n / (rank + 1))
        adjusted[idx] = min(1.0, value)
        previous = adjusted[idx]
    return adjusted


def run_velocity_tests(
    counts: dict[str, tuple[int, int]],
    *,
    alpha: float,
    dispersion: float = DISPERSION,
) -> list[VelocityTest]:
    """Test every category's movement, with FDR control across the family.

    ``counts`` maps category to ``(baseline, current)``.

    Every category is tested, including ones that barely moved, because the
    correction is only valid over the whole family. Testing just the ones that
    look interesting and then correcting for that number is a way of getting
    the arithmetic right and the inference wrong.
    """
    categories = sorted(counts)
    raw = [
        _nb_tail_p_value(counts[c][1], float(counts[c][0]), dispersion)
        for c in categories
    ]
    adjusted = benjamini_hochberg(raw, alpha)

    results = []
    for category, p_raw, p_adj in zip(categories, raw, adjusted, strict=True):
        baseline, current = counts[category]
        change = (current - baseline) / baseline if baseline else math.inf
        results.append(
            VelocityTest(
                category=category,
                baseline=baseline,
                current=current,
                change=change,
                p_value=p_raw,
                adjusted_p_value=p_adj,
                significant=p_adj <= alpha,
            )
        )
    return results


@dataclass(frozen=True)
class MeanShiftTest:
    """Result of testing a shift in mean sentiment for one cell."""

    scope: str
    channel: str
    baseline_mean: float
    current_mean: float
    shift: float
    p_value: float
    adjusted_p_value: float
    significant: bool


def _welch_p_value(
    mean_a: float,
    sd_a: float,
    n_a: int,
    mean_b: float,
    sd_b: float,
    n_b: int,
) -> float:
    """Two-sided p-value for a difference of means, unequal variances.

    Welch rather than Student because the two weeks have neither equal
    variance nor equal size — the whole point of the reporting week is often
    that one cell grew.

    Uses the actual t distribution with Welch-Satterthwaite degrees of
    freedom, not a normal approximation. The approximation is wrong in
    precisely the case that matters here: at a handful of complaints per cell
    it understates the tails badly, so a shift between two four-complaint
    cells comes out significant when it is nothing of the kind. Since this
    test is what decides which cells are too small to trust, approximating it
    would be circular.
    """
    if n_a < 2 or n_b < 2:
        return 1.0

    var_a = (sd_a**2) / n_a
    var_b = (sd_b**2) / n_b
    variance = var_a + var_b
    if variance <= 0:
        return 1.0 if mean_a == mean_b else 0.0

    t_statistic = abs(mean_a - mean_b) / math.sqrt(variance)
    denominator = (var_a**2) / (n_a - 1) + (var_b**2) / (n_b - 1)
    degrees_of_freedom = variance**2 / denominator if denominator > 0 else 1.0

    return float(2.0 * student_t.sf(t_statistic, degrees_of_freedom))


def run_mean_shift_tests(
    cells: dict[tuple[str, str], tuple[float, float, int, float, float, int]],
    *,
    alpha: float,
) -> list[MeanShiftTest]:
    """Test every sentiment cell for a shift, with FDR control.

    ``cells`` maps ``(scope, channel)`` to
    ``(baseline_mean, baseline_sd, baseline_n, current_mean, current_sd, current_n)``.

    Testing rather than thresholding is what keeps small cells out of the
    report. A mean over four complaints will clear any threshold worth
    setting; it will not clear a test.
    """
    keys = sorted(cells)
    raw = [
        _welch_p_value(
            cells[k][3], cells[k][4], cells[k][5], cells[k][0], cells[k][1], cells[k][2]
        )
        for k in keys
    ]
    adjusted = benjamini_hochberg(raw, alpha)

    results = []
    for key, p_raw, p_adj in zip(keys, raw, adjusted, strict=True):
        baseline_mean, _, _, current_mean, _, _ = cells[key]
        results.append(
            MeanShiftTest(
                scope=key[0],
                channel=key[1],
                baseline_mean=baseline_mean,
                current_mean=current_mean,
                shift=current_mean - baseline_mean,
                p_value=p_raw,
                adjusted_p_value=p_adj,
                significant=p_adj <= alpha,
            )
        )
    return results


def minimum_detectable_effect(
    baseline: int, *, alpha: float, dispersion: float = DISPERSION
) -> float:
    """Smallest proportional rise this design can detect at a given baseline.

    Reported alongside the results because a null result is only meaningful
    with a stated sensitivity: "no significant change in a category with a
    baseline of 19" means something quite different from the same statement
    about a baseline of 500. Computed by search rather than a closed form,
    which is slower and exactly right.
    """
    if baseline <= 0:
        return math.inf
    for current in range(baseline, baseline * 10 + 2):
        if _nb_tail_p_value(current, float(baseline), dispersion) <= alpha:
            return (current - baseline) / baseline
    return math.inf
