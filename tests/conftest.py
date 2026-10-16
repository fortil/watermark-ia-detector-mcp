import pytest


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    """Keep tests away from the user's real verifier config."""
    monkeypatch.setenv("WMD_CONFIG", str(tmp_path / "no-such-config.toml"))
