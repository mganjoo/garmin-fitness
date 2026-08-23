"""Tests for the persistent authentication boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from garmin_fitness.auth import (
    AuthenticationError,
    load_client,
    login_interactively,
)


class FakeGarth:
    def __init__(self) -> None:
        self.dumps: list[Path] = []

    def dump(self, path: str) -> None:
        store = Path(path)
        self.dumps.append(store)
        (store / "oauth1_token.json").write_text(json.dumps({"token": "one"}))
        (store / "oauth2_token.json").write_text(json.dumps({"token": "two"}))


class FakeClient:
    def __init__(self, *, fail: bool = False, **kwargs: Any) -> None:
        self.display_name: str | None = "Runner"
        self.garth: FakeGarth = FakeGarth()
        self.fail = fail
        self.kwargs = kwargs
        self.login_args: list[str | None] = []

    def login(self, tokenstore: str | None = None) -> bool:
        self.login_args.append(tokenstore)
        if self.fail:
            raise RuntimeError("rejected")
        return True


def test_load_client_reuses_and_persists_refreshed_tokens(tmp_path: Path) -> None:
    store = tmp_path / "tokens"
    store.mkdir()
    client = FakeClient()

    result = load_client(client_factory=lambda: client, store=store)

    assert result is client
    assert client.login_args == [str(store)]
    assert len(client.garth.dumps) == 1
    assert client.garth.dumps[0] != store
    assert not client.garth.dumps[0].exists()
    assert store.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in store.iterdir())


def test_load_client_does_not_replace_unchanged_token_files(tmp_path: Path) -> None:
    store = tmp_path / "tokens"
    store.mkdir()
    oauth1 = store / "oauth1_token.json"
    oauth2 = store / "oauth2_token.json"
    oauth1.write_text(json.dumps({"token": "one"}))
    oauth2.write_text(json.dumps({"token": "two"}))
    original_inodes = (oauth1.stat().st_ino, oauth2.stat().st_ino)

    load_client(client_factory=FakeClient, store=store)

    assert (oauth1.stat().st_ino, oauth2.stat().st_ino) == original_inodes


def test_failed_token_dump_leaves_existing_store_untouched(tmp_path: Path) -> None:
    store = tmp_path / "tokens"
    store.mkdir()
    oauth1 = store / "oauth1_token.json"
    oauth2 = store / "oauth2_token.json"
    oauth1.write_text(json.dumps({"token": "original-one"}))
    oauth2.write_text(json.dumps({"token": "original-two"}))

    class InterruptedGarth(FakeGarth):
        def dump(self, path: str) -> None:
            staged = Path(path)
            (staged / "oauth1_token.json").write_text(
                json.dumps({"token": "replacement"})
            )
            raise KeyboardInterrupt

    client = FakeClient()
    client.garth = InterruptedGarth()

    with pytest.raises(KeyboardInterrupt):
        load_client(client_factory=lambda: client, store=store)

    assert json.loads(oauth1.read_text()) == {"token": "original-one"}
    assert json.loads(oauth2.read_text()) == {"token": "original-two"}


def test_load_client_missing_store_fails_without_constructing_client(
    tmp_path: Path,
) -> None:
    called = False

    def factory() -> FakeClient:
        nonlocal called
        called = True
        return FakeClient()

    with pytest.raises(AuthenticationError):
        load_client(client_factory=factory, store=tmp_path / "missing")
    assert not called


def test_load_client_maps_rejected_tokens_to_stable_error(tmp_path: Path) -> None:
    store = tmp_path / "tokens"
    store.mkdir()
    with pytest.raises(AuthenticationError) as raised:
        load_client(client_factory=lambda: FakeClient(fail=True), store=store)
    assert raised.value.as_json()["error"] == {
        "code": "authentication_required",
        "message": "Garmin authentication is required or has expired.",
        "action": "Run 'garmin-fetch auth login' in an interactive terminal.",
    }


def test_interactive_login_is_the_only_prompting_boundary(tmp_path: Path) -> None:
    prompts: list[str] = []
    secrets = iter(["password-value", "mfa-value"])
    client: FakeClient | None = None

    def factory(**kwargs: Any) -> FakeClient:
        nonlocal client
        client = FakeClient(**kwargs)
        return client

    def input_prompt(prompt: str) -> str:
        prompts.append(prompt)
        return "runner@example.invalid"

    def secret_prompt(prompt: str) -> str:
        prompts.append(prompt)
        return next(secrets)

    result = login_interactively(
        client_factory=factory,
        store=tmp_path / "tokens",
        input_fn=input_prompt,
        secret_fn=secret_prompt,
    )
    assert result is client
    assert client is not None
    assert client.kwargs["email"] == "runner@example.invalid"
    assert client.kwargs["password"] == "password-value"
    assert client.kwargs["prompt_mfa"]() == "mfa-value"
    assert client.login_args == [None]
    assert prompts == ["Garmin email: ", "Garmin password: ", "Garmin MFA code: "]
