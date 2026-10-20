// In-browser version of zoom-mullet-begone: pose -> leg geometry -> pants mesh
// -> WebGL, all in the page. A port of the Python pipeline
// (analysis/leg_geometry.py, render/mesh.py), minus the close-up fallback
// model, the skin segmenter, forearm cut-outs and trim lines.
//
//   const engine = await PantsEngine.create(canvas, "garments/");
//   engine.setSource(videoOrImageElement);
//   engine.setGarment("dress_navy", "#6e1e28");

const MP_VERSION = "0.10.14";
const MP_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}`;
const POSE_MODEL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task";

// MediaPipe landmark indices
const L_SHOULDER = 11, R_SHOULDER = 12, L_HIP = 23, R_HIP = 24, L_KNEE = 25, R_KNEE = 26, L_ANKLE = 27, R_ANKLE = 28;

// leg_geometry.py constants
const HIP_VISIBLE = 0.5;
const CROTCH_DROP = 0.2;
const CROTCH_DEPTH = [0.15, 0.55];
const CROTCH_DEPTH_DEFAULT = 0.25;
const HEM_EXTEND = 0.08;
const WAIST_RISE = 1 / 8;
const WAIST_DIP = 0.08;
const PROFILE_SAMPLES = 9;
const PROFILE_T = Array.from({ length: PROFILE_SAMPLES }, (_, i) => 0.04 + (0.92 * i) / (PROFILE_SAMPLES - 1));
const WIDTH_CLAMP = [0.5, 2.2];
const WIDTH_EMA = 0.35;
const MERGED_RATIO = 2.5;
const MIDLINE_MIN_COS = 0.3;
// mesh.py constants
const CROTCH_BLEND = 0.35;
const BODY_MARGIN = 1.05;
const BODY_PAD = 2.0;
const FADE_IN_MS = 120;

// --- small vector helpers (points are [x, y]) ------------------------------
const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const mul = (a, s) => [a[0] * s, a[1] * s];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const len = (a) => Math.hypot(a[0], a[1]);
const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
const lerpN = (a, b, t) => a + (b - a) * t;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
function unit(v) {
  const n = len(v);
  return n > 1e-6 ? [v[0] / n, v[1] / n] : [0, 1];
}
function outwardNormal(direction, screenLeft) {
  const d = unit(direction);
  return screenLeft ? [-d[1], d[0]] : [d[1], -d[0]];
}
function interp(x, xs, ys) {
  if (x <= xs[0]) return ys[0];
  for (let i = 1; i < xs.length; i++) {
    if (x <= xs[i]) return lerpN(ys[i - 1], ys[i], (x - xs[i - 1]) / (xs[i] - xs[i - 1]));
  }
  return ys[ys.length - 1];
}
const median = (arr) => {
  const s = [...arr].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

// --- landmark smoothing (tracking/one_euro.py) -----------------------------
class OneEuro {
  constructor(minCutoff = 1.0, beta = 0.05, dCutoff = 1.0) {
    Object.assign(this, { minCutoff, beta, dCutoff });
    this.reset();
  }
  reset() {
    this.x = null;
  }
  static alpha(cutoff, dt) {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
  }
  filter(x, t) {
    if (!this.x || this.x.length !== x.length) {
      this.x = Float64Array.from(x);
      this.dx = new Float64Array(x.length);
      this.t = t;
      return Float64Array.from(x);
    }
    const dt = t - this.t;
    if (dt <= 0) return Float64Array.from(this.x);
    const ad = OneEuro.alpha(this.dCutoff, dt);
    for (let i = 0; i < x.length; i++) {
      const dx = (x[i] - this.x[i]) / dt;
      this.dx[i] += ad * (dx - this.dx[i]);
      const cutoff = this.minCutoff + this.beta * Math.abs(this.dx[i]);
      this.x[i] += OneEuro.alpha(cutoff, dt) * (x[i] - this.x[i]);
    }
    this.t = t;
    return Float64Array.from(this.x);
  }
}

// --- mask scans (leg_geometry.py) ------------------------------------------
// mask: { data: Float32Array (0..1), width, height, sx, sy } where sx/sy scale
// frame pixels to mask pixels (the mask may be smaller than the frame).
const inMask = (mask, x, y) => {
  x = Math.round(x * mask.sx);
  y = Math.round(y * mask.sy);
  return x >= 0 && y >= 0 && x < mask.width && y < mask.height && mask.data[y * mask.width + x] >= 0.5;
};

function midlineLimit(a, b, otherA, otherB, normal) {
  return PROFILE_T.map((t) => {
    const p = lerp(a, b, t), q = lerp(otherA, otherB, t);
    const gap = sub(q, p), dist = len(gap);
    const cos = -dot(gap, normal) / Math.max(dist, 1e-6);
    return Math.max(cos > MIDLINE_MIN_COS ? dist / 2 / Math.max(cos, 1e-6) : Infinity, 1);
  });
}

function scanProfile(mask, a, b, normal, maxR, innerLimit) {
  const half = [], shift = [];
  PROFILE_T.forEach((t, k) => {
    const c = lerp(a, b, t);
    if (!inMask(mask, c[0], c[1])) {
      half.push(NaN);
      shift.push(NaN);
      return;
    }
    const distance = (sign) => {
      for (let r = 1; r <= maxR; r++) {
        if (!inMask(mask, c[0] + sign * r * normal[0], c[1] + sign * r * normal[1])) return r;
      }
      return maxR;
    };
    const dOut = distance(1);
    let dIn = distance(-1);
    const limited = innerLimit && Number.isFinite(innerLimit[k]);
    if (limited) dIn = Math.min(dIn, innerLimit[k]);
    const merged = !limited && dIn > MERGED_RATIO * dOut;
    half.push(merged ? dOut : (dOut + dIn) / 2);
    shift.push(merged ? 0 : (dOut - dIn) / 2);
  });
  return { half, shift };
}

function scanCrotchDepth(mask, start, direction, maxR) {
  if (!inMask(mask, start[0], start[1])) return null;
  for (let r = 0; r <= maxR; r++) {
    const p = add(start, mul(direction, r));
    const onFrame = p[0] >= 0 && p[1] >= 0 && p[0] * mask.sx < mask.width && p[1] * mask.sy < mask.height;
    if (onFrame && !inMask(mask, p[0], p[1])) return r;
  }
  return maxR;
}

class Profile {
  constructor(half, shift) {
    this.half = half;
    this.shift = shift;
  }
  at(t) {
    return [interp(t, PROFILE_T, this.half), interp(t, PROFILE_T, this.shift)];
  }
  get medianHalf() {
    return median(this.half);
  }
}

// --- leg tracker (LegTracker.update) -----------------------------------------
class LegTracker {
  constructor() {
    this.state = new Map();
  }
  reset() {
    this.state.clear();
  }
  ema(key, value) {
    const prev = this.state.get(key);
    if (prev && prev.length === value.length) value = value.map((v, i) => prev[i] + WIDTH_EMA * (v - prev[i]));
    this.state.set(key, value);
    return value;
  }
  profile(key, measured, prior) {
    let half, shift;
    if (!measured || measured.half.every(Number.isNaN)) {
      half = Array(PROFILE_SAMPLES).fill(prior);
      shift = Array(PROFILE_SAMPLES).fill(0);
    } else {
      const idx = [], hv = [], sv = [];
      measured.half.forEach((h, i) => {
        if (!Number.isNaN(h)) idx.push(i), hv.push(h), sv.push(measured.shift[i]);
      });
      half = PROFILE_T.map((_, i) => interp(i, idx, hv));
      shift = PROFILE_T.map((_, i) => interp(i, idx, sv));
      const padded = [half[0], ...half, half[half.length - 1]];
      half = half.map((_, i) => median([padded[i], padded[i + 1], padded[i + 2]]));
      half = half.map((h) => clamp(h, WIDTH_CLAMP[0] * prior, WIDTH_CLAMP[1] * prior));
      shift = shift.map((s, i) => clamp(s, -0.5 * half[i], 0.5 * half[i]));
    }
    return new Profile(this.ema(`${key}.half`, half), this.ema(`${key}.shift`, shift));
  }

  update(pts, vis, mask) {
    if (Math.min(vis[L_HIP], vis[R_HIP]) < HIP_VISIBLE) {
      this.reset();
      return null;
    }
    const sides = [
      [pts[L_HIP], pts[L_KNEE], pts[L_ANKLE], pts[L_SHOULDER]],
      [pts[R_HIP], pts[R_KNEE], pts[R_ANKLE], pts[R_SHOULDER]],
    ].sort((s, t) => s[0][0] - t[0][0]); // screen left first
    const hipL = sides[0][0], hipR = sides[1][0];
    const shoulderMid = mul(add(sides[0][3], sides[1][3]), 0.5);
    const torso = len(sub(shoulderMid, mul(add(hipL, hipR), 0.5)));
    const base = Math.max(len(sub(hipR, hipL)), 0.35 * torso, 4);
    const thighPrior = 0.5 * base, shinPrior = 0.32 * base;
    const maxR = Math.ceil(WIDTH_CLAMP[1] * thighPrior * 2);
    const crotches = sides.map(([hip, knee]) => add(hip, mul(sub(knee, hip), CROTCH_DROP)));

    const legs = sides.map(([hip, knee, ankle, shoulder], i) => {
      const screenLeft = i === 0;
      const otherHip = i === 0 ? hipR : hipL;
      const crotch = crotches[i];
      const hem = add(ankle, mul(sub(ankle, knee), HEM_EXTEND));
      let thighM = null, shinM = null;
      if (mask) {
        const other = sides[1 - i];
        const thighN = outwardNormal(sub(knee, crotch), screenLeft);
        const shinN = outwardNormal(sub(hem, knee), screenLeft);
        thighM = scanProfile(mask, crotch, knee, thighN, maxR, midlineLimit(crotch, knee, crotches[1 - i], other[1], thighN));
        shinM = scanProfile(mask, knee, ankle, shinN, maxR, midlineLimit(knee, ankle, other[1], other[2], shinN));
      }
      const key = screenLeft ? "left" : "right";
      return {
        hip, knee, ankle, crotch, hem, screenLeft,
        waist: add(hip, mul(sub(shoulder, hip), WAIST_RISE)),
        outward: unit(sub(hip, otherHip)),
        thigh: this.profile(`${key}.thigh`, thighM, thighPrior),
        shin: this.profile(`${key}.shin`, shinM, shinPrior),
      };
    });
    for (const leg of legs) {
      leg.thighNormal = outwardNormal(sub(leg.knee, leg.crotch), leg.screenLeft);
      leg.shinNormal = outwardNormal(sub(leg.hem, leg.knee), leg.screenLeft);
      leg.kneeNormal = unit(add(leg.thighNormal, leg.shinNormal));
    }
    const [left, right] = legs;
    const hipMid = mul(add(left.hip, right.hip), 0.5);
    const down = unit(sub(mul(add(left.knee, right.knee), 0.5), hipMid));
    const thighLen = (len(sub(left.knee, left.hip)) + len(sub(right.knee, right.hip))) / 2;
    let depth = null;
    if (mask && thighLen > 1) depth = scanCrotchDepth(mask, hipMid, down, Math.floor(CROTCH_DEPTH[1] * thighLen));
    let ratio = depth === null ? CROTCH_DEPTH_DEFAULT : clamp(depth / thighLen, ...CROTCH_DEPTH);
    ratio = this.ema("crotch.depth", [ratio])[0];
    const crotchMid = add(hipMid, mul(down, ratio * thighLen));
    const waistMid = lerp(mul(add(left.waist, right.waist), 0.5), crotchMid, WAIST_DIP);
    return { left, right, waistMid, crotchMid, scale: base };
  }
}

// --- mesh (render/mesh.py) -----------------------------------------------
const crosses = (p, origin, m, sign) => dot(sub(p, origin), m) * sign > 0;

function legRows(leg, anchors, g, waistMid, crotchMid) {
  const ease = g.ease;
  const thighHalf = leg.thigh.medianHalf, shinHalf = leg.shin.medianHalf;
  const styleTop = thighHalf * ease * 1.05;
  const styleKnee = (0.45 * thighHalf + 0.55 * shinHalf) * ease;
  const styleHem = Math.max(shinHalf * ease, 0.75 * styleKnee);
  const body = (half) => half * BODY_MARGIN + BODY_PAD;
  const shinLen = Math.max(len(sub(leg.ankle, leg.knee)), 1e-6);
  const hemT = len(sub(leg.hem, leg.knee)) / shinLen;
  const thighRow = (t) => {
    const [half, shift] = leg.thigh.at(t);
    return [Math.max(lerpN(styleTop, styleKnee, t), body(half)), shift];
  };
  const shinRow = (t) => {
    const [half, shift] = leg.shin.at(t * hemT);
    return [Math.max(lerpN(styleKnee, styleHem, t), body(half)), shift];
  };
  const [top, topShift] = thighRow(0);
  const [wt, st] = thighRow(1), [ws, ss] = shinRow(0);
  const knee = Math.max(wt, ws), kneeShift = (st + ss) / 2;
  const thighN = leg.thighNormal, shinN = leg.shinNormal, kneeN = leg.kneeNormal;
  const a = anchors;
  const kneeC = add(leg.knee, mul(kneeN, kneeShift));
  const kneeOuter = add(kneeC, mul(kneeN, knee)), kneeInner = sub(kneeC, mul(kneeN, knee));
  const alongLeg = add(unit(sub(leg.knee, leg.crotch)), unit(sub(leg.hem, leg.knee)));
  let m = [-kneeN[1], kneeN[0]];
  if (dot(m, alongLeg) < 0) m = mul(m, -1);

  const rows = [];
  for (let i = 0; i <= g.mesh.waist_rows; i++) {
    const t = i / g.mesh.waist_rows;
    rows.push([
      lerp(add(leg.waist, mul(leg.outward, top)), add(leg.crotch, mul(thighN, top + topShift)), t),
      lerp(waistMid, crotchMid, t),
      lerp(a.waist_out, a.crotch_out, t),
      lerp(g.waist_mid, g.crotch, t),
    ]);
  }
  for (let i = 1; i <= g.mesh.along; i++) {
    const t = i / g.mesh.along;
    let n, c, w;
    if (i === g.mesh.along) {
      n = kneeN; c = kneeC; w = knee;
    } else {
      n = thighN;
      const [ww, shift] = thighRow(t);
      w = ww;
      c = add(lerp(leg.crotch, leg.knee, t), mul(n, shift));
    }
    let inner = lerp(crotchMid, sub(c, mul(n, w)), Math.min(1, t / CROTCH_BLEND));
    let outer = add(c, mul(n, w));
    if (i < g.mesh.along) {
      if (crosses(outer, kneeC, m, 1)) outer = kneeOuter;
      if (crosses(inner, kneeC, m, 1)) inner = kneeInner;
    }
    rows.push([outer, inner, lerp(a.crotch_out, a.knee_out, t), lerp(g.crotch, a.knee_in, t)]);
  }
  for (let i = 1; i <= g.mesh.along; i++) {
    const t = i / g.mesh.along;
    const [w, shift] = shinRow(t);
    const c = add(lerp(leg.knee, leg.hem, t), mul(shinN, shift));
    let outer = add(c, mul(shinN, w)), inner = sub(c, mul(shinN, w));
    if (crosses(outer, kneeC, m, -1)) outer = kneeOuter;
    if (crosses(inner, kneeC, m, -1)) inner = kneeInner;
    rows.push([outer, inner, lerp(a.knee_out, a.hem_out, t), lerp(a.knee_in, a.hem_in, t)]);
  }
  return rows;
}

// Interleaved triangle list: x, y (frame px), u, v (0..1)
function buildMesh(geo, g) {
  const out = [];
  const [tw, th] = g.size;
  for (const [leg, anchors] of [[geo.left, g.left], [geo.right, g.right]]) {
    const rows = legRows(leg, anchors, g, geo.waistMid, geo.crotchMid);
    const across = g.mesh.across;
    const grid = rows.map(([dO, dI, sO, sI]) =>
      Array.from({ length: across + 1 }, (_, k) => {
        const s = k / across;
        const d = lerp(dO, dI, s), uv = lerp(sO, sI, s);
        return [d[0], d[1], uv[0] / tw, uv[1] / th];
      })
    );
    for (let r = 0; r < grid.length - 1; r++) {
      for (let c = 0; c < across; c++) {
        const p = grid[r][c], p1 = grid[r][c + 1], q = grid[r + 1][c], q1 = grid[r + 1][c + 1];
        out.push(...p, ...p1, ...q, ...p1, ...q1, ...q);
      }
    }
  }
  return new Float32Array(out);
}

// --- WebGL -----------------------------------------------------------------
const VS = `#version 300 es
in vec2 a_pos; in vec2 a_uv; uniform vec2 u_size; out vec2 v_uv;
void main() { vec2 p = a_pos / u_size * 2.0 - 1.0; gl_Position = vec4(p.x, -p.y, 0.0, 1.0); v_uv = a_uv; }`;
const FS = `#version 300 es
precision mediump float; in vec2 v_uv; uniform sampler2D u_tex; uniform vec4 u_tint; out vec4 o;
void main() { vec4 c = texture(u_tex, v_uv); o = vec4(c.rgb * u_tint.rgb, c.a) * u_tint.a; }`;

function compile(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
  return s;
}

class Renderer {
  constructor(canvas) {
    const gl = canvas.getContext("webgl2", { premultipliedAlpha: true, alpha: false, preserveDrawingBuffer: false });
    if (!gl) throw new Error("WebGL2 is not available in this browser");
    this.gl = gl;
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    this.prog = prog;
    this.loc = {
      pos: gl.getAttribLocation(prog, "a_pos"),
      uv: gl.getAttribLocation(prog, "a_uv"),
      size: gl.getUniformLocation(prog, "u_size"),
      tex: gl.getUniformLocation(prog, "u_tex"),
      tint: gl.getUniformLocation(prog, "u_tint"),
    };
    this.buf = gl.createBuffer();
    this.frameTex = this.texture(false);
  }
  texture(mipmap) {
    const gl = this.gl;
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mipmap ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return t;
  }
  garmentTexture(image) {
    const gl = this.gl;
    const t = this.texture(true);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.generateMipmap(gl.TEXTURE_2D);
    return t;
  }
  draw(source, w, h, mesh, garmentTex, tint) {
    const gl = this.gl;
    const canvas = gl.canvas;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    gl.viewport(0, 0, w, h);
    gl.useProgram(this.prog);
    gl.uniform2f(this.loc.size, w, h);
    gl.uniform1i(this.loc.tex, 0);
    gl.activeTexture(gl.TEXTURE0);
    // camera frame as a full-screen quad
    gl.bindTexture(gl.TEXTURE_2D, this.frameTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
    gl.disable(gl.BLEND);
    gl.uniform4f(this.loc.tint, 1, 1, 1, 1);
    this.drawArrays(new Float32Array([0, 0, 0, 0, w, 0, 1, 0, 0, h, 0, 1, w, 0, 1, 0, w, h, 1, 1, 0, h, 0, 1]));
    if (mesh && garmentTex) {
      gl.bindTexture(gl.TEXTURE_2D, garmentTex);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.uniform4f(this.loc.tint, tint[0], tint[1], tint[2], tint[3]);
      this.drawArrays(mesh);
    }
  }
  drawArrays(data) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STREAM_DRAW);
    gl.enableVertexAttribArray(this.loc.pos);
    gl.vertexAttribPointer(this.loc.pos, 2, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(this.loc.uv);
    gl.vertexAttribPointer(this.loc.uv, 2, gl.FLOAT, false, 16, 8);
    gl.drawArrays(gl.TRIANGLES, 0, data.length / 4);
  }
}

// --- garments ----------------------------------------------------------------
function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`could not load ${url}`));
    img.src = url;
  });
}

// Recolor keeping the fabric's shading: each pixel's brightness relative to the
// median brightness is applied to the new color (render/garment.py).
function recolor(img, hex) {
  const c = document.createElement("canvas");
  c.width = img.width;
  c.height = img.height;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  const data = ctx.getImageData(0, 0, c.width, c.height);
  const px = data.data;
  const lumas = [];
  for (let i = 0; i < px.length; i += 4 * 7) if (px[i + 3] > 200) lumas.push(0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]);
  const ref = Math.max(median(lumas), 1);
  const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
  for (let i = 0; i < px.length; i += 4) {
    if (!px[i + 3]) continue;
    const k = (0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]) / ref;
    px[i] = Math.min(255, r * k);
    px[i + 1] = Math.min(255, g * k);
    px[i + 2] = Math.min(255, b * k);
  }
  ctx.putImageData(data, 0, 0);
  return c;
}

// --- engine ------------------------------------------------------------------
export class PantsEngine {
  static async create(canvas, garmentsBase, onStatus = () => {}) {
    onStatus("loading");
    const { FilesetResolver, PoseLandmarker } = await import(`${MP_BASE}/vision_bundle.mjs`);
    const fileset = await FilesetResolver.forVisionTasks(`${MP_BASE}/wasm`);
    const options = (delegate) => ({
      baseOptions: { modelAssetPath: POSE_MODEL, delegate },
      runningMode: "VIDEO",
      numPoses: 1,
      outputSegmentationMasks: true,
    });
    let pose;
    try {
      pose = await PoseLandmarker.createFromOptions(fileset, options("GPU"));
    } catch (e) {
      pose = await PoseLandmarker.createFromOptions(fileset, options("CPU"));
    }
    const engine = new PantsEngine(canvas, garmentsBase, pose, onStatus);
    engine.garments = await (await fetch(`${garmentsBase}index.json`)).json();
    return engine;
  }

  constructor(canvas, garmentsBase, pose, onStatus) {
    this.canvas = canvas;
    this.base = garmentsBase;
    this.pose = pose;
    this.onStatus = onStatus;
    this.renderer = new Renderer(canvas);
    this.legs = new LegTracker();
    this.smoother = new OneEuro(1.0, 0.05, 1.0);
    this.cache = new Map(); // "id|color" -> { spec, tex }
    this.sources = new Map(); // id -> Promise<{ spec, img }>
    this.garment = null;
    this.enabled = true;
    this.source = null;
    this.lastTs = -1;
    this.appeared = null;
    this.status = "";
    this.exposure = 1;
    this.frames = 0;
    this.loop = this.loop.bind(this);
  }

  async setGarment(id, color = "") {
    const key = `${id}|${color}`;
    this.wanted = key; // quick clicks: only the last choice is applied
    if (!this.cache.has(key)) {
      if (!this.sources.has(id)) {
        this.sources.set(id, (async () => {
          const spec = await (await fetch(`${this.base}${id}.json`)).json();
          return { spec, img: await loadImage(`${this.base}${spec.texture}`) };
        })());
      }
      const { spec, img } = await this.sources.get(id);
      if (!this.cache.has(key)) {
        this.cache.set(key, { spec, tex: this.renderer.garmentTexture(color ? recolor(img, color) : img) });
      }
    }
    if (this.wanted === key) this.garment = this.cache.get(key);
  }

  setSource(el) {
    this.source = el;
    this.legs.reset();
    this.smoother.reset();
    this.appeared = null;
    if (!this.running) {
      this.running = true;
      requestAnimationFrame(this.loop);
    }
  }

  stop() {
    this.running = false;
    this.source = null;
  }

  setStatus(s) {
    if (s !== this.status) {
      this.status = s;
      this.onStatus(s);
    }
  }

  sourceSize() {
    const s = this.source;
    if (!s) return [0, 0];
    if (s instanceof HTMLVideoElement) return [s.videoWidth, s.videoHeight];
    return [s.naturalWidth || s.width, s.naturalHeight || s.height];
  }

  // Overall exposure of the scene, so the pants are not brighter than the room.
  measureExposure(source, w, h) {
    if (!this.probe) {
      this.probe = document.createElement("canvas");
      this.probe.width = this.probe.height = 16;
      this.probeCtx = this.probe.getContext("2d", { willReadFrequently: true });
    }
    this.probeCtx.drawImage(source, 0, 0, 16, 16);
    const px = this.probeCtx.getImageData(0, 0, 16, 16).data;
    let sum = 0;
    for (let i = 0; i < px.length; i += 4) sum += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    const luma = sum / 256 / 255;
    const target = clamp(Math.sqrt(Math.max(luma, 1e-3) / 0.45), 0.8, 1.1);
    this.exposure += 0.15 * (target - this.exposure);
  }

  loop(now) {
    if (!this.running) return;
    requestAnimationFrame(this.loop);
    const src = this.source;
    const [w, h] = this.sourceSize();
    if (!src || !w || !h) return;
    if (src instanceof HTMLVideoElement && src.readyState < 2) return;

    const ts = Math.max(Math.round(now), this.lastTs + 1); // VIDEO mode needs increasing timestamps
    this.lastTs = ts;
    let geo = null;
    let result;
    try {
      result = this.pose.detectForVideo(src, ts);
    } catch (e) {
      return;
    }
    const lm = result.landmarks && result.landmarks[0];
    if (lm) {
      const raw = new Float64Array(lm.length * 2);
      lm.forEach((p, i) => {
        raw[2 * i] = p.x * w;
        raw[2 * i + 1] = p.y * h;
      });
      const xy = this.smoother.filter(raw, ts / 1000);
      const pts = lm.map((_, i) => [xy[2 * i], xy[2 * i + 1]]);
      const vis = lm.map((p) => p.visibility ?? 1);
      let mask = null;
      const m = result.segmentationMasks && result.segmentationMasks[0];
      if (m) {
        mask = { data: m.getAsFloat32Array(), width: m.width, height: m.height, sx: m.width / w, sy: m.height / h };
      }
      geo = this.legs.update(pts, vis, mask);
    } else {
      this.smoother.reset();
      this.legs.reset();
    }
    if (result.segmentationMasks) result.segmentationMasks.forEach((m) => m.close());

    if (this.frames++ % 15 === 0) this.measureExposure(src, w, h);
    let mesh = null;
    if (geo && this.garment && this.enabled) {
      mesh = buildMesh(geo, this.garment.spec);
      if (this.appeared === null) this.appeared = now;
    } else {
      this.appeared = null;
    }
    const opacity = this.appeared === null ? 0 : Math.min(1, (now - this.appeared) / FADE_IN_MS);
    const e = this.exposure;
    this.renderer.draw(src, w, h, mesh, this.garment && this.garment.tex, [e, e, e, opacity]);
    this.setStatus(!lm ? "nobody" : geo ? "dressed" : "nohips");
  }
}
