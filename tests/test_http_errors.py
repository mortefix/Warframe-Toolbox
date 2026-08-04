"""What an HTTP failure MEANS - core.market.http_error_message.

Written the day warframe.market returned 521 for an hour. The app reported:

    GET /v2/me failed (521): <html>     <head>         <meta charset="UTF-8">

which is a doctype and the start of a stylesheet. Nothing in that tells you
whether the site is down, your login expired, or this app is broken - and
those three have completely different responses.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))

from core.market import http_error_message as msg

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


CF_PAGE = ('<html>\n    <head>\n        <meta charset="UTF-8">\n'
           '        <style>.fallback__container{align-items:center;'
           'display:flex}</style>')

print("Cloudflare origin failures name the site, not the request")
# 52x means Cloudflare could not reach warframe.market at all. Retrying with
# different parameters cannot help, so the message must not invite that.
for code, phrase in ((521, "is down"), (522, "timed out"),
                     (523, "is unreachable"), (524, "took too long")):
    text = msg(code, CF_PAGE)
    check(f"{code} says what happened", phrase in text)
    check(f"{code} names warframe.market", "warframe.market" in text)
    check(f"{code} carries no HTML", "<" not in text)
    check(f"{code} says it is not ours to fix", "their end" in text)

print("\nthe status code survives, for anyone reporting a bug")
check("521 keeps its number", "521" in msg(521, CF_PAGE))

print("\nrate limiting is a different instruction")
text = msg(429, "")
check("429 says we are being throttled", "rate-limiting" in text)
check("and to wait", "minute" in text)

print("\nordinary server errors")
for code in (500, 502, 503, 504):
    check(f"{code} suggests retrying", "Try again" in msg(code, CF_PAGE))

print("\nany HTML body is a web page, whatever the code")
# A proxy or captive portal can return 200-shaped HTML on an odd code; the
# giveaway is the body, not the number
check("an unlisted code with HTML is still called out",
      msg(418, "<!doctype html><html>…"),
      "warframe.market returned a web page instead of data (HTTP 418).")

print("\na real API error message is passed through intact")
check("JSON-ish bodies survive",
      msg(400, '{"error": "quantity must be positive"}'),
      'HTTP 400: {"error": "quantity must be positive"}')
check("and long ones are trimmed, not dropped",
      len(msg(400, "x" * 500)), len("HTTP 400: ") + 200)

print("\nwhitespace-only bodies do not produce a dangling colon")
check("empty body", msg(400, "   \n  "), "HTTP 400: ")

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL HTTP ERROR CHECKS PASSED")
