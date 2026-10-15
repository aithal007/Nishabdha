"""Run fixed authorization scenarios in pytest's separate temporary database.

All voice results are SIMULATED; these are gateway tests, not detector benchmarks.
There is deliberately no production HTTP fault-injection endpoint.
"""

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path

SCENARIOS = {
    "fresh_request_timeout": "tests/test_evidence_security.py::test_current_check_timeout_clears_old_request_and_historic_trust",
    "typed_request_after_voice": "tests/test_evidence_security.py::test_typed_request_cannot_reuse_previous_voice",
    "genuine_then_clone": "tests/test_flows.py::test_mid_call_swap_detected",
    "detector_false_negative_without_approval": "tests/test_decisions.py::test_detector_false_negative_cannot_replace_approval",
    "approved_transaction_tampering": "tests/test_decisions.py::test_approved_amount_or_recipient_tamper_has_signed_refusal",
    "spoken_policy_bypass": "tests/test_flows.py::test_prompt_injection_cannot_bypass",
    "authorized_transfer_once": "tests/test_decisions.py::test_retry_returns_same_durable_success_decision",
    "delegate_scope_and_replay": "tests/test_decisions.py::test_delegate_denial_ticket_and_replay_have_distinct_receipts",
    "revoked_or_invalid_delegate": "tests/test_agents.py::test_reject_invalid_authority",
}

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("RENDER")}
    env.update(
        APP_ENV="test", TEST_VOICE="mock", VOICE_PRIMARY="mock", VOICE_FALLBACK="none"
    )
    print(
        "SIMULATED AUTHORIZATION SCENARIOS — not a DetectifAI accuracy evaluation",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="nishabdha_attack_results_") as directory:
        report = Path(directory) / "results.xml"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *SCENARIOS.values(),
                f"--junitxml={report}",
            ],
            cwd=root,
            env=env,
            check=False,
        )
        cases = ET.parse(report).findall(".//testcase") if report.exists() else []
        summary = {
            "simulation": True,
            "model_benchmark": False,
            "scenario_groups": SCENARIOS,
            "passed": sum(
                not any(c.find(k) is not None for k in ("failure", "error", "skipped"))
                for c in cases
            ),
            "failed": sum(
                any(c.find(k) is not None for k in ("failure", "error")) for c in cases
            ),
            "skipped": sum(c.find("skipped") is not None for c in cases),
        }
        results = []
        for scenario, target in SCENARIOS.items():
            selected = [
                c
                for c in cases
                if c.get("name", "").split("[")[0] == target.rsplit("::", 1)[1]
            ]
            results.append(
                {
                    "scenario": scenario,
                    "passed": sum(
                        not any(
                            c.find(k) is not None
                            for k in ("failure", "error", "skipped")
                        )
                        for c in selected
                    ),
                    "failed": sum(
                        any(c.find(k) is not None for k in ("failure", "error"))
                        for c in selected
                    ),
                    "skipped": sum(c.find("skipped") is not None for c in selected),
                }
            )
        summary["results"] = results
        output = root / "data" / "adversarial-results.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        rows = "".join(
            f"<tr><td>{escape(r['scenario'].replace('_', ' '))}</td><td>{r['passed']}</td><td>{r['failed']}</td><td>{r['skipped']}</td></tr>"
            for r in results
        )
        output.with_suffix(".html").write_text(
            "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Nishabdha authorization scenarios</title><style>body{font:16px/1.6 system-ui;background:#f0f6f3;color:#14362f;max-width:900px;margin:40px auto;padding:24px}"
            "table{width:100%;border-collapse:collapse;background:white}th,td{padding:14px;text-align:left;border-bottom:1px solid #cbdcd2}"
            ".notice{padding:20px;background:#fff1d0;border-radius:12px}h1{line-height:1.2}</style>"
            "<h1>A copied voice cannot copy your permissions.</h1><p class='notice'><strong>SIMULATED AUTHORIZATION TESTS</strong><br>"
            "Voice outputs and transcripts are test fixtures. Passkey assertions and request/receipt signatures use real cryptography. "
            "These results do not measure DetectifAI accuracy or a live spoken attack.</p>"
            f"<p>{summary['passed']} passed · {summary['failed']} failed · {summary['skipped']} skipped.</p>"
            "<table><caption>Isolated gateway scenarios</caption><thead><tr><th>Scenario</th><th>Passed</th><th>Failed</th><th>Skipped</th></tr></thead><tbody>"
            + rows
            + "</tbody></table><p>Each run uses a new temporary database. No production bypass or fault-injection endpoint is exposed.</p></html>",
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2))
        sys.exit(result.returncode)
