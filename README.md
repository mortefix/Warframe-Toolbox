# Warframe Toolbox

A desktop companion for **warframe.market** traders. Link your account once and
manage your listings, browse the live market, plan Vosfor spending, and keep the
wiki and other sites a click away — all in one window, styled after an Orokin
treasury.

Windows-first. Your warframe.market password is used for a single sign-in and
**never stored**; everything the app saves about you stays on your own PC.

## Install

Download **`Install Warframe Toolbox.exe`** and run it. It installs per-user (no
admin), sets up anything it needs, and creates the shortcuts you choose. First
launch, click **Link account** and sign in once.

The app **updates itself on launch**, so you always have the latest version — no
reinstalling.

> It's unsigned, so Windows SmartScreen may warn on first run: **More info →
> Run anyway**.

## What's inside

Pick an app from the sidebar. Nothing loads until you open it.

- **My Listings** — your warframe.market sell (WTS) and buy (WTB) orders as a
  dashboard. See when you've been undercut or outbid, and **Reprice** to match
  the best online price in one click (never below a floor you set, never
  overbidding). Mark items **Sold**, edit price/quantity/visibility, or bulk
  show/hide.
- **Market** — a read-only browser of warframe.market: search any tradeable
  item and see the live order book (sellers cheapest-first, buyers highest,
  with online/in-game status), browse **Contracts** (riven & lich auctions),
  and keep a **Watchlist** of items to track. Each row has a **✉** button that
  copies a ready-to-send in-game trade whisper.
- **Vosfor** — a planner for **Arcane Dissolution**. It ranks the nine arcane
  collections by how much value your Vosfor buys, tells you how many packs to
  spend where, and can weight the plan by how easily each arcane is farmed or
  how cheap it is to just buy on the market. It reads which arcanes you own
  from AlecaFrame (or you tick them off by hand).
- **WF Live · Wiki · Overframe** — three sites embedded right in the app (world
  state, the wiki, and Overframe), with a built-in **ad blocker** on by default.
  Item names throughout the app link straight into the Wiki tab.

## Your account & data — what's collected and why

The app talks to a few services on your behalf. Here's exactly what it uses and
where it goes:

- **warframe.market login.** Your password signs you in **once**; only the
  resulting session token, username, platform, and login email (to prefill the
  form) are cached locally in `wfm_session.json`. The token **never leaves your
  computer** — every market request is routed through a small local gateway that
  adds it, so individual tools never see your credentials. Deleting the file (or
  **Unlink**) signs you out.
- **Warframe.com profile** *(optional)* — if you connect it, the app reads your
  public profile (mastery, loadout, progression) from Digital Extremes' own
  servers using your public account ID. Read-only.
- **AlecaFrame inventory** *(optional, for Vosfor)* — the app reads your arcane
  inventory **read-only** from AlecaFrame's local cache to know what you own.
  Nothing is ever written back to AlecaFrame or to the game, and every
  game-file access the app makes is strictly read-only.

**Where it lives.** The app itself carries no personal data — everything it
generates about you sits in `%LOCALAPPDATA%\WarframeToolbox` on your machine:
your session, settings, watchlist, listing floors, cached prices, downloaded
item images, and the embedded browser's cookies. You can inspect or delete any
of it from **Settings › Data › WF Toolbox**.

## Settings worth knowing

- **Display › Window** — launch fullscreen, pick window size and monitor,
  **launch on Windows startup**, **launch the Toolbox when Warframe starts**, and
  **send to tray when minimized**.
- **Market › Messaging** — edit the trade-whisper templates the ✉ button copies.
- **Data › WebView** — toggle the ad blocker and clear the embedded browser's
  cache or cookies.
- **Data › WF Toolbox** — see every file the app has saved about you, delete
  cached item images, or **Delete ALL user data** (both wipes ask you to type
  `goodbye` to confirm).

## Uninstall

Uninstall from **Add or remove programs** (or the Start Menu entry). It closes
the app if it's running, cleans up its shortcuts, and **asks before deleting
your saved data** — keep it or wipe it, your choice.

## Run from source

You don't need this to use the app — the installer handles everything. But the
repo is public, so if you'd rather run it yourself: install **Python 3.11+**,
then

```
pip install -r requirements.txt
```

and double-click **`Warframe Toolbox.pyw`**.

## License

GPLv3, with a linking exception for the Overwolf platform. See
[`LICENSE`](LICENSE).
