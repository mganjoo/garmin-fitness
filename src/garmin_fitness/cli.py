"""Command-line entry point for read-only Garmin JSON fetches."""

from __future__ import annotations

import argparse
import inspect
import json
import math
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NoReturn, cast

from garminconnect import (  # type: ignore[import-untyped]
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_fitness.auth import AuthenticationError, load_client, login_interactively
from garmin_fitness.policy import (
    ALLOWED_METHODS,
    DENIED_METHODS,
    PolicyAuditError,
    verify_policy,
)

_SAFE_STRING_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*\Z")


@dataclass(frozen=True)
class CliError(Exception):
    """A stable, public command-line error."""

    code: str
    message: str
    exit_code: int = 2

    def as_json(self) -> dict[str, dict[str, str]]:
        """Return the public JSON error representation."""
        return {"error": {"code": self.code, "message": self.message}}


class _ArgumentParser(argparse.ArgumentParser):
    """Convert parser failures into the JSON CLI error contract."""

    def error(self, message: str) -> NoReturn:
        """Raise a stable error without writing argparse text to stderr."""
        del message
        raise CliError("invalid_command", "Invalid command syntax.")


def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the non-fetch command surfaces."""
    parser = _ArgumentParser(prog="garmin-fetch", add_help=False)
    parser.set_defaults(command=None)
    commands = parser.add_subparsers(dest="command")

    auth = commands.add_parser(
        "auth", help="Manage Garmin authentication.", add_help=False
    )
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_commands.add_parser(
        "login", help="Log in and save OAuth tokens.", add_help=False
    )
    auth_commands.add_parser(
        "status", help="Validate saved OAuth tokens.", add_help=False
    )

    commands.add_parser("methods", help="List allowed read methods.", add_help=False)
    help_command = commands.add_parser(
        "help", help="Describe an allowed read method.", add_help=False
    )
    help_command.add_argument("method")
    return parser


def _fetch_parser() -> argparse.ArgumentParser:
    """Build the parser for an allowed method invocation."""
    parser = _ArgumentParser(prog="garmin-fetch", add_help=False)
    parser.add_argument("method")
    parser.add_argument("--params", required=True)
    return parser


def _write_json(value: object, *, error: bool = False, sort_keys: bool = False) -> None:
    """Write compact JSON to the selected standard stream."""
    stream = sys.stderr if error else sys.stdout
    print(
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=sort_keys),
        file=stream,
    )


def _write_error(error: CliError | AuthenticationError) -> int:
    """Write a stable error and return its deterministic exit code."""
    _write_json(error.as_json(), error=True, sort_keys=True)
    if isinstance(error, AuthenticationError):
        return 2
    return error.exit_code


def _require_allowed_method(method_name: str) -> None:
    """Reject denied and unknown method names before client construction."""
    if method_name in DENIED_METHODS:
        raise CliError("method_denied", "The requested method is not allowed.")
    if method_name not in ALLOWED_METHODS:
        raise CliError("method_unknown", "The requested method is not available.")


def method_signature(method_name: str) -> inspect.Signature:
    """Return the public bound-method signature from pinned garminconnect."""
    method = cast(Callable[..., object], getattr(Garmin, method_name))
    signature = inspect.signature(method)
    parameters = tuple(signature.parameters.values())
    if parameters and parameters[0].name in {"self", "cls"}:
        parameters = parameters[1:]
    return signature.replace(parameters=parameters)


def _is_safe_param_value(value: object) -> bool:
    """Return whether a value can safely reach a reviewed method call."""
    if isinstance(value, str):
        return ".." not in value and _SAFE_STRING_VALUE.fullmatch(value) is not None
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (bool, int))


def _parse_params(raw_params: str, signature: inspect.Signature) -> dict[str, object]:
    """Parse and bind one JSON object of named method parameters."""
    try:
        decoded = json.loads(raw_params)
    except json.JSONDecodeError as exc:
        raise CliError("invalid_params", "Parameters must be a JSON object.") from exc
    if not isinstance(decoded, dict):
        raise CliError("invalid_params", "Parameters must be a JSON object.")

    params = cast(dict[str, object], decoded)
    named_parameters = {
        parameter.name
        for parameter in signature.parameters.values()
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    }
    if set(params) - named_parameters:
        raise CliError(
            "invalid_params", "Parameters do not match the method signature."
        )
    try:
        signature.bind(**params)
    except TypeError as exc:
        raise CliError(
            "invalid_params", "Parameters do not match the method signature."
        ) from exc
    if any(not _is_safe_param_value(value) for value in params.values()):
        raise CliError("invalid_params", "Parameters must use URL-safe scalar values.")
    return params


def _method_help(method_name: str) -> dict[str, str]:
    """Return metadata derived directly from the pinned client method."""
    _require_allowed_method(method_name)
    method = cast(Callable[..., object], getattr(Garmin, method_name))
    return {
        "name": method_name,
        "signature": str(method_signature(method_name)),
        "docstring": inspect.getdoc(method) or "",
    }


def _run_auth(auth_command: str) -> int:
    """Run the preserved authentication command surface."""
    try:
        client = login_interactively() if auth_command == "login" else load_client()
    except AuthenticationError as exc:
        return _write_error(exc)
    _write_json({"authenticated": True, "display_name": client.display_name})
    return 0


def _run_fetch(method_name: str, raw_params: str) -> int:
    """Preflight and invoke one allowed method using saved authentication."""
    try:
        _require_allowed_method(method_name)
        params = _parse_params(raw_params, method_signature(method_name))
    except CliError as exc:
        return _write_error(exc)

    try:
        client = load_client()
        method = cast(Callable[..., object], getattr(client, method_name))
        result = method(**params)
    except AuthenticationError as exc:
        return _write_error(exc)
    except GarminConnectTooManyRequestsError:
        return _write_error(
            CliError("rate_limited", "Garmin rate-limited the request.", 1)
        )
    except GarminConnectConnectionError:
        return _write_error(
            CliError("connection_failed", "Garmin could not be reached.", 1)
        )
    except GarminConnectAuthenticationError:
        return _write_error(
            CliError(
                "access_denied",
                "Garmin denied access to the requested data.",
                1,
            )
        )
    except Exception:
        return _write_error(
            CliError("method_failed", "The method could not be completed.", 1)
        )

    try:
        _write_json(result)
    except (OverflowError, RecursionError, TypeError, ValueError):
        return _write_error(
            CliError(
                "serialization_error", "The method result is not JSON serializable.", 1
            )
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    arguments = list(sys.argv[1:] if argv is None else argv)

    try:
        verify_policy()
        if not arguments:
            raise CliError("invalid_command", "Invalid command syntax.")
        if arguments[0] in {"auth", "methods", "help"}:
            args = build_parser().parse_args(arguments)
            if args.command == "auth":
                return _run_auth(args.auth_command)
            if args.command == "methods":
                _write_json({"methods": sorted(ALLOWED_METHODS)})
                return 0
            if args.command == "help":
                _write_json(_method_help(args.method))
                return 0
        args = _fetch_parser().parse_args(arguments)
        return _run_fetch(args.method, args.params)
    except CliError as exc:
        return _write_error(exc)
    except PolicyAuditError:
        return _write_error(
            CliError(
                "policy_drift",
                "The installed Garmin client does not match the reviewed policy.",
                1,
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
