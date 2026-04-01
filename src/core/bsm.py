"""
Black-Scholes-Merton (BSM) Greeks Engine

Pure-math implementation -- no scipy, no external numerical libraries.
Uses only Python standard library (math module) so it runs in any environment.

Normal CDF implemented via math.erf per NIST DLMF 7.2.2:
    N(x) = 0.5 * (1 + erf(x / sqrt(2)))

Normal PDF (standard Gaussian density):
    phi(x) = exp(-0.5 * x^2) / sqrt(2 * pi)

Greeks implemented for European calls and puts:
    - Delta:  sensitivity of option price to underlying price movement
    - Gamma:  second-order price sensitivity (same for calls and puts)
    - Theta:  time decay (negative for long options; expressed per calendar day)
    - Vega:   sensitivity to implied volatility (expressed per 1-point IV change)
    - Rho:    sensitivity to risk-free rate (expressed per 1-point rate change)

Module-level constants:
    _SPREAD_WIDTH_PERCENT = 0.05  (5%) -- OTM leg placement for spread structures

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, no scipy dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

# Spread OTM leg displacement as a fraction of the underlying spot price.
# A call spread sells a call 5% above spot; a put spread buys a put 5% below spot.
_SPREAD_WIDTH_PERCENT: float = 0.05

# Minimum time-to-expiry in years to avoid division-by-zero in BSM denominator.
# Below this threshold greeks_for_strategy() returns None.
_MIN_TIME_TO_EXPIRY_YEARS: float = 1.0 / 365.0  # 1 calendar day

# Risk-free rate proxy — 3-month US T-bill yield; overridable via argument.
# Using a constant default keeps the module self-contained for Phase 1.
DEFAULT_RISK_FREE_RATE: float = 0.05  # 5% annualized


# ---------------------------------------------------------------------------
# Internal math helpers
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function N(x).

    Uses the complementary error function identity:
        N(x) = 0.5 * (1 + erf(x / sqrt(2)))

    Args:
        x: Real-valued argument.

    Returns:
        Probability P(Z ≤ x) for Z ~ N(0, 1).
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function φ(x).

    Args:
        x: Real-valued argument.

    Returns:
        Density value at x.
    """
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BSMGreeks:
    """
    Black-Scholes-Merton Greeks for a single option leg.

    All values are expressed in standard market conventions:
        - delta:  dimensionless, sign-adjusted per option_type
        - gamma:  per $1 move in underlying
        - theta:  per calendar day (negative for long options)
        - vega:   per 1-point (1.0) move in implied volatility
        - rho:    per 1-point (1.0) move in risk-free rate
        - price:  theoretical option premium
        - option_type: 'call' or 'put'
    """

    delta: float
    gamma: float
    theta: float  # daily theta
    vega: float
    rho: float
    price: float
    option_type: str


# ---------------------------------------------------------------------------
# Core BSM computation
# ---------------------------------------------------------------------------

def compute_bsm_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    implied_vol: float,
    option_type: str,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> BSMGreeks:
    """
    Compute Black-Scholes-Merton price and Greeks for a European option.

    Formula reference: Hull, *Options, Futures, and Other Derivatives*, 11th ed.
        d1 = (ln(S/K) + (r + 0.5*vol^2)*T) / (vol*sqrt(T))
        d2 = d1 - vol*sqrt(T)
        Call price = S*N(d1) - K*exp(-r*T)*N(d2)
        Put  price = K*exp(-r*T)*N(-d2) - S*N(-d1)

    Greeks:
        Delta (call) = N(d1),  Delta (put) = N(d1) - 1
        Gamma        = phi(d1) / (S*vol*sqrt(T))            [same for call and put]
        Theta (call) = -(S*phi(d1)*vol)/(2*sqrt(T)) - r*K*exp(-r*T)*N(d2)
        Theta (put)  = -(S*phi(d1)*vol)/(2*sqrt(T)) + r*K*exp(-r*T)*N(-d2)
        Vega         = S*phi(d1)*sqrt(T)                    [same for call and put]
        Rho  (call)  = K*T*exp(-r*T)*N(d2)
        Rho  (put)   = -K*T*exp(-r*T)*N(-d2)

    Theta and Vega are scaled to market conventions:
        - Theta: divided by 365 to express daily decay.
        - Vega:  divided by 100 to express sensitivity per 1-point IV move.

    Args:
        spot: Current underlying price (S). Must be > 0.
        strike: Option strike price (K). Must be > 0.
        time_to_expiry_years: Time to expiration expressed in years (T). Must be > 0.
        implied_vol: Annualized implied volatility as a decimal (e.g. 0.30 for 30%).
                     Must be > 0.
        option_type: 'call' or 'put'.
        risk_free_rate: Annualized continuous risk-free rate (default 5%).

    Returns:
        BSMGreeks dataclass with delta, gamma, theta, vega, rho, and price.

    Raises:
        ValueError: If spot, strike, time_to_expiry_years, or implied_vol are
                    non-positive, or if option_type is not 'call' or 'put'.
    """
    if spot <= 0.0:
        raise ValueError(f"spot must be positive, got {spot}")
    if strike <= 0.0:
        raise ValueError(f"strike must be positive, got {strike}")
    if time_to_expiry_years <= 0.0:
        raise ValueError(f"time_to_expiry_years must be positive, got {time_to_expiry_years}")
    if implied_vol <= 0.0:
        raise ValueError(f"implied_vol must be positive, got {implied_vol}")
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    # Standard BSM variable aliases: S=spot, K=strike, T=time, r=rate, vol=implied_vol
    S = spot      # noqa: N806
    K = strike    # noqa: N806
    T = time_to_expiry_years  # noqa: N806
    r = risk_free_rate
    sigma = implied_vol

    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    disc = math.exp(-r * T)
    phi_d1 = _norm_pdf(d1)

    if option_type == "call":
        price = S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta_annual = (
            -(S * phi_d1 * sigma) / (2.0 * sqrt_t)
            - r * K * disc * _norm_cdf(d2)
        )
        rho = K * T * disc * _norm_cdf(d2)
    else:  # put
        price = K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta_annual = (
            -(S * phi_d1 * sigma) / (2.0 * sqrt_t)
            + r * K * disc * _norm_cdf(-d2)
        )
        rho = -K * T * disc * _norm_cdf(-d2)

    gamma = phi_d1 / (S * sigma * sqrt_t)
    vega_annual = S * phi_d1 * sqrt_t

    # Scale to market conventions
    theta_daily = theta_annual / 365.0
    vega_per_point = vega_annual / 100.0
    rho_per_point = rho / 100.0

    return BSMGreeks(
        delta=delta,
        gamma=gamma,
        theta=theta_daily,
        vega=vega_per_point,
        rho=rho_per_point,
        price=price,
        option_type=option_type,
    )


