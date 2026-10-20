// node tests/js/mjpeg.test.js
"use strict";
const assert = require("node:assert");
const { MjpegParser } = require("../../browser-extension/mjpeg.js");

const enc = (s) => new TextEncoder().encode(s);
function part(bytes) {
  const head = enc(`--zoommulletbegoneframe\r\nContent-Type: image/jpeg\r\nContent-Length: ${bytes.length}\r\n\r\n`);
  const out = new Uint8Array(head.length + bytes.length + 2);
  out.set(head, 0); out.set(bytes, head.length); out.set(enc("\r\n"), head.length + bytes.length);
  return out;
}
const a = new Uint8Array([0xff, 0xd8, 1, 2, 3, 13, 10, 13, 10, 0xff, 0xd9]); // contains CRLFCRLF inside the JPEG
const b = new Uint8Array([0xff, 0xd8, 9, 0xff, 0xd9]);
const stream = new Uint8Array([...part(a), ...part(b)]);

for (const chunk of [stream.length, 1, 3, 7, 50]) {
  const frames = [];
  const p = new MjpegParser((f) => frames.push(Array.from(f)));
  for (let i = 0; i < stream.length; i += chunk) p.push(stream.subarray(i, i + chunk));
  assert.deepStrictEqual(frames, [Array.from(a), Array.from(b)], `chunk size ${chunk}`);
}
console.log("mjpeg parser: ok");
