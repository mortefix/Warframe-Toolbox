"""Ad and tracker blocking policy - the rules, with no engine attached.

This is the whole of what the app blocks and hides, and it survived the move
from Edge WebView2 to QtWebEngine untouched, because none of it is about
either one. A host-suffix blocklist, a cosmetic selector list, a heuristic
that walks up from every iframe, and a per-site CSS tweak table are facts
about the open web, not about a widget toolkit.

Two engines consume it:

  * WebView2 answered a matching request with a local 403 through
    `WebResourceRequested` (the retired Tk host);
  * QtWebEngine calls `info.block(True)` from a `QWebEngineUrlRequestInterceptor`
    (the Qt app, `ui/web.py`).

Same host-suffix semantics either way - verified 1:1 against live overframe.gg
during the Phase 1.5 spike.

`data/adblock-hosts.txt` (one host per line, # comments) extends the list
without touching code.
"""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent

# -- ad blocker ---------------------------------------------------------------
# Network-level blocking: every request in every embedded browser passes a
# WebView2 WebResourceRequested handler; anything whose host matches this
# list is answered with a local 403 instead of hitting the network (the
# same mechanism browser ad blockers use). Chrome/Firefox extensions can't
# be loaded - pywebview creates the WebView2 environment without extension
# support - so the list lives here. `data/adblock-hosts.txt` (one host per
# line, # comments) extends it without touching code.
ADBLOCK_HOSTS = (
    # ad exchanges / SSPs / ad servers
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "adservice.google.com", "googletagservices.com", "adtrafficquality.google",
    "amazon-adsystem.com", "adnxs.com", "adsrvr.org", "criteo.com",
    "criteo.net", "rubiconproject.com", "pubmatic.com", "openx.net",
    "casalemedia.com", "indexexchange.com", "33across.com", "smartadserver.com",
    "sharethrough.com", "teads.tv", "yieldmo.com", "triplelift.com",
    "gumgum.com", "media.net", "sonobi.com", "springserve.com",
    "unrulymedia.com", "spotxchange.com", "undertone.com", "adform.net",
    "bidswitch.net", "yieldlab.net", "improvedigital.com", "adkernel.com",
    "onetag-sys.com", "seedtag.com", "minutemedia.com", "amplitude.com",
    # video / site monetizers. overframe.gg runs AdThrive/Raptive (scraped
    # from the live DOM 2026-07: ads.adthrive.com serves, kargo renders,
    # optable/liadm/rkdms do identity) - blocking the ad SERVER is what
    # actually stops the banners; the exchanges above are just its bidders.
    "adthrive.com", "raptive.com", "raptivecdn.com", "kargo.com",
    "optable.co", "liadm.com", "rkdms.com", "privacymanager.io",
    "jwplayer.com",
    "playwire.com", "bolt-cdn.com", "imasdk.googleapis.com",
    "btloader.com", "confiant-integrations.net",
    # trackers / analytics / attribution
    "google-analytics.com", "googletagmanager.com", "scorecardresearch.com",
    "quantserve.com", "quantcount.com", "hotjar.com", "mouseflow.com",
    "fullstory.com", "connect.facebook.net", "branch.io", "chartbeat.com",
    "permutive.com", "id5-sync.com", "liveramp.com", "rlcdn.com",
    "agkn.com", "eyeota.net", "tapad.com", "bluekai.com", "demdex.net",
    "everesttech.net", "crwdcntrl.net", "adsafeprotected.com",
    "doubleverify.com", "moatads.com", "sentry.io",
    "cookielaw.org", "onetrust.com",
)
ADBLOCK_EXTRA_FILE = DATA_DIR / "adblock-hosts.txt"

