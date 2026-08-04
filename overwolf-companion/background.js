/*
 * Warframe Toolbox Companion - background page.
 *
 * The whole job: subscribe to Overwolf's Game Events "inventory" feature for
 * Warframe and write the raw inventory JSON to
 *   %LOCALAPPDATA%\WarframeToolbox\inventory.json
 * which Warframe Toolbox's OverwolfCompanionProvider reads. That's the same data
 * AlecaFrame gets (Overwolf's provider is what supplies it) - we just write it
 * as plaintext for our own app instead of an encrypted cache.
 *
 * No overlay, no screen capture, no writing to any game file. The inventory
 * refreshes on login and loading screens, so travelling to a relay/dojo and back
 * forces an update - same behaviour AlecaFrame documents.
 */

const WF_GAME_ID = 8954;
const FEATURES = ["inventory", "match_info"];
// Overwolf expands %LOCALAPPDATA% in io paths; this matches the Python side's
// OverwolfCompanionProvider.PATH exactly.
const OUT_PATH = "%LOCALAPPDATA%\\WarframeToolbox\\inventory.json";

function log(msg) { console.log("[WFTB-Companion] " + msg); }

function writeInventory(invString) {
  // Write the game-events inventory string verbatim, so the toolbox parses
  // exactly what the game reported. Best-effort: a failed write is retried by the
  // next update rather than surfaced.
  // 4-arg form (filePath, content, encoding, callback) - the widely-compatible
  // one. The target folder is created by the Toolbox on first run, so no
  // create-dirs flag is needed here.
  overwolf.io.writeFileContents(
    OUT_PATH, invString, overwolf.io.enums.eEncoding.UTF8,
    function (result) {
      if (result && result.success) log("inventory written (" + invString.length + " B)");
      else log("write failed: " + JSON.stringify(result));
    });
}

function setRequiredFeatures() {
  overwolf.games.events.setRequiredFeatures(FEATURES, function (info) {
    if (!info || info.success === false) {
      log("setRequiredFeatures retry: " + JSON.stringify(info));
      setTimeout(setRequiredFeatures, 2000);
    } else {
      log("features set");
    }
  });
}

// Live updates: the inventory arrives as info.info.match_info.inventory.
overwolf.games.events.onInfoUpdates2.addListener(function (info) {
  const mi = info && info.info && info.info.match_info;
  if (mi && mi.inventory) writeInventory(mi.inventory);
});

// Pull the current snapshot once (getInfo returns the last-known inventory).
function pullOnce() {
  overwolf.games.events.getInfo(function (p) {
    const mi = p && p.success && p.res && p.res.match_info;
    if (mi && mi.inventory) writeInventory(mi.inventory);
  });
}

// Wire up when Warframe is detected, and also try immediately in case it is
// already running when the companion starts.
overwolf.games.onGameInfoUpdated.addListener(function (e) {
  if (e && e.gameInfo && e.gameInfo.id === WF_GAME_ID && e.gameInfo.isRunning) {
    setRequiredFeatures();
    setTimeout(pullOnce, 1500);
  }
});

overwolf.games.getRunningGameInfo(function (game) {
  if (game && game.id === WF_GAME_ID && game.isRunning) {
    setRequiredFeatures();
    setTimeout(pullOnce, 1500);
  }
});
