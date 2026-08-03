"""Command-line interface for reproducible PipeProof workflows."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pipeproof.connectors import fetch_nyc_311
from pipeproof.contracts import contract_to_yaml, generate_contract
from pipeproof.io import load_table
from pipeproof.pipeline import run_pipeline
from pipeproof.profiler import profile_batch


def build_parser() -> argparse.ArgumentParser:
    """Build the PipeProof argument parser."""

    parser = argparse.ArgumentParser(
        prog="pipeproof",
        description="Contract-first data intake and reliability checks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile = subparsers.add_parser("profile", help="Profile a tabular file.")
    profile.add_argument("file", type=Path)

    contract = subparsers.add_parser("contract", help="Generate a YAML contract.")
    contract.add_argument("file", type=Path)
    contract.add_argument("--name", default="incoming_batch")
    contract.add_argument("--output", type=Path)

    check = subparsers.add_parser("check", help="Validate and compare a current batch.")
    check.add_argument("current", type=Path)
    check.add_argument("--baseline", type=Path)
    check.add_argument("--name", default="incoming_batch")
    check.add_argument("--output", type=Path, default=Path("data/runtime/runs"))

    demo = subparsers.add_parser("demo", help="Run the bundled 311 incident replay.")
    demo.add_argument("--output", type=Path, default=Path("data/runtime/runs"))

    fetch = subparsers.add_parser("fetch-nyc-311", help="Download a recent public 311 snapshot.")
    fetch.add_argument("--output", type=Path, default=Path("data/nyc_311_latest.csv"))
    fetch.add_argument("--days", type=int, default=7)
    fetch.add_argument("--limit", type=int, default=2000)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute a PipeProof CLI command."""

    args = build_parser().parse_args(argv)
    if args.command == "profile":
        profile = profile_batch(load_table(args.file))
        print(json.dumps(asdict(profile), indent=2, default=str))
        return 0
    if args.command == "contract":
        contract = generate_contract(profile_batch(load_table(args.file)), args.name)
        content = contract_to_yaml(contract)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content, encoding="utf-8")
            print(args.output)
        else:
            print(content, end="")
        return 0
    if args.command == "check":
        result = run_pipeline(
            args.current,
            args.baseline,
            store_root=args.output,
            dataset_name=args.name,
        )
        print(json.dumps(asdict(result), indent=2, default=str))
        return 1 if result.status == "failed" else 0
    if args.command == "demo":
        root = Path(__file__).resolve().parents[2]
        result = run_pipeline(
            root / "data/sample/nyc_311_incident.csv",
            root / "data/sample/nyc_311_baseline.csv",
            store_root=args.output,
            dataset_name="nyc_311_service_requests",
        )
        print(json.dumps(asdict(result), indent=2, default=str))
        return 0
    if args.command == "fetch-nyc-311":
        print(fetch_nyc_311(args.output, days=args.days, limit=args.limit))
        return 0
    return 2
