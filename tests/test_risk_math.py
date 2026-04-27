def test_risk_cash():
    capital = 1420
    risk_pct = 0.0025
    assert capital * risk_pct == 3.1


def test_notional_with_min_stop():
    risk_cash = 3.1
    stop_pct = 0.0035
    notional = risk_cash / stop_pct
    assert round(notional, 2) == 885.71
