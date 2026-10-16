# PLAN — watermark-ia-detector-mcp

Origen: diseñado en una sesión sobre `watermark-detector` (2026-10-15), entregado el 2026-10-16 para ejecutarse en un repo aparte. Este documento es autocontenido: ejecútalo tal cual, sin re-planear.

## Objetivo

Crear en este directorio un proyecto nuevo `watermark-ia-detector-mcp`: un servidor MCP (transporte stdio) que expone como tools la detección del paquete `watermark_detector` para clientes como Claude Desktop, ZCode o Cursor.

El motor vive en el repo hermano `../watermark-detector`. Ese repo NO se modifica en nada: se consume como librería Python y sirve de referencia de lectura.

## Reglas innegociables

1. Solo detección. Ningún tool de remove, strip, rewrite, perturb ni forja de marcas. Nunca.
2. No modificar nada dentro de `../watermark-detector`.
3. Tests offline. HTTP solo hacia `127.0.0.1`/`localhost` (mocks); nada de red real.
4. Las llaves de API de los verificadores remotos se leen de variables de entorno nombradas en el TOML del usuario y jamás se imprimen, loguean ni devuelven en un resultado.
5. `remote` (verificadores de texto por HTTP) es opt-in explícito por llamada; por defecto no hay red.
6. El server hereda el comportamiento del paquete base: no agregar ningún eco de secretos nuevo.

## El hermano: mapa de la API disponible (todo en `../watermark-detector/src/watermark_detector/`)

- `detect.py`
  - `MAX_INPUT_BYTES = 512 * 2**20` (tope pre-lectura).
  - `DetectOptions(anchors_pem: tuple[str,...] = (), remote: bool = False, config_path: Path | None = None)` (dataclass frozen).
  - `detect_path(path, opts) -> Report`. Nunca lanza por input malo: los errores van en `report.errors` (`"file too large"`, `"cannot read file: <ExcType>"`, `"unsupported file type"`).
- `model.py`
  - `Report(path, kind, mime, findings, coverage, errors)` (dataclass mutable).
  - `Finding(layer, verdict, provider, location, evidence)` (frozen; `evidence: dict[str, Any]`).
  - `Verdict` incluye: `confirmed, claimed, via_ingredient, invalid, ai_unknown_provider, present_other, unsigned_hint, remote_reference, absent, skipped, score, not_configured, not_run, error`.
  - `PROVIDERS = ("claude", "gemini", "gpt", "zai")`.
- `report.py`
  - `report_to_dict(r) -> dict` (incluye `schema`, `tool_version`, `c2pa_sdk`, `summary`), `render_text(r)`, `render_json(reports)`. `SCHEMA = "watermark-detector/report@1"`.
- `certs.py`
  - `extract_certs(data: bytes, mime: str, active_serial: int | None) -> list[CertInfo]`; `CertInfo(index, sha256, serial, der: bytes, pem: str, is_active_signer)`. Excluir `der` de cualquier salida JSON.
- `capabilities.py`
  - `CAPABILITIES: tuple[Capability, ...]` (18 filas: provider, modality, signal, local, how_to_check, notes, sources). `coverage_for(kind, configured, remote)`.
- `text_verifiers.py`
  - `default_config_path()` honra `WMD_CONFIG`, si no `~/.config/watermark-detector/verifiers.toml`.
  - `load_configs(path | None) -> dict[str, VerifierConfig]` (archivo inexistente → `{}`; `ValueError` si el TOML está mal). Endpoint https obligatorio, http solo localhost.
  - `run_verifier(cfg, text) -> Finding` (nunca lanza; la llave sale de `os.environ[cfg.api_key_env]`, si falta → verdict `not_configured` con evidence `missing_env` = nombre de la variable, nunca el valor).
  - `VerifierConfig(name, endpoint, api_key_env, score_path, ...)` con `timeout_s`, `max_chars`.
