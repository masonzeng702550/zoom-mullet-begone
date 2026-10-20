"use strict";

const DEFAULT_PORT = 8765;
const $ = (id) => document.getElementById(id);

async function refresh() {
  const { port = DEFAULT_PORT } = await chrome.storage.local.get("port");
  $("port").value = port;
  $("settings").href = `http://127.0.0.1:${port}/`;
  try {
    const r = await fetch(`http://127.0.0.1:${port}/api/settings`, { cache: "no-store" });
    const data = await r.json();
    $("state").textContent = "meet-pants 執行中";
    $("state").className = "ok";
    $("detail").textContent = data.status || "";
  } catch (e) {
    $("state").textContent = "找不到 meet-pants";
    $("state").className = "bad";
    $("detail").textContent = "請先在電腦上啟動 meet-pants（例如 python -m meet_pants --background）。";
  }
}

$("port").addEventListener("change", async () => {
  const port = Number($("port").value);
  if (Number.isInteger(port) && port > 0 && port < 65536) {
    await chrome.storage.local.set({ port });
    refresh();
  }
});

refresh();
