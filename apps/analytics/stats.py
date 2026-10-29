"""Statistical routines in plain Python (standard library only), so the system needs no extra packages.

Every function here is a textbook method; docs/ANALYTICS.md names each one and its assumptions. The numerical
results were cross-checked against SciPy during development (see test_stats.py); SciPy is NOT a dependency.

Nothing here knows about students, groups or the database. Functions take lists of numbers and return dictionaries,
and say so explicitly (``None`` or a ``note``) when a quantity cannot be estimated, instead of guessing.
"""
import math
from itertools import chain

# ---- Distribution functions ---------------------------------------------------------------------------------------


def norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def norm_sf(x):
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def norm_ppf(p):
    """Inverse standard normal CDF by bisection (accurate to ~1e-12)."""
    if not 0 < p < 1:
        raise ValueError("p must be between 0 and 1")
    lo, hi = -40.0, 40.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if norm_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _betacf(a, b, x):
    """Continued fraction for the incomplete beta function (modified Lentz)."""
    tiny, eps = 1e-300, 1e-14
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a, b, x):
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_sf(t, df):
    """P(T > t) for Student's t with df degrees of freedom."""
    x = df / (df + t * t)
    tail = 0.5 * betainc(df / 2.0, 0.5, x)
    return tail if t > 0 else 1.0 - tail


def t_cdf(t, df):
    return 1.0 - t_sf(t, df)


def t_two_sided_p(t, df):
    return min(1.0, 2.0 * t_sf(abs(t), df))


def t_ppf(p, df):
    """Inverse Student's t CDF by bisection."""
    if not 0 < p < 1:
        raise ValueError("p must be between 0 and 1")
    if p == 0.5:
        return 0.0
    lo, hi = -1e4, 1e4
    for _ in range(300):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---- Descriptives -------------------------------------------------------------------------------------------------


def mean(x):
    return math.fsum(x) / len(x)


def variance(x):
    """Sample variance (n - 1 denominator)."""
    m = mean(x)
    return math.fsum((v - m) ** 2 for v in x) / (len(x) - 1)


def sd(x):
    return math.sqrt(variance(x))


def median(x):
    s = sorted(x)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def describe(x, alpha=0.05):
    """n, mean, SD, median, min, max and a t-based confidence interval of the mean (None where not estimable)."""
    n = len(x)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "median": None, "min": None, "max": None, "ci_low": None, "ci_high": None}
    m = mean(x)
    out = {"n": n, "mean": m, "sd": None, "median": median(x), "min": min(x), "max": max(x), "ci_low": None, "ci_high": None}
    if n > 1:
        s = sd(x)
        out["sd"] = s
        half = t_ppf(1 - alpha / 2, n - 1) * s / math.sqrt(n)
        out["ci_low"], out["ci_high"] = m - half, m + half
    return out


# ---- Ranks and normality screening ---------------------------------------------------------------------------------


def rank_data(x):
    """Average ranks (ties share the mean rank)."""
    order = sorted(range(len(x)), key=lambda i: x[i])
    ranks = [0.0] * len(x)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _tie_sizes(values):
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return [c for c in counts.values() if c > 1]


