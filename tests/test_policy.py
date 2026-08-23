"""Tests for the exhaustive Garmin method policy."""

from __future__ import annotations

from importlib.metadata import version

import pytest
from garminconnect import Garmin  # type: ignore[import-untyped]

from garmin_fitness.policy import (
    ALLOWED_METHODS,
    DENIED_METHODS,
    PINNED_GARMINCONNECT_VERSION,
    PolicyAuditError,
    audit_method_policy,
    public_callable_names,
    verify_policy,
)

EXPECTED_REMOTE_MUTATIONS = frozenset(
    {
        "add_body_composition",
        "add_hydration_data",
        "add_weigh_in",
        "add_weigh_in_with_timestamps",
        "create_manual_activity",
        "create_manual_activity_from_json",
        "delete_activity",
        "delete_blood_pressure",
        "delete_weigh_in",
        "delete_weigh_ins",
        "request_reload",
        "set_activity_name",
        "set_activity_type",
        "set_blood_pressure",
        "set_gear_default",
        "upload_activity",
    }
)


def _callable() -> None:
    return None


def _surface_without(method_name: str) -> type[object]:
    return type(
        "ChangedGarmin",
        (),
        {
            name: staticmethod(_callable)
            for name in public_callable_names(Garmin)
            if name != method_name
        },
    )


def test_policy_matches_pinned_public_callable_surface() -> None:
    verify_policy()
    surface = public_callable_names(Garmin)

    assert version("garminconnect") == PINNED_GARMINCONNECT_VERSION
    assert len(surface) == 97
    assert len(ALLOWED_METHODS) == 72
    assert len(DENIED_METHODS) == 25
    assert ALLOWED_METHODS.isdisjoint(DENIED_METHODS)
    assert ALLOWED_METHODS | DENIED_METHODS.keys() == surface
    assert all(reason.strip() for reason in DENIED_METHODS.values())


def test_all_remote_mutations_are_denied() -> None:
    assert len(EXPECTED_REMOTE_MUTATIONS) == 16
    assert EXPECTED_REMOTE_MUTATIONS <= DENIED_METHODS.keys()
    assert EXPECTED_REMOTE_MUTATIONS.isdisjoint(ALLOWED_METHODS)
    assert {
        name
        for name, reason in DENIED_METHODS.items()
        if reason.startswith("Remote mutation:")
    } == EXPECTED_REMOTE_MUTATIONS


def test_unknown_public_callable_causes_audit_failure() -> None:
    changed_surface = {
        name: staticmethod(_callable) for name in public_callable_names(Garmin)
    }
    changed_surface["unexpected_method"] = staticmethod(_callable)
    changed_garmin = type("ChangedGarmin", (), changed_surface)

    with pytest.raises(PolicyAuditError, match="unclassified public callables"):
        audit_method_policy(changed_garmin, ALLOWED_METHODS, DENIED_METHODS)


def test_removed_public_callable_causes_audit_failure() -> None:
    removed_method = next(iter(ALLOWED_METHODS))

    with pytest.raises(
        PolicyAuditError, match="policy entries absent from public surface"
    ):
        audit_method_policy(
            _surface_without(removed_method), ALLOWED_METHODS, DENIED_METHODS
        )


@pytest.mark.parametrize("classification", ["allowed", "denied"])
def test_duplicate_policy_entry_causes_audit_failure(
    classification: str,
) -> None:
    allowed_entries: tuple[str, ...] = tuple(ALLOWED_METHODS)
    denied_entries: tuple[tuple[str, str], ...] = tuple(DENIED_METHODS.items())
    if classification == "allowed":
        allowed_entries += (allowed_entries[0],)
    else:
        denied_entries += (denied_entries[0],)

    with pytest.raises(PolicyAuditError, match=f"duplicate {classification}"):
        audit_method_policy(Garmin, allowed_entries, denied_entries)


def test_multiply_classified_method_causes_audit_failure() -> None:
    allowed_name = next(iter(ALLOWED_METHODS))
    denied_entries = (*DENIED_METHODS.items(), (allowed_name, "Test denial."))

    with pytest.raises(PolicyAuditError, match="classified as both allowed and denied"):
        audit_method_policy(Garmin, ALLOWED_METHODS, denied_entries)
