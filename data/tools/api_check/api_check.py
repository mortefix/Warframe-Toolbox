#!/usr/bin/env python3
"""
api_check.py - verifies that the warframe.market API surface the tools depend
on is up and still shaped the way we expect. Read-only: it never writes.

Runs only inside WF Market Helper: all traffic goes through the host's
gateway, which also exercises the gateway path itself - if these checks pass,
the exact pipeline every other tool uses is proven working.

Checks, in order:
  1. v2 items index          (the catalogue exists and parses)
  2. v2 order book           (public orders for a known item, fields we need)
  3. v1 signin surface       (endpoint exists; no credentials are sent)
  4. authenticated account   (v2 /me - the session the gateway injects works)
  5. authenticated orders    (v2 your own sell orders - only if linked)

Exit code 0 = everything the tools rely on responded correctly.
"""

from __future__ import annotations

import json
import os
import sys

import requests

# A safe, permanently-tradeable item to probe the order book with.
PROBE_SLUG = "primed_continuity"

PASS, FAIL, SKIP = "PASS", "FAIL", "skip"
results: list[tuple[str, str, str]] = []


def require_host() -> tuple[str, str]:
    gateway = os.environ.get("WFM_GATEWAY")
    token = os.environ.get("WFM_GATEWAY_TOKEN")
    if not gateway or not token:
        print("ERROR: this tool must be launched from WF Market Helper.\n"
              "All API traffic runs through the host's gateway - start "
              "'Warframe Toolbox.pyw' and open the tool from there.",
              file=sys.stderr)
        raise SystemExit(2)
    return gateway, token


def check(name: str, status: str, detail: str = "") -> None:
    mark = {"PASS": "OK ", "FAIL": "ERR", "skip": "-- "}[status]
    print(f"[{mark}] {name:<38} {detail}")
    results.append((name, status, detail))


def main() -> int:
    base, token = require_host()
    s = requests.Session()
    s.headers.update({"X-Gateway-Token": token, "Accept": "application/json"})
    platform = os.environ.get("WFM_PLATFORM", "pc")
    linked = os.environ.get("WFM_INGAME_NAME")

    print(f"warframe.market API check via host gateway {base} "
          f"(platform={platform})\n")

    def get(path: str) -> requests.Response:
        return s.get(f"{base}{path}", timeout=35)

    # 1. v2 items index ----------------------------------------------------
    try:
        r = get("/v2/items")
        items = r.json().get("data", []) if r.ok else []
        if r.ok and items:
            check("v2 items index", PASS, f"{len(items)} items")
        else:
            check("v2 items index", FAIL, f"HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        check("v2 items index", FAIL, str(exc)[:80])

    # 2. v2 order book -----------------------------------------------------
    v2_ok = False
    try:
        r = get(f"/v2/orders/item/{PROBE_SLUG}")
        if r.ok:
            orders = r.json().get("data", [])
            sample = orders[0] if orders else {}
            have = {"type", "platinum"}.issubset(sample.keys()) if sample else False
            v2_ok = bool(orders) and have
            check("v2 order book", PASS if v2_ok else FAIL,
                  f"{len(orders)} orders for {PROBE_SLUG}"
                  + ("" if have else " - MISSING expected fields"))
        else:
            check("v2 order book", FAIL, f"HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        check("v2 order book", FAIL, str(exc)[:80])

    # 3. v1 signin surface ---------------------------------------------------
    # POST with no credentials: any 4xx means the endpoint exists and is
    # parsing requests. A 404 would mean the auth flow moved.
    try:
        r = s.post(f"{base}/v1/auth/signin", data=json.dumps({}), timeout=35)
        if r.status_code == 404:
            check("v1 signin endpoint", FAIL, "404 - auth flow has moved!")
        elif 400 <= r.status_code < 500:
            check("v1 signin endpoint", PASS,
                  f"present (HTTP {r.status_code} for empty creds, as expected)")
        else:
            check("v1 signin endpoint", FAIL, f"unexpected HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        check("v1 signin endpoint", FAIL, str(exc)[:80])

    # 4. authenticated account (v2 /me) -------------------------------------
    account_id = None
    if linked:
        try:
            r = get("/v2/me")
            if r.ok:
                me = r.json().get("data", {})
                account_id = me.get("id")
                check("authenticated account", PASS,
                      f"{me.get('ingameName', linked)} (id {account_id})")
            else:
                check("authenticated account", FAIL,
                      f"HTTP {r.status_code} - session invalid/expired? "
                      "Re-link in the host.")
        except Exception as exc:  # noqa: BLE001
            check("authenticated account", FAIL, str(exc)[:80])
    else:
        check("authenticated account", SKIP, "no account linked in the host")

    # 5. authenticated orders (v2) ------------------------------------------
    if account_id:
        try:
            r = get(f"/v2/orders/user/{account_id}")
            if r.ok:
                orders = r.json().get("data", [])
                sells = [o for o in orders if o.get("type") == "sell"]
                check("authenticated orders", PASS,
                      f"{len(sells)} live sell orders")
            else:
                check("authenticated orders", FAIL, f"HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            check("authenticated orders", FAIL, str(exc)[:80])
    elif linked:
        check("authenticated orders", SKIP, "could not resolve account id")
    else:
        check("authenticated orders", SKIP, "no account linked in the host")

    # ------------------------------------------------------------------ tally
    fails = [n for n, st, _ in results if st == FAIL]
    print()
    if fails:
        print(f"RESULT: {len(fails)} check(s) FAILED: {', '.join(fails)}")
        return 1
    print("RESULT: all checks passed - the API surface the tools rely on is up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
