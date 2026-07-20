(() => {
  "use strict";

  const config = JSON.parse(document.body.dataset.lsmConfig || "{}");
  const uiPath = String(config.uiPath || "/ui").replace(/\/$/, "");
  const apiPrefix = String(config.apiPrefix || "/api/ui").replace(/\/$/, "");
  const oauth = config.oauth && typeof config.oauth === "object" ? config.oauth : null;
  const tokenStorageKey = "local-shell-mcp-ui-access-token";
  const pendingStorageKey = "local-shell-mcp-ui-oauth-pending";
  const pendingMaxAgeMs = 10 * 60 * 1000;
  const encoder = new TextEncoder();
  let accessToken = sessionStorage.getItem(tokenStorageKey) || "";
  let terminalSocket = null;
  let selectedShellId = "";
  let terminalSessions = [];
  let terminalGeneration = 0;

  const elements = {
    authDetail: document.getElementById("auth-detail"),
    authForm: document.getElementById("auth-form"),
    authMode: document.getElementById("auth-mode"),
    authPanel: document.getElementById("auth-panel"),
    connectionState: document.getElementById("connection-state"),
    lastUpdated: document.getElementById("last-updated"),
    machineList: document.getElementById("machine-list"),
    machineOnline: document.getElementById("machine-online"),
    machineTotal: document.getElementById("machine-total"),
    oauthLogin: document.getElementById("oauth-login"),
    refresh: document.getElementById("refresh"),
    signOut: document.getElementById("sign-out"),
    terminalInput: document.getElementById("terminal-input"),
    terminalInputForm: document.getElementById("terminal-input-form"),
    terminalKill: document.getElementById("terminal-kill"),
    terminalList: document.getElementById("terminal-list"),
    terminalName: document.getElementById("terminal-name"),
    terminalOutput: document.getElementById("terminal-output"),
    terminalStartForm: document.getElementById("terminal-start-form"),
    terminalState: document.getElementById("terminal-state"),
    terminalTitle: document.getElementById("terminal-title"),
    tokenInput: document.getElementById("access-token"),
    version: document.getElementById("version"),
  };

  function text(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
  }

  function setConnection(label, state) {
    elements.connectionState.textContent = label;
    elements.connectionState.className = `status status-${state}`;
  }

  function clearAccessToken() {
    accessToken = "";
    sessionStorage.removeItem(tokenStorageKey);
  }

  function oauthAvailable() {
    return config.authMode === "oauth" && oauth !== null;
  }

  function showAuthentication(message, detail) {
    elements.authPanel.hidden = false;
    elements.oauthLogin.hidden = !oauthAvailable();
    elements.oauthLogin.disabled = false;
    elements.signOut.hidden = true;
    elements.tokenInput.setAttribute("aria-invalid", "true");
    elements.authDetail.textContent = detail || "Sign in through the local-shell-mcp OAuth approval page.";
    setConnection(message || "Authentication required", "error");
  }

  function hideAuthentication() {
    elements.authPanel.hidden = true;
    elements.tokenInput.removeAttribute("aria-invalid");
    elements.signOut.hidden = config.authMode !== "oauth" || !accessToken;
  }

  async function responsePayload(response) {
    try {
      return await response.json();
    } catch {
      return {};
    }
  }

  async function request(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const response = await fetch(`${apiPrefix}${path}`, {
      ...options,
      headers,
      cache: "no-store",
      credentials: "same-origin",
    });
    if (response.status === 401 || response.status === 403) {
      const error = new Error("Authentication required");
      error.authenticationRequired = true;
      throw error;
    }
    const payload = await responsePayload(response);
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || `Request failed (${response.status})`);
    }
    return payload.data;
  }

  function base64Url(bytes) {
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function randomVerifier() {
    if (!globalThis.crypto || typeof globalThis.crypto.getRandomValues !== "function") {
      throw new Error("Secure browser randomness is unavailable. Use HTTPS or localhost.");
    }
    return base64Url(globalThis.crypto.getRandomValues(new Uint8Array(48)));
  }

  async function sha256(value) {
    if (!globalThis.crypto || !globalThis.crypto.subtle) {
      throw new Error("Web Crypto is unavailable. Use HTTPS or localhost for OAuth sign-in.");
    }
    const digest = await globalThis.crypto.subtle.digest("SHA-256", encoder.encode(value));
    return base64Url(new Uint8Array(digest));
  }

  function oauthEndpoint(name) {
    const value = oauth && oauth[name];
    if (typeof value !== "string" || !value) {
      throw new Error(`OAuth configuration is missing ${name}.`);
    }
    return new URL(value, location.origin);
  }

  function callbackUrl() {
    return new URL(`${uiPath}/callback`, location.origin).href;
  }

  function normalizeIssuer(value) {
    return String(value || "").replace(/\/+$/, "");
  }

  function cleanCallbackUrl() {
    history.replaceState({}, "", uiPath);
  }

  function parsePendingOAuth() {
    const raw = sessionStorage.getItem(pendingStorageKey);
    if (!raw) throw new Error("The OAuth request state is missing. Start authentication again.");
    let pending;
    try {
      pending = JSON.parse(raw);
    } catch {
      sessionStorage.removeItem(pendingStorageKey);
      throw new Error("The saved OAuth request state is invalid. Start authentication again.");
    }
    const valid =
      pending &&
      typeof pending.clientId === "string" &&
      pending.clientId.length > 0 &&
      typeof pending.verifier === "string" &&
      pending.verifier.length >= 43 &&
      pending.verifier.length <= 128 &&
      typeof pending.state === "string" &&
      pending.state.length >= 32 &&
      typeof pending.redirectUri === "string" &&
      pending.redirectUri === callbackUrl() &&
      typeof pending.createdAt === "number" &&
      Number.isFinite(pending.createdAt);
    if (!valid) {
      sessionStorage.removeItem(pendingStorageKey);
      throw new Error("The saved OAuth request state is incomplete. Start authentication again.");
    }
    const ageMs = Date.now() - pending.createdAt;
    if (ageMs < -60000 || ageMs > pendingMaxAgeMs) {
      sessionStorage.removeItem(pendingStorageKey);
      throw new Error("The OAuth request expired. Start authentication again.");
    }
    return pending;
  }

  async function startOAuth() {
    if (!oauthAvailable()) {
      showAuthentication(
        "OAuth unavailable",
        "This server did not advertise a browser OAuth configuration. Use an existing access token instead.",
      );
      return;
    }
    elements.oauthLogin.disabled = true;
    elements.authDetail.textContent = "Preparing a secure OAuth authorization request…";
    try {
      const redirectUri = callbackUrl();
      const registration = await fetch(oauthEndpoint("registrationEndpoint"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          client_name: "local-shell-mcp WebUI",
          redirect_uris: [redirectUri],
        }),
        cache: "no-store",
        credentials: "same-origin",
      });
      const registered = await responsePayload(registration);
      if (!registration.ok || typeof registered.client_id !== "string") {
        throw new Error(
          registered.error_description || registered.error || `Client registration failed (${registration.status})`,
        );
      }

      const verifier = randomVerifier();
      const state = randomVerifier();
      const challenge = await sha256(verifier);
      sessionStorage.setItem(
        pendingStorageKey,
        JSON.stringify({
          clientId: registered.client_id,
          verifier,
          state,
          redirectUri,
          createdAt: Date.now(),
        }),
      );

      const authorize = oauthEndpoint("authorizationEndpoint");
      authorize.searchParams.set("response_type", "code");
      authorize.searchParams.set("client_id", registered.client_id);
      authorize.searchParams.set("redirect_uri", redirectUri);
      authorize.searchParams.set("scope", String(oauth.scope || ""));
      authorize.searchParams.set("resource", String(oauth.resource || ""));
      authorize.searchParams.set("code_challenge", challenge);
      authorize.searchParams.set("code_challenge_method", "S256");
      authorize.searchParams.set("state", state);
      location.assign(authorize);
    } catch (error) {
      sessionStorage.removeItem(pendingStorageKey);
      elements.oauthLogin.disabled = false;
      elements.authDetail.textContent = error instanceof Error ? error.message : String(error);
    }
  }

  async function finishOAuthCallback() {
    const url = new URL(location.href);
    const callbackError = url.searchParams.get("error");
    if (callbackError) {
      sessionStorage.removeItem(pendingStorageKey);
      cleanCallbackUrl();
      throw new Error(url.searchParams.get("error_description") || callbackError);
    }

    const code = url.searchParams.get("code");
    if (!code) return false;
    if (!oauthAvailable()) {
      cleanCallbackUrl();
      throw new Error("OAuth callback received while browser OAuth is unavailable.");
    }
    let pending;
    try {
      pending = parsePendingOAuth();
    } catch (error) {
      cleanCallbackUrl();
      throw error;
    }
    if (url.searchParams.get("state") !== pending.state) {
      sessionStorage.removeItem(pendingStorageKey);
      cleanCallbackUrl();
      throw new Error("OAuth state verification failed.");
    }

    const expectedIssuer = normalizeIssuer(oauth && oauth.issuer);
    const responseIssuer = normalizeIssuer(url.searchParams.get("iss"));
    if (!expectedIssuer || responseIssuer !== expectedIssuer) {
      sessionStorage.removeItem(pendingStorageKey);
      cleanCallbackUrl();
      throw new Error("OAuth issuer verification failed.");
    }

    const form = new URLSearchParams({
      grant_type: "authorization_code",
      code,
      client_id: pending.clientId,
      redirect_uri: pending.redirectUri,
      resource: String(oauth.resource || ""),
      code_verifier: pending.verifier,
    });
    const response = await fetch(oauthEndpoint("tokenEndpoint"), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: form,
      cache: "no-store",
      credentials: "same-origin",
    });
    const result = await responsePayload(response);
    if (!response.ok || typeof result.access_token !== "string" || !result.access_token) {
      throw new Error(result.error_description || result.error || "OAuth token exchange failed.");
    }

    accessToken = result.access_token;
    sessionStorage.setItem(tokenStorageKey, accessToken);
    sessionStorage.removeItem(pendingStorageKey);
    cleanCallbackUrl();
    return true;
  }

  function machineCard(machine) {
    const article = document.createElement("article");
    article.className = "machine";

    const header = document.createElement("div");
    header.className = "machine-header";

    const name = document.createElement("span");
    name.className = "machine-name";
    name.textContent = text(machine.name, "unnamed");

    const status = document.createElement("span");
    const state = machine.status === "online" ? "online" : "offline";
    status.className = `status status-${state}`;
    status.textContent = text(machine.status, "unknown");
    header.append(name, status);

    const workdir = document.createElement("p");
    workdir.className = "machine-detail";
    workdir.textContent = text(machine.workdir, "No workdir reported");

    const meta = document.createElement("div");
    meta.className = "machine-meta";
    const queue = document.createElement("span");
    queue.textContent = `queue ${text(machine.queue_depth, "0")}`;
    const capabilities = document.createElement("span");
    const values = Array.isArray(machine.capabilities) ? machine.capabilities : [];
    capabilities.textContent = values.length ? values.join(" · ") : "capabilities unavailable";
    meta.append(queue, capabilities);

    article.append(header, workdir, meta);
    return article;
  }
  function terminalSocketProtocols() {
    const protocols = ["lsm-ui-terminal"];
    if (accessToken) protocols.push(`bearer.${base64Url(encoder.encode(accessToken))}`);
    return protocols;
  }

  function terminalSize() {
    const bounds = elements.terminalOutput.getBoundingClientRect();
    const cols = Math.max(20, Math.min(300, Math.floor(bounds.width / 8.2)));
    const rows = Math.max(3, Math.min(120, Math.floor(bounds.height / 19)));
    return { cols, rows };
  }

  function setTerminalControls(enabled) {
    elements.terminalInput.disabled = !enabled;
    elements.terminalInputForm.querySelector("button").disabled = !enabled;
    elements.terminalKill.disabled = !selectedShellId;
  }

  function closeTerminalSocket() {
    terminalGeneration += 1;
    const socket = terminalSocket;
    terminalSocket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, "Client changed terminal");
    elements.terminalState.textContent = selectedShellId ? "Disconnected" : "No session";
    setTerminalControls(false);
  }

  function renderTerminalList(payload) {
    terminalSessions = Array.isArray(payload && payload.shells) ? payload.shells : [];
    if (selectedShellId && !terminalSessions.some((item) => item.shell_id === selectedShellId)) {
      closeTerminalSocket();
      selectedShellId = "";
      elements.terminalTitle.textContent = "No terminal selected";
      elements.terminalState.textContent = "No session";
      elements.terminalOutput.textContent = "Select or create a terminal session.";
    }

    elements.terminalList.replaceChildren();
    if (!terminalSessions.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No persistent terminals are running.";
      elements.terminalList.append(empty);
      setTerminalControls(false);
      return;
    }

    for (const session of terminalSessions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "terminal-session";
      button.textContent = text(session.shell_id, "unnamed");
      button.title = text(session.shell_id, "unnamed");
      button.setAttribute("aria-current", session.shell_id === selectedShellId ? "true" : "false");
      button.addEventListener("click", () => connectTerminal(session.shell_id));
      elements.terminalList.append(button);
    }
    elements.terminalKill.disabled = !selectedShellId;
  }

  function terminalWebSocketUrl(shellId) {
    const url = new URL(`${uiPath}/ws/terminals/${encodeURIComponent(shellId)}`, location.href);
    url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("lines", "1000");
    return url;
  }

  function sendTerminalResize() {
    if (!terminalSocket || terminalSocket.readyState !== WebSocket.OPEN) return;
    terminalSocket.send(JSON.stringify({ type: "resize", ...terminalSize() }));
  }

  function connectTerminal(shellId) {
    if (!shellId || (shellId === selectedShellId && terminalSocket?.readyState === WebSocket.OPEN)) return;
    closeTerminalSocket();
    selectedShellId = shellId;
    const generation = terminalGeneration;
    elements.terminalTitle.textContent = shellId;
    elements.terminalState.textContent = "Connecting";
    elements.terminalOutput.textContent = "Connecting to terminal…";
    renderTerminalList({ shells: terminalSessions });

    const socket = new WebSocket(terminalWebSocketUrl(shellId), terminalSocketProtocols());
    terminalSocket = socket;
    socket.addEventListener("open", () => {
      if (generation !== terminalGeneration || socket !== terminalSocket) return;
      elements.terminalState.textContent = "Connected";
      setTerminalControls(true);
      sendTerminalResize();
      elements.terminalInput.focus();
    });
    socket.addEventListener("message", (event) => {
      if (generation !== terminalGeneration || socket !== terminalSocket) return;
      let message;
      try {
        message = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (message.type === "snapshot") {
        const pinned = elements.terminalOutput.scrollTop + elements.terminalOutput.clientHeight >= elements.terminalOutput.scrollHeight - 24;
        elements.terminalOutput.textContent = text(message.output, "");
        if (pinned) elements.terminalOutput.scrollTop = elements.terminalOutput.scrollHeight;
      } else if (message.type === "exit") {
        elements.terminalState.textContent = "Exited";
        elements.terminalOutput.textContent = text(message.message, "Terminal session exited.");
        setTerminalControls(false);
        void refreshTerminals();
      }
    });
    socket.addEventListener("close", (event) => {
      if (generation !== terminalGeneration || socket !== terminalSocket) return;
      terminalSocket = null;
      setTerminalControls(false);
      if (event.code === 4401 || event.code === 4403) {
        clearAccessToken();
        showAuthentication("Authentication required", event.reason || "Terminal authorization failed.");
      } else {
        elements.terminalState.textContent = event.reason || "Disconnected";
      }
    });
    socket.addEventListener("error", () => {
      if (generation === terminalGeneration && socket === terminalSocket) {
        elements.terminalState.textContent = "Connection error";
      }
    });
  }

  async function refreshTerminals() {
    const payload = await request("/terminals");
    renderTerminalList(payload);
    return payload;
  }

  async function terminalAction(action, body) {
    return request(`/terminals/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }


  function render(data) {
    const counts = data.counts || {};
    const machines = Array.isArray(data.machines) ? data.machines : [];
    elements.version.textContent = text(data.version && data.version.version);
    elements.machineTotal.textContent = text(counts.total, machines.length);
    elements.machineOnline.textContent = text(counts.online, "0");
    elements.authMode.textContent = text(data.ui && data.ui.auth_mode, config.authMode);
    elements.lastUpdated.textContent = `Updated ${new Date().toLocaleTimeString()}`;

    elements.machineList.replaceChildren();
    if (!machines.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No machines are registered.";
      elements.machineList.append(empty);
    } else {
      for (const machine of machines) elements.machineList.append(machineCard(machine));
    }
    hideAuthentication();
    setConnection("Connected", "online");
  }

  async function load() {
    setConnection("Connecting", "idle");
    elements.refresh.disabled = true;
    try {
      render(await request("/bootstrap"));
      try {
        await refreshTerminals();
      } catch (error) {
        if (error.authenticationRequired) throw error;
        elements.terminalState.textContent = "Terminal list unavailable";
        elements.terminalOutput.textContent = error instanceof Error ? error.message : String(error);
      }
    } catch (error) {
      if (error.authenticationRequired) {
        closeTerminalSocket();
        clearAccessToken();
        showAuthentication("Authentication required");
      } else {
        setConnection("Unavailable", "error");
        elements.lastUpdated.textContent = error instanceof Error ? error.message : String(error);
      }
    } finally {
      elements.refresh.disabled = false;
    }
  }

  async function boot() {
    try {
      await finishOAuthCallback();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (accessToken) {
        await load();
        if (elements.authPanel.hidden) {
          elements.lastUpdated.textContent = `OAuth callback ignored: ${message}`;
        }
      } else {
        showAuthentication("Unable to sign in", message);
      }
      return;
    }
    await load();
  }

  elements.authForm.addEventListener("submit", (event) => {
    event.preventDefault();
    closeTerminalSocket();
    accessToken = elements.tokenInput.value.trim();
    if (accessToken) sessionStorage.setItem(tokenStorageKey, accessToken);
    else sessionStorage.removeItem(tokenStorageKey);
    void load();
  });

  elements.terminalStartForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = elements.terminalStartForm.querySelector("button");
    button.disabled = true;
    try {
      const name = elements.terminalName.value.trim();
      const result = await terminalAction("start", { cwd: ".", name: name || null });
      elements.terminalName.value = "";
      await refreshTerminals();
      connectTerminal(result.shell_id);
    } catch (error) {
      elements.terminalState.textContent = "Unable to start terminal";
      elements.terminalOutput.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      button.disabled = false;
    }
  });

  elements.terminalInputForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = elements.terminalInput.value;
    if (!value || !terminalSocket || terminalSocket.readyState !== WebSocket.OPEN) return;
    terminalSocket.send(JSON.stringify({ type: "input", data: value, enter: true }));
    elements.terminalInput.value = "";
  });

  elements.terminalKill.addEventListener("click", async () => {
    if (!selectedShellId) return;
    const shellId = selectedShellId;
    elements.terminalKill.disabled = true;
    try {
      await terminalAction("kill", { shell_id: shellId });
      closeTerminalSocket();
      selectedShellId = "";
      elements.terminalTitle.textContent = "No terminal selected";
      elements.terminalState.textContent = "No session";
      elements.terminalOutput.textContent = `Terminal ${shellId} was terminated.`;
      await refreshTerminals();
    } catch (error) {
      elements.terminalState.textContent = "Unable to kill terminal";
      elements.terminalOutput.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      elements.terminalKill.disabled = !selectedShellId;
    }
  });

  elements.oauthLogin.addEventListener("click", () => void startOAuth());
  elements.refresh.addEventListener("click", () => void load());
  elements.signOut.addEventListener("click", () => {
    closeTerminalSocket();
    clearAccessToken();
    sessionStorage.removeItem(pendingStorageKey);
    elements.tokenInput.value = "";
    showAuthentication("Signed out", "The browser token was removed from this tab.");
  });

  window.addEventListener("resize", () => window.requestAnimationFrame(sendTerminalResize));
  window.addEventListener("beforeunload", closeTerminalSocket);
  elements.oauthLogin.hidden = !oauthAvailable();
  elements.authMode.textContent = text(config.authMode);
  void boot();
  window.setInterval(() => {
    if (terminalSocket?.readyState === WebSocket.OPEN) {
      terminalSocket.send(JSON.stringify({ type: "ping" }));
    }
    if (config.authMode !== "oauth" || accessToken) void load();
  }, 30000);
})();
