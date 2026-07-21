(() => {
  "use strict";

  const panel = document.getElementById("opentui-panel");
  const terminalElement = document.getElementById("opentui-terminal");
  const startButton = document.getElementById("opentui-start");
  const stopButton = document.getElementById("opentui-stop");
  const state = document.getElementById("opentui-state");
  if (!panel || !terminalElement || !startButton || !stopButton || !state) return;

  const config = JSON.parse(document.body.dataset.lsmConfig || "{}");
  if (!config.opentuiAvailable) return;
  panel.hidden = false;

  const uiPath = String(config.uiPath || "/ui").replace(/\/$/, "");
  const tokenStorageKey = "local-shell-mcp-ui-access-token";
  const encoder = new TextEncoder();
  let terminal = null;
  let fitAddon = null;
  let socket = null;
  let dataSubscription = null;
  let binarySubscription = null;
  let reconnectTimer = null;
  let intentionalStop = false;

  function base64Url(bytes) {
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function protocols() {
    const result = ["lsm-ui-terminal"];
    const token = sessionStorage.getItem(tokenStorageKey) || "";
    if (token) result.push(`bearer.${base64Url(encoder.encode(token))}`);
    return result;
  }

  function ensureTerminal() {
    if (terminal) return true;
    const api = globalThis.LsmXterm;
    if (!api || typeof api.Terminal !== "function" || typeof api.FitAddon !== "function") {
      state.textContent = "xterm assets unavailable";
      return false;
    }
    terminal = new api.Terminal({
      convertEol: false,
      cursorBlink: true,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
      fontSize: 14,
      scrollback: 2000,
      allowTransparency: true,
      theme: { background: "rgba(3, 8, 12, 0.78)", foreground: "#d8e9f5", cursor: "#6bd5ff" },
    });
    fitAddon = new api.FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(terminalElement);
    dataSubscription = terminal.onData((value) => sendBytes(encoder.encode(value)));
    binarySubscription = terminal.onBinary((value) => {
      const bytes = Uint8Array.from(value, (character) => character.charCodeAt(0) & 0xff);
      sendBytes(bytes);
    });
    return true;
  }

  function size() {
    fitAddon?.fit();
    return {
      cols: Math.max(20, Math.min(400, terminal?.cols || 120)),
      rows: Math.max(8, Math.min(200, terminal?.rows || 36)),
    };
  }

  function sendBytes(bytes) {
    if (!socket || socket.readyState !== WebSocket.OPEN || !bytes.byteLength) return;
    for (let offset = 0; offset < bytes.byteLength; offset += 65536) {
      socket.send(bytes.slice(offset, Math.min(bytes.byteLength, offset + 65536)));
    }
  }

  function sendResize() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "resize", ...size() }));
  }

  function stop(reason = "Stopped") {
    intentionalStop = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    const current = socket;
    socket = null;
    if (current && current.readyState < WebSocket.CLOSING) current.close(1000, reason);
    startButton.disabled = false;
    stopButton.disabled = true;
    state.textContent = reason;
  }

  function start() {
    if (socket && socket.readyState < WebSocket.CLOSING) return;
    intentionalStop = false;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    if (!ensureTerminal()) return;
    const dimensions = size();
    const url = new URL(`${uiPath}/ws/opentui`, location.href);
    url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("cols", String(dimensions.cols));
    url.searchParams.set("rows", String(dimensions.rows));
    url.searchParams.set("cell_aspect", "2");
    terminal.reset();
    terminal.focus();
    state.textContent = "Connecting";
    startButton.disabled = true;
    stopButton.disabled = false;

    const current = new WebSocket(url, protocols());
    current.binaryType = "arraybuffer";
    socket = current;
    current.addEventListener("open", () => {
      if (socket !== current) return;
      state.textContent = "OpenTUI running";
      sendResize();
      terminal.focus();
    });
    current.addEventListener("message", (event) => {
      if (socket !== current) return;
      if (event.data instanceof ArrayBuffer) terminal.write(new Uint8Array(event.data));
      else if (event.data instanceof Blob) void event.data.arrayBuffer().then((value) => terminal.write(new Uint8Array(value)));
      else terminal.write(String(event.data));
    });
    current.addEventListener("close", (event) => {
      if (socket !== current) return;
      socket = null;
      startButton.disabled = false;
      stopButton.disabled = true;
      const authenticationFailure = event.code === 4401 || event.code === 4403;
      state.textContent = authenticationFailure
        ? "Authenticate in the WebUI first"
        : event.reason || "OpenTUI stopped";
      if (!intentionalStop && !authenticationFailure && event.code !== 1000 && !document.hidden) {
        state.textContent = "OpenTUI exited; reconnecting";
        reconnectTimer = setTimeout(start, 1200);
      }
    });
    current.addEventListener("error", () => {
      if (socket === current) state.textContent = "OpenTUI connection failed";
    });
  }

  startButton.addEventListener("click", start);
  stopButton.addEventListener("click", () => stop());
  for (const button of document.querySelectorAll("[data-opentui-key]")) {
    button.addEventListener("click", () => {
      const encoded = String(button.dataset.opentuiKey || "");
      try {
        sendBytes(encoder.encode(JSON.parse(`"${encoded.replace(/"/g, '\\"')}"`)));
      } catch {
        sendBytes(encoder.encode(encoded));
      }
      terminal?.focus();
    });
  }
  window.addEventListener("resize", () => window.requestAnimationFrame(sendResize));
  window.addEventListener("beforeunload", () => {
    dataSubscription?.dispose();
    binarySubscription?.dispose();
    stop("Page closed");
    terminal?.dispose();
  });
})();
