"""
Black-Scholes-Merton (BSM) option pricing and Greeks engine.

Provides European-style option pricing and the standard first-order Greeks
(Delta, Gamma, Vega, Theta, Rho) using only the Python standard library.
No scipy or numpy dependency is required.

Inspired by the quant engine in EconomiaUNMSM/OptionStrat-AI, adapted for the
energy options domain and refactored for our agent pipeline.

Usage example (ATM call on USO):
    >>> result = compute_bsm_greeks(
    ...     spot=40.0, strike=40.0, time_to_expiry_years=30/365,
    ...     volatility=0.35, risk_free_rate=0.05, option_type="call"
    ... )
    >>> result.delta   # approx 0.53 for ATM call with T=30d, IV=35%
"""

from __future__ import annotations

from dataclasses import dataclass
import math

# Default annualized risk-free rate for energy options greeks computation.
# Approximates the 1-month US T-bill yield; callers may override per request.
DEFAULT_RISK_FREE_RATE: float = 0.05

# Convention: Vega and Rho are returned per 1-percentage-point change in
# volatility / rate (i.e., divided by 100), matching thinkorswim display units.
_PER_PERCENTAGE_POINT: float = 100.0

# Short-leg strike width for spread structures: the OTM leg is placed 5% from the ATM strike.
# Long call_spread: sell strike = ATM * (1 + _SPREAD_WIDTH_PERCENT)
# Long put_spread:  sell strike = ATM * (1 - _SPREAD_WIDTH_PERCENT)
_SPREAD_WIDTH_PERCENT: float = 0.05


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc (no external dependencies).

    Accurate to machine precision for all finite inputs.

    Args:
        x: Real-valued input.

    Returns:
        P(Z ≤ x) where Z ~ N(0, 1).
    """
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF.

    Args:
        x: Real-valued input.

    Returns:
        (1/√(2π)) * exp(-x²/2).
    """
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class BSMResult:
    """BSM option price and Greeks for a single option leg.

    All Greek values use the same denomination as the underlying price.
    Vega and Rho are scaled per 1% change in volatility / rate respectively,
    matching standard broker display conventions (e.g. thinkorswim).

    Attributes:
        price: Theoretical option price (same currency as spot/strike).
        delta: Rate of change of price with respect to the underlying price.
            Call delta ∈ (0, 1); put delta ∈ (-1, 0).
        gamma: Second derivative of option price with respect to the underlying.
            Always non-negative; identical for calls and puts.
        vega: Price change per +1% move in implied volatility.
        theta: Price change per calendar day (typically negative).
        rho: Price change per +1% move in risk-free rate.
        d1: Internal BSM d₁ parameter (useful for further computations).
        d2: Internal BSM d₂ parameter (useful for further computations).
    """

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    d1: float
    d2: float


def compute_bsm_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    option_type: str = "call",
) -> BSMResult | None:
    """Compute BSM option price and Greeks for a European option.

    Returns None if any input is invalid (e.g. zero or negative time/volatility)
    rather than raising, so callers can safely skip greeks enrichment when data
    is insufficient without crashing the pipeline.

    Args:
        spot: Current underlying price (must be positive).
        strike: Option strike price (must be positive).
        time_to_expiry_years: Time to expiration in years (must be positive).
            Use calendar_days / 365 for energy options.
        volatility: Annualized implied volatility as a decimal (e.g. 0.35 = 35%).
            Must be positive.
        risk_free_rate: Annualized continuously-compounded risk-free rate (decimal).
            Defaults to DEFAULT_RISK_FREE_RATE (5%).
        option_type: "call" or "put" (case-insensitive).

    Returns:
        BSMResult with price and all Greeks, or None if inputs are invalid.
    """
    opt = option_type.lower()
    if opt not in ("call", "put"):
        return None
    if spot <= 0.0 or strike <= 0.0:
        return None
    if time_to_expiry_years <= 0.0 or not math.isfinite(time_to_expiry_years):
        return None
    if volatility <= 0.0 or not math.isfinite(volatility):
        return None

    sqrt_t = math.sqrt(time_to_expiry_years)
    log_moneyness = math.log(spot / strike)
    d1 = (log_moneyness + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry_years) / (
        volatility * sqrt_t
    )
    d2 = d1 - volatility * sqrt_t

    disc = math.exp(-risk_free_rate * time_to_expiry_years)
    nd1 = _norm_cdf(d1)
    nd2 = _norm_cdf(d2)
    n_prime_d1 = _norm_pdf(d1)

    if opt == "call":
        price = spot * nd1 - strike * disc * nd2
        delta = nd1
        rho = strike * time_to_expiry_years * disc * nd2 / _PER_PERCENTAGE_POINT
    else:
        price = strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = nd1 - 1.0
        rho = -strike * time_to_expiry_years * disc * _norm_cdf(-d2) / _PER_PERCENTAGE_POINT

    gamma = n_prime_d1 / (spot * volatility * sqrt_t)
    vega = spot * n_prime_d1 * sqrt_t / _PER_PERCENTAGE_POINT
    theta = (
        -(spot * n_prime_d1 * volatility / (2.0 * sqrt_t))
        - risk_free_rate * strike * disc * (nd2 if opt == "call" else _norm_cdf(-d2))
    ) / 365.0  # per calendar day

    return BSMResult(
        price=price,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        rho=rho,
        d1=d1,
        d2=d2,
    )


