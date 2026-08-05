"""Behaviour tests for core.gateway.path_allowed.

This is the tool-facing security control: it decides which paths the host will
proxy WITH ITS REAL JWT ATTACHED. A bare startswith('/v1/') passes
'/v1/../secret', which requests/urllib3 and the CDN then resolve to '/secret'
with the host's Authorization still on it - a credential-leak / SSRF shape. The
function normalises (double-unquote, reject backslashes, posixpath.normpath,
restore a trailing slash) before checking BOTH the normalised and the raw path
start with an allowed prefix. Every branch below is one way that control could
be quietly weakened, so each gets a case.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import gateway

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


print("real /v1 and /v2 paths are allowed")
for p in ["/v1/items", "/v1/", "/v2/orders/item/ash_prime_set",
          "/v2/orders/item/ash_prime_set/",      # trailing slash survives normpath
          "/v1/profile?ignore=the_query"]:       # query is stripped before the check
    check(f"allow {p!r}", gateway.path_allowed(p), True)

print("\ntraversal and out-of-scope paths are rejected")
for p in ["/admin", "/v3/x", "/", "",
          "/v1/../admin",                         # plain dot-segment
          "/v1/../../etc/passwd",
          "/v2/orders/../../admin",
          "/v1/%2e%2e/admin",                     # single-encoded ..
          "/v1/%252e%252e/admin",                 # double-encoded .. (survives one unquote)
          "/v1/..%2fadmin",                       # encoded slash after ..
          "/v1/\\..\\admin",                      # backslash traversal
          "/v2/..%5cadmin"]:                      # encoded backslash
    check(f"reject {p!r}", gateway.path_allowed(p), False)

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL GATEWAY ALLOWLIST CHECKS PASSED")
