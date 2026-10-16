# AGENTS.md

MCP server (stdio) that exposes the `watermark-detector` package as tools.

## Layout

- `src/watermark_ia_detector_mcp/server.py`: the four tool handlers as plain functions, `_build_server()` registration and the stdio `main()`.
- `src/watermark_ia_detector_mcp/inline.py`: the in-memory text pipeline behind `detect_text`.
- `tests/`: offline suite. `fixtures.py` runs a localhost mock verifier and signs a JPEG with a throwaway PKI at test time.
- `PLAN.md`: the original design document, executed as written except for the deviations listed below.

## Working here

- `make install` creates `.venv` (Python 3.12, uv) and installs the package editable with dev extras. `make test` runs pytest.
- The engine is the sibling repo `../watermark-detector`, consumed as a library through `[tool.uv.sources]` in `pyproject.toml`. Never modify it: it is the source of truth for detection behavior, verdicts and the report schema. If the repo moves, that one pyproject line is what to fix.
- Detection only. No tool may remove, strip, rewrite or perturb a watermark.
- Tests stay offline: HTTP only to 127.0.0.1 mocks, and `tests/conftest.py` pins `WMD_CONFIG` to a nonexistent file so the user's real config is never loaded.
- API keys come from environment variables named in the user's TOML and must never be printed, logged or returned.

## Deviations from PLAN.md

- PLAN.md says `from mcp.server.fastmcp import FastMCP`. That import belongs to mcp 1.x; this repo pins `mcp>=2.3,<3`, where the class is `MCPServer` from `mcp.server.mcpserver`. `_build_server()` uses that. The rest of the plan's server design is unchanged.
- The plan's first-choice integration test (an in-memory SDK client wired to the server session by hand) hangs against mcp 2.x internals, so the suite uses the plan's stated fallback: the SDK stdio client against a `wmd-mcp` subprocess. It covers initialize, tools/list and tools/call end to end.
