# pylint: disable=missing-docstring, import-outside-toplevel, protected-access, unused-argument, redefined-outer-name
# pylint: disable=too-few-public-methods, missing-function-docstring
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_encryption_key_unavailable.py — #283 (COG-21).

With ``storage.encrypt: true`` and ``keyring`` + ``cryptography`` installed but no keyring backend reachable (SSH
without a desktop session, a container, another user, a locked keychain), the graph refused to save with
"graph.pkl is encrypted and could not be decrypted ... Install keyring + cryptography". The refusal is right; the
text was not: graph.pkl may be plain, and the packages were installed. The message now names the cause:

* the packages are missing (the old text, still right for that case),
* there is no usable keyring backend here (which one, and how to get one),
* the keychain is locked,
* the key in the keychain does not open this file,
* the file is encrypted but ``storage.encrypt`` is off.

The ``null`` keyring backend also stops handing out a throw-away key on every call (data encrypted under it could
never be read again).
"""
from __future__ import annotations

import json
import os
import sys
import warnings

import pytest

keyring = pytest.importorskip("keyring")
pytest.importorskip("cryptography")

from keyring.backend import KeyringBackend  # noqa: E402  # pylint: disable=wrong-import-position
from keyring.backends import fail, null  # noqa: E402  # pylint: disable=wrong-import-position
from keyring.errors import KeyringLocked  # noqa: E402  # pylint: disable=wrong-import-position

from data.graph.knowledge_graph import (  # noqa: E402  # pylint: disable=wrong-import-position
    GraphLockedError, KnowledgeGraph, NodeType, _graph_file, _journal_file,
)


class _Memory(KeyringBackend):
    """A keychain that works, held in a dict."""
    priority = 1

    def __init__(self):
        super().__init__()
        self.store: dict = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


class _Locked(KeyringBackend):
    """A keychain that exists but is locked."""
    priority = 1

    def get_password(self, service, username):
        raise KeyringLocked("the keychain is locked")

    def set_password(self, service, username, password):
        raise KeyringLocked("the keychain is locked")

    def delete_password(self, service, username):
        raise KeyringLocked("the keychain is locked")


@pytest.fixture()
def use_keyring():
    """Switch the active keyring backend for one test and put the real one back."""
    original = keyring.get_keyring()
    yield keyring.set_keyring
    keyring.set_keyring(original)


def _config(encrypt: bool) -> None:
    with open(os.path.join(".cognirepo", "config.json"), "w", encoding="utf-8") as f:
        json.dump({"project_id": "cog21", "storage": {"encrypt": encrypt}}, f)


def _load_quietly() -> "tuple[KnowledgeGraph, list[str]]":
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        graph = KnowledgeGraph()
    return graph, [str(w.message) for w in caught]


def _save_error(graph: KnowledgeGraph) -> str:
    with pytest.raises(GraphLockedError) as err:
        graph.save()
    return str(err.value)


def _encrypted_graph(backend) -> None:
    """Write an encrypted graph.pkl under *backend*'s key."""
    keyring.set_keyring(backend)
    _config(True)
    graph = KnowledgeGraph()
    graph.add_node("secret.py", NodeType.FILE)
    graph.save()
    assert open(_graph_file(), "rb").read().startswith(b"gAAAAA")


def _plain_graph_with_a_journal() -> None:
    """The A6 state: a plain graph.pkl and a plain journal on disk."""
    _config(False)
    graph = KnowledgeGraph()
    graph.add_node("plain.py", NodeType.FILE)
    graph.save()
    graph = KnowledgeGraph()
    graph.begin_journal()
    graph.add_node("later.py", NodeType.FILE)
    graph.end_journal()
    assert os.path.exists(_journal_file())


# ── the reported case: encrypt on, plain files, no keyring backend ────────────

