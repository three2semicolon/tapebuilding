"""lib.config - every env var the project reads is named, defaulted, and parsed in one place."""

import pytest

from lib import config


def test_string_var_returns_env_when_set(monkeypatch):
    monkeypatch.setenv("SOUNDCLOUD_USER", "someone")
    assert config.SOUNDCLOUD_USER == "someone"


def test_string_var_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("SOUNDCLOUD_USER", raising=False)
    assert config.SOUNDCLOUD_USER == "me"


def test_string_var_returns_none_when_no_default(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    assert config.SPOTIFY_CLIENT_ID is None


def test_bool_parsing(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_PRE_SKIP_EXISTING", "false")
    assert config.DOWNLOAD_PRE_SKIP_EXISTING is False
    monkeypatch.setenv("DOWNLOAD_PRE_SKIP_EXISTING", "1")
    assert config.DOWNLOAD_PRE_SKIP_EXISTING is True


def test_int_parsing(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_RETRIES", "5")
    assert config.DOWNLOAD_RETRIES == 5


def test_list_parsing(monkeypatch):
    monkeypatch.setenv("PLAYLISTS_EXCLUDE", "a, b ,,c")
    assert config.PLAYLISTS_EXCLUDE == ["a", "b", "c"]


def test_list_empty_when_unset(monkeypatch):
    monkeypatch.delenv("PLAYLISTS_EXCLUDE", raising=False)
    assert config.PLAYLISTS_EXCLUDE == []


def test_float_parsing(monkeypatch):
    monkeypatch.setenv("SPOTAPI_DELAY", "0.5")
    assert config.SPOTAPI_DELAY == 0.5


def test_unknown_attribute_raises():
    with pytest.raises(AttributeError):
        config.NOT_A_SETTING  # type: ignore[attr-defined]
