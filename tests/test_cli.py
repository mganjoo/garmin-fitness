"""Tests for command-line JSON routing and authentication."""

import inspect
import json
from typing import Any

import pytest
from garminconnect import (  # type: ignore[import-untyped]
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

import garmin_fitness.cli as cli
from garmin_fitness.auth import AuthenticationError
from garmin_fitness.cli import build_parser, main
from garmin_fitness.policy import ALLOWED_METHODS, DENIED_METHODS, PolicyAuditError


def test_parser_has_expected_program_name() -> None:
    assert build_parser().prog == "garmin-fetch"


def test_bare_invocation_emits_invalid_command(capsys: Any) -> None:
    assert main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "invalid_command"


def test_policy_drift_emits_stable_json(monkeypatch: Any, capsys: Any) -> None:
    def fail_policy() -> None:
        raise PolicyAuditError("private audit detail")

    monkeypatch.setattr(cli, "verify_policy", fail_policy)
    assert main(["methods"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "policy_drift",
            "message": (
                "The installed Garmin client does not match the reviewed policy."
            ),
        }
    }


def test_auth_parser_has_login_and_status() -> None:
    assert build_parser().parse_args(["auth", "login"]).auth_command == "login"
    assert build_parser().parse_args(["auth", "status"]).auth_command == "status"


@pytest.mark.parametrize(
    "arguments",
    (
        ["--help"],
        ["auth", "--help"],
        ["auth", "login", "--help"],
        ["methods", "--help"],
        ["help", "--help"],
        ["get_activities", "--help"],
    ),
)
def test_help_flags_emit_stable_json_errors(arguments: list[str], capsys: Any) -> None:
    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "invalid_command",
            "message": "Invalid command syntax.",
        }
    }


