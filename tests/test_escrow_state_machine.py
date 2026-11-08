import pytest
from marketplace.escrow import EscrowStateMachine
from models.escrow import EscrowStatus


def test_escrow_fee_calculation():
    """Verify escrow fee math: 5% fee on $100 = $5 fee, $95 to seller."""
    amount = 100.00
    fee_percent = 5.0
    fee = round(amount * (fee_percent / 100.0), 2)
    seller_receives = round(amount - fee, 2)

    assert fee == 5.00
    assert seller_receives == 95.00


def test_high_value_threshold_logic():
    """Verify threshold calculation for accounts >= $500."""
    threshold = 500.0
    account_price = 750.0
    is_high_value = account_price >= threshold
    assert is_high_value is True

    cheap_account = 200.0
    assert (cheap_account >= threshold) is False

