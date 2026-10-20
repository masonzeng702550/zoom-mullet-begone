// Splits a multipart/x-mixed-replace (MJPEG) byte stream into JPEG frames.
// Each part: "--boundary\r\n" headers "\r\n\r\n" <Content-Length bytes> "\r\n".
"use strict";

class MjpegParser {
  constructor(onFrame) {
    this.onFrame = onFrame; // called with a Uint8Array per JPEG
    this.buffer = new Uint8Array(0);
  }

  push(chunk) {
    const merged = new Uint8Array(this.buffer.length + chunk.length);
    merged.set(this.buffer, 0);
    merged.set(chunk, this.buffer.length);
    this.buffer = merged;
    for (;;) {
      const headerEnd = indexOf(this.buffer, CRLFCRLF, 0);
      if (headerEnd < 0) return;
      const headers = new TextDecoder().decode(this.buffer.subarray(0, headerEnd));
      const match = /content-length:\s*(\d+)/i.exec(headers);
      if (!match) {
        // not a part header (stray bytes): drop up to the end of this header block
        this.buffer = this.buffer.subarray(headerEnd + 4);
        continue;
      }
      const start = headerEnd + 4;
      const end = start + Number(match[1]);
      if (this.buffer.length < end) return; // wait for the rest of the frame
      this.onFrame(this.buffer.slice(start, end));
      this.buffer = this.buffer.subarray(end);
    }
  }
}

const CRLFCRLF = new Uint8Array([13, 10, 13, 10]);

function indexOf(haystack, needle, from) {
  outer: for (let i = from; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return i;
  }
  return -1;
}

if (typeof module !== "undefined") module.exports = { MjpegParser };
