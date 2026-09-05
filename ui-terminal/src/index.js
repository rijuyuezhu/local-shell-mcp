import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";

import {
  WEB_IMAGE_ADDON_OPTIONS,
  createImageAddon,
} from "./image-support.js";

globalThis.WorkgateXterm = Object.freeze({
  FitAddon,
  Terminal,
  WEB_IMAGE_ADDON_OPTIONS,
  createImageAddon,
});
