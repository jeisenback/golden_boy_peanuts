"""
Unit tests for src/core/bsm.py — Black-Scholes-Merton Greeks engine.

Reference values computed against known BSM closed-form solutions.
No external dependencies required — pure-Python math only.
"""

from __future__ import annotations

import math

import pytest

from src.core.bsm import (
    _SPREAD_WIDTH_PERCENT,
    BSMGreeks,
    compute_bsm_greeks,
    greeks_for_strategy,
)

# ---------------------------------------------------------------------------
# Fixtures: canonical BSM inputs
# ---------------------------------------------------------------------------

# ATM call: S=100, K=100, T=1yr, r=5%, vol=20%
# Reference: Hull 11th ed. Example 19.1 — approximate values used.
_ATM_SPOT = 100.0
_ATM_STRIKE = 100.0
_ATM_T = 1.0        # 1 year
_ATM_VOL = 0.20     # 20%
_ATM_R = 0.05       # 5%

# OTM call: S=100, K=110, T=0.5yr, r=5%, vol=25%
_OTM_SPOT = 100.0
_OTM_STRIKE = 110.0
_OTM_T = 0.5
_OTM_VOL = 0.25
_OTM_R = 0.05

# Deep ITM put: S=100, K=120, T=1yr, r=5%, vol=20%
_ITM_PUT_SPOT = 100.0
_ITM_PUT_STRIKE = 120.0
_ITM_PUT_T = 1.0
_ITM_PUT_VOL = 0.20
_ITM_PUT_R = 0.05


