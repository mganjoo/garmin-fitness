"""Exhaustive read-only policy for the pinned Garmin client."""

from __future__ import annotations

import inspect
from collections import Counter
from collections.abc import Iterable, Mapping
from importlib.metadata import version
from types import MappingProxyType

from garminconnect import Garmin  # type: ignore[import-untyped]

PINNED_GARMINCONNECT_VERSION = "0.2.25"

# Keep the source ledger as a sequence so the audit can detect duplicate entries.
_ALLOWED_STRUCTURED_READ_ENTRIES = (
    "get_activities",
    "get_activities_by_date",
    "get_activities_fordate",
    "get_activity",
    "get_activity_details",
    "get_activity_exercise_sets",
    "get_activity_gear",
    "get_activity_hr_in_timezones",
    "get_activity_split_summaries",
    "get_activity_splits",
    "get_activity_typed_splits",
    "get_activity_types",
    "get_activity_weather",
    "get_adhoc_challenges",
    "get_all_day_events",
    "get_all_day_stress",
    "get_available_badge_challenges",
    "get_badge_challenges",
    "get_blood_pressure",
    "get_body_battery",
    "get_body_battery_events",
    "get_body_composition",
    "get_daily_steps",
    "get_daily_weigh_ins",
    "get_device_alarms",
    "get_device_last_used",
    "get_device_settings",
    "get_device_solar_data",
    "get_devices",
    "get_earned_badges",
    "get_endurance_score",
    "get_fitnessage_data",
    "get_floors",
    "get_full_name",
    "get_gear",
    "get_gear_ativities",
    "get_gear_defaults",
    "get_gear_stats",
    "get_goals",
    "get_heart_rates",
    "get_hill_score",
    "get_hrv_data",
    "get_hydration_data",
    "get_inprogress_virtual_challenges",
    "get_intensity_minutes_data",
    "get_last_activity",
    "get_max_metrics",
    "get_menstrual_calendar_data",
    "get_menstrual_data_for_date",
    "get_non_completed_badge_challenges",
    "get_personal_record",
    "get_pregnancy_summary",
    "get_primary_training_device",
    "get_progress_summary_between_dates",
    "get_race_predictions",
    "get_respiration_data",
    "get_rhr_day",
    "get_sleep_data",
    "get_spo2_data",
    "get_stats",
    "get_stats_and_body",
    "get_steps_data",
    "get_stress_data",
    "get_training_readiness",
    "get_training_status",
    "get_unit_system",
    "get_user_profile",
    "get_user_summary",
    "get_userprofile_settings",
    "get_weigh_ins",
    "get_workout_by_id",
    "get_workouts",
)

# Keep reasons with the source ledger so every denial is reviewable on its own.
_DENIED_METHOD_ENTRIES = (
    (
        "ActivityDownloadFormat",
        "Callable enum, not an instance data-read method.",
    ),
    (
        "ActivityUploadFormat",
        "Callable enum, not an instance data-read method.",
    ),
    (
        "add_body_composition",
        "Remote mutation: uploads a body-composition record.",
    ),
    (
        "add_hydration_data",
        "Remote mutation: writes a hydration record.",
    ),
    (
        "add_weigh_in",
        "Remote mutation: creates a weigh-in.",
    ),
    (
        "add_weigh_in_with_timestamps",
        "Remote mutation: creates a timestamped weigh-in.",
    ),
    (
        "connectapi",
        "Low-level request wrapper can access unreviewed endpoints and verbs.",
    ),
    (
        "create_manual_activity",
        "Remote mutation: creates a manual activity.",
    ),
    (
        "create_manual_activity_from_json",
        "Remote mutation: creates an activity from an arbitrary payload.",
    ),
    (
        "delete_activity",
        "Remote mutation: deletes an activity.",
    ),
    (
        "delete_blood_pressure",
        "Remote mutation: deletes a blood-pressure record.",
    ),
    (
        "delete_weigh_in",
        "Remote mutation: deletes a weigh-in.",
    ),
    (
        "delete_weigh_ins",
        "Remote mutation: deletes one or more weigh-ins.",
    ),
    (
        "download",
        "Low-level binary download bypasses the structured-read policy.",
    ),
    (
        "download_activity",
        "Binary activity download is deferred from structured reads.",
    ),
    (
        "download_workout",
        "Binary workout download is deferred from structured reads.",
    ),
    (
        "login",
        "Authentication only; token handling belongs to the auth boundary.",
    ),
    (
        "logout",
        "Authentication only; session handling belongs to the auth boundary.",
    ),
    (
        "query_garmin_graphql",
        "Arbitrary GraphQL can issue unreviewed reads or mutations.",
    ),
    (
        "request_reload",
        "Remote mutation: requests a server-side data reload.",
    ),
    (
        "set_activity_name",
        "Remote mutation: changes an activity name.",
    ),
    (
        "set_activity_type",
        "Remote mutation: changes an activity type.",
    ),
    (
        "set_blood_pressure",
        "Remote mutation: creates a blood-pressure record.",
    ),
    (
        "set_gear_default",
        "Remote mutation: changes or removes a default gear assignment.",
    ),
    (
        "upload_activity",
        "Remote mutation: uploads an activity file.",
    ),
)


