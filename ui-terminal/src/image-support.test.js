import assert from "node:assert/strict";
import test from "node:test";

globalThis.self = globalThis;

const { ImageAddon } = await import("@xterm/addon-image");
const { WEB_IMAGE_ADDON_OPTIONS, createImageAddon } = await import(
  "./image-support.js"
);

test("enables bounded Sixel and iTerm inline image protocols", () => {
  assert.equal(WEB_IMAGE_ADDON_OPTIONS.enableSizeReports, true);
  assert.equal(WEB_IMAGE_ADDON_OPTIONS.sixelSupport, true);
  assert.equal(WEB_IMAGE_ADDON_OPTIONS.iipSupport, true);
  assert.equal(WEB_IMAGE_ADDON_OPTIONS.pixelLimit, 16_777_216);
  assert.equal(WEB_IMAGE_ADDON_OPTIONS.sixelSizeLimit, 25_000_000);
  assert.equal(WEB_IMAGE_ADDON_OPTIONS.iipSizeLimit, 20_000_000);
  assert.equal(WEB_IMAGE_ADDON_OPTIONS.storageLimit, 64);
  assert.equal(Object.isFrozen(WEB_IMAGE_ADDON_OPTIONS), true);
});

test("constructs the official xterm image addon", () => {
  assert.ok(createImageAddon() instanceof ImageAddon);
});
