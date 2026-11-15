"""Unit tests for the Phase 2 risk metrics, using inputs with known answers."""
import numpy as np
import pandas as pd
import pytest

from ftselab import risk


def _series(values, start="2026-01-05"):
    idx = pd.bdate_range(start, periods=len(values)).strftime("%Y-%m-%d")
    return pd.Series(values, index=idx, dtype=float)


def test_daily_returns_do_not_bridge_gaps():
    prices = pd.DataFrame({"A": [100, 110, np.nan, 121, 133.1]})
    r = risk.daily_returns(prices)["A"]
    assert r.iloc[1] == pytest.approx(0.10)
    assert np.isnan(r.iloc[2]) and np.isnan(r.iloc[3])  # no price, then no previous price
    assert r.iloc[4] == pytest.approx(0.10)


def test_daily_risk_free_compounds_back_to_annual():
    rf = risk.daily_risk_free(pd.Series([5.0]), periods=252)
    assert (1 + rf.iloc[0]) ** 252 - 1 == pytest.approx(0.05)


def test_volatility_of_constant_returns_is_zero_and_scales_with_sqrt_time():
    assert risk.annualised_volatility(_series([0.01] * 50)) == pytest.approx(0.0)
    r = _series([0.01, -0.01] * 50)
    assert risk.annualised_volatility(r, periods=252) == pytest.approx(r.std() * np.sqrt(252))


def test_annualised_return_is_compound_growth():
    # 252 days of 0.1% a day compounds to (1.001^252 - 1) for one year
    r = _series([0.001] * 252)
    assert risk.annualised_return(r, periods=252) == pytest.approx(1.001 ** 252 - 1)
    # two years at that rate give the same annual figure
    assert risk.annualised_return(_series([0.001] * 504), periods=252) == pytest.approx(1.001 ** 252 - 1)


def test_max_drawdown_dates_and_recovery():
    p = _series([100, 120, 90, 60, 100, 125, 110])
    dd = risk.max_drawdown(p)
    assert dd["max_drawdown"] == pytest.approx(-0.5)  # 120 -> 60
    assert dd["peak_date"] == p.index[1] and dd["trough_date"] == p.index[3]
    assert dd["recovery_date"] == p.index[5]           # first close at or above 120
    assert dd["days_to_recover"] == 4


def test_max_drawdown_not_recovered():
    dd = risk.max_drawdown(_series([100, 80, 90]))
    assert dd["max_drawdown"] == pytest.approx(-0.2)
    assert dd["recovery_date"] is None and dd["days_to_recover"] is None


def test_max_drawdown_of_rising_series_is_zero():
    assert risk.max_drawdown(_series([1, 2, 3]))["max_drawdown"] == 0


def test_beta_recovers_known_multiple():
    rng = np.random.default_rng(0)
    m = _series(rng.normal(0, 0.01, 500))
    assert risk.beta(2 * m, m) == pytest.approx(2.0)
    assert risk.beta(-0.5 * m + 0.001, m) == pytest.approx(-0.5)
    assert risk.beta(m, m) == pytest.approx(1.0)


def test_beta_uses_shared_days_only():
    m = _series([0.01, -0.02, 0.03, np.nan, 0.01])
    s = _series([0.02, -0.04, 0.06, 0.50, np.nan])
    assert risk.beta(s, m) == pytest.approx(2.0)


def test_sharpe_matches_hand_calculation():
    r = _series([0.002, 0.000, 0.004, -0.002])
    rf = _series([0.001] * 4)
    excess = r - rf
    expected = excess.mean() / excess.std(ddof=1) * np.sqrt(252)
    assert risk.sharpe_ratio(r, rf) == pytest.approx(expected)


def test_sharpe_is_nan_without_variation():
    assert np.isnan(risk.sharpe_ratio(_series([0.01] * 5), _series([0.0] * 5)))


def test_equal_weight_uses_available_members():
    r = pd.DataFrame({"A": [0.02, 0.02], "B": [0.00, np.nan]})
    assert risk.equal_weight_portfolio(r).tolist() == pytest.approx([0.01, 0.02])


def test_sector_returns_groups_by_industry_and_respects_subset():
    r = pd.DataFrame({"A": [0.02, 0.04], "B": [0.00, 0.00], "C": [0.10, np.nan]})
    members = pd.DataFrame({"ticker": ["A", "B", "C"],
                            "icb_industry": ["Energy", "Energy", "Utilities"]})
    s = risk.sector_returns(r, members)
    assert s["Energy"].tolist() == pytest.approx([0.01, 0.02])
    assert s["Utilities"].iloc[0] == pytest.approx(0.10) and np.isnan(s["Utilities"].iloc[1])
    only_a = risk.sector_returns(r, members, tickers=["A"])
    assert list(only_a.columns) == ["Energy"] and only_a["Energy"].tolist() == pytest.approx([0.02, 0.04])


def test_window_return_runs_from_base_close_to_end_close():
    r = _series([0.10, 0.10, -0.50, 0.20])  # dates 5, 6, 7, 8 Jan 2026
    # base 5 Jan: returns on 6, 7 and 8 Jan compound
    assert risk.window_return(r, "2026-01-05", "2026-01-08") == pytest.approx(1.1 * 0.5 * 1.2 - 1)


def test_average_pairwise_correlation():
    x = np.arange(20, dtype=float)
    df = pd.DataFrame({"a": x, "b": 2 * x, "c": -x})
    # pairs: a-b = 1, a-c = -1, b-c = -1 -> mean -1/3
    assert risk.average_pairwise_correlation(df) == pytest.approx(-1 / 3)


def test_wealth_index_treats_missing_as_flat():
    w = risk.wealth_index(_series([0.10, np.nan, -0.10]))
    assert w.tolist() == pytest.approx([1.1, 1.1, 0.99])
