#!/usr/bin/env python3
"""UAT runner: replay a known supply event and run the pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import pathlib
import sys
from unittest.mock import patch

# Ensure project root is on sys.path so local packages (backtests, src) import correctly
repo = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))

from backtests.backtest_gdelt_vol import evaluate as gdelt_evaluate
from src.agents.alternative_data.models import (
    AlternativeDataState,
    EventType as ShippingEventType,
    NarrativeSignal,
    Sentiment,
    ShippingEvent,
)
from src.agents.event_detection.models import (
    DetectedEvent,
    EventIntensity,
    EventType,
)
from src.agents.feature_generation.feature_generation_agent import (
    compute_narrative_velocity,
    compute_tanker_disruption_index,
)
from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.ingestion.models import MarketState
from src.agents.strategy_evaluation.strategy_evaluation_agent import evaluate_strategies
import src.pipeline as pipeline


def run_phase3_scenario() -> dict[str, object]:
    """UAT scenario for issue #162: Suez Canal blockage (Ever Given, 2021-03-23..29).

    Real, well-documented tanker chokepoint disruption event (see:
    https://en.wikipedia.org/wiki/2021_Suez_Canal_obstruction) with a
    reported positive correlation to crude oil price returns during the
    blockage week. The shipping and narrative records below are
    synthetic/injected — no live MarineTraffic/Reddit history is queried —
    but are dated to, and order-of-magnitude representative of, this real
    event, using the same injection methodology as the GDELT scenario above.

    Computes tanker_disruption_index and narrative_velocity from the injected
    records via the real compute_* functions, builds a Phase 1+2-only
    baseline FeatureSet and an otherwise-identical FeatureSet with those two
    Phase 3 signals added, and calls the real evaluate_strategies() on both
    (DB persistence mocked) to compare edge_score before/after.
    """
    event_window_start = datetime(2021, 3, 23, 7, 40, tzinfo=UTC)
    event_window_end = datetime(2021, 3, 29, 15, 5, tzinfo=UTC)
    instrument = "BZ=F"

    shipping_events = [
        ShippingEvent(
            vessel_id="EVER-GIVEN",
            event_type=ShippingEventType.ANCHORED,
            latitude=30.0,
            longitude=32.5,
            timestamp=event_window_start,
            source="marinetraffic",
            instrument=instrument,
        ),
    ] + [
        ShippingEvent(
            vessel_id=f"QUEUE-{i}",
            event_type=ShippingEventType.DELAYED,
            latitude=30.2,
            longitude=32.6,
            timestamp=datetime(2021, 3, 25, tzinfo=UTC),
            source="marinetraffic",
            instrument=instrument,
        )
        for i in range(1, 9)
    ]
    narrative_signals = [
        NarrativeSignal(
            instrument=instrument,
            platform="reddit",
            score=1200,
            mention_count=1500,
            sentiment=Sentiment.POSITIVE,
            window_start=event_window_start,
            window_end=event_window_end,
            source="reddit",
        ),
    ]
    alt_data = AlternativeDataState(
        snapshot_time=event_window_end,
        shipping_events=shipping_events,
        narrative_signals=narrative_signals,
    )

    tanker_disruption_index = compute_tanker_disruption_index(alt_data)
    narrative_velocity = compute_narrative_velocity(alt_data)

    vol_gap = VolatilityGap(
        instrument=instrument,
        realized_vol=0.18,
        implied_vol=0.30,
        gap=0.12,
        computed_at=event_window_end,
    )
    baseline_fs = FeatureSet(
        snapshot_time=event_window_end,
        volatility_gaps=[vol_gap],
        sector_dispersion=0.10,
    )
    phase3_fs = FeatureSet(
        snapshot_time=event_window_end,
        volatility_gaps=[vol_gap],
        sector_dispersion=0.10,
        tanker_disruption_index=tanker_disruption_index,
        narrative_velocity=narrative_velocity,
    )

    _sea = "src.agents.strategy_evaluation.strategy_evaluation_agent"
    with patch(f"{_sea}.get_engine"), patch(f"{_sea}.write_strategy_candidates"):
        baseline_candidates = evaluate_strategies(baseline_fs)
        phase3_candidates = evaluate_strategies(phase3_fs)

    baseline_c = next((c for c in baseline_candidates if c.instrument == instrument), None)
    phase3_c = next((c for c in phase3_candidates if c.instrument == instrument), None)
    baseline_score = baseline_c.edge_score if baseline_c else None
    phase3_score = phase3_c.edge_score if phase3_c else None

    return {
        "scenario": "Suez Canal blockage (Ever Given), 2021-03-23 to 2021-03-29",
        "instrument": instrument,
        "injected_shipping_events": len(shipping_events),
        "injected_narrative_signals": len(narrative_signals),
        "tanker_disruption_index": tanker_disruption_index,
        "narrative_velocity": narrative_velocity,
        "baseline_edge_score": baseline_score,
        "phase3_edge_score": phase3_score,
        "delta": (
            phase3_score - baseline_score
            if baseline_score is not None and phase3_score is not None
            else None
        ),
    }


def main() -> int:
    repo = pathlib.Path(__file__).resolve().parents[1]
    gdelt = repo / "backtests" / "sample_gdelt.csv"
    prices = repo / "backtests" / "sample_prices.csv"

    print("Running GDELT backtest evaluate() on sample data...")
    out = gdelt_evaluate(gdelt, prices, threshold=2.0, hold=3)
    print(json.dumps(out, indent=2))

    # Construct a DetectedEvent for the GDELT spike date
    detected = DetectedEvent(
        event_id="uat-gdelt-20220224",
        event_type=EventType.SUPPLY_DISRUPTION,
        description="Backtest supply spike (sample)",
        source="backtest",
        confidence_score=0.9,
        intensity=EventIntensity.HIGH,
        detected_at=datetime(2022, 2, 24, tzinfo=UTC),
        affected_instruments=["CL=F", "USO"],
        raw_headline="Sample GDELT volume spike detected",
    )

    print("Injecting one DetectedEvent into pipeline and running run_pipeline()...")

    # Monkeypatch the run_event_detection used by pipeline
    pipeline.run_event_detection = lambda: [detected]

    # Construct a synthetic FeatureSet for UAT to avoid DB expectations
    fs = FeatureSet(
        snapshot_time=datetime.now(tz=UTC),
        volatility_gaps=[
            VolatilityGap(
                instrument="CL=F",
                realized_vol=0.15,
                implied_vol=0.30,
                gap=0.15,
                computed_at=datetime.now(tz=UTC),
            )
        ],
        sector_dispersion=0.08,
        futures_curve_steepness=-0.02,
        supply_shock_probability=0.8,
    )

    # Monkeypatch run_ingestion and run_feature_generation to return controlled data
    pipeline.run_ingestion = lambda: MarketState(
        snapshot_time=detected.detected_at, prices=[], options=[], ingestion_errors=[]
    )
    pipeline.run_feature_generation = lambda market_state, events: fs

    candidates = pipeline.run_pipeline()

    print(f"Pipeline produced {len(candidates)} candidate(s)")
    if candidates:
        # Print a summary of top 5 candidates
        summary = [
            {
                "instrument": c.instrument,
                "structure": (
                    c.structure.value if hasattr(c.structure, "value") else str(c.structure)
                ),
                "edge_score": c.edge_score,
                "signals": c.signals,
            }
            for c in candidates[:5]
        ]
        print(json.dumps(summary, indent=2))

    print("\n" + "=" * 70)
    print("Phase 3 UAT scenario (issue #162): Suez Canal blockage, 2021-03-23..29")
    print("=" * 70)
    phase3_result = run_phase3_scenario()
    print(json.dumps(phase3_result, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
