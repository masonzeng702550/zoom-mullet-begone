// Remembers which tab sessions may receive zoom-mullet-begone video. The content
// script authorizes a session only after checking the site's camera
// permission; the bridge frame asks here before it starts streaming.
"use strict";

const key = (tabId, session) => `auth:${tabId}:${session}`;

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  const tabId = sender.tab && sender.tab.id;
  if (tabId === undefined || !message || typeof message.session !== "string") {
    reply(false);
    return false;
  }
  const k = key(tabId, message.session);
  if (message.type === "authorize") {
    chrome.storage.session.set({ [k]: true }).then(() => reply(true));
  } else if (message.type === "revoke") {
    chrome.storage.session.remove(k).then(() => reply(true));
  } else if (message.type === "may-stream") {
    chrome.storage.session.get(k).then((items) => reply(items[k] === true));
  } else {
    reply(false);
    return false;
  }
  return true; // reply is async
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const items = await chrome.storage.session.get(null);
  const stale = Object.keys(items).filter((k) => k.startsWith(`auth:${tabId}:`));
  if (stale.length) await chrome.storage.session.remove(stale);
});
