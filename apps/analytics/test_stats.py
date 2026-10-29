"""Unit tests for the plain-Python statistics in apps/analytics/stats.py.

The reference numbers below were computed with SciPy 1.17 while developing (SciPy itself is NOT a dependency of the
application) on small invented data sets. A broader randomised comparison against SciPy (several hundred cases across
t, Welch, paired, Mann-Whitney exact and tie-corrected, Wilcoxon exact and tie-corrected, D'Agostino-Pearson and
Cronbach's alpha) was run during development with no discrepancy above 1e-7 (relative).
"""
import math

from django.test import SimpleTestCase

from . import stats

X = [12.1, 14.3, 9.8, 15.2, 11.7, 13.4, 16.0, 10.5]
Y = [9.9, 11.2, 8.7, 12.5, 10.1, 9.4, 11.8, 10.3, 8.9]
BASE = [50, 62, 48, 71, 55, 60, 66, 52]
POST = [58, 65, 47, 80, 61, 63, 74, 60]
DIFFS = [b - a for a, b in zip(BASE, POST)]
EXPONENTIAL = [0.11, 0.39, 1.4, 2.2, 0.343, 0.258, 0.435, 0.103, 1.001, 0.066, 0.451, 3.348, 0.267, 1.285, 0.516, 2.034,
               0.908, 1.485, 0.289, 0.178, 0.002, 1.165, 0.894, 1.216]


class DistributionTests(SimpleTestCase):
    def test_t_cdf_matches_reference(self):
        for df, t, expected in ((5, 2.0, 0.9490302605850708), (10, -1.5, 0.08225366322272007), (30, 0.7, 0.7553397782501642)):
            self.assertAlmostEqual(stats.t_cdf(t, df), expected, places=9)

    def test_t_quantiles_and_normal_quantile(self):
        self.assertAlmostEqual(stats.t_ppf(0.975, 7), 2.364624251592784, places=8)
        self.assertAlmostEqual(stats.t_ppf(0.975, 60), 2.0002978220142604, places=8)
        self.assertAlmostEqual(stats.norm_ppf(0.975), 1.959963984540054, places=9)

    def test_symmetry_and_limits(self):
        self.assertAlmostEqual(stats.t_cdf(0, 12), 0.5, places=12)
        self.assertAlmostEqual(stats.t_cdf(-1.3, 9) + stats.t_cdf(1.3, 9), 1.0, places=12)
        self.assertAlmostEqual(stats.t_two_sided_p(0, 5), 1.0, places=12)
        self.assertLess(stats.t_two_sided_p(40, 5), 1e-6)


