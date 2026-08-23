"""Persistent, noninteractive Garmin authentication boundary."""

from __future__ import annotations

import getpass
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from garminconnect import Garmin  # type: ignore[import-untyped]

TOKEN_STORE = Path("~/.garminconnect")


class TokenClient(Protocol):
    """The token persistence surface provided by Garth."""

    def dump(self, path: str) -> None: ...


class GarminSession(Protocol):
    """The Garmin client surface required by the authentication boundary."""

    @property
    def display_name(self) -> str | None: ...

    @property
    def garth(self) -> TokenClient: ...

    def login(self, tokenstore: str | None = None) -> bool: ...


ClientFactory = Callable[..., GarminSession]


class AuthenticationError(Exception):
    """A stable authentication failure safe to expose to CLI consumers."""

    code = "authentication_required"
    message = "Garmin authentication is required or has expired."
    action = "Run 'garmin-fetch auth login' in an interactive terminal."

    def as_json(self) -> dict[str, object]:
        """Return the public JSON error representation."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "action": self.action,
            }
        }


def token_store_path() -> Path:
    """Return the fixed library token-store path for the current home directory."""
    return TOKEN_STORE.expanduser()


def _secure_dump(client: GarminSession, store: Path) -> None:
    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    store.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix=".garmin-tokens-", dir=store.parent) as tmp:
        staged_store = Path(tmp)
        old_umask = os.umask(0o077)
        try:
            client.garth.dump(str(staged_store))
        finally:
            os.umask(old_umask)

        staged_files = tuple(staged_store.glob("*_token.json"))
        if {path.name for path in staged_files} != {
            "oauth1_token.json",
            "oauth2_token.json",
        }:
            raise RuntimeError("Garmin token dump was incomplete.")
        for staged_file in staged_files:
            payload = json.loads(staged_file.read_text())
            if not isinstance(payload, dict) or not payload:
                raise RuntimeError("Garmin token dump was invalid.")

        for staged_file in staged_files:
            destination = store / staged_file.name
            if (
                destination.is_file()
                and destination.read_bytes() == staged_file.read_bytes()
            ):
                destination.chmod(0o600)
                continue
            staged_file.chmod(0o600)
            os.replace(staged_file, destination)


def load_client(
    *, client_factory: ClientFactory = Garmin, store: Path | None = None
) -> GarminSession:
    """Load, validate, refresh, and persist saved tokens without prompting."""
    token_store = store or token_store_path()
    if not token_store.is_dir():
        raise AuthenticationError
    client = client_factory()
    try:
        client.login(str(token_store))
        _secure_dump(client, token_store)
    except Exception as exc:
        raise AuthenticationError from exc
    return client


def login_interactively(
    *,
    client_factory: ClientFactory = Garmin,
    store: Path | None = None,
    input_fn: Callable[[str], str] = input,
    secret_fn: Callable[[str], str] = getpass.getpass,
) -> GarminSession:
    """Prompt for credentials, authenticate, and save only OAuth tokens."""
    email = input_fn("Garmin email: ")
    password = secret_fn("Garmin password: ")
    client: GarminSession | None = None
    try:
        client = client_factory(
            email=email,
            password=password,
            prompt_mfa=lambda: secret_fn("Garmin MFA code: "),
        )
        client.login()
        _secure_dump(client, store or token_store_path())
    except Exception as exc:
        raise AuthenticationError from exc
    finally:
        email = ""
        password = ""
        if client is not None:
            setattr(client, "username", None)
            setattr(client, "password", None)
            setattr(client, "prompt_mfa", None)
    assert client is not None
    return client
