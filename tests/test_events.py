"""Unit tests for the Phase 3 event-study building blocks (synthetic data)."""
import numpy as np
import pandas as pd
import pytest

from ftselab import config, events


def _frame(n=600, seed=0, alpha=0.0005, beta=1.5, noise=0.002):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n).strftime("%Y-%m-%d")
    m = pd.Series(rng.normal(0, 0.01, n), index=idx)
    r = alpha + beta * m + rng.normal(0, noise, n)
    return pd.DataFrame({"S": r}, index=idx), m


def test_market_model_recovers_alpha_and_beta():
    r, m = _frame()
    no_exclusion = pd.Series(False, index=r.index)
    a, b = events.rolling_market_model(r, m, no_exclusion)
    assert b["S"].iloc[-1] == pytest.approx(1.5, abs=0.05)
    assert a["S"].iloc[-1] == pytest.approx(0.0005, abs=0.0004)


def test_market_model_uses_only_days_minus_250_to_minus_11():
    r, m = _frame()
    no_exclusion = pd.Series(False, index=r.index)
    a, b = events.rolling_market_model(r, m, no_exclusion)
    # a huge shock on day t must not change the parameters used for day t ... t+10
    shocked = r.copy()
    t = 400
    shocked.iloc[t, 0] += 0.5
    a2, b2 = events.rolling_market_model(shocked, m, no_exclusion)
    assert b2["S"].iloc[t: t + config.EVENT_EST_LAST].equals(b["S"].iloc[t: t + config.EVENT_EST_LAST])
    assert b2["S"].iloc[t + config.EVENT_EST_LAST] != b["S"].iloc[t + config.EVENT_EST_LAST]


def test_too_little_history_gives_no_parameters():
    r, m = _frame()
    a, b = events.rolling_market_model(r, m, pd.Series(False, index=r.index))
    first_valid = config.EVENT_MIN_EST_OBS - 1 + config.EVENT_EST_LAST
    assert a["S"].iloc[:first_valid].isna().all()
    assert not np.isnan(a["S"].iloc[first_valid])


def test_constant_mean_model_has_zero_beta():
    r, m = _frame()
    a, b = events.rolling_market_model(r, m, pd.Series(False, index=r.index), constant_mean=True)
    assert (b["S"].dropna() == 0).all()
    # for the last day t, the window is days t-250 .. t-11
    assert a["S"].iloc[-1] == pytest.approx(r["S"].iloc[-251:-11].mean())


def test_exclusion_mask_covers_event_windows():
    idx = pd.Index([f"d{i}" for i in range(20)])
    mask = events.event_exclusion_mask(idx, ["d5", "d18"], before=1, after=2)
    assert list(np.where(mask)[0]) == [4, 5, 6, 7, 17, 18, 19]


def test_abnormal_return_detects_injected_event_effect():
    r, m = _frame(noise=0.0)
    a, b = events.rolling_market_model(r, m, pd.Series(False, index=r.index))
    R = r.to_numpy().copy()
    pos = np.array([450, 500, 550])
    R[pos, 0] += 0.03                     # +3% on each event day
    R[pos + 1, 0] -= 0.01                 # -1% the day after
    A, B, M = a.to_numpy(), b.to_numpy(), m.to_numpy()
    ar0 = events.abnormal_returns(R, M, A, B, pos, 0)
    assert ar0[:, 0] == pytest.approx([0.03] * 3, abs=1e-6)
    car = events.cumulative_abnormal(R, M, A, B, pos, 0, 1)
    assert car[:, 0] == pytest.approx([0.02] * 3, abs=1e-6)


def test_abnormal_returns_outside_data_are_nan():
    r, m = _frame(n=300)
    a, b = events.rolling_market_model(r, m, pd.Series(False, index=r.index))
    out = events.abnormal_returns(r.to_numpy(), m.to_numpy(), a.to_numpy(), b.to_numpy(),
                                  np.array([299]), 1)
    assert np.isnan(out).all()


def test_summarise_matches_scipy():
    from scipy import stats
    x = np.array([0.01, 0.02, -0.005, 0.015, 0.03, 0.0, 0.012])
    s = events.summarise(x)
    t = stats.ttest_1samp(x, 0)
    assert s["t_stat"] == pytest.approx(t.statistic)
    assert s["p_t"] == pytest.approx(t.pvalue)
    assert s["ci95_low"] < s["mean"] < s["ci95_high"]
    assert s["share_positive"] == pytest.approx(5 / 7)