class TestComputeBSMGreeks:
    """Tests for compute_bsm_greeks()."""

    def test_atm_call_price_within_expected_range(self) -> None:
        """ATM call price should be roughly 10.45 for Hull's canonical inputs."""
        g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call", _ATM_R)
        # Hull example: ~10.45
        assert 9.5 < g.price < 11.5, f"Unexpected ATM call price: {g.price}"

    def test_atm_call_delta_near_half(self) -> None:
        """ATM call delta should be > 0.5 (r > 0 shifts d1 above 0, so N(d1) > 0.5)."""
        g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call", _ATM_R)
        # With r=5%, T=1yr: d1=(0+0.07)/0.2=0.35, N(0.35)≈0.637
        assert 0.50 < g.delta < 0.70, f"ATM call delta out of range: {g.delta}"

    def test_atm_put_price_within_expected_range(self) -> None:
        """ATM put price: by put-call parity P = C - S + K*e^(-rT)."""
        call_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call", _ATM_R)
        put_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "put", _ATM_R)
        pcp = call_g.price - _ATM_SPOT + _ATM_STRIKE * math.exp(-_ATM_R * _ATM_T)
        assert abs(put_g.price - pcp) < 1e-8, "Put-call parity violated"

    def test_put_delta_negative(self) -> None:
        """Put delta must be in (-1, 0)."""
        g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "put", _ATM_R)
        assert -1.0 < g.delta < 0.0, f"Put delta out of range: {g.delta}"

    def test_gamma_same_for_call_and_put(self) -> None:
        """Gamma is identical for call and put with same inputs."""
        call_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call", _ATM_R)
        put_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "put", _ATM_R)
        assert abs(call_g.gamma - put_g.gamma) < 1e-10

    def test_vega_same_for_call_and_put(self) -> None:
        """Vega is identical for call and put with same inputs."""
        call_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call", _ATM_R)
        put_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "put", _ATM_R)
        assert abs(call_g.vega - put_g.vega) < 1e-10

    def test_theta_negative_for_long_options(self) -> None:
        """Theta should be negative (time decay hurts long options)."""
        call_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call", _ATM_R)
        put_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "put", _ATM_R)
        assert call_g.theta < 0.0, f"Call theta should be negative: {call_g.theta}"
        assert put_g.theta < 0.0, f"Put theta should be negative: {put_g.theta}"

    def test_rho_call_positive_put_negative(self) -> None:
        """Call rho is positive (higher r → higher call); put rho is negative."""
        call_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call", _ATM_R)
        put_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "put", _ATM_R)
        assert call_g.rho > 0.0, f"Call rho should be positive: {call_g.rho}"
        assert put_g.rho < 0.0, f"Put rho should be negative: {put_g.rho}"

    def test_otm_call_price_positive(self) -> None:
        """OTM call price must be positive (time value remains)."""
        g = compute_bsm_greeks(_OTM_SPOT, _OTM_STRIKE, _OTM_T, _OTM_VOL, "call", _OTM_R)
        assert g.price > 0.0

    def test_deep_itm_put_price_near_intrinsic(self) -> None:
        """Deep ITM put price ≈ K*e^(-rT) - S (close to intrinsic value)."""
        g = compute_bsm_greeks(
            _ITM_PUT_SPOT, _ITM_PUT_STRIKE, _ITM_PUT_T, _ITM_PUT_VOL, "put", _ITM_PUT_R
        )
        intrinsic = _ITM_PUT_STRIKE * math.exp(-_ITM_PUT_R * _ITM_PUT_T) - _ITM_PUT_SPOT
        # BSM put price should exceed discounted intrinsic due to time value
        assert g.price > intrinsic * 0.9, (
            f"Deep ITM put price {g.price:.4f} far below discounted intrinsic {intrinsic:.4f}"
        )

    def test_option_type_stored_in_result(self) -> None:
        """option_type should be preserved in the returned BSMGreeks."""
        call_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call", _ATM_R)
        put_g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "put", _ATM_R)
        assert call_g.option_type == "call"
        assert put_g.option_type == "put"

    def test_returns_bsm_greeks_dataclass(self) -> None:
        """Return type must be BSMGreeks."""
        g = compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call", _ATM_R)
        assert isinstance(g, BSMGreeks)

    # --- Input validation ---

    def test_raises_on_non_positive_spot(self) -> None:
        with pytest.raises(ValueError, match="spot"):
            compute_bsm_greeks(0.0, _ATM_STRIKE, _ATM_T, _ATM_VOL, "call")

    def test_raises_on_non_positive_strike(self) -> None:
        with pytest.raises(ValueError, match="strike"):
            compute_bsm_greeks(_ATM_SPOT, -1.0, _ATM_T, _ATM_VOL, "call")

    def test_raises_on_non_positive_tte(self) -> None:
        with pytest.raises(ValueError, match="time_to_expiry_years"):
            compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, 0.0, _ATM_VOL, "call")

    def test_raises_on_non_positive_vol(self) -> None:
        with pytest.raises(ValueError, match="implied_vol"):
            compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, 0.0, "call")

    def test_raises_on_invalid_option_type(self) -> None:
        with pytest.raises(ValueError, match="option_type"):
            compute_bsm_greeks(_ATM_SPOT, _ATM_STRIKE, _ATM_T, _ATM_VOL, "forward")


