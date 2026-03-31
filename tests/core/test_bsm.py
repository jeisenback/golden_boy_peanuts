"""
Unit tests for src/core/bsm.py — Black-Scholes-Merton Greeks engine.

Tests cover:
  - compute_bsm_greeks: price and Greeks for calls and puts
  - Input validation: None returned on invalid inputs
  - ATM parity: put-call parity must hold
  - greeks_for_strategy: combined Greeks for long_straddle, call_spread, put_spread
"""

from __future__ import annotations

import math

import pytest

from src.core.bsm import BSMResult, compute_bsm_greeks, greeks_for_strategy

# Standard test case: ATM call, 30-day expiry, 35% IV, 5% risk-free rate
_SPOT = 40.0
_STRIKE = 40.0  # ATM
_T = 30 / 365  # ≈ 0.0822 years
_IV = 0.35
_R = 0.05


class TestComputeBSMGreeks:
    """Tests for compute_bsm_greeks() covering pricing, Greeks, and guards."""

    def test_call_price_positive(self) -> None:
        """ATM call price should be positive."""
        result = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        assert result is not None
        assert result.price > 0.0

    def test_put_price_positive(self) -> None:
        """ATM put price should be positive."""
        result = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "put")
        assert result is not None
        assert result.price > 0.0

    def test_put_call_parity(self) -> None:
        """C - P = S - K*exp(-r*T) (put-call parity for European options)."""
        call = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        put = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "put")
        assert call is not None and put is not None
        lhs = call.price - put.price
        rhs = _SPOT - _STRIKE * math.exp(-_R * _T)
        assert abs(lhs - rhs) < 1e-10

    def test_call_delta_atm_near_half(self) -> None:
        """ATM call delta should be slightly above 0.5 (N(d1) with d1 > 0)."""
        result = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        assert result is not None
        assert 0.5 < result.delta < 0.6

    def test_put_delta_atm_near_neg_half(self) -> None:
        """ATM put delta should be slightly above -0.5."""
        result = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "put")
        assert result is not None
        assert -0.6 < result.delta < -0.4

    def test_call_put_delta_parity(self) -> None:
        """call.delta - put.delta == 1 (BSM delta parity for European options)."""
        call = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        put = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "put")
        assert call is not None and put is not None
        # Delta parity: call_delta = put_delta + 1 → call_delta - put_delta == 1
        assert abs(call.delta - put.delta - 1.0) < 1e-10

    def test_gamma_positive(self) -> None:
        """Gamma must always be positive (same for calls and puts)."""
        call = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        put = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "put")
        assert call is not None and put is not None
        assert call.gamma > 0.0
        assert put.gamma > 0.0

    def test_call_put_gamma_equal(self) -> None:
        """Call and put gamma are identical (same underlying, same inputs)."""
        call = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        put = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "put")
        assert call is not None and put is not None
        assert abs(call.gamma - put.gamma) < 1e-12

    def test_vega_positive(self) -> None:
        """Vega must be positive (higher IV → higher option value)."""
        call = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        assert call is not None
        assert call.vega > 0.0

    def test_call_put_vega_equal(self) -> None:
        """Call and put vega are identical (same inputs)."""
        call = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        put = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "put")
        assert call is not None and put is not None
        assert abs(call.vega - put.vega) < 1e-12

    def test_theta_negative(self) -> None:
        """Theta must be negative for long options (time decay)."""
        call = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        assert call is not None
        assert call.theta < 0.0

    def test_call_rho_positive(self) -> None:
        """Call rho must be positive (higher rate → higher call value)."""
        call = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        assert call is not None
        assert call.rho > 0.0

    def test_put_rho_negative(self) -> None:
        """Put rho must be negative (higher rate → lower put value)."""
        put = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "put")
        assert put is not None
        assert put.rho < 0.0

    def test_returns_none_on_zero_spot(self) -> None:
        """Zero spot price returns None (guard against division by zero)."""
        assert compute_bsm_greeks(0.0, _STRIKE, _T, _IV) is None

    def test_returns_none_on_negative_spot(self) -> None:
        """Negative spot returns None."""
        assert compute_bsm_greeks(-1.0, _STRIKE, _T, _IV) is None

    def test_returns_none_on_zero_time(self) -> None:
        """Zero time to expiry returns None."""
        assert compute_bsm_greeks(_SPOT, _STRIKE, 0.0, _IV) is None

    def test_returns_none_on_zero_volatility(self) -> None:
        """Zero volatility returns None."""
        assert compute_bsm_greeks(_SPOT, _STRIKE, _T, 0.0) is None

    def test_returns_none_on_invalid_option_type(self) -> None:
        """Unknown option type returns None."""
        assert compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, option_type="straddle") is None

    def test_case_insensitive_option_type(self) -> None:
        """Option type matching is case-insensitive."""
        lower = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, option_type="call")
        upper = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, option_type="CALL")
        assert lower is not None and upper is not None
        assert abs(lower.price - upper.price) < 1e-12

    def test_deep_itm_call_delta_near_one(self) -> None:
        """Deep ITM call (spot >> strike) delta should approach 1."""
        result = compute_bsm_greeks(100.0, 50.0, _T, _IV, _R, "call")
        assert result is not None
        assert result.delta > 0.99

    def test_deep_otm_call_delta_near_zero(self) -> None:
        """Deep OTM call (spot << strike) delta should approach 0."""
        result = compute_bsm_greeks(20.0, 100.0, _T, _IV, _R, "call")
        assert result is not None
        assert result.delta < 0.01

    def test_returns_bsm_result_instance(self) -> None:
        """Return type is BSMResult dataclass."""
        result = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        assert isinstance(result, BSMResult)

    def test_energy_instrument_uso(self) -> None:
        """Realistic USO parameters: 30d, 35% IV, $40 spot."""
        result = compute_bsm_greeks(40.0, 40.0, 30 / 365, 0.35, 0.05, "call")
        assert result is not None
        # ATM call price should be roughly S * σ * sqrt(T/(2π))
        rough_est = 40.0 * 0.35 * math.sqrt((30 / 365) / (2 * math.pi))
        assert abs(result.price - rough_est) < rough_est * 0.25  # within 25%


