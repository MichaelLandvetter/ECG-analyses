ECG Compatibility Aliases (Transitional)
This project currently supports both:

ECG-first names:
detect_ecg_peaks
refresh_ecg_analysis_config
Legacy compatibility aliases:
detect_ver_peaks
refresh_analysis_config
Why this exists
During the VER → ECG transition, compatibility aliases allow older call sites and external scripts to continue working while migration PRs land incrementally.

Current contract
ecg_analysis_engine exports both ECG-first names and legacy aliases.
Tests enforce this export surface to avoid accidental breaking changes.

Suggested deprecation path (future)
Keep both names during transition.
Announce deprecation of legacy aliases in release notes.
Optionally add non-failing runtime warnings for legacy alias usage.
Remove aliases only after all internal/external consumers are migrated and a deprecation window has elapsed.
Maintainer note
Do not remove legacy aliases in refactor-only PRs unless accompanied by:

migration updates for all known call sites,
test updates,
and an explicit breaking-change communication.