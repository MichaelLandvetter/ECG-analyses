"""ECG-named analysis-flow compatibility module.

Transitional shim that re-exports analysis routing helpers from the inherited module.
"""
from src.ecg_analyses.ver.ver_analysis_flow import (
    BACK_TO_ANALYSIS,
    PROCEED_TO_VALIDATION,
    RoutingDecision,
    decide_next_step,
)

__all__ = [
    "BACK_TO_ANALYSIS",
    "PROCEED_TO_VALIDATION",
    "RoutingDecision",
    "decide_next_step",
]
