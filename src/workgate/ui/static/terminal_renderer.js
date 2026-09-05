(() => {
  "use strict";

  const MAX_RUNS = 10_000;
  const ANSI_16 = [
    "rgb(7, 17, 31)",
    "rgb(255, 123, 139)",
    "rgb(110, 231, 168)",
    "rgb(255, 212, 121)",
    "rgb(108, 167, 255)",
    "rgb(217, 167, 255)",
    "rgb(87, 215, 255)",
    "rgb(216, 233, 245)",
    "rgb(73, 100, 121)",
    "rgb(255, 154, 167)",
    "rgb(139, 241, 186)",
    "rgb(255, 224, 154)",
    "rgb(145, 189, 255)",
    "rgb(231, 196, 255)",
    "rgb(139, 231, 255)",
    "rgb(243, 251, 255)",
  ];

  function emptyStyle() {
    return {
      bold: false,
      dim: false,
      italic: false,
      underline: false,
      inverse: false,
      hidden: false,
      strike: false,
      fg: null,
      bg: null,
    };
  }

  function copyStyle(style) {
    return { ...style };
  }

  function styleKey(style) {
    return [
      style.bold ? 1 : 0,
      style.dim ? 1 : 0,
      style.italic ? 1 : 0,
      style.underline ? 1 : 0,
      style.inverse ? 1 : 0,
      style.hidden ? 1 : 0,
      style.strike ? 1 : 0,
      style.fg || "",
      style.bg || "",
    ].join("|");
  }

  function byte(value) {
    return Number.isInteger(value) && value >= 0 && value <= 255 ? value : null;
  }

  function paletteColor(value) {
    const index = byte(value);
    if (index === null) return null;
    if (index < 16) return ANSI_16[index];
    if (index < 232) {
      const offset = index - 16;
      const levels = [0, 95, 135, 175, 215, 255];
      const red = levels[Math.floor(offset / 36) % 6];
      const green = levels[Math.floor(offset / 6) % 6];
      const blue = levels[offset % 6];
      return `rgb(${red}, ${green}, ${blue})`;
    }
    const gray = 8 + (index - 232) * 10;
    return `rgb(${gray}, ${gray}, ${gray})`;
  }

  function trueColor(red, green, blue) {
    const r = byte(red);
    const g = byte(green);
    const b = byte(blue);
    if (r === null || g === null || b === null) return null;
    return `rgb(${r}, ${g}, ${b})`;
  }

  function sgrNumbers(parameters) {
    if (!parameters) return [0];
    return parameters.split(";").map((part) => {
      if (part === "") return 0;
      if (!/^\d+$/.test(part)) return null;
      const value = Number(part);
      return Number.isSafeInteger(value) ? value : null;
    });
  }

  function applySgr(style, parameters) {
    const values = sgrNumbers(parameters);
    for (let index = 0; index < values.length; index += 1) {
      const code = values[index];
      if (code === null) continue;
      if (code === 0) {
        Object.assign(style, emptyStyle());
      } else if (code === 1) {
        style.bold = true;
      } else if (code === 2) {
        style.dim = true;
      } else if (code === 3) {
        style.italic = true;
      } else if (code === 4 || code === 21) {
        style.underline = true;
      } else if (code === 7) {
        style.inverse = true;
      } else if (code === 8) {
        style.hidden = true;
      } else if (code === 9) {
        style.strike = true;
      } else if (code === 22) {
        style.bold = false;
        style.dim = false;
      } else if (code === 23) {
        style.italic = false;
      } else if (code === 24) {
        style.underline = false;
      } else if (code === 27) {
        style.inverse = false;
      } else if (code === 28) {
        style.hidden = false;
      } else if (code === 29) {
        style.strike = false;
      } else if (code >= 30 && code <= 37) {
        style.fg = ANSI_16[code - 30];
      } else if (code === 39) {
        style.fg = null;
      } else if (code >= 40 && code <= 47) {
        style.bg = ANSI_16[code - 40];
      } else if (code === 49) {
        style.bg = null;
      } else if (code >= 90 && code <= 97) {
        style.fg = ANSI_16[code - 90 + 8];
      } else if (code >= 100 && code <= 107) {
        style.bg = ANSI_16[code - 100 + 8];
      } else if (code === 38 || code === 48) {
        const target = code === 38 ? "fg" : "bg";
        const mode = values[index + 1];
        if (mode === 5) {
          const color = paletteColor(values[index + 2]);
          if (color !== null) style[target] = color;
          index += 2;
        } else if (mode === 2) {
          const color = trueColor(
            values[index + 2],
            values[index + 3],
            values[index + 4],
          );
          if (color !== null) style[target] = color;
          index += 4;
        }
      }
    }
  }

  function stringControlEnd(input, start, allowBell) {
    for (let index = start; index < input.length; index += 1) {
      const code = input.charCodeAt(index);
      if (allowBell && code === 7) return index + 1;
      if (code === 0x9c) return index + 1;
      if (code === 27 && input[index + 1] === "\\") return index + 2;
    }
    return input.length;
  }

  function parseAnsi(value) {
    const input = String(value ?? "");
    const runs = [];
    let style = emptyStyle();
    let buffer = "";
    let overflow = false;

    const flush = () => {
      if (!buffer) return;
      if (overflow) {
        runs[runs.length - 1].text += buffer;
        buffer = "";
        return;
      }
      const key = styleKey(style);
      const previous = runs[runs.length - 1];
      if (previous && previous.key === key) {
        previous.text += buffer;
      } else if (runs.length >= MAX_RUNS - 1) {
        runs.push({ text: buffer, key: styleKey(emptyStyle()), ...emptyStyle() });
        overflow = true;
      } else {
        runs.push({ text: buffer, key, ...copyStyle(style) });
      }
      buffer = "";
    };
    for (let index = 0; index < input.length; ) {
      const code = input.charCodeAt(index);
      if (code === 0x9b) {
        flush();
        let end = index + 1;
        while (end < input.length) {
          const finalCode = input.charCodeAt(end);
          if (finalCode >= 0x40 && finalCode <= 0x7e) break;
          end += 1;
        }
        if (end >= input.length) break;
        if (!overflow && input[end] === "m") {
          applySgr(style, input.slice(index + 1, end));
        }
        index = end + 1;
        continue;
      }
      if (code === 0x9d) {
        flush();
        index = stringControlEnd(input, index + 1, true);
        continue;
      }
      if (code === 0x90 || code === 0x98 || code === 0x9e || code === 0x9f) {
        flush();
        index = stringControlEnd(input, index + 1, false);
        continue;
      }
      if (code >= 0x80 && code <= 0x9f) {
        index += 1;
        continue;
      }
      if (code === 27) {
        flush();
        const kind = input[index + 1];
        if (kind === "[") {
          let end = index + 2;
          while (end < input.length) {
            const finalCode = input.charCodeAt(end);
            if (finalCode >= 0x40 && finalCode <= 0x7e) break;
            end += 1;
          }
          if (end >= input.length) break;
          if (!overflow && input[end] === "m") {
            applySgr(style, input.slice(index + 2, end));
          }
          index = end + 1;
          continue;
        }
        if (kind === "]") {
          index = stringControlEnd(input, index + 2, true);
          continue;
        }
        if (kind === "P" || kind === "_" || kind === "^" || kind === "X") {
          index = stringControlEnd(input, index + 2, false);
          continue;
        }
        index = Math.min(input.length, index + 2);
        continue;
      }
      if (code < 32) {
        if (code === 9 || code === 10 || code === 13) buffer += input[index];
        index += 1;
        continue;
      }
      if (code === 127) {
        index += 1;
        continue;
      }
      buffer += input[index];
      index += 1;
    }
    flush();
    return runs.map(({ key: _key, ...run }) => run);
  }

  function renderInto(element, value) {
    const documentObject = element.ownerDocument;
    const fragment = documentObject.createDocumentFragment();
    for (const run of parseAnsi(value)) {
      const styled =
        run.bold ||
        run.dim ||
        run.italic ||
        run.underline ||
        run.inverse ||
        run.hidden ||
        run.strike ||
        run.fg !== null ||
        run.bg !== null;
      if (!styled) {
        fragment.append(documentObject.createTextNode(run.text));
        continue;
      }
      const span = documentObject.createElement("span");
      span.className = "terminal-run";
      if (run.bold) span.classList.add("ansi-bold");
      if (run.dim) span.classList.add("ansi-dim");
      if (run.italic) span.classList.add("ansi-italic");
      if (run.underline) span.classList.add("ansi-underline");
      if (run.inverse) span.classList.add("ansi-inverse");
      if (run.hidden) span.classList.add("ansi-hidden");
      if (run.strike) span.classList.add("ansi-strike");
      if (run.fg !== null) span.style.setProperty("--ansi-fg", run.fg);
      if (run.bg !== null) span.style.setProperty("--ansi-bg", run.bg);
      span.textContent = run.text;
      fragment.append(span);
    }
    element.replaceChildren(fragment);
  }

  const api = { MAX_RUNS, paletteColor, parseAnsi, renderInto };
  if (typeof globalThis !== "undefined") globalThis.WorkgateTerminalRenderer = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
