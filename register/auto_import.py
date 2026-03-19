#!/usr/bin/env python3
"""Auto-import registered accounts to the admin panel.

Reads accounts from output/*Outlook.zip or output/.staging_outlook/*.json
and POSTs them to the admin bulk import endpoint.

Usage:
    python -m register.auto_import

Environment variables:
    OUTLOOK2API_URL  - Admin panel URL (e.g. https://ohmyapi-outlook2api.hf.space)
    ADMIN_PASSWORD   - Admin panel password
"""
import glob
import json
import os
import sys
import zipfile

import requests


def collect_accounts() -> list[str]:
    """Collect email:password lines from zip files and staging dir."""
    accounts = []
    seen = set()

    # From zip files
    for zpath in sorted(glob.glob("output/*Outlook.zip")):
        try:
            with zipfile.ZipFile(zpath) as zf:
                for name in zf.namelist():
                    if name.endswith(".txt"):
                        content = zf.read(name).decode("utf-8", errors="replace")
                        for line in content.strip().splitlines():
                            line = line.strip()
                            if ":" in line and line not in seen:
                                seen.add(line)
                                accounts.append(line)
        except Exception as e:
            print(f"[Import] Error reading {zpath}: {e}")

    # From staging dir
    for fpath in sorted(glob.glob("output/.staging_outlook/outlook_*.json")):
        try:
            with open(fpath) as f:
                d = json.load(f)
            email = d.get("email", "").strip()
            password = d.get("password", "").strip()
            if email and password:
                line = f"{email}:{password}"
                if line not in seen:
                    seen.add(line)
                    accounts.append(line)
        except Exception:
            pass

    return accounts


def main():
    url = os.environ.get("OUTLOOK2API_URL", "").rstrip("/")
    password = os.environ.get("ADMIN_PASSWORD", "")

    if not url or not password:
        print("[Import] Skipping: OUTLOOK2API_URL or ADMIN_PASSWORD not set")
        return

    # Login
    try:
        r = requests.post(f"{url}/admin/api/login",
                          json={"password": password}, timeout=15)
        r.raise_for_status()
        token = r.json()["token"]
        print(f"[Import] Logged in to {url}")
    except Exception as e:
        print(f"[Import] Login failed: {e}")
        return

    # Collect accounts
    accounts = collect_accounts()
    if not accounts:
        print("[Import] No accounts to import")
        return

    print(f"[Import] Found {len(accounts)} accounts")

    # Bulk import
    try:
        r = requests.post(
            f"{url}/admin/api/accounts/bulk",
            headers={"Authorization": f"Bearer {token}"},
            json={"accounts": accounts, "source": "ci"},
            timeout=30,
        )
        r.raise_for_status()
        result = r.json()
        print(f"[Import] Result: imported={result.get('imported')}, skipped={result.get('skipped')}")
    except Exception as e:
        print(f"[Import] Bulk import failed: {e}")


if __name__ == "__main__":
    main()