class DescriptiveTests(SimpleTestCase):
    def test_describe(self):
        d = stats.describe([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertEqual((d["n"], d["mean"], d["median"], d["min"], d["max"]), (8, 5.0, 4.5, 2, 9))
        self.assertAlmostEqual(d["sd"], 2.138089935299395, places=9)
        self.assertTrue(d["ci_low"] < 5.0 < d["ci_high"])

    def test_describe_small_and_empty(self):
        self.assertEqual(stats.describe([])["n"], 0)
        one = stats.describe([3.0])
        self.assertEqual((one["n"], one["mean"], one["sd"], one["ci_low"]), (1, 3.0, None, None))

    def test_rank_data_averages_ties(self):
        self.assertEqual(stats.rank_data([10, 20, 20, 30]), [1.0, 2.5, 2.5, 4.0])


class TwoSampleTests(SimpleTestCase):
    def test_welch_matches_reference(self):
        r = stats.welch_t(X, Y)
        self.assertAlmostEqual(r["statistic"], 2.860147602890037, places=9)
        self.assertAlmostEqual(r["df"], 10.99245511513917, places=8)
        self.assertAlmostEqual(r["p"], 0.015522265613638689, places=9)
        self.assertAlmostEqual(r["ci_low"], 0.5907200965358623, places=7)
        self.assertAlmostEqual(r["ci_high"], 4.537057681241914, places=7)
        self.assertAlmostEqual(r["diff"], stats.mean(X) - stats.mean(Y), places=12)

    def test_welch_effect_size_is_hedges_g(self):
        r = stats.welch_t(X, Y)
        n1, n2 = len(X), len(Y)
        pooled = math.sqrt(((n1 - 1) * stats.variance(X) + (n2 - 1) * stats.variance(Y)) / (n1 + n2 - 2))
        expected = (stats.mean(X) - stats.mean(Y)) / pooled * (1 - 3 / (4 * (n1 + n2) - 9))
        self.assertAlmostEqual(r["effect"]["value"], expected, places=12)
        self.assertTrue(r["effect"]["ci_low"] < r["effect"]["value"] < r["effect"]["ci_high"])

    def test_welch_swapping_groups_flips_sign_not_p(self):
        a, b = stats.welch_t(X, Y), stats.welch_t(Y, X)
        self.assertAlmostEqual(a["statistic"], -b["statistic"], places=12)
        self.assertAlmostEqual(a["p"], b["p"], places=12)

    def test_welch_not_estimable_cases(self):
        self.assertFalse(stats.welch_t([1.0], [2.0, 3.0])["estimable"])
        r = stats.welch_t([5, 5, 5], [5, 5, 5])
        self.assertFalse(r["estimable"])
        self.assertIn("no variation", r["note"])

    def test_mann_whitney_exact_matches_reference(self):
        r = stats.mann_whitney(X, Y)
        self.assertEqual(r["statistic"], 60.0)
        self.assertAlmostEqual(r["p"], 0.02064993829699712, places=10)
        self.assertEqual(r["method"], "exact")
        self.assertAlmostEqual(r["superiority"], 60 / (len(X) * len(Y)), places=12)
        self.assertAlmostEqual(r["effect"]["value"], 2 * 60 / (len(X) * len(Y)) - 1, places=12)

    def test_mann_whitney_with_ties_uses_corrected_normal_approximation(self):
        r = stats.mann_whitney([3, 5, 5, 7, 8, 8, 8, 10, 12], [2, 4, 5, 5, 6, 6, 9, 9, 9, 11])
        self.assertEqual(r["statistic"], 50.0)
        self.assertAlmostEqual(r["p"], 0.7109919960746027, places=9)
        self.assertIn("tie", r["method"])

    def test_mann_whitney_identical_values_not_estimable(self):
        self.assertFalse(stats.mann_whitney([2, 2, 2], [2, 2, 2, 2])["estimable"])

    def test_mann_whitney_complete_separation_p_value(self):
        r = stats.mann_whitney([1, 2, 3], [4, 5, 6])
        self.assertAlmostEqual(r["p"], 0.1, places=12)  # exact: 2 / C(6,3)
        self.assertEqual(r["effect"]["value"], -1.0)


class PairedTests(SimpleTestCase):
    def test_paired_t_matches_reference(self):
        r = stats.paired_t(DIFFS)
        self.assertAlmostEqual(r["statistic"], 4.438206216322609, places=9)
        self.assertEqual(r["df"], 7)
        self.assertAlmostEqual(r["p"], 0.0030142237117970535, places=9)
        self.assertAlmostEqual(r["ci_low"], 2.569664465808373, places=7)
        self.assertAlmostEqual(r["ci_high"], 8.430335534191627, places=7)
        self.assertAlmostEqual(r["effect"]["value"], 1.569142855933003, places=9)

    def test_paired_t_not_estimable_cases(self):
        self.assertFalse(stats.paired_t([3])["estimable"])
        self.assertFalse(stats.paired_t([2, 2, 2])["estimable"])

    def test_wilcoxon_exact_matches_reference_when_there_are_no_ties(self):
        r = stats.wilcoxon_signed_rank([0.5, 1.2, -0.3, 2.1, 1.7, 0.9, 3.3, 2.8, -0.6])
        self.assertEqual(r["statistic"], 4.0)
        self.assertAlmostEqual(r["p"], 0.02734375, places=12)
        self.assertEqual(r["method"], "exact")

    def test_wilcoxon_tied_differences_use_the_corrected_approximation_not_the_exact_table(self):
        r = stats.wilcoxon_signed_rank(DIFFS)  # 3 appears twice and 8 three times
        self.assertEqual(r["statistic"], 1.0)
        self.assertAlmostEqual(r["p"], 0.020085286672471166, places=9)
        self.assertIn("tie", r["method"])

    def test_wilcoxon_ties_and_zeros(self):
        r = stats.wilcoxon_signed_rank([2, -1, 3, 0, 1, 1, -2, 4, 2, 0, 3, 1])
        self.assertEqual(r["dropped_zero"], 2)
        self.assertAlmostEqual(r["statistic"], 8.5, places=9)
        self.assertAlmostEqual(r["p"], 0.05686662768004776, places=9)
        self.assertIn("tie", r["method"])

    def test_wilcoxon_all_zero_not_estimable(self):
        self.assertFalse(stats.wilcoxon_signed_rank([0, 0, 0])["estimable"])


class NormalityAndReliabilityTests(SimpleTestCase):
    def test_dagostino_pearson_matches_reference(self):
        r = stats.dagostino_pearson(EXPONENTIAL)
        self.assertAlmostEqual(r["k2"], 12.285650287937868, places=8)
        self.assertAlmostEqual(r["p"], 0.002148844240436233, places=8)

    def test_dagostino_needs_8_values_and_variation(self):
        self.assertIsNone(stats.dagostino_pearson([1, 2, 3]))
        self.assertIsNone(stats.dagostino_pearson([4.0] * 10))

    def test_cronbach_alpha(self):
        rows = [[4, 5, 4], [3, 3, 4], [5, 5, 5], [2, 3, 2], [4, 4, 5], [3, 2, 3], [5, 4, 4], [1, 2, 2]]
        self.assertAlmostEqual(stats.cronbach_alpha(rows)["alpha"], 0.9247159090909091, places=12)

    def test_cronbach_alpha_undefined_cases(self):
        self.assertIsNone(stats.cronbach_alpha([[3], [4]])["alpha"])           # one item
        self.assertIsNone(stats.cronbach_alpha([[3, 4]])["alpha"])             # one respondent
        self.assertIsNone(stats.cronbach_alpha([[3, 3], [3, 3], [3, 3]])["alpha"])  # no variation


class TestSelectionTests(SimpleTestCase):
    def test_small_samples_use_rank_based_primary(self):
        choice, reason = stats.choose_two_sample(X, Y)
        self.assertEqual(choice, "mann_whitney")
        self.assertIn("fewer than 20", reason)
        self.assertEqual(stats.choose_paired(DIFFS)[0], "wilcoxon")

    def test_large_samples_use_t_test(self):
        big = [float(i % 17) for i in range(40)]
        self.assertEqual(stats.choose_two_sample(big, big)[0], "welch")
        self.assertEqual(stats.choose_paired(big)[0], "paired_t")

    def test_medium_samples_depend_on_the_normality_screen(self):
        skewed = EXPONENTIAL  # 24 values, strongly non-normal
        self.assertEqual(stats.choose_two_sample(skewed, skewed)[0], "mann_whitney")
        self.assertEqual(stats.choose_paired(skewed)[0], "wilcoxon")
        symmetric = [10 + ((i * 7) % 13) - 6 + (i % 3) * 0.1 for i in range(24)]
        self.assertEqual(stats.choose_two_sample(symmetric, symmetric)[0], "welch")