def test_auth_status_emits_json_without_prompting(
    monkeypatch: Any, capsys: Any
) -> None:
    client = type("Client", (), {"display_name": "Runner"})()
    monkeypatch.setattr(cli, "load_client", lambda: client)
    assert main(["auth", "status"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "authenticated": True,
        "display_name": "Runner",
    }


def test_auth_error_is_stable_json_on_stderr(monkeypatch: Any, capsys: Any) -> None:
    def fail() -> None:
        raise AuthenticationError

    monkeypatch.setattr(cli, "load_client", fail)
    assert main(["auth", "status"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "authentication_required"


def test_methods_lists_only_allowed_methods(capsys: Any) -> None:
    assert main(["methods"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {"methods": sorted(ALLOWED_METHODS)}
    assert not (set(json.loads(captured.out)["methods"]) & DENIED_METHODS.keys())


def test_help_uses_pinned_method_metadata(capsys: Any) -> None:
    assert main(["help", "get_activities"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["name"] == "get_activities"
    assert payload["signature"] == str(cli.method_signature("get_activities"))
    assert payload["docstring"] == inspect.getdoc(Garmin.get_activities)


def test_help_rejects_denied_method_without_loading_client(
    monkeypatch: Any, capsys: Any
) -> None:
    def fail_load() -> None:
        raise AssertionError("load_client must not run")

    monkeypatch.setattr(cli, "load_client", fail_load)
    assert main(["help", "delete_activity"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "method_denied"


def test_denied_and_unknown_fetches_fail_before_client_loading(
    monkeypatch: Any, capsys: Any
) -> None:
    def fail_load() -> None:
        raise AssertionError("load_client must not run")

    monkeypatch.setattr(cli, "load_client", fail_load)
    for method_name, error_code in (
        ("delete_activity", "method_denied"),
        ("not_a_garmin_method", "method_unknown"),
    ):
        assert main([method_name, "--params", "{}"]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert json.loads(captured.err) == {
            "error": {
                "code": error_code,
                "message": (
                    "The requested method is not allowed."
                    if error_code == "method_denied"
                    else "The requested method is not available."
                ),
            }
        }


def test_invalid_json_and_signature_arguments_fail_before_client_loading(
    monkeypatch: Any, capsys: Any
) -> None:
    def fail_load() -> None:
        raise AssertionError("load_client must not run")

    monkeypatch.setattr(cli, "load_client", fail_load)
    invalid_calls = (
        ["get_activities", "--params", "not json"],
        ["get_activities", "--params", "[]"],
        ["get_activity", "--params", "{}"],
        ["get_activities", "--params", '{"unexpected":1}'],
    )
    for arguments in invalid_calls:
        assert main(arguments) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert json.loads(captured.err)["error"]["code"] == "invalid_params"


def test_params_reject_positional_only_fields() -> None:
    def positional_only(value: object, /) -> None:
        del value

    with pytest.raises(cli.CliError, match="invalid_params"):
        cli._parse_params('{"value":1}', inspect.signature(positional_only))


@pytest.mark.parametrize(
    "value",
    (
        "../../../userprofile-service/socialProfile",
        "segment..segment",
        "2026-08-22?redirect=profile",
        "2026-08-22#fragment",
        "2026-08-22%2f..%2fprofile",
        "2026-08-22 with-space",
    ),
)
def test_fetch_rejects_unsafe_string_values_before_client_loading(
    monkeypatch: Any, capsys: Any, value: str
) -> None:
    def fail_load() -> None:
        raise AssertionError("load_client must not run")

    monkeypatch.setattr(cli, "load_client", fail_load)
    arguments = [
        "get_training_readiness",
        "--params",
        json.dumps({"cdate": value}),
    ]
    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "invalid_params"


def test_fetch_rejects_nested_values_before_client_loading(
    monkeypatch: Any, capsys: Any
) -> None:
    def fail_load() -> None:
        raise AssertionError("load_client must not run")

    monkeypatch.setattr(cli, "load_client", fail_load)
    params = json.dumps({"cdate": ["../../../userprofile-service/socialProfile"]})
    assert main(["get_training_readiness", "--params", params]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "invalid_params"


def test_fetch_serializes_raw_result_to_stdout(monkeypatch: Any, capsys: Any) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def get_activities(self, start: int = 0, limit: int = 20) -> object:
            calls.append({"start": start, "limit": limit})
            return {"second": [1, 2], "first": True}

    monkeypatch.setattr(cli, "load_client", FakeClient)
    assert main(["get_activities", "--params", '{"limit":1}']) == 0
    captured = capsys.readouterr()
    assert captured.out == '{"second":[1,2],"first":true}\n'
    assert captured.err == ""
    assert calls == [{"start": 0, "limit": 1}]


def test_fetch_maps_authentication_and_serialization_errors(
    monkeypatch: Any, capsys: Any
) -> None:
    def auth_failure() -> None:
        raise AuthenticationError

    monkeypatch.setattr(cli, "load_client", auth_failure)
    assert main(["get_activities", "--params", "{}"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "authentication_required"

    class NonJsonClient:
        def get_activities(self, start: int = 0, limit: int = 20) -> object:
            del start, limit
            return {"not-json"}

    monkeypatch.setattr(cli, "load_client", NonJsonClient)
    assert main(["get_activities", "--params", "{}"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "serialization_error",
            "message": "The method result is not JSON serializable.",
        }
    }


@pytest.mark.parametrize(
    ("exception", "code"),
    (
        (GarminConnectTooManyRequestsError("limited"), "rate_limited"),
        (GarminConnectConnectionError("offline"), "connection_failed"),
        (GarminConnectAuthenticationError("private"), "access_denied"),
        (RuntimeError("unexpected"), "method_failed"),
    ),
)
def test_fetch_maps_remote_failures_to_stable_codes(
    monkeypatch: Any, capsys: Any, exception: Exception, code: str
) -> None:
    class FailingClient:
        def get_activities(self, start: int = 0, limit: int = 20) -> object:
            del start, limit
            raise exception

    monkeypatch.setattr(cli, "load_client", FailingClient)
    assert main(["get_activities", "--params", "{}"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == code


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_fetch_rejects_nonfinite_numbers_without_partial_stdout(
    monkeypatch: Any, capsys: Any, value: float
) -> None:
    class NonFiniteClient:
        def get_activities(self, start: int = 0, limit: int = 20) -> object:
            del start, limit
            return {"value": value}

    monkeypatch.setattr(cli, "load_client", NonFiniteClient)
    assert main(["get_activities", "--params", "{}"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "serialization_error",
            "message": "The method result is not JSON serializable.",
        }
    }
