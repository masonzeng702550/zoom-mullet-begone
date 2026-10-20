// Isolated content script: starts and stops the bridge frame that pulls video
// from the meet-pants app, but only for sites that hold camera permission.
(() => {
  "use strict";
  const bridges = new Map(); // session -> iframe

  async function siteMayUseCamera() {
    try {
      const status = await navigator.permissions.query({ name: "camera" });
      return status.state === "granted";
    } catch (e) {
      return false;
    }
  }

  async function start(session) {
    if (bridges.has(session) || !(await siteMayUseCamera())) return;
    await chrome.runtime.sendMessage({ type: "authorize", session });
    const frame = document.createElement("iframe");
    frame.src = chrome.runtime.getURL("bridge.html") + "#" + encodeURIComponent(session);
    frame.allow = "";
    frame.setAttribute("aria-hidden", "true");
    frame.style.cssText = "position:fixed;width:0;height:0;border:0;opacity:0;pointer-events:none;";
    (document.body || document.documentElement).appendChild(frame);
    bridges.set(session, frame);
  }

  function stop(session) {
    const frame = bridges.get(session);
    if (frame) frame.remove(); // aborts its stream; meet-pants stops when no tab watches
    bridges.delete(session);
    chrome.runtime.sendMessage({ type: "revoke", session }).catch(() => {});
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.source !== "meet-pants-page" || typeof data.session !== "string") return;
    if (data.type === "start") start(data.session);
    else if (data.type === "stop") stop(data.session);
  });

  window.addEventListener("pagehide", () => {
    for (const session of [...bridges.keys()]) stop(session);
  });
})();
