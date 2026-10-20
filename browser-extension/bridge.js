// Hidden extension frame inside the page: reads the MJPEG stream from the
// meet-pants app (as the extension, so websites cannot) and hands decoded
// frames to the page script.
"use strict";

const DEFAULT_PORT = 8765;
const RETRY_MS = 2000;
const session = decodeURIComponent(location.hash.slice(1));

function toPage(message, transfer) {
  window.parent.postMessage({ source: "meet-pants-bridge", session, ...message }, "*", transfer || []);
}

async function streamOnce(port) {
  const response = await fetch(`http://127.0.0.1:${port}/stream.mjpg`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  toPage({ type: "status", text: "meet-pants 啟動中…" });
  let decoding = false;
  let latest = null; // newest frame not yet decoded; older ones are dropped
  const decode = async () => {
    decoding = true;
    while (latest) {
      const jpeg = latest;
      latest = null;
      try {
        const bitmap = await createImageBitmap(new Blob([jpeg], { type: "image/jpeg" }));
        toPage({ type: "frame", bitmap }, [bitmap]);
      } catch (e) {
        /* skip a broken frame */
      }
    }
    decoding = false;
  };
  const parser = new MjpegParser((jpeg) => {
    latest = jpeg;
    if (!decoding) decode();
  });
  const reader = response.body.getReader();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    parser.push(value);
  }
}

async function main() {
  const allowed = await chrome.runtime.sendMessage({ type: "may-stream", session });
  if (!allowed) return;
  const { port = DEFAULT_PORT } = await chrome.storage.local.get("port");
  for (;;) {
    try {
      await streamOnce(port);
    } catch (e) {
      toPage({ type: "status", text: "找不到 meet-pants，請先啟動它" });
    }
    await new Promise((r) => setTimeout(r, RETRY_MS));
  }
}

main();