def dagostino_pearson(x):
    """D'Agostino-Pearson K-squared omnibus normality test (skewness and kurtosis). Needs n >= 8.

    Low power in small samples; the app only uses it when n >= 20 (see ANALYTICS.md). Returns {"k2", "p"} or None."""
    n = len(x)
    if n < 8:
        return None
    m = mean(x)
    m2 = math.fsum((v - m) ** 2 for v in x) / n
    if m2 == 0:
        return None
    m3 = math.fsum((v - m) ** 3 for v in x) / n
    m4 = math.fsum((v - m) ** 4 for v in x) / n
    g1, b2 = m3 / m2 ** 1.5, m4 / m2 ** 2
    # skewness test (D'Agostino 1970)
    y = g1 * math.sqrt((n + 1) * (n + 3) / (6.0 * (n - 2)))
    beta2 = 3.0 * (n ** 2 + 27 * n - 70) * (n + 1) * (n + 3) / ((n - 2.0) * (n + 5) * (n + 7) * (n + 9))
    w2 = -1 + math.sqrt(2 * (beta2 - 1))
    delta = 1 / math.sqrt(0.5 * math.log(w2))
    alpha = math.sqrt(2.0 / (w2 - 1))
    y = y if y != 0 else 1.0
    z1 = delta * math.log(y / alpha + math.sqrt((y / alpha) ** 2 + 1))
    # kurtosis test (Anscombe and Glynn 1983)
    e = 3.0 * (n - 1) / (n + 1)
    var_b2 = 24.0 * n * (n - 2) * (n - 3) / ((n + 1) ** 2 * (n + 3) * (n + 5))
    xx = (b2 - e) / math.sqrt(var_b2)
    sqrtbeta1 = 6.0 * (n * n - 5 * n + 2) / ((n + 7) * (n + 9)) * math.sqrt(6.0 * (n + 3) * (n + 5) / (n * (n - 2) * (n - 3)))
    a = 6.0 + 8.0 / sqrtbeta1 * (2.0 / sqrtbeta1 + math.sqrt(1 + 4.0 / sqrtbeta1 ** 2))
    term1 = 1 - 2 / (9.0 * a)
    denom = 1 + xx * math.sqrt(2 / (a - 4.0))
    term2 = math.copysign(abs((1 - 2.0 / a) / abs(denom)) ** (1 / 3.0), denom) if denom != 0 else 0.0
    z2 = (term1 - term2) / math.sqrt(2 / (9.0 * a))
    k2 = z1 * z1 + z2 * z2
    return {"k2": k2, "p": math.exp(-k2 / 2.0)}  # chi-square survival function with 2 degrees of freedom


# ---- Two independent groups ----------------------------------------------------------------------------------------


def welch_t(x, y, alpha=0.05):
    """Welch's unequal-variance t-test for a difference in means (x minus y), with a confidence interval and
    Hedges' g. Assumes independent observations; approximately normal sampling distribution of each mean."""
    n1, n2 = len(x), len(y)
    if n1 < 2 or n2 < 2:
        return {"estimable": False, "note": "Each group needs at least 2 observations."}
    m1, m2, v1, v2 = mean(x), mean(y), variance(x), variance(y)
    se2 = v1 / n1 + v2 / n2
    if se2 == 0:
        return {"estimable": False, "note": "Both groups have identical values (no variation), so the t statistic is undefined.",
                "diff": m1 - m2}
    se = math.sqrt(se2)
    t = (m1 - m2) / se
    df = se2 ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    p = t_two_sided_p(t, df)
    half = t_ppf(1 - alpha / 2, df) * se
    pooled = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    effect = None
    if pooled > 0:
        d = (m1 - m2) / pooled
        j = 1 - 3 / (4 * (n1 + n2) - 9)
        g = d * j
        se_g = math.sqrt((n1 + n2) / (n1 * n2) + g * g / (2 * (n1 + n2 - 2)))
        z = norm_ppf(1 - alpha / 2)
        effect = {"name": "Hedges' g", "value": g, "ci_low": g - z * se_g, "ci_high": g + z * se_g}
    return {"estimable": True, "test": "Welch's t-test", "statistic": t, "df": df, "p": p, "diff": m1 - m2,
            "ci_low": m1 - m2 - half, "ci_high": m1 - m2 + half, "effect": effect}


_EXACT_MW_MAX = 20
_mw_cache = {}


def _mw_counts(m, n):
    """Frequencies of the Mann-Whitney U statistic for sample sizes m and n with no ties (index = U)."""
    key = (m, n)
    if key in _mw_cache:
        return _mw_cache[key]
    if m == 0 or n == 0:
        result = [1]
    else:
        a, b = _mw_counts(m - 1, n), _mw_counts(m, n - 1)
        size = m * n + 1
        result = [0] * size
        for u, c in enumerate(a):          # largest observation belongs to the first group: U rises by n
            result[u + n] += c
        for u, c in enumerate(b):
            result[u] += c
    _mw_cache[key] = result
    return result