class PolicyAuditError(RuntimeError):
    """Report a fail-closed mismatch between the client and method policy."""


def public_callable_names(owner: type[object]) -> frozenset[str]:
    """Return every public callable visible on a class."""
    return frozenset(
        name
        for name, member in inspect.getmembers(owner)
        if not name.startswith("_") and callable(member)
    )


def audit_method_policy(
    owner: type[object],
    allowed_entries: Iterable[str],
    denied_entries: Mapping[str, str] | Iterable[tuple[str, str]],
) -> None:
    """Raise an error unless the policy classifies the exact callable surface."""
    allowed = tuple(allowed_entries)
    denied = tuple(
        denied_entries.items()
        if isinstance(denied_entries, Mapping)
        else denied_entries
    )
    denied_names = tuple(name for name, _reason in denied)

    problems: list[str] = []
    duplicate_allowed = sorted(
        name for name, count in Counter(allowed).items() if count > 1
    )
    duplicate_denied = sorted(
        name for name, count in Counter(denied_names).items() if count > 1
    )
    if duplicate_allowed:
        problems.append(f"duplicate allowed entries: {duplicate_allowed}")
    if duplicate_denied:
        problems.append(f"duplicate denied entries: {duplicate_denied}")

    allowed_names = frozenset(allowed)
    denied_name_set = frozenset(denied_names)
    multiply_classified = sorted(allowed_names & denied_name_set)
    if multiply_classified:
        problems.append(
            f"methods classified as both allowed and denied: {multiply_classified}"
        )

    missing_reasons = sorted(name for name, reason in denied if not reason.strip())
    if missing_reasons:
        problems.append(f"denied methods without reasons: {missing_reasons}")

    surface = public_callable_names(owner)
    classified = allowed_names | denied_name_set
    unclassified = sorted(surface - classified)
    removed = sorted(classified - surface)
    if unclassified:
        problems.append(f"unclassified public callables: {unclassified}")
    if removed:
        problems.append(f"policy entries absent from public surface: {removed}")

    if problems:
        raise PolicyAuditError("; ".join(problems))


def _verify_pinned_dependency() -> None:
    installed_version = version("garminconnect")
    if installed_version != PINNED_GARMINCONNECT_VERSION:
        raise PolicyAuditError(
            "garminconnect version drift: expected "
            f"{PINNED_GARMINCONNECT_VERSION}, found {installed_version}"
        )


def verify_policy() -> None:
    """Fail closed if the installed client drifts from the reviewed policy."""
    _verify_pinned_dependency()
    audit_method_policy(
        Garmin,
        _ALLOWED_STRUCTURED_READ_ENTRIES,
        _DENIED_METHOD_ENTRIES,
    )


ALLOWED_METHODS = frozenset(_ALLOWED_STRUCTURED_READ_ENTRIES)
DENIED_METHODS: Mapping[str, str] = MappingProxyType(dict(_DENIED_METHOD_ENTRIES))

__all__ = [
    "ALLOWED_METHODS",
    "DENIED_METHODS",
    "PINNED_GARMINCONNECT_VERSION",
    "PolicyAuditError",
    "audit_method_policy",
    "public_callable_names",
    "verify_policy",
]
