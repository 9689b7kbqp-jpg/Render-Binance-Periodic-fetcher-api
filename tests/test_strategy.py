from app.strategy import floor_to_step, labr, trade_notional, is_buyer_aggressive


def test_trade_notional():
    trade = {"p": "100.0", "q": "0.5"}
    assert trade_notional(trade) == 50.0


def test_is_buyer_aggressive_binance_m_false():
    assert is_buyer_aggressive({"m": False}) is True


def test_is_seller_aggressive_binance_m_true():
    assert is_buyer_aggressive({"m": True}) is False


def test_labr():
    trades = [
        {"p": "100", "q": "1", "m": False},  # buy aggressive, notional 100
        {"p": "100", "q": "3", "m": True},   # sell aggressive, notional 300
    ]
    assert labr(trades) == 0.25


def test_floor_to_step():
    assert floor_to_step(0.123456, 0.001) == 0.123
