"""Helpers for end-of-analysis action handling."""

import logging

log = logging.getLogger(__name__)

PROCEED_TO_VALIDATION = "proceed_to_validation"
BACK_TO_ANALYSIS = "back_to_analysis"
CANCEL_ANALYSIS = "cancel"


def normalize_analysis_complete_action(action: str | None) -> str:
    """Normalize any completion action to a supported value."""

    if action in {PROCEED_TO_VALIDATION, BACK_TO_ANALYSIS, CANCEL_ANALYSIS}:
        return action
    if action is not None:
        log.warning("Unexpected analysis completion action %r; treating it as cancel.", action)
    return CANCEL_ANALYSIS


def should_proceed_to_human_validation(action: str | None) -> bool:
    """Return True only when the completion choice explicitly proceeds."""

    return normalize_analysis_complete_action(action) == PROCEED_TO_VALIDATION


def status_message_for_analysis_complete_action(
    action: str | None,
    *,
    has_session_averages: bool,
) -> str:
    """Return the post-EOF status message for the selected action."""

    normalized_action = normalize_analysis_complete_action(action)
    if not has_session_averages or normalized_action == PROCEED_TO_VALIDATION:
        return "End of file reached"
    if normalized_action == BACK_TO_ANALYSIS:
        return "Analysis complete. Adjust settings and rerun when ready."
    return "Analysis complete."