class TestGreeksForStrategy:
    """Tests for greeks_for_strategy() composite structure Greeks."""

    def test_long_straddle_delta_near_zero(self) -> None:
        """Long straddle ATM delta is approximately zero (call + put ≈ cancel).

        With a non-zero risk-free rate, straddle delta = 2*N(d1) - 1 ≈ 0.07
        for r=5%, so the threshold is set to 0.15 to accommodate realistic rates.
        """
        result = greeks_for_strategy("long_straddle", _SPOT, _STRIKE, _T, _IV, _R)
        assert result is not None
        assert abs(result["delta"]) < 0.15  # small but non-zero due to risk-free rate

    def test_long_straddle_vega_double(self) -> None:
        """Long straddle vega ≈ 2x single-leg vega (long call + long put)."""
        single = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        straddle = greeks_for_strategy("long_straddle", _SPOT, _STRIKE, _T, _IV, _R)
        assert single is not None and straddle is not None
        # straddle vega is rounded to 6 dp; compare with 1e-6 tolerance
        assert abs(straddle["vega"] - 2 * single.vega) < 1e-6

    def test_long_straddle_theta_double(self) -> None:
        """Long straddle theta ≈ 2x single-leg theta (twice the time decay)."""
        single = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        straddle = greeks_for_strategy("long_straddle", _SPOT, _STRIKE, _T, _IV, _R)
        assert single is not None and straddle is not None
        # straddle theta is rounded to 6 dp; compare with 1e-4 tolerance (theta is small)
        assert abs(straddle["theta"] - 2 * single.theta) < 1e-4

    def test_call_spread_delta_positive(self) -> None:
        """Call spread (long ATM call - short OTM call) has positive delta."""
        result = greeks_for_strategy("call_spread", _SPOT, _STRIKE, _T, _IV, _R)
        assert result is not None
        assert result["delta"] > 0.0

    def test_call_spread_delta_less_than_one(self) -> None:
        """Call spread delta must be less than 1 (short call reduces delta)."""
        result = greeks_for_strategy("call_spread", _SPOT, _STRIKE, _T, _IV, _R)
        assert result is not None
        assert result["delta"] < 1.0

    def test_put_spread_delta_negative(self) -> None:
        """Put spread (long ATM put - short OTM put) has negative delta."""
        result = greeks_for_strategy("put_spread", _SPOT, _STRIKE, _T, _IV, _R)
        assert result is not None
        assert result["delta"] < 0.0

    def test_unknown_structure_returns_none(self) -> None:
        """Unknown structure name returns None."""
        result = greeks_for_strategy("iron_condor", _SPOT, _STRIKE, _T, _IV, _R)
        assert result is None

    def test_invalid_inputs_return_none(self) -> None:
        """Zero volatility returns None (propagates from compute_bsm_greeks guard)."""
        result = greeks_for_strategy("long_straddle", _SPOT, _STRIKE, _T, 0.0, _R)
        assert result is None

    def test_call_spread_vega_less_than_single_call(self) -> None:
        """Call spread vega is less than a naked call (short leg reduces exposure)."""
        single = compute_bsm_greeks(_SPOT, _STRIKE, _T, _IV, _R, "call")
        spread = greeks_for_strategy("call_spread", _SPOT, _STRIKE, _T, _IV, _R)
        assert single is not None and spread is not None
        assert spread["vega"] < single.vega

    def test_result_keys_complete(self) -> None:
        """All expected Greek keys are present in the result dict."""
        result = greeks_for_strategy("long_straddle", _SPOT, _STRIKE, _T, _IV, _R)
        assert result is not None
        assert set(result.keys()) == {"delta", "gamma", "vega", "theta", "rho"}
