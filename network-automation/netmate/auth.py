"""SSH authentication options: password, or key file / ssh-agent without a password."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization

# Same order OpenSSH tries identities in.
DEFAULT_KEY_NAMES = ("id_ed25519", "id_ecdsa", "id_rsa")


class AuthMethod(str, Enum):
    PASSWORD = "password"  # noqa: S105 - enum label, not a credential
    SSH_KEY = "ssh_key"


class AuthError(ValueError):
    """The chosen credentials cannot be used; message is shown to the user."""


@dataclass(frozen=True)
class AuthConfig:
    method: AuthMethod = AuthMethod.PASSWORD
    password: str = ""
    key_file: str = ""  # blank: default key in ~/.ssh, then ssh-agent
    passphrase: str = ""

    def resolved_key_file(self) -> Path | None:
        if self.key_file.strip():
            return Path(self.key_file.strip()).expanduser()
        return default_key_file()

    def validate(self) -> None:
        """Raise AuthError before any device is contacted if login cannot work."""
        if self.method is AuthMethod.PASSWORD:
            if not self.password:
                raise AuthError("Please enter a password, or choose SSH key login")
            return
        key = self.resolved_key_file()
        if key is None:
            if agent_available():
                return
            raise AuthError(
                "No SSH key found. Choose a key file, put a key in ~/.ssh "
                f"({', '.join(DEFAULT_KEY_NAMES)}), or start ssh-agent."
            )
        if not key.is_file():
            raise AuthError(f"SSH key file not found: {key}")
        check_key(key, self.passphrase)

    def connection_params(self) -> dict[str, Any]:
        """Netmiko ConnectHandler arguments for this login."""
        if self.method is AuthMethod.PASSWORD:
            return {"password": self.password}
        key = self.resolved_key_file()
        return {
            "use_keys": key is not None,  # netmiko requires key_file when use_keys is set
            "key_file": str(key) if key is not None else None,
            "passphrase": self.passphrase or None,
            "allow_agent": True,
            "password": "",
        }

    def describe(self) -> str:
        if self.method is AuthMethod.PASSWORD:
            return "password"
        key = self.resolved_key_file()
        return f"ssh key {key}" if key is not None else "ssh-agent"


def default_key_file(ssh_dir: Path | None = None) -> Path | None:
    directory = ssh_dir if ssh_dir is not None else Path.home() / ".ssh"
    for name in DEFAULT_KEY_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def agent_available() -> bool:
    if os.name == "nt":  # Pageant / Windows OpenSSH agent: probed by paramiko itself
        return True
    return bool(os.environ.get("SSH_AUTH_SOCK"))


def check_key(path: Path, passphrase: str = "") -> None:
    """Load the private key once so a bad file or passphrase fails fast and clearly.

    Uses the same loaders paramiko uses (OpenSSH format first, then PEM).
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        raise AuthError(f"Cannot open SSH key {path}: {e.strerror or e}") from e
    password = passphrase.encode() or None
    for loader in (serialization.load_ssh_private_key, serialization.load_pem_private_key):
        try:
            loader(data, password)
        except TypeError as e:  # encrypted without a passphrase, or the reverse
            if password is None:
                raise AuthError(f"SSH key {path} is encrypted; enter its passphrase") from e
            try:
                loader(data, None)  # passphrase given for an unencrypted key: harmless
            except (TypeError, ValueError, UnsupportedAlgorithm):
                continue
            return
        except (ValueError, UnsupportedAlgorithm):
            continue
        return
    if password is not None:
        raise AuthError(f"Wrong passphrase for SSH key {path}")
    raise AuthError(f"{path} is not a supported SSH private key")
