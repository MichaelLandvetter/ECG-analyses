"""Canonical string constants shared across the VER analysis application.

Centralising these names prevents mismatches between UI labels and backend
comparisons when strings are used as mode keys.
"""

# ---------------------------------------------------------------------------
# Scope filter modes
# ---------------------------------------------------------------------------
# These are the display labels shown in the UI dropdown *and* the values that
# BandpassFilter.scope_mode is compared against.  Always use these constants
# instead of raw string literals so that a rename only needs to happen here.

SCOPE_FILTER_BUTTERWORTH = "Butterworth"
SCOPE_FILTER_FIR = "FIR (Linear Phase)"
SCOPE_FILTER_SAVGOL = "Savitzky-Golay (Peak Preserve)"

# Ordered list used to populate the dropdown widget.
SCOPE_FILTER_MODES = [
    SCOPE_FILTER_BUTTERWORTH,
    SCOPE_FILTER_FIR,
    SCOPE_FILTER_SAVGOL,
]

# The default mode used when the filter is first constructed.
DEFAULT_SCOPE_FILTER_MODE = SCOPE_FILTER_BUTTERWORTH