# ---------------------------------------------------------------------------
# Strategy-level Greeks aggregation
# ---------------------------------------------------------------------------

def greeks_for_strategy(
    spot: float,
    strike_atm: float,
    time_to_expiry_years: float,
    implied_vol: float,
    structure: str,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> BSMGreeks | None:
    """
    Compute net BSM Greeks for a multi-leg option structure.

    Supported structures (PRD Section 3.2):
        long_straddle  — long ATM call + long ATM put
        call_spread    — long ATM call + short OTM call (_SPREAD_WIDTH_PERCENT above spot)
        put_spread     — long ATM put  + short OTM put  (_SPREAD_WIDTH_PERCENT below spot)
        calendar_spread — not yet implemented; returns None

    The returned BSMGreeks represents the net position (sum of all legs),
    where long legs contribute positively and short legs contribute negatively.

    Args:
        spot: Current underlying price.
        strike_atm: ATM strike to use for the primary leg (typically closest to spot).
        time_to_expiry_years: Time to expiration in years. Returns None if below
                              _MIN_TIME_TO_EXPIRY_YEARS (< 1 calendar day).
        implied_vol: Annualized implied volatility (decimal).
        structure: One of 'long_straddle', 'call_spread', 'put_spread',
                   'calendar_spread'.
        risk_free_rate: Annualized risk-free rate (default DEFAULT_RISK_FREE_RATE).

    Returns:
        BSMGreeks with net position Greeks, or None if:
          - structure is 'calendar_spread' (not implemented),
          - time_to_expiry_years is below _MIN_TIME_TO_EXPIRY_YEARS,
          - implied_vol is 0 or negative (cannot price).
    """
    if time_to_expiry_years < _MIN_TIME_TO_EXPIRY_YEARS:
        return None
    if implied_vol <= 0.0:
        return None
    if structure == "calendar_spread":
        return None

    otm_strike_call = spot * (1.0 + _SPREAD_WIDTH_PERCENT)
    otm_strike_put = spot * (1.0 - _SPREAD_WIDTH_PERCENT)

    if structure == "long_straddle":
        call_leg = compute_bsm_greeks(
            spot, strike_atm, time_to_expiry_years, implied_vol, "call", risk_free_rate
        )
        put_leg = compute_bsm_greeks(
            spot, strike_atm, time_to_expiry_years, implied_vol, "put", risk_free_rate
        )
        return BSMGreeks(
            delta=call_leg.delta + put_leg.delta,
            gamma=call_leg.gamma + put_leg.gamma,
            theta=call_leg.theta + put_leg.theta,
            vega=call_leg.vega + put_leg.vega,
            rho=call_leg.rho + put_leg.rho,
            price=call_leg.price + put_leg.price,
            option_type="straddle",
        )

    if structure == "call_spread":
        long_call = compute_bsm_greeks(
            spot, strike_atm, time_to_expiry_years, implied_vol, "call", risk_free_rate
        )
        short_call = compute_bsm_greeks(
            spot, otm_strike_call, time_to_expiry_years, implied_vol, "call", risk_free_rate
        )
        return BSMGreeks(
            delta=long_call.delta - short_call.delta,
            gamma=long_call.gamma - short_call.gamma,
            theta=long_call.theta - short_call.theta,
            vega=long_call.vega - short_call.vega,
            rho=long_call.rho - short_call.rho,
            price=long_call.price - short_call.price,
            option_type="call_spread",
        )

    if structure == "put_spread":
        long_put = compute_bsm_greeks(
            spot, strike_atm, time_to_expiry_years, implied_vol, "put", risk_free_rate
        )
        short_put = compute_bsm_greeks(
            spot, otm_strike_put, time_to_expiry_years, implied_vol, "put", risk_free_rate
        )
        return BSMGreeks(
            delta=long_put.delta - short_put.delta,
            gamma=long_put.gamma - short_put.gamma,
            theta=long_put.theta - short_put.theta,
            vega=long_put.vega - short_put.vega,
            rho=long_put.rho - short_put.rho,
            price=long_put.price - short_put.price,
            option_type="put_spread",
        )

    return None