def mann_whitney(x, y, alpha=0.05):
    """Mann-Whitney U (Wilcoxon rank-sum) test, two-sided. Exact p-value when there are no ties and both groups have
    at most 20 observations, otherwise a normal approximation with tie and continuity corrections.

    Effect size: probability of superiority P(X > Y) + 0.5 P(X = Y) and the rank-biserial correlation 2P - 1.
    Compares whole distributions; it estimates a shift in location only if the shapes are similar."""
    n1, n2 = len(x), len(y)
    if n1 < 1 or n2 < 1:
        return {"estimable": False, "note": "Each group needs at least 1 observation."}
    combined = list(x) + list(y)
    ranks = rank_data(combined)
    r1 = math.fsum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    ties = _tie_sizes(combined)
    if not ties and n1 <= _EXACT_MW_MAX and n2 <= _EXACT_MW_MAX:
        counts = _mw_counts(n1, n2)
        total = math.comb(n1 + n2, n1)
        small = int(min(u1, u2))
        p = min(1.0, 2.0 * sum(counts[: small + 1]) / total)
        method = "exact"
    else:
        n = n1 + n2
        tie_term = math.fsum(t ** 3 - t for t in ties) / (n * (n - 1)) if ties else 0.0
        sigma2 = n1 * n2 / 12.0 * ((n + 1) - tie_term)
        if sigma2 <= 0:
            return {"estimable": False, "note": "All values are identical, so ranks cannot separate the groups.", "u": u1}
        mu = n1 * n2 / 2.0
        z = (max(u1, u2) - mu - 0.5) / math.sqrt(sigma2)  # continuity correction
        p = min(1.0, 2.0 * norm_sf(max(z, 0.0)))
        method = "normal approximation with tie and continuity correction" if ties else "normal approximation with continuity correction"
    superiority = u1 / (n1 * n2)
    return {"estimable": True, "test": "Mann-Whitney U test", "statistic": u1, "p": p, "method": method,
            "effect": {"name": "Rank-biserial correlation", "value": 2 * superiority - 1},
            "superiority": superiority}


# ---- Paired observations ------------------------------------------------------------------------------------------


def paired_t(diffs, alpha=0.05):
    """Paired t-test on the differences (post minus baseline, or x minus y). Effect size: Cohen's d_z."""
    n = len(diffs)
    if n < 2:
        return {"estimable": False, "note": "At least 2 complete pairs are needed."}
    m, s = mean(diffs), sd(diffs)
    if s == 0:
        return {"estimable": False, "note": "Every pair changed by exactly the same amount, so the t statistic is undefined.", "diff": m}
    se = s / math.sqrt(n)
    t = m / se
    df = n - 1
    half = t_ppf(1 - alpha / 2, df) * se
    dz = m / s
    se_dz = math.sqrt(1.0 / n + dz * dz / (2.0 * n))
    z = norm_ppf(1 - alpha / 2)
    return {"estimable": True, "test": "Paired t-test", "statistic": t, "df": df, "p": t_two_sided_p(t, df), "diff": m,
            "ci_low": m - half, "ci_high": m + half,
            "effect": {"name": "Cohen's d_z", "value": dz, "ci_low": dz - z * se_dz, "ci_high": dz + z * se_dz}}


_wilcoxon_cache = {}


def _signed_rank_counts(n):
    """Frequencies of the sum of positive ranks W+ for n untied non-zero differences."""
    if n in _wilcoxon_cache:
        return _wilcoxon_cache[n]
    top = n * (n + 1) // 2
    counts = [0] * (top + 1)
    counts[0] = 1
    for r in range(1, n + 1):
        for s in range(top, r - 1, -1):
            counts[s] += counts[s - r]
    _wilcoxon_cache[n] = counts
    return counts


def wilcoxon_signed_rank(diffs):
    """Wilcoxon signed-rank test, two-sided. Zero differences are dropped (Wilcoxon's method). Exact p-value when
    there are no ties and at most 25 non-zero differences, otherwise a normal approximation with tie and continuity
    corrections. Effect size: matched-pairs rank-biserial correlation (W+ - W-) / (n(n+1)/2)."""
    nonzero = [d for d in diffs if d != 0]
    n, dropped = len(nonzero), len(diffs) - len(nonzero)
    if n < 1:
        return {"estimable": False, "note": "Every difference is zero, so there is nothing to test.", "dropped_zero": dropped}
    ranks = rank_data([abs(d) for d in nonzero])
    w_plus = math.fsum(r for r, d in zip(ranks, nonzero) if d > 0)
    w_minus = n * (n + 1) / 2.0 - w_plus
    ties = _tie_sizes([abs(d) for d in nonzero])
    if not ties and n <= 25:
        counts = _signed_rank_counts(n)
        small = int(min(w_plus, w_minus))
        p = min(1.0, 2.0 * sum(counts[: small + 1]) / 2 ** n)
        method = "exact"
    else:
        mu = n * (n + 1) / 4.0
        sigma2 = n * (n + 1) * (2 * n + 1) / 24.0 - math.fsum(t ** 3 - t for t in ties) / 48.0
        z = (max(w_plus, w_minus) - mu - 0.5) / math.sqrt(sigma2)
        p = min(1.0, 2.0 * norm_sf(max(z, 0.0)))
        method = "normal approximation with tie and continuity correction" if ties else "normal approximation with continuity correction"
    return {"estimable": True, "test": "Wilcoxon signed-rank test", "statistic": min(w_plus, w_minus), "p": p, "method": method,
            "dropped_zero": dropped, "n_used": n,
            "effect": {"name": "Matched-pairs rank-biserial correlation", "value": (w_plus - w_minus) / (n * (n + 1) / 2.0)}}