def test_summarise_ignores_missing():
    s = events.summarise(np.array([0.01, np.nan, 0.03]))
    assert s["n_events"] == 2 and s["mean"] == pytest.approx(0.02)


def test_benjamini_hochberg_known_example():
    p = np.array([0.01, 0.04, 0.03, 0.005, np.nan])
    q = events.benjamini_hochberg(p)
    # sorted p: .005 .01 .03 .04 -> p*m/rank: .02 .02 .04 .04
    assert q[:4] == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert np.isnan(q[4])


def test_calendar_stratum():
    s = events.calendar_stratum(["2022-09-22", "2023-02-02", "2024-08-29", "2024-08-01"])
    assert list(s) == ["09-3", "02-0", "08-3", "08-0"]


def test_matched_draws_stay_in_stratum_and_fall_back_to_month():
    pool = np.array(["02-0"] * 6 + ["02-2"] * 2 + ["05-1"] * 6)
    rng = np.random.default_rng(0)
    idx = events.matched_draws(np.array(["02-0", "02-1", "05-1"]), pool, draws=500, rng=rng)
    assert idx.shape == (500, 3)
    assert set(pool[idx[:, 0]]) == {"02-0"}
    assert {s[:2] for s in pool[idx[:, 1]]} == {"02"}   # '02-1' has no days: same month
    assert set(pool[idx[:, 2]]) == {"05-1"}


def _pool_and_draws(n_events=20, seed=1, centre=0.0):
    rng = np.random.default_rng(seed)
    pool = rng.normal(centre, 0.01, 1000)
    strata = np.array(["01-0"] * 1000)
    idx = events.matched_draws(np.array(["01-0"] * n_events), strata, draws=2000, rng=rng)
    return pool, idx, rng


def test_placebo_large_p_for_typical_events_small_for_shifted():
    pool, idx, rng = _pool_and_draws()
    typical = rng.normal(0, 0.01, 20)
    shifted = rng.normal(0.01, 0.01, 20)       # +1% on every event day
    p_stud, p_mean, means = events.placebo_pvalue(typical, pool, idx)
    assert p_stud > 0.05 and p_mean > 0.05
    p_stud, p_mean, _ = events.placebo_pvalue(shifted, pool, idx)
    assert p_stud < 0.01 and p_mean < 0.01
    assert means.std() == pytest.approx(0.01 / np.sqrt(20), rel=0.15)


def test_placebo_compares_with_placebo_centre_not_zero():
    """If comparable days average -0.5%, real events averaging -0.5% are not unusual."""
    pool, idx, rng = _pool_and_draws(centre=-0.005)
    events_like_pool = rng.normal(-0.005, 0.01, 20)
    p_stud, p_mean, means = events.placebo_pvalue(events_like_pool, pool, idx)
    assert np.median(means) == pytest.approx(-0.005, abs=0.001)
    assert p_stud > 0.05 and p_mean > 0.05


def test_studentised_placebo_not_fooled_by_extra_volatility():
    """Event days three times as volatile but with no shift in the average: the
    studentised test should reject about 5% of the time; the raw-mean test
    rejects far more often."""
    pool, idx, rng = _pool_and_draws(n_events=30)
    rej_stud = rej_mean = 0
    trials = 300
    for _ in range(trials):
        noisy = rng.normal(0, 0.03, 30)
        p_stud, p_mean, _ = events.placebo_pvalue(noisy, pool, idx)
        rej_stud += p_stud < 0.05
        rej_mean += p_mean < 0.05
    assert rej_stud / trials < 0.10
    assert rej_mean / trials > 0.30


def test_placebo_applies_signs():
    pool = np.array([0.01, 0.012, 0.008, 0.011] * 25)   # placebo days are about +1%
    idx = np.tile(np.arange(4), (100, 1))
    # with signs +,+,-,- the signed placebo mean is (1.0 + 1.2 - 0.8 - 1.1) / 4 = 0.075%,
    # so real events averaging +0.5% are extreme
    p_stud, p_mean, means = events.placebo_pvalue(np.array([0.005, 0.006, 0.004, 0.005]), pool, idx,
                                                  signs=np.array([1, 1, -1, -1]))
    assert np.allclose(means, 0.00075) and p_mean < 0.02


def test_t_pvalues_vectorised_matches_summarise():
    rng = np.random.default_rng(2)
    samples = rng.normal(0.001, 0.01, (5, 12))
    expected = [events.summarise(row)["p_t"] for row in samples]
    assert events.t_pvalues(samples) == pytest.approx(expected)
