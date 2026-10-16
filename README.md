# watermark-ia-detector-mcp

<p align="center">
  <a href="https://github.com/fortil/watermark-ia-detector-mcp"><img src="https://img.shields.io/badge/github-fortil%2Fwatermark--ia--detector--mcp-181717?logo=github" alt="github.com/fortil/watermark-ia-detector-mcp"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/MCP-server-5F45AF" alt="MCP server">
  <img src="https://img.shields.io/badge/detects-C2PA%20%7C%20IPTC%20XMP%20%7C%20GB%2045438-4B3B99" alt="detects C2PA, IPTC XMP and GB 45438">
  <img src="https://img.shields.io/badge/engine-watermark--detector-2B2B2B" alt="watermark-detector engine">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license MIT">
</p>

An MCP server (stdio transport) that exposes the `watermark-detector` package as tools, for clients such as Claude Desktop, ZCode or Cursor. Detection only: no tool here removes, rewrites or perturbs a watermark.

The engine lives in the sibling repo `../watermark-detector`. This repo is the MCP wrapper and does not modify the engine.

## Install

```
make install
```

This creates `.venv` with Python 3.12 through uv and installs the package with its dev tools. `pyproject.toml` points uv at the sibling repo through `[tool.uv.sources]`, so `../watermark-detector` must exist next to this repo. Nothing is published to PyPI; installation always references that local path.

Without uv:

```
python -m venv .venv
.venv/bin/pip install -e ../watermark-detector
.venv/bin/pip install -e '.[dev]'
```

## Client configuration

The entrypoint is `.venv/bin/wmd-mcp` (also `python -m watermark_ia_detector_mcp`). Use an absolute path in the client config.

Generic MCP client:

```json
{
  "mcpServers": {
    "watermark-detector": {
      "command": "/ABSOLUTE/PATH/TO/watermark-ia-detector-mcp/.venv/bin/wmd-mcp",
      "env": {
        "WMD_CONFIG": "/ABSOLUTE/PATH/TO/verifiers.toml",
        "CLAUDE_DETECTOR_KEY": "..."
      }
    }
  }
}
```

Claude Desktop uses the same `mcpServers` block, in `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS.

The `env` keys are optional. `WMD_CONFIG` points at the verifier TOML described below. The other variables are the API keys named by that TOML; the server reads them from its process environment and never prints, logs or returns them.

## Tools

| Tool | What it does |
|---|---|
| `detect_file` | Detects provenance signals in one file: C2PA, XMP, GB 45438 AIGC labels, embedded media, remote text verifiers. Takes an absolute path. |
| `detect_text` | Checks a text string with the configured remote verifiers. Without `remote=true` it returns `not_run` findings and makes no network call. |
| `certs` | Lists certificates embedded in a signed file, marking the active signer. Use its sha256 or pem to pin a trust anchor. |
| `capabilities` | Lists what can and cannot be checked per provider and modality, with sources. |

`detect_file` and `detect_text` accept `remote` (default false) and `config_path`; `detect_file` also accepts `anchors_pem`. Report shape, verdicts and coverage rows come from `watermark-detector`; see that repo's README for the full verdict list.

## Remote text verifiers

Remote checks need a TOML file naming each verifier's endpoint, the environment variable holding its key and where the score sits in the response:

```toml
[verifiers.claude]
endpoint = "https://PROVIDER-HOST/PATH"
api_key_env = "CLAUDE_DETECTOR_KEY"
score_path = "result.likelihood"
# optional: label_path, auth_header, auth_scheme, text_field, extra_body, timeout_s, max_chars
```

Names can be `claude`, `gemini` or `gpt`. The file is found through `config_path`, then `WMD_CONFIG`, then `~/.config/watermark-detector/verifiers.toml`. Endpoints must use https; http is only allowed for localhost.

## Security notes

- No network traffic unless a call passes `remote=true`, and then only to the endpoints in your TOML.
- API keys are read from the environment at call time. They are never printed, logged or returned.
- stdio servers run locally with your user's permissions: a client can ask this server to read any file you can read. Files are capped at 512 MiB. Only point clients you trust at it.
- Absence of a signal does not prove human authorship. Screenshots, re-saving and format conversion remove C2PA and metadata labels, and text watermarks can only be checked with the provider's detector.

## Tests

```
make test
```

The suite is offline. HTTP goes only to a mock on 127.0.0.1, and the signed fixtures are generated at test time with a throwaway PKI; nothing signed is committed.

## License

MIT. See [LICENSE](LICENSE).

