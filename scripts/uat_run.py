#!/usr/bin/env python3
"""UAT runner: replay a known supply event and run the pipeline."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import sys

# Ensure project root is on sys.path so local packages (backtests, src) import correctly
repo = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))

from backtests.backtest_gdelt_vol import evaluate as gdelt_evaluate
from src.agents.event_detection.models import (
    DetectedEvent,
    EventType,
    EventIntensity,
)
import src.pipeline as pipeline
from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.ingestion.models import MarketState
from datetime import datetime as _dt


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
        detected_at=datetime(2022, 2, 24, tzinfo=timezone.utc),
        affected_instruments=["CL=F", "USO"],
        raw_headline="Sample GDELT volume spike detected",
    )

    print("Injecting one DetectedEvent into pipeline and running run_pipeline()...")

    # Monkeypatch the run_event_detection used by pipeline
    pipeline.run_event_detection = lambda: [detected]

    # Construct a synthetic FeatureSet for UAT to avoid DB expectations
    fs = FeatureSet(
        snapshot_time=_dt.now(tz=timezone.utc),
        volatility_gaps=[
            VolatilityGap(
                instrument="CL=F",
                realized_vol=0.15,
                implied_vol=0.30,
                gap=0.15,
                computed_at=_dt.now(tz=timezone.utc),
            )
        ],
        sector_dispersion=0.08,
        futures_curve_steepness=-0.02,
        supply_shock_probability=0.8,
    )

    # Monkeypatch run_ingestion and run_feature_generation to return controlled data
    pipeline.run_ingestion = lambda: MarketState(snapshot_time=detected.detected_at, prices=[], options=[], ingestion_errors=[])
    pipeline.run_feature_generation = lambda market_state, events: fs

    candidates = pipeline.run_pipeline()

    print(f"Pipeline produced {len(candidates)} candidate(s)")
    if candidates:
        # Print a summary of top 5 candidates
        summary = [
            {
                "instrument": c.instrument,
                "structure": c.structure.value if hasattr(c.structure, "value") else str(c.structure),
                "edge_score": c.edge_score,
                "signals": c.signals,
            }
            for c in candidates[:5]
        ]
        print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
