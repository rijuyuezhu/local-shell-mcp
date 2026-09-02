export function createTerminalController({
  elements,
  request,
  text,
  encoder,
  uiPath,
  sessionBindingToken,
  sessionBindingProtocolPrefix,
  showAuthentication,
  onAuthenticationRequired,
}) {
  const controllerState = {
    terminalSocket: null,
    terminalSocketMachine: "",
    terminalMachine: "local",
    terminalMode: "snapshot",
    terminalReady: false,
    terminalXterm: null,
    terminalFitAddon: null,
    terminalXtermData: null,
    terminalXtermBinary: null,
    selectedShellId: "",
    terminalSessions: [],
    terminalGeneration: 0,
    terminalListGeneration: 0,
    terminalLoading: false,
    terminalMachineStates: new Map([["local", "online"]]),
    terminalFollowOutput: true,
    terminalPendingOutput: null,
    terminalPendingUpdates: 0,
    terminalLastOutput: "",
    terminalCommandHistory: [],
    terminalHistoryIndex: 0,
    terminalHistoryDraft: "",
  };

  const terminalSpecialKeys = Object.freeze({
    escape: "\u001b",
    tab: "\t",
    up: "\u001b[A",
    down: "\u001b[B",
    "ctrl-c": "\u0003",
    "ctrl-d": "\u0004",
  });
  const terminalHistoryLimit = 100;

  function terminalAtBottom() {
    return (
      elements.terminalOutput.scrollTop + elements.terminalOutput.clientHeight >=
      elements.terminalOutput.scrollHeight - 24
    );
  }

  function updateTerminalLatestControl() {
    const pending = controllerState.terminalMode !== "pty" && controllerState.terminalPendingOutput !== null;
    elements.terminalLatest.hidden = !pending;
    elements.terminalPendingCount.textContent = pending
      ? `(${Math.max(1, controllerState.terminalPendingUpdates)})`
      : "";
  }

  function renderTerminalOutput(value, { scrollToBottom = false } = {}) {
    const output = String(value ?? "");
    controllerState.terminalLastOutput = output;
    const renderer = globalThis.LsmTerminalRenderer;
    if (renderer && typeof renderer.renderInto === "function") {
      renderer.renderInto(elements.terminalOutput, output);
    } else {
      elements.terminalOutput.textContent = output;
    }
    if (scrollToBottom) {
      elements.terminalOutput.scrollTop = elements.terminalOutput.scrollHeight;
    }
  }

  function showTerminalMessage(message) {
    activateTerminalMode("snapshot");
    controllerState.terminalFollowOutput = true;
    controllerState.terminalPendingOutput = null;
    controllerState.terminalPendingUpdates = 0;
    controllerState.terminalLastOutput = "";
    elements.terminalOutput.textContent = String(message ?? "");
    elements.terminalOutput.scrollTop = 0;
    updateTerminalLatestControl();
  }

  function acceptTerminalSnapshot(value) {
    activateTerminalMode("snapshot");
    const output = String(value ?? "");
    controllerState.terminalLastOutput = output;
    if (!terminalAtBottom()) {
      controllerState.terminalFollowOutput = false;
      controllerState.terminalPendingOutput = output;
      controllerState.terminalPendingUpdates = Math.min(9999, controllerState.terminalPendingUpdates + 1);
      updateTerminalLatestControl();
      return;
    }
    controllerState.terminalFollowOutput = true;
    controllerState.terminalPendingOutput = null;
    controllerState.terminalPendingUpdates = 0;
    renderTerminalOutput(output, { scrollToBottom: true });
    updateTerminalLatestControl();
  }

  function jumpToLatestTerminalOutput() {
    const output = controllerState.terminalPendingOutput ?? controllerState.terminalLastOutput;
    controllerState.terminalFollowOutput = true;
    controllerState.terminalPendingOutput = null;
    controllerState.terminalPendingUpdates = 0;
    renderTerminalOutput(output, { scrollToBottom: true });
    updateTerminalLatestControl();
  }

  function rememberTerminalCommand(command) {
    if (!command) return;
    if (controllerState.terminalCommandHistory[controllerState.terminalCommandHistory.length - 1] !== command) {
      controllerState.terminalCommandHistory.push(command);
      if (controllerState.terminalCommandHistory.length > terminalHistoryLimit) {
        controllerState.terminalCommandHistory = controllerState.terminalCommandHistory.slice(-terminalHistoryLimit);
      }
    }
    controllerState.terminalHistoryIndex = controllerState.terminalCommandHistory.length;
    controllerState.terminalHistoryDraft = "";
  }

  function navigateTerminalHistory(direction) {
    if (!controllerState.terminalCommandHistory.length) return;
    if (controllerState.terminalHistoryIndex === controllerState.terminalCommandHistory.length) {
      controllerState.terminalHistoryDraft = elements.terminalInput.value;
    }
    controllerState.terminalHistoryIndex = Math.max(
      0,
      Math.min(controllerState.terminalCommandHistory.length, controllerState.terminalHistoryIndex + direction),
    );
    elements.terminalInput.value =
      controllerState.terminalHistoryIndex === controllerState.terminalCommandHistory.length
        ? controllerState.terminalHistoryDraft
        : controllerState.terminalCommandHistory[controllerState.terminalHistoryIndex];
    elements.terminalInput.setSelectionRange(
      elements.terminalInput.value.length,
      elements.terminalInput.value.length,
    );
  }

  function terminalSocketCurrent() {
    return Boolean(
      controllerState.terminalSocket &&
      controllerState.terminalSocket.readyState === WebSocket.OPEN &&
      controllerState.terminalSocketMachine === controllerState.terminalMachine
    );
  }

  function sendTerminalBytes(data) {
    if (!controllerState.terminalReady || !terminalSocketCurrent() || controllerState.terminalMode !== "pty") return false;
    const bytes = data instanceof Uint8Array ? data : encoder.encode(String(data ?? ""));
    if (!bytes.byteLength) return false;
    for (let offset = 0; offset < bytes.byteLength; offset += 65536) {
      controllerState.terminalSocket.send(bytes.slice(offset, Math.min(bytes.byteLength, offset + 65536)));
    }
    return true;
  }

  function ensureTerminalXterm() {
    if (controllerState.terminalXterm) return true;
    const api = globalThis.LsmXterm;
    if (!api || typeof api.Terminal !== "function" || typeof api.FitAddon !== "function") {
      return false;
    }
    controllerState.terminalXterm = new api.Terminal({
      allowProposedApi: false,
      convertEol: false,
      cursorBlink: true,
      cursorStyle: "block",
      disableStdin: false,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
      fontSize: 13,
      lineHeight: 1.15,
      linkHandler: {
        activate: () => {},
        allowNonHttpProtocols: false,
      },
      scrollback: 5000,
      theme: {
        background: "#07111f",
        foreground: "#d8e9f5",
        cursor: "#57d7ff",
        cursorAccent: "#07111f",
        selectionBackground: "#24546e",
        black: "#07111f",
        red: "#ff6b7a",
        green: "#62d196",
        yellow: "#f1c75b",
        blue: "#5aa9ff",
        magenta: "#c792ea",
        cyan: "#57d7ff",
        white: "#d8e9f5",
        brightBlack: "#66788a",
        brightRed: "#ff8794",
        brightGreen: "#7ee2aa",
        brightYellow: "#ffe08a",
        brightBlue: "#82c0ff",
        brightMagenta: "#d9a7f2",
        brightCyan: "#8be8ff",
        brightWhite: "#f3fbff",
      },
    });
    controllerState.terminalXterm.parser.registerOscHandler(8, () => true);
    if (typeof api.createImageAddon === "function") {
      controllerState.terminalXterm.loadAddon(api.createImageAddon());
    }
    controllerState.terminalFitAddon = new api.FitAddon();
    controllerState.terminalXterm.loadAddon(controllerState.terminalFitAddon);
    controllerState.terminalXterm.open(elements.terminalXterm);
    controllerState.terminalXtermData = controllerState.terminalXterm.onData((data) => {
      sendTerminalBytes(encoder.encode(data));
    });
    controllerState.terminalXtermBinary = controllerState.terminalXterm.onBinary((data) => {
      const bytes = new Uint8Array(data.length);
      for (let index = 0; index < data.length; index += 1) {
        bytes[index] = data.charCodeAt(index) & 0xff;
      }
      sendTerminalBytes(bytes);
    });
    return true;
  }

  function activateTerminalMode(mode, { reset = false } = {}) {
    controllerState.terminalMode = mode === "pty" ? "pty" : "snapshot";
    const raw = controllerState.terminalMode === "pty";
    if (raw && !ensureTerminalXterm()) return false;
    elements.terminalXterm.hidden = !raw;
    elements.terminalOutput.hidden = raw;
    if (raw) {
      controllerState.terminalPendingOutput = null;
      controllerState.terminalPendingUpdates = 0;
      updateTerminalLatestControl();
      if (reset) controllerState.terminalXterm.reset();
      window.requestAnimationFrame(() => {
        if (controllerState.terminalMode !== "pty" || !controllerState.terminalFitAddon) return;
        sendTerminalResize();
        controllerState.terminalXterm.focus();
      });
    }
    return true;
  }

  function sendTerminalData(data, enter = false) {
    if (!data || !controllerState.terminalReady || !terminalSocketCurrent()) return false;
    if (controllerState.terminalMode === "pty") {
      const bytes = encoder.encode(`${data}${enter ? "\r" : ""}`);
      return sendTerminalBytes(bytes);
    }
    controllerState.terminalSocket.send(JSON.stringify({ type: "input", data, enter }));
    return true;
  }

  function terminalSocketProtocols() {
    const protocols = ["lsm-ui-terminal"];
    const bindingToken = sessionBindingToken();
    if (bindingToken) protocols.push(`${sessionBindingProtocolPrefix}${bindingToken}`);
    return protocols;
  }

  function terminalMachineOnline(machine = controllerState.terminalMachine) {
    return machine === "local" || controllerState.terminalMachineStates.get(machine) === "online";
  }

  function terminalSize() {
    if (controllerState.terminalMode === "pty" && controllerState.terminalXterm) {
      return {
        cols: Math.max(20, Math.min(300, controllerState.terminalXterm.cols)),
        rows: Math.max(3, Math.min(120, controllerState.terminalXterm.rows)),
      };
    }
    const bounds = elements.terminalOutput.getBoundingClientRect();
    const cols = Math.max(20, Math.min(300, Math.floor(bounds.width / 8.2)));
    const rows = Math.max(3, Math.min(120, Math.floor(bounds.height / 19)));
    return { cols, rows };
  }

  function setTerminalControls(enabled = false) {
    const online = terminalMachineOnline();
    const connected =
      enabled &&
      online &&
      controllerState.terminalSocketMachine === controllerState.terminalMachine &&
      controllerState.terminalReady &&
      controllerState.terminalSocket?.readyState === WebSocket.OPEN;
    elements.terminalMachine.disabled = controllerState.terminalLoading;
    elements.terminalStartForm.querySelector("button").disabled = controllerState.terminalLoading || !online;
    elements.terminalName.disabled = controllerState.terminalLoading || !online;
    elements.terminalInput.disabled = !connected;
    elements.terminalInputForm.querySelector("button").disabled = !connected;
    for (const button of elements.terminalKeyButtons) button.disabled = !connected;
    elements.terminalKill.disabled = controllerState.terminalLoading || !online || !controllerState.selectedShellId;
  }

  function closeTerminalSocket() {
    controllerState.terminalGeneration += 1;
    const socket = controllerState.terminalSocket;
    controllerState.terminalSocket = null;
    controllerState.terminalSocketMachine = "";
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close(1000, "Client changed terminal");
    }
    controllerState.terminalMode = "snapshot";
    controllerState.terminalReady = false;
    elements.terminalXterm.hidden = true;
    elements.terminalOutput.hidden = false;
    controllerState.terminalXterm?.reset();
    controllerState.terminalPendingOutput = null;
    controllerState.terminalPendingUpdates = 0;
    updateTerminalLatestControl();
    elements.terminalState.textContent = controllerState.selectedShellId ? "Disconnected" : "No session";
    setTerminalControls(false);
  }

  function resetTerminalWorkspace(machine) {
    closeTerminalSocket();
    controllerState.terminalMachine = machine || "local";
    controllerState.terminalListGeneration += 1;
    controllerState.terminalSessions = [];
    controllerState.selectedShellId = "";
    controllerState.terminalCommandHistory = [];
    controllerState.terminalHistoryIndex = 0;
    controllerState.terminalHistoryDraft = "";
    elements.terminalMachine.value = controllerState.terminalMachine;
    elements.terminalTitle.textContent = "No terminal selected";
    elements.terminalState.textContent = `Not loaded · ${controllerState.terminalMachine}`;
    showTerminalMessage(`Select or create a terminal session on ${controllerState.terminalMachine}.`);
    renderTerminalList({ shells: [] }, { emptyMessage: `Terminals for ${controllerState.terminalMachine} are not loaded.` });
    setTerminalControls(false);
  }

  function renderTerminalMachines(machines) {
    const available = Array.isArray(machines) ? machines : [];
    controllerState.terminalMachineStates = new Map([["local", "online"]]);
    elements.terminalMachine.replaceChildren();
    let localPresent = false;
    let currentPresent = false;
    let currentOnline = controllerState.terminalMachine === "local";
    for (const machine of available) {
      const name = text(machine.name, "");
      if (!name) continue;
      if (name === "local") localPresent = true;
      const state = name === "local" ? "online" : text(machine.status, "offline");
      const online = name === "local" || state === "online";
      controllerState.terminalMachineStates.set(name, state);
      const option = document.createElement("option");
      option.value = name;
      option.textContent = online ? name : `${name} (${state})`;
      option.disabled = !online;
      option.selected = name === controllerState.terminalMachine;
      if (option.selected) {
        currentPresent = true;
        currentOnline = online;
      }
      elements.terminalMachine.append(option);
    }
    if (!localPresent) {
      const local = document.createElement("option");
      local.value = "local";
      local.textContent = "local";
      local.selected = controllerState.terminalMachine === "local";
      elements.terminalMachine.prepend(local);
      if (local.selected) {
        currentPresent = true;
        currentOnline = true;
      }
    }
    if (!currentPresent && controllerState.terminalMachine !== "local") {
      const stale = document.createElement("option");
      stale.value = controllerState.terminalMachine;
      stale.textContent = `${controllerState.terminalMachine} (unavailable)`;
      stale.disabled = true;
      stale.selected = true;
      elements.terminalMachine.append(stale);
    }
    if (!currentPresent || !currentOnline) {
      const changed = controllerState.terminalMachine !== "local";
      resetTerminalWorkspace("local");
      if (changed) refreshTerminalsInBackground({ force: true });
    } else {
      elements.terminalMachine.value = controllerState.terminalMachine;
      setTerminalControls(controllerState.terminalSocket?.readyState === WebSocket.OPEN);
    }
  }

  function renderTerminalList(payload, { emptyMessage = "No persistent terminals are running." } = {}) {
    controllerState.terminalSessions = Array.isArray(payload && payload.shells) ? payload.shells : [];
    if (controllerState.selectedShellId && !controllerState.terminalSessions.some((item) => item.shell_id === controllerState.selectedShellId)) {
      closeTerminalSocket();
      controllerState.selectedShellId = "";
      elements.terminalTitle.textContent = "No terminal selected";
      elements.terminalState.textContent = "No session";
      showTerminalMessage(`Select or create a terminal session on ${controllerState.terminalMachine}.`);
    }

    elements.terminalList.replaceChildren();
    if (!controllerState.terminalSessions.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = emptyMessage;
      elements.terminalList.append(empty);
      setTerminalControls(false);
      return;
    }

    for (const session of controllerState.terminalSessions) {
      const shellId = text(session.shell_id, "");
      if (!shellId) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "terminal-session";
      button.textContent = text(session.name, shellId);
      const details = [controllerState.terminalMachine, shellId, session.cwd, session.command].filter(Boolean);
      button.title = details.join(" · ");
      button.setAttribute("aria-current", shellId === controllerState.selectedShellId ? "true" : "false");
      button.addEventListener("click", () => connectTerminal(shellId));
      elements.terminalList.append(button);
    }
    setTerminalControls(controllerState.terminalSocket?.readyState === WebSocket.OPEN);
  }

  function terminalWebSocketUrl(shellId, machine) {
    const url = new URL(`${uiPath}/ws/terminals/${encodeURIComponent(shellId)}`, location.href);
    url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const size = terminalSize();
    url.searchParams.set("machine", machine);
    url.searchParams.set("lines", "1000");
    url.searchParams.set("mode", "auto");
    url.searchParams.set("cols", String(size.cols));
    url.searchParams.set("rows", String(size.rows));
    return url;
  }

  function sendTerminalResize() {
    if (document.body.dataset.activeView !== "terminals") return;
    if (!controllerState.terminalReady || !terminalSocketCurrent()) return;
    if (controllerState.terminalMode === "pty" && controllerState.terminalFitAddon && !elements.terminalXterm.hidden) {
      controllerState.terminalFitAddon.fit();
    }
    controllerState.terminalSocket.send(JSON.stringify({ type: "resize", ...terminalSize() }));
  }

  function terminalNotice(value, fallback = "Terminal session exited.") {
    return text(value, fallback)
      .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
      .slice(0, 4096);
  }

  function connectTerminal(shellId) {
    const requestedMachine = controllerState.terminalMachine;
    if (
      !shellId ||
      !terminalMachineOnline(requestedMachine) ||
      (shellId === controllerState.selectedShellId &&
        controllerState.terminalSocketMachine === requestedMachine &&
        controllerState.terminalSocket?.readyState === WebSocket.OPEN)
    ) return;
    closeTerminalSocket();
    controllerState.selectedShellId = shellId;
    const generation = controllerState.terminalGeneration;
    elements.terminalTitle.textContent = `${requestedMachine} / ${shellId}`;
    elements.terminalState.textContent = "Connecting";
    controllerState.terminalCommandHistory = [];
    controllerState.terminalHistoryIndex = 0;
    controllerState.terminalHistoryDraft = "";
    showTerminalMessage(`Connecting to ${requestedMachine}…`);
    renderTerminalList({ shells: controllerState.terminalSessions });

    const socket = new WebSocket(
      terminalWebSocketUrl(shellId, requestedMachine),
      terminalSocketProtocols(),
    );
    socket.binaryType = "arraybuffer";
    controllerState.terminalSocket = socket;
    controllerState.terminalSocketMachine = requestedMachine;
    const current = () =>
      generation === controllerState.terminalGeneration &&
      socket === controllerState.terminalSocket &&
      requestedMachine === controllerState.terminalMachine &&
      requestedMachine === controllerState.terminalSocketMachine;
    socket.addEventListener("open", () => {
      if (!current()) return;
      elements.terminalState.textContent = `Negotiating · ${requestedMachine}`;
      controllerState.terminalReady = false;
      setTerminalControls(false);
    });
    socket.addEventListener("message", (event) => {
      if (!current()) return;
      if (event.data instanceof ArrayBuffer) {
        if (controllerState.terminalMode === "pty" && controllerState.terminalXterm) {
          controllerState.terminalXterm.write(new Uint8Array(event.data));
        }
        return;
      }
      let message;
      try {
        message = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (
        message.machine !== requestedMachine ||
        message.shell_id !== shellId
      ) return;
      if (message.type === "ready") {
        const mode = message.mode === "pty" ? "pty" : "snapshot";
        if (!activateTerminalMode(mode, { reset: mode === "pty" })) {
          elements.terminalState.textContent = "xterm assets unavailable";
          socket.close(1011, "xterm assets unavailable");
          return;
        }
        controllerState.terminalReady = true;
        elements.terminalState.textContent = `Connected · ${requestedMachine} · ${mode.toUpperCase()}`;
        setTerminalControls(true);
        sendTerminalResize();
        if (document.body.dataset.activeView === "terminals") {
          if (mode === "pty") controllerState.terminalXterm?.focus();
          else elements.terminalInput.focus();
        }
      } else if (message.type === "snapshot") {
        acceptTerminalSnapshot(text(message.output, ""));
        controllerState.terminalReady = true;
        elements.terminalState.textContent = `Connected · ${requestedMachine} · SNAPSHOT`;
        setTerminalControls(true);
        if (document.body.dataset.activeView === "terminals") {
          elements.terminalInput.focus();
        }
      } else if (message.type === "exit") {
        const detail = terminalNotice(message.message);
        controllerState.terminalReady = false;
        elements.terminalState.textContent = `Exited · ${requestedMachine}`;
        if (controllerState.terminalMode === "pty" && controllerState.terminalXterm) {
          controllerState.terminalXterm.write(`\r\n\u001b[31m[${detail}]\u001b[0m\r\n`);
        } else {
          showTerminalMessage(detail);
        }
        setTerminalControls(false);
        refreshTerminalsInBackground({ force: true });
      }
    });
    socket.addEventListener("close", (event) => {
      if (!current()) return;
      controllerState.terminalSocket = null;
      controllerState.terminalSocketMachine = "";
      controllerState.terminalReady = false;
      setTerminalControls(false);
      if (event.code === 4401 || event.code === 4403) {
        showAuthentication("Authentication required", event.reason || "Terminal authorization failed.");
      } else {
        elements.terminalState.textContent = event.reason || `Disconnected · ${requestedMachine}`;
        if (event.code === 4404) refreshTerminalsInBackground({ force: true });
      }
    });
    socket.addEventListener("error", () => {
      if (current()) elements.terminalState.textContent = `Connection error · ${requestedMachine}`;
    });
  }

  function terminalQueryPath(machine = controllerState.terminalMachine) {
    const params = new URLSearchParams({ machine });
    return `/terminals?${params.toString()}`;
  }

  async function refreshTerminals({ force = false } = {}) {
    if ((controllerState.terminalLoading && !force) || !terminalMachineOnline()) return null;
    const generation = ++controllerState.terminalListGeneration;
    const requestedMachine = controllerState.terminalMachine;
    controllerState.terminalLoading = true;
    setTerminalControls(controllerState.terminalSocket?.readyState === WebSocket.OPEN);
    elements.terminalState.textContent = `Loading ${requestedMachine}`;
    try {
      const payload = await request(terminalQueryPath(requestedMachine));
      if (generation !== controllerState.terminalListGeneration || requestedMachine !== controllerState.terminalMachine) return null;
      if (payload.machine !== requestedMachine) throw new Error("Terminal machine response mismatch");
      renderTerminalList(payload);
      const connected =
        controllerState.terminalReady &&
        controllerState.terminalSocketMachine === requestedMachine &&
        controllerState.terminalSocket?.readyState === WebSocket.OPEN;
      elements.terminalState.textContent = controllerState.selectedShellId
        ? `${connected ? "Connected" : "Selected"} · ${requestedMachine}`
        : `${controllerState.terminalSessions.length} session(s) · ${requestedMachine}`;
      return payload;
    } catch (error) {
      if (error.authenticationRequired) throw error;
      if (generation !== controllerState.terminalListGeneration || requestedMachine !== controllerState.terminalMachine) return null;
      controllerState.terminalSessions = [];
      renderTerminalList(
        { shells: [] },
        { emptyMessage: `Terminals unavailable on ${requestedMachine}.` },
      );
      elements.terminalState.textContent = error instanceof Error ? error.message : String(error);
      return null;
    } finally {
      if (generation === controllerState.terminalListGeneration) {
        controllerState.terminalLoading = false;
        setTerminalControls(controllerState.terminalSocket?.readyState === WebSocket.OPEN);
      }
    }
  }

  function refreshTerminalsInBackground(options = {}) {
    void refreshTerminals(options).catch((error) => {
      if (error.authenticationRequired) onAuthenticationRequired();
    });
  }

  async function terminalAction(action, body) {
    return request(`/terminals/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ machine: controllerState.terminalMachine, ...body }),
    });
  }


  function bind() {
  elements.terminalStartForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = elements.terminalStartForm.querySelector("button");
    button.disabled = true;
    try {
      const requestedMachine = controllerState.terminalMachine;
      const name = elements.terminalName.value.trim();
      const result = await terminalAction("start", { cwd: ".", name: name || null });
      if (requestedMachine !== controllerState.terminalMachine || result.machine !== requestedMachine) return;
      elements.terminalName.value = "";
      await refreshTerminals({ force: true });
      if (requestedMachine === controllerState.terminalMachine) connectTerminal(result.shell_id);
    } catch (error) {
      elements.terminalState.textContent = "Unable to start terminal";
      showTerminalMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setTerminalControls(controllerState.terminalSocket?.readyState === WebSocket.OPEN);
    }
  });

  elements.terminalInputForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = elements.terminalInput.value;
    if (!sendTerminalData(value, true)) return;
    rememberTerminalCommand(value);
    elements.terminalInput.value = "";
  });

  elements.terminalInput.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.key === "ArrowUp") {
      event.preventDefault();
      navigateTerminalHistory(-1);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      navigateTerminalHistory(1);
    }
  });

  elements.terminalInput.addEventListener("input", () => {
    if (controllerState.terminalHistoryIndex !== controllerState.terminalCommandHistory.length) {
      controllerState.terminalHistoryIndex = controllerState.terminalCommandHistory.length;
      controllerState.terminalHistoryDraft = elements.terminalInput.value;
    }
  });

  elements.terminalLatest.addEventListener("click", jumpToLatestTerminalOutput);
  elements.terminalOutput.addEventListener("scroll", () => {
    if (terminalAtBottom()) {
      if (controllerState.terminalPendingOutput !== null) jumpToLatestTerminalOutput();
      else controllerState.terminalFollowOutput = true;
    } else {
      controllerState.terminalFollowOutput = false;
    }
  });

  for (const button of elements.terminalKeyButtons) {
    button.addEventListener("click", () => {
      const data = terminalSpecialKeys[button.dataset.terminalKey || ""];
      if (data && sendTerminalData(data, false)) {
        if (controllerState.terminalMode === "pty") controllerState.terminalXterm?.focus();
        else elements.terminalInput.focus();
      }
    });
  }

  elements.terminalKill.addEventListener("click", async () => {
    if (!controllerState.selectedShellId) return;
    const shellId = controllerState.selectedShellId;
    elements.terminalKill.disabled = true;
    try {
      await terminalAction("kill", { shell_id: shellId });
      closeTerminalSocket();
      controllerState.selectedShellId = "";
      elements.terminalTitle.textContent = "No terminal selected";
      elements.terminalState.textContent = "No session";
      showTerminalMessage(`Terminal ${controllerState.terminalMachine} / ${shellId} was terminated.`);
      await refreshTerminals({ force: true });
    } catch (error) {
      elements.terminalState.textContent = "Unable to kill terminal";
      showTerminalMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setTerminalControls(controllerState.terminalSocket?.readyState === WebSocket.OPEN);
    }
  });

  elements.terminalMachine.addEventListener("change", () => {
    if (controllerState.terminalLoading) return;
    resetTerminalWorkspace(elements.terminalMachine.value || "local");
    refreshTerminalsInBackground({ force: true });
  });

  }

  function ping() {
    if (
      controllerState.terminalSocket?.readyState === WebSocket.OPEN &&
      controllerState.terminalSocketMachine === controllerState.terminalMachine
    ) {
      controllerState.terminalSocket.send(JSON.stringify({ type: "ping" }));
    }
  }

  return {
    bind,
    close: closeTerminalSocket,
    ping,
    refresh: refreshTerminals,
    renderMachines: renderTerminalMachines,
    reset: resetTerminalWorkspace,
    resize: sendTerminalResize,
    showMessage: showTerminalMessage,
  };
}
