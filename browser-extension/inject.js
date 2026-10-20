// Runs in the page (MAIN world) before the page's own scripts.
// Adds a "meet-pants" camera to navigator.mediaDevices. When a page asks for
// it, returns a stream drawn from frames the meet-pants app sends (via the
// extension's content script and bridge frame).
(() => {
  "use strict";
  const md = navigator.mediaDevices;
  if (!md || md.__meetPants) return;
  Object.defineProperty(md, "__meetPants", { value: true });

  const DEVICE_ID = "meet-pants-camera";
  const LABEL = "meet-pants";
  const FPS = 30;
  const originalGetUserMedia = md.getUserMedia.bind(md);
  const originalEnumerate = md.enumerateDevices.bind(md);

  // --- device list -------------------------------------------------------
  function fakeDevice() {
    const info = Object.create(MediaDeviceInfo.prototype);
    const props = { deviceId: DEVICE_ID, groupId: DEVICE_ID, kind: "videoinput", label: LABEL };
    for (const [k, v] of Object.entries(props)) Object.defineProperty(info, k, { value: v, enumerable: true });
    Object.defineProperty(info, "toJSON", { value: () => ({ ...props }) });
    return info;
  }

  md.enumerateDevices = async function enumerateDevices() {
    const devices = await originalEnumerate();
    return [...devices, fakeDevice()];
  };

  // --- does this request ask for our camera? -----------------------------
  function mentionsUs(value) {
    if (!value) return false;
    if (typeof value === "string") return value === DEVICE_ID;
    if (Array.isArray(value)) return value.some(mentionsUs);
    if (typeof value === "object") return mentionsUs(value.exact) || mentionsUs(value.ideal);
    return false;
  }
  const wantsUs = (constraints) =>
    !!constraints && typeof constraints.video === "object" && mentionsUs(constraints.video.deviceId);

  // --- frames from the content script ------------------------------------
  const sessions = new Map(); // session id -> { canvas, ctx, gotFrame }

  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || data.source !== "meet-pants-bridge") return;
    const session = sessions.get(data.session);
    if (!session) {
      if (data.bitmap) data.bitmap.close();
      return;
    }
    if (data.type === "frame" && data.bitmap) {
      const { canvas, ctx } = session;
      if (canvas.width !== data.bitmap.width || canvas.height !== data.bitmap.height) {
        canvas.width = data.bitmap.width;
        canvas.height = data.bitmap.height;
      }
      ctx.drawImage(data.bitmap, 0, 0);
      data.bitmap.close();
      session.gotFrame = true;
    } else if (data.type === "status" && !session.gotFrame) {
      placeholder(session, data.text);
    }
  });

  function placeholder({ canvas, ctx }, text) {
    ctx.fillStyle = "#111";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#ddd";
    ctx.font = "28px -apple-system, 'PingFang TC', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);
  }

  function tellContentScript(message) {
    // "*": sandboxed and about:blank frames have an opaque origin; only session ids are sent
    window.postMessage({ source: "meet-pants-page", ...message }, "*");
  }

  async function ensureCameraPermission() {
    try {
      const status = await navigator.permissions.query({ name: "camera" });
      if (status.state === "granted") return;
    } catch (e) {
      /* some browsers cannot query camera permission: ask below */
    }
    // The site must hold camera permission, exactly as for a real camera:
    // ask through the real camera once, then release it.
    const probe = await originalGetUserMedia({ video: true });
    probe.getTracks().forEach((t) => t.stop());
  }

  async function meetPantsStream(constraints) {
    await ensureCameraPermission();
    const id = Math.random().toString(36).slice(2) + Date.now().toString(36);
    const canvas = document.createElement("canvas");
    canvas.width = 1280;
    canvas.height = 720;
    const session = { canvas, ctx: canvas.getContext("2d"), gotFrame: false };
    sessions.set(id, session);
    placeholder(session, "meet-pants 啟動中…");

    const stream = canvas.captureStream(FPS);
    const [track] = stream.getVideoTracks();
    // Look like the device the page picked.
    const settings = track.getSettings.bind(track);
    track.getSettings = () => ({ ...settings(), deviceId: DEVICE_ID, groupId: DEVICE_ID });
    Object.defineProperty(track, "label", { value: LABEL });
    const stop = track.stop.bind(track);
    let stopped = false;
    const end = () => {
      if (stopped) return;
      stopped = true;
      sessions.delete(id);
      tellContentScript({ type: "stop", session: id });
    };
    track.stop = () => {
      stop();
      end();
    };
    track.addEventListener("ended", end);

    if (constraints.audio) {
      const audio = await originalGetUserMedia({ audio: constraints.audio });
      audio.getAudioTracks().forEach((t) => stream.addTrack(t));
    }
    tellContentScript({ type: "start", session: id });
    return stream;
  }

  md.getUserMedia = function getUserMedia(constraints) {
    return wantsUs(constraints) ? meetPantsStream(constraints) : originalGetUserMedia(constraints);
  };
})();
