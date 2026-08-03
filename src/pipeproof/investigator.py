"""Evidence-grounded incident summaries with an optional LLM layer."""

from __future__ import annotations

import json
import os
from typing import Any

from pipeproof.models import DriftSignal, ValidationSummary

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is included in the installed package
    pass


def deterministic_investigation(
    summary: ValidationSummary, drift: list[DriftSignal]
) -> dict[str, Any]:
    """Build a deterministic diagnosis from validation and drift evidence."""

    failed = [check for check in summary.checks if not check.passed]
    errors = [check for check in failed if check.severity == "error"]
    ranked = sorted(
        drift,
        key=lambda item: (item.severity != "error", -item.score),
    )

    evidence = [check.message for check in errors[:3]] + [item.message for item in ranked[:3]]
    if not evidence:
        headline = "The batch passed its contract and no material drift was detected."
        actions = [
            "Promote the accepted output to downstream consumers.",
            "Retain this run as a healthy comparison point for future batches.",
        ]
        risk = "Low"
    else:
        risk = "High" if errors or any(item.severity == "error" for item in drift) else "Moderate"
        headline = (
            f"The batch is {summary.status}: {summary.quarantined_rows} row(s) were quarantined, "
            f"with {len(errors)} blocking check(s) and {len(drift)} drift signal(s)."
        )
        actions = []
        if any(check.check == "required_column" for check in errors):
            actions.append("Restore or explicitly remap missing source columns before rerunning.")
        if any(check.check in {"data_type", "pattern"} for check in errors):
            actions.append(
                "Inspect quarantined examples and correct source serialization or mapping rules."
            )
        if any(check.check == "uniqueness" for check in errors):
            actions.append(
                "Confirm the source primary key and deduplicate before downstream materialization."
            )
        if drift:
            actions.append(
                "Confirm whether the highest drift signal reflects a real business "
                "change or source defect."
            )
        if not actions:
            actions.append(
                "Review the failed checks and quarantined rows before accepting the batch."
            )

    return {
        "risk": risk,
        "headline": headline,
        "evidence": evidence[:5],
        "recommended_actions": actions[:4],
        "mode": "deterministic",
        "llm_available": bool(os.getenv("ANTHROPIC_API_KEY")),
    }


def investigate(summary: ValidationSummary, drift: list[DriftSignal]) -> dict[str, Any]:
    """Return a bounded incident investigation with graceful offline behavior."""

    report = deterministic_investigation(summary, drift)
    if not os.getenv("ANTHROPIC_API_KEY"):
        return report
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            max_tokens=350,
            system=(
                "You are a data reliability incident investigator. Rewrite the supplied "
                "evidence into a concise three-paragraph operator brief. Do not invent causes, "
                "numbers, columns, or checks. Clearly distinguish evidence from hypotheses."
            ),
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "risk": report["risk"],
                            "headline": report["headline"],
                            "evidence": report["evidence"],
                            "recommended_actions": report["recommended_actions"],
                        }
                    ),
                }
            ],
        )
        narrative = "\n".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        if narrative:
            report["agent_narrative"] = narrative
            report["mode"] = "claude-assisted"
    except Exception:
        report["agent_narrative"] = (
            "Claude enrichment was unavailable; deterministic evidence is shown."
        )
    return report