- `textio.py`: `extract_text(data, kind, mime)`, `word_count(text)`, `WORD_MIME`.
- `sniff.py`: `sniff_bytes(data) -> (kind, mime)`.
- `c2pa_reader.py`: `build_context(anchors_pem)`, `read_c2pa(data, mime, ctx)` (verify offline; `remote_manifest_fetch/ocsp_fetch` en False).
- `cli.py` del hermano: referencia del flujo `certs` (sniff → `build_context()` → `read_c2pa` para el serial del firmante activo → `extract_certs`).
- `tests/fixtures/` del hermano (`build.py`, `pki.py`, `mock_verifier.py`): patrón a replicar en versión mínima. No son importables (no empaquetados); copiar la idea, no importar.

## Estructura del repo nuevo

```
watermark-ia-detector-mcp/
├── PLAN.md              (este archivo; se mantiene en el repo)
├── pyproject.toml
├── Makefile
├── README.md
├── .gitignore
├── AGENTS.md
├── src/watermark_ia_detector_mcp/
│   ├── __init__.py      (__version__)
│   ├── __main__.py      (python -m watermark_ia_detector_mcp)
│   ├── server.py        (handlers planos + _build_server() + main() stdio)
│   └── inline.py        (pipeline de texto en memoria)
└── tests/
    ├── conftest.py      (WMD_CONFIG → archivo inexistente; autouse)
    ├── fixtures.py      (mock HTTP localhost + firmador mínimo de JPEG)
    └── test_server.py
```

Nombre: distribución `watermark-ia-detector-mcp`, módulo `watermark_ia_detector_mcp`, script `wmd-mcp`. Python `>=3.11`, `.venv` 3.12 con uv.

## pyproject.toml

- `dependencies = ["watermark-detector", "mcp>=2.3,<3"]`.
- `[tool.uv.sources] watermark-detector = { path = "../watermark-detector", editable = true }`.
- `[project.scripts] wmd-mcp = "watermark_ia_detector_mcp.server:main"`.
- `[project.optional-dependencies] dev = ["pytest>=9,<10", "pillow>=12,<13", "cryptography>=50"]` (`c2pa-python==0.38.0` llega por transitividad del hermano; para firmar fixtures de test se importa directamente).
- Build backend setuptools con `[tool.setuptools.packages.find] where = ["src"]`.
- Makefile espejo del hermano: `make install` (`uv venv --allow-existing --python 3.12 .venv` + `uv pip install --python .venv/bin/python -e '.[dev]'`), `make test` (`.venv/bin/python -m pytest -q`, con `T ?= tests`).

## server.py — 4 tools

Handlers como funciones planas (testeables sin levantar el server). `_build_server()` las registra en FastMCP (`from mcp.server.fastmcp import FastMCP`) y `main()` corre stdio.

1. `detect_file(path: str, remote: bool = False, config_path: str | None = None, anchors_pem: list[str] | None = None) -> dict`
   - Envuelve `detect_path(Path(path), DetectOptions(...))` + `report_to_dict`. Path absoluto (documentarlo en la descripción del tool). Descripciones de tools en inglés, frases cortas, con la advertencia de que ausencia de señal no prueba autoría humana.
2. `detect_text(text: str, remote: bool = False, config_path: str | None = None) -> dict`
   - Implementado en `inline.py`: compone `load_configs`, `run_verifier`/findings `not_run`, `word_count` y `coverage_for("text", ...)`, y arma `Report(path="inline-text", kind="text", mime="text/plain", ...)`. Serializa con `report_to_dict`. Sin `remote=True` devuelve findings `not_run`: no hay señales locales en texto plano.
3. `certs(path: str, include_pem: bool = False) -> list[dict]`
   - `sniff_bytes` → `build_context(())` → `read_c2pa` (serial del firmante activo; sin manifiesto → serial None) → `extract_certs`. Devuelve `index/sha256/serial/is_active_signer` (+ `pem` si `include_pem`); nunca `der`.