# ---- Reliability ----------------------------------------------------------------------------------------------------


def cronbach_alpha(rows):
    """Cronbach's alpha for a list of respondents, each a list of item scores of equal length (complete cases only).

    Returns {"alpha", "n", "items"} or {"alpha": None, "note"}. Alpha can be negative or undefined when items vary
    too little; the note says why."""
    n = len(rows)
    k = len(rows[0]) if rows else 0
    if k < 2:
        return {"alpha": None, "n": n, "items": k, "note": "At least 2 items are needed."}
    if n < 2:
        return {"alpha": None, "n": n, "items": k, "note": "At least 2 complete responses are needed."}
    item_vars = [variance([r[j] for r in rows]) for j in range(k)]
    total_var = variance([math.fsum(r) for r in rows])
    if total_var == 0:
        return {"alpha": None, "n": n, "items": k, "note": "Total scores do not vary, so alpha is undefined."}
    return {"alpha": k / (k - 1) * (1 - math.fsum(item_vars) / total_var), "n": n, "items": k}


# ---- Choosing between the parametric and rank-based test -------------------------------------------------------------

NORMALITY_MIN_N = 20      # below this, a normality test has too little power to be informative
LARGE_SAMPLE_N = 30       # at or above this in every group, the t-test is relied on without a normality check
NORMALITY_ALPHA = 0.05


def choose_two_sample(x, y):
    """Return ("welch" | "mann_whitney", reason)."""
    n1, n2 = len(x), len(y)
    if min(n1, n2) >= LARGE_SAMPLE_N:
        return "welch", f"Both groups have at least {LARGE_SAMPLE_N} observations, so the t-test is robust to moderate non-normality."
    if min(n1, n2) < NORMALITY_MIN_N:
        return "mann_whitney", (f"At least one group has fewer than {NORMALITY_MIN_N} observations, so normality cannot be assessed "
                                "reliably; the rank-based test is used as the primary test.")
    tests = [dagostino_pearson(g) for g in (x, y)]
    if any(t is None for t in tests):
        return "mann_whitney", "Normality could not be assessed (a group has no variation); the rank-based test is used."
    if all(t["p"] >= NORMALITY_ALPHA for t in tests):
        return "welch", f"The D'Agostino-Pearson normality screen did not reject normality in either group (p >= {NORMALITY_ALPHA})."
    return "mann_whitney", f"The D'Agostino-Pearson normality screen rejected normality in at least one group (p < {NORMALITY_ALPHA})."


def choose_paired(diffs):
    """Return ("paired_t" | "wilcoxon", reason) for a set of paired differences."""
    n = len(diffs)
    if n >= LARGE_SAMPLE_N:
        return "paired_t", f"There are at least {LARGE_SAMPLE_N} pairs, so the paired t-test is robust to moderate non-normality."
    if n < NORMALITY_MIN_N:
        return "wilcoxon", (f"There are fewer than {NORMALITY_MIN_N} pairs, so normality of the differences cannot be assessed "
                            "reliably; the rank-based test is used as the primary test.")
    test = dagostino_pearson(diffs)
    if test is None:
        return "wilcoxon", "Normality of the differences could not be assessed; the rank-based test is used."
    if test["p"] >= NORMALITY_ALPHA:
        return "paired_t", f"The normality screen did not reject normality of the differences (p >= {NORMALITY_ALPHA})."
    return "wilcoxon", f"The normality screen rejected normality of the differences (p < {NORMALITY_ALPHA})."


def flatten(lists):
    return list(chain.from_iterable(lists))
