"""Shared pytest setup: headless Qt and test isolation."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

# Must be set before the first QApplication is created (pytest-qt creates it lazily).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Settings, session and log files are relative to the working directory."""
    monkeypatch.chdir(tmp_path)
    yield tmp_path


KEY_PASSPHRASE = "s3cret-phrase"


@dataclass(frozen=True)
class SshKeys:
    """Private key files (OpenSSH format) with matching .pub files next to them."""

    plain: Path  # ed25519, no passphrase (the usual ~/.ssh/id_ed25519)
    encrypted: Path  # ed25519 protected by KEY_PASSPHRASE
    rsa_encrypted: Path  # RSA protected by KEY_PASSPHRASE
    unauthorized: Path  # valid key the test server does not accept

    @property
    def authorized_pubs(self) -> list[Path]:
        return [
            p.with_name(p.name + ".pub") for p in (self.plain, self.encrypted, self.rsa_encrypted)
        ]


def _write_key(
    path: Path,
    key: ed25519.Ed25519PrivateKey | rsa.RSAPrivateKey,
    passphrase: str = "",
) -> Path:
    encryption: serialization.KeySerializationEncryption = (
        serialization.BestAvailableEncryption(passphrase.encode())
        if passphrase
        else serialization.NoEncryption()
    )
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, encryption
        )
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    path.with_name(path.name + ".pub").write_bytes(public + b" test@netmate\n")
    return path


@pytest.fixture(scope="session")
def ssh_keys(tmp_path_factory: pytest.TempPathFactory) -> SshKeys:
    d = tmp_path_factory.mktemp("keys")
    return SshKeys(
        plain=_write_key(d / "id_ed25519", ed25519.Ed25519PrivateKey.generate()),
        encrypted=_write_key(
            d / "id_ed25519_enc", ed25519.Ed25519PrivateKey.generate(), KEY_PASSPHRASE
        ),
        rsa_encrypted=_write_key(
            d / "id_rsa_enc", rsa.generate_private_key(65537, 2048), KEY_PASSPHRASE
        ),
        unauthorized=_write_key(d / "id_other", ed25519.Ed25519PrivateKey.generate()),
    )