4. `capabilities() -> list[dict]`
   - `[dataclasses.asdict(c) for c in CAPABILITIES]`.

Semántica heredada del CLI del hermano: config por `config_path` o `default_config_path()` (`WMD_CONFIG`); las llaves las lee `run_verifier` del entorno del proceso del server (el cliente las pasa en `env` de su config MCP).

## Tests (offline)

`tests/conftest.py`: fixture autouse que apunta `WMD_CONFIG` a `tmp_path/"no-such-config.toml"` (patrón del hermano).

`tests/fixtures.py`:
- `mock_verifier` compacto: `ThreadingHTTPServer` en `127.0.0.1:0` (puerto efímero, hilo daemon) que responde JSON `{"result": {"likelihood": 0.87, "label": "likely"}}` y registra los POST; helper `write_config(path, url, ...)` que escribe el TOML con `api_key_env = "WMD_TEST_KEY"`.
- Firmador mínimo: PKI EC desechable con `cryptography` y un JPEG firmado con `c2pa-python` (referencia: `build.py`/`pki.py` del hermano). Nada firmado se commitea; todo se genera en el momento del test.

`tests/test_server.py`:
- Handlers planos: `detect_file` sobre el JPEG firmado → algún finding `confirmed` con provider; archivo ileíble → `"cannot read file"` en `errors`; `detect_text` con mock + env `WMD_TEST_KEY=<valor>`: con `remote=True` → finding `score` y `json.dumps(salida)` NO contiene el valor de la llave; con `remote=False` → `not_run`. `certs` → fila con `is_active_signer=true`, sin `der`. `capabilities()` → 18 filas.
- Integración con el SDK (es dependencia principal, sin importorskip): cliente en memoria del SDK contra `_build_server()`; verifica 4 tools en `tools/list` y un `tools/call` de `detect_file` con veredicto esperado. Si la utilidad en memoria de mcp 2.x resulta frágil, respaldo: cliente stdio del SDK contra subprocess de `wmd-mcp`.

## README.md y AGENTS.md

README (inglés, frases cortas, sin emoji, sin em dashes, como el hermano): qué es; instalación (uv con path source y alternativa `pip install -e ../watermark-detector` + `pip install -e '.[dev]'`); snippet JSON de config de cliente MCP genérico y Claude Desktop (command = `.venv/bin/wmd-mcp` con path absoluto, `env` con `WMD_CONFIG` y las variables de llaves); tabla de tools; notas de seguridad: `remote` opt-in, llaves solo de entorno y nunca impresas, stdio implica confianza local (el cliente puede pedir al server que lea cualquier archivo legible por el usuario; tope 512 MiB), ausencia de señal no prueba autoría humana.

AGENTS.md breve (inglés): layout del repo, `make install`/`make test`, regla detects-only heredada, fuente de verdad del motor en `../watermark-detector`, y el detalle del path source de uv.

`.gitignore`: `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`.

## Pasos y definición de done

1. Esqueleto + pyproject + `make install` (verifica que resuelve el path source del hermano).
2. `inline.py` + `server.py` con handlers planos.
3. `tests/` completo → `make test` en verde.
4. Smoke manual por stdio: cliente JSON-RPC contra `wmd-mcp` (initialize, tools/list, tools/call sobre la fixture firmada).
5. README + AGENTS.md + `.gitignore`.
6. `git init`, rama `main`, commit inicial. No commitear nada de `.venv/`, `__pycache__/`, `*.egg-info/` ni llaves.

Done = pasos 1-6 verificados, `make test` pasando y commit inicial creado.

## Riesgos y notas

- El path source depende de la ubicación del hermano (`../watermark-detector`): si se mueve, se ajusta una línea de pyproject.
- Deriva de API del SDK `mcp` 2.x: mitigada con handlers planos y un único punto de construcción del server en `_build_server()`.
- Sin publicación a PyPI (el hermano es local): la instalación siempre referencia el path; decirlo explícito en el README.