# Cosmetic filter, injected at document start into every page (and every
# navigation): REMOVES ad containers instead of leaving blocked-but-empty
# boxes behind (removal fails -> forced to 0x0). Three prongs:
#   1. a static selector list - AdThrive/Raptive + Kargo (overframe.gg,
#      scraped from its live DOM), Google GPT/AdSense, Playwire, generic
#      ad-slot names;
#   2. a heuristic that walks up from EVERY iframe: ad-network src or an
#      ad-named ancestor -> the topmost ad-named ancestor is removed, so
#      new/renamed ad units die without a selector update (content embeds
#      like the wiki's YouTube players have neither and are untouched);
#   3. sweeps run from a MutationObserver AND a 2s interval - timers keep
#      firing in hidden windows, where requestAnimationFrame never does
#      (the browsers load while parked off-screen).
ADBLOCK_CSS_SELECTORS = ", ".join((
    "ins.adsbygoogle",
    '[id^="div-gpt-ad"]', '[id^="google_ads_iframe"]',
    'iframe[title="3rd party ad content"]',
    'iframe[src*="doubleclick"]', 'iframe[src*="googlesyndication"]',
    ".adthrive-ad", '[id^="AdThrive_"]', '[class*="adthrive-sticky"]',
    ".adthrive-sticky-outstream", ".google-ad-manager-fallback-container",
    '[class*="kargo-ad"]', ".rap-of-sticky-sidebar",
    '[id^="pw-oop"]', '[id^="pw-slot"]', '[id^="pw-report"]',
    "div[data-pw-desk]", "div[data-pw-mobi]", ".pw-tag", ".pw-in-article",
    ".adsbox", ".ad-slot", ".adSlot", ".ad-banner", ".ad-container",
    ".ad-wrapper", ".video-ads", '[class*="AdContainer"]',
))
ADBLOCK_JS = """
(function () {
  var SEL = '%s';
  var HOSTRX = /(adthrive|raptive|kargo|doubleclick|googlesyndication|adsystem|adnxs|pubmatic|openx|rubicon|criteo|casalemedia|adsrvr|teads|sharethrough|gumgum|smartadserver|taboola|outbrain|playwire|jwplayer|adform|bidswitch)/i;
  var TOKRX = /(^|[-_ ])(ad|ads|advert|adthrive|adsense|adslot|sponsored?|gpt|dfp|kargo|raptive|outstream|takeover)([-_ ]|$)/i;
  function isAdName(el) {
    var s = (el.id || '') + ' ' +
            (typeof el.className === 'string' ? el.className : '');
    return TOKRX.test(s);
  }
  function zap(el) {
    try { el.remove(); return; } catch (e) {}
    try {
      el.style.setProperty('display', 'none', 'important');
      el.style.setProperty('width', '0px', 'important');
      el.style.setProperty('height', '0px', 'important');
      el.style.setProperty('min-width', '0px', 'important');
      el.style.setProperty('min-height', '0px', 'important');
      el.style.setProperty('overflow', 'hidden', 'important');
    } catch (e) {}
  }
  var pending = false;
  function sweep() {
    pending = false;
    try {
      document.querySelectorAll(SEL).forEach(zap);
      document.querySelectorAll('iframe').forEach(function (f) {
        var top = HOSTRX.test(f.src || '') ? f : null;
        var el = f.parentElement, n = 10;
        while (el && el !== document.body && n-- > 0) {
          if (isAdName(el)) top = el;
          el = el.parentElement;
        }
        if (top) zap(top);
      });
    } catch (e) {}
  }
  function schedule() {
    if (!pending) { pending = true; setTimeout(sweep, 200); }
  }
  function init() {
    var style = document.createElement('style');
    style.textContent = SEL + ' { display: none !important; }';
    (document.head || document.documentElement).appendChild(style);
    new MutationObserver(schedule)
      .observe(document.documentElement, { childList: true, subtree: true });
    setInterval(sweep, 2000);
    sweep();
  }
  if (document.documentElement) { init(); }
  else { document.addEventListener('DOMContentLoaded', init); }
})();
""" % ADBLOCK_CSS_SELECTORS


def load_blocklist() -> tuple[str, ...]:
    hosts = list(ADBLOCK_HOSTS)
    try:
        if ADBLOCK_EXTRA_FILE.exists():
            for line in ADBLOCK_EXTRA_FILE.read_text(
                    encoding="utf-8").splitlines():
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    hosts.append(line)
    except OSError:
        pass
    return tuple(hosts)


# Per-site cosmetic tweaks (CSS injected at document start, same pipeline
# as the ad filter). Keyed by the web-app key. Selectors lean on stable
# attributes (hrefs) - the sites' class names are build-hashed.
SITE_TWEAKS = {
    # overframe.gg: drop the Download App button + Discord/Twitter links from
    # the site header, then centre the home page.
    #
    # Centring needs BOTH rules, and the sidebar one is the part that was
    # missing. Measured in the live DOM: `homeContainer` is already
    # `display:flex; justify-content:center`, but it has two children -
    # the content column at 1057px and `homeSidebarRight` at 300px, which
    # together fill the 1357px row exactly. Blocking the ads emptied that
    # sidebar (innerHTML length 0) without collapsing its BOX, so flex had
    # no free space left to centre with and the content stayed hard left.
    # Removing the empty box is what gives `justify-content` something to do.
    "web_builds": """
header a[href*="app.overframe.gg"],
header a[href*="/discord"],
header a[href*="twitter.com"],
header a[href*="x.com"] { display: none !important; }
[class*="homeSidebar"] { display: none !important; }
[class*="homeContainer"] { justify-content: center !important; }
[class*="itemBundle__"] { justify-content: center !important; }
[class*="itemBundleName"] { text-align: center !important; }
""",
}


def tweak_js(css: str) -> str:
    """Per-site CSS that STAYS applied.

    The previous version appended a <style> once and hoped. It runs at
    document creation, when `document.head` does not exist yet, so the style
    landed on `documentElement` - and the HTML parser then relocates or drops
    a stray <style> while it builds <head>. The result was the symptom that
    looked like a race: overframe.gg came up uncentred on a cold load and
    correct on a revisit, because the timing differed just enough for the
    element to survive.

    The ad blocker never showed this because it also re-sweeps from a
    MutationObserver and an interval - it self-heals. This does the same
    thing: keep a handle on the element, re-attach it whenever it is not in
    the document, and prefer <head> once there is one. A single-page app that
    swaps its own head cannot lose the tweak either.
    """
    import json
    return """
(function () {
  var node = null;
  function attach() {
    if (!node) {
      node = document.createElement('style');
      node.setAttribute('data-wftoolbox', 'site-tweak');
      node.textContent = %s;
    }
    var host = document.head || document.documentElement;
    if (host && node.parentNode !== host) { host.appendChild(node); }
  }
  attach();
  document.addEventListener('DOMContentLoaded', attach);
  // re-attach if the page replaces its own head, and once more after the
  // first paint - a framework that hydrates can rebuild the document
  new MutationObserver(attach).observe(document.documentElement,
                                       { childList: true, subtree: false });
  setInterval(attach, 1000);
})();
""" % json.dumps(css)


def host_blocked(host: str, blocklist: tuple[str, ...]) -> bool:
    """Suffix match, the way a hosts-file blocker works: an entry blocks that
    host and every subdomain of it, and nothing else.

    The dot in `"." + entry` is load-bearing. Without it "ads.com" would also
    match "notads.com", and a blocklist that silently over-blocks is far worse
    than one that misses - it breaks sites with no visible reason why.
    """
    for entry in blocklist:
        if host == entry or host.endswith("." + entry):
            return True
    return False
