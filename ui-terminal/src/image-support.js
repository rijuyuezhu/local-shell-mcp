import { ImageAddon } from "@xterm/addon-image";

export const WEB_IMAGE_ADDON_OPTIONS = Object.freeze({
  enableSizeReports: true,
  sixelSupport: true,
  sixelScrolling: true,
  sixelPaletteLimit: 256,
  sixelSizeLimit: 25_000_000,
  iipSupport: true,
  iipSizeLimit: 20_000_000,
  pixelLimit: 16_777_216,
  storageLimit: 64,
  showPlaceholder: false,
});

export function createImageAddon() {
  return new ImageAddon(WEB_IMAGE_ADDON_OPTIONS);
}