def greeks_for_strategy(
    structure: str,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict[str, float] | None:
    """Compute combined Greeks for a multi-leg option structure.

    Aggregates per-leg Greeks using standard sign conventions:
    - long_straddle  : long call + long put (same strike)
    - call_spread    : long call (ATM) + short call (+1 strike tier, approx. ATM + 5%)
    - put_spread     : long put (ATM) + short put (-1 strike tier, approx. ATM - 5%)

    All structures are computed at the provided strike with the same IV, which
    is the ATM implied volatility passed by the caller. This is a simplified
    model; real spread Greeks depend on the short-leg strike which may differ.

    Args:
        structure: "long_straddle", "call_spread", or "put_spread".
        spot: Current underlying price.
        strike: ATM strike (closest to spot).
        time_to_expiry_years: Years to expiration.
        volatility: ATM implied volatility (annualized decimal).
        risk_free_rate: Annualized risk-free rate.

    Returns:
        Dict mapping Greek names to floats, or None if any leg computation fails.
        Keys: "delta", "gamma", "vega", "theta", "rho".
    """
    call = compute_bsm_greeks(
        spot, strike, time_to_expiry_years, volatility, risk_free_rate, "call"
    )
    put = compute_bsm_greeks(
        spot, strike, time_to_expiry_years, volatility, risk_free_rate, "put"
    )

    if call is None or put is None:
        return None

    # Spread short-leg strike: approximate 5% OTM from the ATM strike
    short_strike_call = strike * (1.0 + _SPREAD_WIDTH_PERCENT)
    short_strike_put = strike * (1.0 - _SPREAD_WIDTH_PERCENT)

    if structure == "long_straddle":
        # Long call + long put at the same strike
        return {
            "delta": round(call.delta + put.delta, 6),
            "gamma": round(call.gamma + put.gamma, 6),
            "vega": round(call.vega + put.vega, 6),
            "theta": round(call.theta + put.theta, 6),
            "rho": round(call.rho + put.rho, 6),
        }

    if structure == "call_spread":
        # Long ATM call - short OTM call
        short_call = compute_bsm_greeks(
            spot, short_strike_call, time_to_expiry_years, volatility, risk_free_rate, "call"
        )
        if short_call is None:
            return None
        return {
            "delta": round(call.delta - short_call.delta, 6),
            "gamma": round(call.gamma - short_call.gamma, 6),
            "vega": round(call.vega - short_call.vega, 6),
            "theta": round(call.theta - short_call.theta, 6),
            "rho": round(call.rho - short_call.rho, 6),
        }

    if structure == "put_spread":
        # Long ATM put - short OTM put
        short_put = compute_bsm_greeks(
            spot, short_strike_put, time_to_expiry_years, volatility, risk_free_rate, "put"
        )
        if short_put is None:
            return None
        return {
            "delta": round(put.delta - short_put.delta, 6),
            "gamma": round(put.gamma - short_put.gamma, 6),
            "vega": round(put.vega - short_put.vega, 6),
            "theta": round(put.theta - short_put.theta, 6),
            "rho": round(put.rho - short_put.rho, 6),
        }

    return None
