"""In-memory text pipeline: remote verifiers, word count and coverage."""
from __future__ import annotations

from pathlib import Path

from watermark_detector.capabilities import coverage_for
from watermark_detector.model import Finding, Report
from watermark_detector.report import report_to_dict
from watermark_detector.text_verifiers import default_config_path, load_configs, run_verifier
from watermark_detector.textio import word_count


def detect_text(text: str, remote: bool = False, config_path: str | None = None) -> dict:
    """Check a text string for AI watermarks with the configured remote verifiers.

    Plain text carries no signal that can be checked locally, so without
    remote=true every configured verifier is reported as not_run and no network
    call is made. Verifier keys are read from the environment variables named in
    the config file and are never included in the result. Absence of a signal
    does not prove human authorship.
    """
    configs = {}
    errors: list[str] = []
    try:
        configs = load_configs(Path(config_path) if config_path else default_config_path())
    except ValueError as e:
        errors.append(f"verifier config error: {e}")
    wc = word_count(text)
    findings: list[Finding] = []
    for name, cfg in configs.items():
        if remote:
            f = run_verifier(cfg, text)
            findings.append(Finding(f.layer, f.verdict, f.provider, f.location, {**f.evidence, "word_count": wc}))
        else:
            findings.append(
                Finding(
                    "text-watermark", "not_run", name, "text",
                    {"reason": "remote verification disabled; pass remote=true", "word_count": wc},
                )
            )
    report = Report(
        path="inline-text",
        kind="text",
        mime="text/plain",
        findings=findings,
        coverage=coverage_for("text", frozenset(configs), remote),
        errors=errors,
    )
    return report_to_dict(report)
