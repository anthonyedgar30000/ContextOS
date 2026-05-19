#!/usr/bin/env python3
"""Tiny JillyPickles target app used by ContextOS demos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_ORDER_ROUTE = "/pickles/order"


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def health_findings(config: dict) -> list[str]:
    findings: list[str] = []
    if config.get("app_name") != "JillyPickles":
        findings.append("app_name must be JillyPickles")
    if config.get("environment") != "production":
        findings.append("environment must be production for the storefront demo")
    if not config.get("feature_flags", {}).get("pickle_ordering_enabled"):
        findings.append("pickle ordering feature flag is disabled")
    if config.get("routes", {}).get("order") != REQUIRED_ORDER_ROUTE:
        findings.append(f"order route must be {REQUIRED_ORDER_ROUTE}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the JillyPickles demo app health check")
    parser.add_argument("--config", default=Path(__file__).with_name("config.json"), type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    findings = health_findings(config)
    print("JillyPickles storefront")
    print(f"Environment: {config.get('environment')}")
    print(f"Order route: {config.get('routes', {}).get('order')}")
    print(f"Pickle ordering enabled: {config.get('feature_flags', {}).get('pickle_ordering_enabled')}")
    print(f"Banner: {config.get('banner')}")

    if findings:
        print("BROKEN:")
        for finding in findings:
            print(f"  - {finding}")
        return 1

    print("HEALTHY: customers can order pickles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