class TestGreeksForStrategy:
    """Tests for greeks_for_strategy()."""

    def test_long_straddle_positive_vega(self) -> None:
        """Straddle is long vega: must be positive."""
        g = greeks_for_strategy(
            spot=100.0,
            strike_atm=100.0,
            time_to_expiry_years=0.25,
            implied_vol=0.30,
            structure="long_straddle",
        )
        assert g is not None
        assert g.vega > 0.0, f"Straddle vega should be positive: {g.vega}"

    def test_long_straddle_near_zero_delta(self) -> None:
        """ATM straddle delta is near 0 but not exactly 0 when r > 0.

        Straddle delta = N(d1) + (N(d1) - 1) = 2*N(d1) - 1.
        With r=5%, T=0.25, vol=30%: d1≈0.158, N(0.158)≈0.563, delta≈0.126.
        We accept |delta| < 0.20 as 'near zero' for a symmetric structure.
        """
        g = greeks_for_strategy(
            spot=100.0,
            strike_atm=100.0,
            time_to_expiry_years=0.25,
            implied_vol=0.30,
            structure="long_straddle",
        )
        assert g is not None
        assert abs(g.delta) < 0.20, f"Straddle delta should be small: {g.delta}"

    def test_long_straddle_option_type_label(self) -> None:
        """Straddle result should carry 'straddle' as option_type."""
        g = greeks_for_strategy(100.0, 100.0, 0.25, 0.30, "long_straddle")
        assert g is not None
        assert g.option_type == "straddle"

    def test_call_spread_positive_delta(self) -> None:
        """Bull call spread has net positive delta."""
        g = greeks_for_strategy(100.0, 100.0, 0.25, 0.30, "call_spread")
        assert g is not None
        assert g.delta > 0.0, f"Call spread delta should be positive: {g.delta}"

    def test_put_spread_negative_delta(self) -> None:
        """Bear put spread has net negative delta."""
        g = greeks_for_strategy(100.0, 100.0, 0.25, 0.30, "put_spread")
        assert g is not None
        assert g.delta < 0.0, f"Put spread delta should be negative: {g.delta}"

    def test_call_spread_price_positive(self) -> None:
        """Call spread debit must be positive (long leg > short leg)."""
        g = greeks_for_strategy(100.0, 100.0, 0.25, 0.30, "call_spread")
        assert g is not None
        assert g.price > 0.0, f"Call spread price should be positive: {g.price}"

    def test_put_spread_price_positive(self) -> None:
        """Put spread debit must be positive (long leg > short leg)."""
        g = greeks_for_strategy(100.0, 100.0, 0.25, 0.30, "put_spread")
        assert g is not None
        assert g.price > 0.0, f"Put spread price should be positive: {g.price}"

    def test_calendar_spread_returns_none(self) -> None:
        """Calendar spread is not yet implemented; should return None."""
        g = greeks_for_strategy(100.0, 100.0, 0.25, 0.30, "calendar_spread")
        assert g is None

    def test_unknown_structure_returns_none(self) -> None:
        """Unknown structure name should return None."""
        g = greeks_for_strategy(100.0, 100.0, 0.25, 0.30, "iron_condor")
        assert g is None

    def test_zero_tte_returns_none(self) -> None:
        """Near-zero time-to-expiry returns None (not a valid option)."""
        g = greeks_for_strategy(100.0, 100.0, 0.0005, 0.30, "long_straddle")
        assert g is None

    def test_zero_vol_returns_none(self) -> None:
        """Zero implied volatility returns None (cannot price)."""
        g = greeks_for_strategy(100.0, 100.0, 0.25, 0.0, "long_straddle")
        assert g is None

    def test_spread_otm_leg_uses_spread_width_percent(self) -> None:
        """OTM leg of call spread should be placed at spot*(1+_SPREAD_WIDTH_PERCENT)."""
        spot = 200.0
        expected_otm_strike = spot * (1.0 + _SPREAD_WIDTH_PERCENT)
        # Verify the spread is priced consistently with the OTM leg definition.
        # Long leg = ATM call at 200; short leg = OTM call at 210.
        long_call = compute_bsm_greeks(spot, spot, 0.25, 0.30, "call")
        short_call = compute_bsm_greeks(spot, expected_otm_strike, 0.25, 0.30, "call")
        g = greeks_for_strategy(spot, spot, 0.25, 0.30, "call_spread")
        assert g is not None
        assert abs(g.price - (long_call.price - short_call.price)) < 1e-8

    def test_straddle_price_equals_sum_of_legs(self) -> None:
        """Straddle price should equal ATM call price + ATM put price."""
        call_g = compute_bsm_greeks(100.0, 100.0, 0.5, 0.25, "call")
        put_g = compute_bsm_greeks(100.0, 100.0, 0.5, 0.25, "put")
        straddle_g = greeks_for_strategy(100.0, 100.0, 0.5, 0.25, "long_straddle")
        assert straddle_g is not None
        assert abs(straddle_g.price - (call_g.price + put_g.price)) < 1e-8
