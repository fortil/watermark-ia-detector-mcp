"""MCP server (stdio) exposing watermark_detector as tools. Detection only."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from watermark_detector.c2pa_reader import build_context, read_c2pa
from watermark_detector.capabilities import CAPABILITIES
from watermark_detector.certs import extract_certs
from watermark_detector.detect import MAX_INPUT_BYTES, DetectOptions, detect_path
from watermark_detector.report import report_to_dict
from watermark_detector.sniff import sniff_bytes

from watermark_ia_detector_mcp.inline import detect_text

SERVER_NAME = "watermark-ia-detector-mcp"


def detect_file(
    path: str,
    remote: bool = False,
    config_path: str | None = None,
    anchors_pem: list[str] | None = None,
) -> dict:
    """Detect AI provenance signals in one file.

    Checks C2PA Content Credentials, XMP, GB 45438 AIGC labels, embedded media
    and, for text, PDF and DOCX, the remote text verifiers. Use an absolute
    path. Remote verifiers run only when remote is true. anchors_pem holds PEM
    certificates to pin as trust anchors, obtained from the certs tool.
    Absence of a signal does not prove human authorship: screenshots,
    re-saving and format conversion remove marks.
    """
    opts = DetectOptions(
        anchors_pem=tuple(anchors_pem or ()),
        remote=remote,
        config_path=Path(config_path) if config_path else None,
    )
    return report_to_dict(detect_path(Path(path), opts))


def certs(path: str, include_pem: bool = False) -> list[dict]:
    """List the certificates embedded in a C2PA-signed file.

    Use an absolute path. The row with is_active_signer true holds the signer
    of the active manifest; pin its sha256 or pem in detect_file to upgrade
    claimed verdicts to confirmed. DER bytes are never returned. Files are
    limited to 512 MiB.
    """
    p = Path(path)
    try:
        if p.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("file too large")
        data = p.read_bytes()
    except OSError as e:
        raise ValueError(f"cannot read file: {type(e).__name__}") from e
    kind, mime = sniff_bytes(data)
    if kind not in ("image", "svg", "pdf", "ooxml") or mime is None:
        return []
    active = None
    for m in read_c2pa(data, mime, build_context(())).manifests:
        if m.is_active:
            active = m.signer_serial
    out = []
    for c in extract_certs(data, mime, active):
        row = {
            "index": c.index,
            "sha256": c.sha256,
            "serial": c.serial,
            "is_active_signer": c.is_active_signer,
        }
        if include_pem:
            row["pem"] = c.pem
        out.append(row)
    return out


def capabilities() -> list[dict]:
    """List what can and cannot be checked per provider and modality.

    One row per signal: provider, modality, whether it can be checked locally,
    how to check it by hand, notes and sources. Use it before claiming a file
    is clean.
    """
    return [dataclasses.asdict(c) for c in CAPABILITIES]


def _build_server() -> MCPServer:
    server = MCPServer(SERVER_NAME)
    for tool in (detect_file, detect_text, certs, capabilities):
        server.tool()(tool)
    return server


def main() -> None:
    _build_server().run(transport="stdio")
