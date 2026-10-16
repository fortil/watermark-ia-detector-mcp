"""Tests for the plain handlers and the MCP server built on top of them."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from fixtures import mock_verifier, signed_jpeg, write_config
from watermark_ia_detector_mcp.server import (
    SERVER_NAME,
    capabilities,
    certs,
    detect_file,
    detect_text,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def signed(tmp_path_factory):
    data, pki = signed_jpeg()
    p = tmp_path_factory.mktemp("fx") / "claude_like.jpg"
    p.write_bytes(data)
    return p, pki


# --- plain handlers -----------------------------------------------------------


def test_detect_file_confirmed_with_pinned_anchor(signed):
    p, pki = signed
    out = detect_file(str(p), anchors_pem=[pki.root_pem.decode()])
    assert out["errors"] == []
    hits = [f for f in out["findings"] if f["verdict"] == "confirmed" and f["provider"]]
    assert hits, out
    assert hits[0]["provider"] == "claude"
    assert hits[0]["evidence"]["trusted_via"] == "user-anchor"


def test_detect_file_claimed_without_anchor(signed):
    p, _ = signed
    out = detect_file(str(p))
    assert any(f["verdict"] == "claimed" and f["provider"] == "claude" for f in out["findings"])


def test_detect_file_unreadable(tmp_path):
    out = detect_file(str(tmp_path / "no-such.jpg"))
    assert out["errors"] == ["cannot read file: FileNotFoundError"]


def test_detect_file_unsupported(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"\x00\x01\x02\x00")
    out = detect_file(str(p))
    assert out["errors"] == ["unsupported file type"]


def test_detect_text_remote_scores_and_never_leaks_the_key(tmp_path, monkeypatch):
    key = "test-key-value-do-not-print"
    with mock_verifier() as mock:
        cfg = write_config(tmp_path / "verifiers.toml", mock.url)
        monkeypatch.setenv("WMD_TEST_KEY", key)
        out = detect_text("some watermarked words here", remote=True, config_path=str(cfg))
    f = next(f for f in out["findings"] if f["provider"] == "claude")
    assert f["verdict"] == "score"
    assert f["evidence"]["score"] == 0.87
    assert f["evidence"]["label"] == "likely"
    assert f["evidence"]["word_count"] == 4
    assert key not in json.dumps(out)
    assert mock.requests
    assert mock.requests[0]["body"]["text"] == "some watermarked words here"
    assert mock.requests[0]["headers"]["Authorization"] == f"Bearer {key}"


def test_detect_text_offline_by_default(tmp_path, monkeypatch):
    with mock_verifier() as mock:
        cfg = write_config(tmp_path / "verifiers.toml", mock.url)
        monkeypatch.setenv("WMD_TEST_KEY", "k")
        out = detect_text("plain text", config_path=str(cfg))
    assert [f["verdict"] for f in out["findings"]] == ["not_run"]
    assert mock.requests == []


def test_detect_text_not_configured_when_env_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("WMD_TEST_KEY", raising=False)
    with mock_verifier() as mock:
        cfg = write_config(tmp_path / "verifiers.toml", mock.url)
        out = detect_text("plain text", remote=True, config_path=str(cfg))
    f = next(f for f in out["findings"] if f["provider"] == "claude")
    assert f["verdict"] == "not_configured"
    assert f["evidence"]["missing_env"] == "WMD_TEST_KEY"
    assert mock.requests == []


def test_certs_lists_signer_without_der(signed):
    p, _ = signed
    rows = certs(str(p))
    assert rows
    assert any(r["is_active_signer"] for r in rows)
    assert all("der" not in r and "pem" not in r for r in rows)
    with_pem = certs(str(p), include_pem=True)
    assert all("BEGIN CERTIFICATE" in r["pem"] for r in with_pem)


def test_certs_unreadable_raises_tool_error(tmp_path):
    with pytest.raises(ValueError, match="cannot read file"):
        certs(str(tmp_path / "no-such.jpg"))


def test_certs_empty_for_unsigned_kinds(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("just text")
    assert certs(str(p)) == []


def test_capabilities_table():
    rows = capabilities()
    assert len(rows) == 18
    assert {r["provider"] for r in rows} == {"claude", "gemini", "gpt", "zai"}


# --- SDK client against the real stdio entrypoint -------------------------------


def _pick(obj, *names, default=None):
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def _result_dict(result) -> dict:
    data = _pick(result, "structured_content", "structuredContent")
    if isinstance(data, dict):
        return data
    text = "".join(c.text for c in result.content if _pick(c, "type") == "text")
    return json.loads(text)


def test_stdio_roundtrip(signed, tmp_path):
    p, pki = signed
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "WMD_CONFIG": str(tmp_path / "no-such-config.toml"),
    }

    async def run():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=str(REPO / ".venv/bin/wmd-mcp"), args=[], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool(
                    "detect_file",
                    {"path": str(p), "anchors_pem": [pki.root_pem.decode()]},
                )
        return init, tools, result

    init, tools, result = asyncio.run(run())
    assert _pick(init, "server_info", "serverInfo").name == SERVER_NAME
    assert sorted(t.name for t in tools.tools) == ["capabilities", "certs", "detect_file", "detect_text"]
    assert not _pick(result, "isError", "is_error", default=False)
    report = _result_dict(result)
    assert any(f["verdict"] == "confirmed" and f["provider"] == "claude" for f in report["findings"])
