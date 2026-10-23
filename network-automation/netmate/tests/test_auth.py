"""SSH key / password login: validation, key discovery and real SSH logins."""

from __future__ import annotations

import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import auth
from auth import AuthConfig, AuthError, AuthMethod, check_key, default_key_file
from engine import Engine, Event, EventKind, Settings
from tests.conftest import KEY_PASSPHRASE, SshKeys
from tests.fake_ios import USERNAME, FakeIosServer

KEY = AuthMethod.SSH_KEY


# --------------------------------------------------------------------------- validation


def test_password_login_needs_a_password() -> None:
    with pytest.raises(AuthError, match="enter a password"):
        AuthConfig(AuthMethod.PASSWORD).validate()
    AuthConfig(AuthMethod.PASSWORD, password="x").validate()


def test_password_params() -> None:
    assert AuthConfig(AuthMethod.PASSWORD, password="pw").connection_params() == {"password": "pw"}


def test_key_params_need_no_password(ssh_keys: SshKeys) -> None:
    params = AuthConfig(KEY, key_file=str(ssh_keys.plain)).connection_params()
    assert params == {
        "use_keys": True,
        "key_file": str(ssh_keys.plain),
        "passphrase": None,
        "allow_agent": True,
        "password": "",
    }


@pytest.mark.parametrize(
    ("which", "passphrase", "error"),
    [
        ("plain", "", None),
        ("plain", "unneeded", None),
        ("encrypted", KEY_PASSPHRASE, None),
        ("rsa_encrypted", KEY_PASSPHRASE, None),
        ("encrypted", "", "is encrypted; enter its passphrase"),
        ("rsa_encrypted", "", "is encrypted; enter its passphrase"),
        ("encrypted", "wrong", "Wrong passphrase"),
        ("rsa_encrypted", "wrong", "Wrong passphrase"),
    ],
)
def test_check_key(ssh_keys: SshKeys, which: str, passphrase: str, error: str | None) -> None:
    path: Path = getattr(ssh_keys, which)
    if error is None:
        check_key(path, passphrase)
    else:
        with pytest.raises(AuthError, match=error):
            check_key(path, passphrase)


def test_public_key_or_garbage_is_rejected(ssh_keys: SshKeys, tmp_path: Path) -> None:
    with pytest.raises(AuthError, match="not a supported SSH private key"):
        check_key(ssh_keys.plain.with_name("id_ed25519.pub"))
    junk = tmp_path / "junk"
    junk.write_text("hello")
    with pytest.raises(AuthError, match="not a supported SSH private key"):
        check_key(junk)


def test_missing_key_file(tmp_path: Path) -> None:
    with pytest.raises(AuthError, match="not found"):
        AuthConfig(KEY, key_file=str(tmp_path / "nope")).validate()


def test_key_file_path_expands_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert AuthConfig(KEY, key_file="~/k").resolved_key_file() == tmp_path / "k"


def test_default_key_discovery_order(ssh_keys: SshKeys, tmp_path: Path) -> None:
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    assert default_key_file(ssh_dir) is None
    shutil.copy(ssh_keys.plain, ssh_dir / "id_rsa")
    assert default_key_file(ssh_dir) == ssh_dir / "id_rsa"
    shutil.copy(ssh_keys.plain, ssh_dir / "id_ed25519")
    assert default_key_file(ssh_dir) == ssh_dir / "id_ed25519"


def test_blank_key_file_uses_default_key(
    ssh_keys: SshKeys, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    shutil.copy(ssh_keys.plain, ssh_dir / "id_ed25519")
    monkeypatch.setattr(auth.Path, "home", staticmethod(lambda: tmp_path))
    cfg = AuthConfig(KEY)
    cfg.validate()
    assert cfg.connection_params()["key_file"] == str(ssh_dir / "id_ed25519")
    assert cfg.describe().startswith("ssh key ")


def test_agent_only_when_no_key_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(auth.os, "name", "posix")
    monkeypatch.setenv("SSH_AUTH_SOCK", "agent.sock")
    cfg = AuthConfig(KEY)
    cfg.validate()
    params = cfg.connection_params()
    assert params["use_keys"] is False  # netmiko rejects use_keys without a key_file
    assert params["allow_agent"] is True
    assert cfg.describe() == "ssh-agent"

    monkeypatch.delenv("SSH_AUTH_SOCK")
    with pytest.raises(AuthError, match="No SSH key found"):
        cfg.validate()


# --------------------------------------------------------------------------- real SSH


def run_with(server: FakeIosServer, cfg: AuthConfig) -> list[Event]:
    events: list[Event] = []
    lock = threading.Lock()

    def collect(e: Event) -> None:
        with lock:
            events.append(e)

    device: dict[str, Any] = {
        "device_type": "cisco_ios",
        "host": "127.0.0.1",
        "port": server.port,
        "username": USERNAME,
        **cfg.connection_params(),
    }
    Engine([device], ["show version"], collect, settings=Settings()).run()
    return events


@pytest.fixture
def key_only_server(ssh_keys: SshKeys) -> Iterator[FakeIosServer]:
    """Accepts the test keys and refuses password logins entirely."""
    with FakeIosServer(authorized_keys=ssh_keys.authorized_pubs, allow_password=False) as srv:
        yield srv


@pytest.mark.integration
@pytest.mark.parametrize(
    ("which", "passphrase"),
    [("plain", ""), ("encrypted", KEY_PASSPHRASE), ("rsa_encrypted", KEY_PASSPHRASE)],
)
def test_key_login_without_password(
    key_only_server: FakeIosServer, ssh_keys: SshKeys, which: str, passphrase: str
) -> None:
    cfg = AuthConfig(KEY, key_file=str(getattr(ssh_keys, which)), passphrase=passphrase)
    cfg.validate()
    events = run_with(key_only_server, cfg)
    (ok,) = [e for e in events if e.kind is EventKind.COMMAND_OK]
    assert "R1 uptime" in ok.output


@pytest.mark.integration
def test_unauthorized_key_is_an_auth_error(
    key_only_server: FakeIosServer, ssh_keys: SshKeys
) -> None:
    events = run_with(key_only_server, AuthConfig(KEY, key_file=str(ssh_keys.unauthorized)))
    (failed,) = [e for e in events if e.kind is EventKind.DEVICE_FAILED]
    assert failed.message.startswith("AUTH ERROR")
    assert key_only_server.connections == 1  # not retried


@pytest.mark.integration
def test_password_refused_by_key_only_device(key_only_server: FakeIosServer) -> None:
    events = run_with(key_only_server, AuthConfig(AuthMethod.PASSWORD, password="cisco123"))
    (failed,) = [e for e in events if e.kind is EventKind.DEVICE_FAILED]
    assert failed.message.startswith("AUTH ERROR")