def test_no_keyring_backend_is_reported_as_that_and_not_as_missing_packages(isolated_cognirepo, use_keyring):
    _plain_graph_with_a_journal()
    _config(True)
    use_keyring(fail.Keyring())

    graph, _ = _load_quietly()
    msg = _save_error(graph)

    assert "no usable keyring backend" in msg
    assert "backends.fail.Keyring" in msg, "the backend that was found must be named"
    assert "keyring and cryptography are installed" in msg
    assert "PYTHON_KEYRING_BACKEND" in msg, "the way to get a backend must be there"
    assert "pipx inject" not in msg and "Install keyring" not in msg, "the packages are installed: do not send the user to install them"


def test_the_message_does_not_claim_a_plain_graph_is_encrypted(isolated_cognirepo, use_keyring):
    _plain_graph_with_a_journal()
    _config(True)
    use_keyring(fail.Keyring())

    graph, warned = _load_quietly()

    assert "graph.pkl is encrypted" not in _save_error(graph)
    assert not any("graph.pkl is encrypted" in w for w in warned)
    assert graph.G.has_node("plain.py"), "the plain graph.pkl still loads; only saving needs the key"


def test_a_plain_files_refusal_leaves_everything_on_disk_untouched(isolated_cognirepo, use_keyring):
    _plain_graph_with_a_journal()
    before = (open(_graph_file(), "rb").read(), open(_journal_file(), "rb").read())
    _config(True)
    use_keyring(fail.Keyring())

    graph, _ = _load_quietly()
    _save_error(graph)

    assert (open(_graph_file(), "rb").read(), open(_journal_file(), "rb").read()) == before


# ── an encrypted graph.pkl: each cause says what it is ────────────────────────

def test_encrypted_graph_without_a_keyring_backend(isolated_cognirepo, use_keyring):
    _encrypted_graph(_Memory())
    use_keyring(fail.Keyring())

    graph, warned = _load_quietly()
    msg = _save_error(graph)

    assert "graph.pkl is encrypted" in msg, "this file really is encrypted"
    assert "no usable keyring backend" in msg and "Install keyring" not in msg
    assert any("no usable keyring backend" in w for w in warned)


def test_a_locked_keychain_says_it_is_locked(isolated_cognirepo, use_keyring):
    _encrypted_graph(_Memory())
    use_keyring(_Locked())

    graph, _ = _load_quietly()
    msg = _save_error(graph)

    assert "locked" in msg and "unlock" in msg
    assert "Install keyring" not in msg


def test_a_key_that_does_not_open_the_file_says_so(isolated_cognirepo, use_keyring):
    _encrypted_graph(_Memory())
    use_keyring(_Memory())  # a different, empty keychain: it mints a different key

    graph, _ = _load_quietly()
    msg = _save_error(graph)

    assert "does not decrypt" in msg
    assert "Install keyring" not in msg


def test_an_encrypted_file_with_encryption_switched_off_says_to_switch_it_on(isolated_cognirepo, use_keyring):
    """The fallout of #280: storage.encrypt flipped to false while the files stayed encrypted."""
    _encrypted_graph(_Memory())
    _config(False)

    graph, warned = _load_quietly()
    msg = _save_error(graph)

    assert "storage.encrypt" in msg and "true" in msg
    assert "Install keyring" not in msg and "pipx inject" not in msg
    assert any("storage.encrypt" in w for w in warned)


def test_missing_packages_still_get_the_install_hint(isolated_cognirepo, use_keyring, monkeypatch):
    _encrypted_graph(_Memory())
    monkeypatch.setitem(sys.modules, "keyring", None)  # import keyring -> ImportError

    graph, _ = _load_quietly()
    msg = _save_error(graph)

    assert "pipx inject cognirepo keyring cryptography" in msg


def test_a_lock_is_cleared_when_the_key_comes_back(isolated_cognirepo, use_keyring):
    memory = _Memory()
    _encrypted_graph(memory)
    use_keyring(fail.Keyring())
    graph, _ = _load_quietly()
    assert graph._locked

    use_keyring(memory)
    graph.load()

    assert not graph._locked and graph.G.has_node("secret.py")
    graph.save()  # no longer refused


