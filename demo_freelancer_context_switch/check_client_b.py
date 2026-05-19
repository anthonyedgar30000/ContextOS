#!/usr/bin/env python3
"""Validate the ClientB demo config."""

from __future__ import annotations

import json
from pathlib import Path


CONFIG = Path(__file__).with_name("ClientB") / "site_config.json"


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    print("ClientB storefront check")
    print(f"Client: {config.get('client')}")
    print(f"Route: {config.get('public_route')}")
    print(f"Payments enabled: {config.get('payments_enabled')}")
    print(f"Support email: {config.get('support_email')}")
    findings = []
    if config.get('client') != 'ClientB':
        findings.append('config belongs to the wrong client')
    if config.get('public_route') != '/client-b/shop':
        findings.append('public route points at the wrong client experience')
    if config.get('payments_enabled') is not True:
        findings.append('payments are disabled for ClientB')
    if config.get('support_email') != 'help@client-b.example':
        findings.append('support email points at the wrong client')
    if findings:
        print('BROKEN:')
        for finding in findings:
            print(f'  - {finding}')
        return 1
    print('HEALTHY: ClientB storefront context is correct.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