def test_the_incremental_index_guard_reports_the_same_cause(isolated_cognirepo, use_keyring):
    _encrypted_graph(_Memory())
    use_keyring(fail.Keyring())
    graph, _ = _load_quietly()

    ok, reason = graph.incremental_base_status(10)

    assert not ok and "no usable keyring backend" in reason


def test_a_damaged_journal_keeps_its_own_wording(isolated_cognirepo):
    """Not a key problem: the existing 'could not be read' warning is unchanged."""
    _plain_graph_with_a_journal()
    with open(_journal_file(), "r+b") as f:  # flip bytes inside the first record's payload
        f.seek(20)
        f.write(b"\xff\xff\xff\xff")
        f.seek(0, os.SEEK_END)
        f.write(b"\x00" * 64)  # more data after it, so it is mid-file damage and not a torn tail

    _, warned = _load_quietly()

    assert any("could not be read" in w for w in warned)


# ── saving when nothing is locked yet ─────────────────────────────────────────

def test_saving_a_new_graph_without_a_keyring_backend_gives_the_clear_message(isolated_cognirepo, use_keyring):
    from core.security.encryption import KeyUnavailableError

    _config(True)
    use_keyring(fail.Keyring())
    graph = KnowledgeGraph()
    graph.add_node("x.py", NodeType.FILE)

    with pytest.raises(KeyUnavailableError, match="no usable keyring backend"):
        graph.save()
    assert not os.path.exists(_graph_file())


# ── the helper ────────────────────────────────────────────────────────────────

def test_get_or_create_key_wraps_a_keyring_failure_and_keeps_the_cause(isolated_cognirepo, use_keyring):
    from core.security.encryption import KeyUnavailableError, get_or_create_key

    use_keyring(fail.Keyring())

    with pytest.raises(KeyUnavailableError) as err:
        get_or_create_key("p")

    assert isinstance(err.value.__cause__, keyring.errors.NoKeyringError)


def test_the_null_backend_does_not_hand_out_a_throw_away_key(isolated_cognirepo, use_keyring):
    """null.get_password() returns None and set_password() drops the key, so every call minted a new one and
    anything encrypted with it could never be read again."""
    from core.security.encryption import KeyUnavailableError, get_or_create_key

    use_keyring(null.Keyring())

    with pytest.raises(KeyUnavailableError, match="no usable keyring backend"):
        get_or_create_key("p")


def test_a_working_keychain_keeps_giving_the_same_key(isolated_cognirepo, use_keyring):
    from core.security.encryption import get_or_create_key

    memory = _Memory()
    use_keyring(memory)

    assert get_or_create_key("p") == get_or_create_key("p")
    assert len(memory.store) == 1


@pytest.mark.parametrize("exc,needle", [
    (ImportError("Encryption requires additional packages.\n  pipx (recommended):  pipx inject cognirepo keyring cryptography"),
     "pipx inject"),
    (RuntimeError("something odd"), "RuntimeError: something odd"),
    (None, "storage.encrypt"),
])
def test_explain_key_failure(isolated_cognirepo, use_keyring, exc, needle):
    from core.security.encryption import explain_key_failure

    use_keyring(_Memory())  # a usable backend, so the backend itself is not what is being explained

    assert needle in explain_key_failure(exc)


def test_explain_key_failure_for_a_wrong_key(isolated_cognirepo, use_keyring):
    from cryptography.fernet import InvalidToken
    from core.security.encryption import explain_key_failure

    use_keyring(_Memory())

    assert "does not decrypt" in explain_key_failure(InvalidToken())


def test_the_install_probe_and_the_core_helper_agree_on_what_is_unusable():
    from core.security.encryption import is_unusable_backend
    from interface.cli import install_probe

    for backend in ("keyring.backends.fail.Keyring", "keyring.backends.null.Keyring",
                    "keyring.backends.SecretService.Keyring", None):
        assert install_probe.is_unusable_backend(backend) == is_unusable_backend(backend)
