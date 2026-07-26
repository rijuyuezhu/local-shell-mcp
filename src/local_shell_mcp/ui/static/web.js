(() => {
  "use strict";

  const config = JSON.parse(document.body.dataset.lsmConfig || "{}");
  const uiPath = String(config.uiPath || "/ui").replace(/\/$/, "");
  const apiPrefix = String(config.apiPrefix || "/api/ui").replace(/\/$/, "");
  const oauth = config.oauth && typeof config.oauth === "object" ? config.oauth : null;
  const wallpaper = ["aurora", "grid", "none"].includes(String(config.wallpaper || ""))
    ? String(config.wallpaper)
    : "aurora";
  document.body.dataset.wallpaper = wallpaper;
  const tokenStorageKey = "local-shell-mcp-ui-access-token";
  const pendingStorageKey = "local-shell-mcp-ui-oauth-pending";
  const pendingMaxAgeMs = 10 * 60 * 1000;
  const encoder = new TextEncoder();
  let accessToken = sessionStorage.getItem(tokenStorageKey) || "";
  let terminalSocket = null;
  let terminalSocketMachine = "";
  let terminalMachine = "local";
  let terminalMode = "snapshot";
  let terminalReady = false;
  let terminalXterm = null;
  let terminalFitAddon = null;
  let terminalXtermData = null;
  let terminalXtermBinary = null;
  let selectedShellId = "";
  let terminalSessions = [];
  let terminalGeneration = 0;
  let terminalListGeneration = 0;
  let terminalLoading = false;
  let terminalMachineStates = new Map([["local", "online"]]);
  let terminalFollowOutput = true;
  let terminalPendingOutput = null;
  let terminalPendingUpdates = 0;
  let terminalLastOutput = "";
  let terminalCommandHistory = [];
  let terminalHistoryIndex = 0;
  let terminalHistoryDraft = "";
  let fileMachine = "local";
  let filePath = ".";
  let fileParentPath = ".";
  let fileEntries = [];
  let selectedFilePath = "";
  let fileListGeneration = 0;
  let filePreviewGeneration = 0;
  let fileEditorPath = "";
  let fileMutationBusy = false;
  let fileMutations = {
    write: true,
    delete: true,
    copy: true,
    move: true,
    rename: true,
  };
  let todoMachine = "local";
  let todoSessionId = "";
  let todoSessions = [];
  let sessionIncludeInactive = false;
  let sessionLoading = false;
  let sessionTerminating = false;
  let todoItems = [];
  let todoRevision = 0;
  let todoGeneration = 0;
  let todoMutationBusy = false;
  let todoDirty = false;
  let todoSequence = 0;
  let todoMachineStates = new Map([["local", "online"]]);
  let todoLimits = {
    todos: 1000,
    bytes: 1000000,
    id_bytes: 256,
    content_bytes: 16384,
    label_bytes: 64,
  };
  let sessionAuditEntries = [];
  let sessionAuditSelectedId = "";
  let sessionAuditGeneration = 0;
  let sessionAuditDetailGeneration = 0;
  let sessionAuditLoading = false;
  let auditMachine = "local";
  let auditEntries = [];
  let auditSelectedId = "";
  let auditGeneration = 0;
  let auditDetailGeneration = 0;
  let auditLoading = false;
  let auditMachineStates = new Map([["local", "online"]]);
  let dashboardMachine = "local";
  let dashboardGeneration = 0;
  let dashboardLoading = false;
  let dashboardMachineStates = new Map([["local", "online"]]);
  let dashboardHistory = [];
  let dashboardTimer = null;
  let remoteMachines = [];
  let remoteSelectedName = "";
  let remoteEnabled = false;
  let remoteGeneration = 0;
  let remoteLoading = false;
  let remoteTimer = null;
  let remoteInviteCommand = "";

  const elements = {
    dashboardActivity: document.getElementById("dashboard-activity"),
    dashboardAlertCount: document.getElementById("dashboard-alert-count"),
    dashboardAlerts: document.getElementById("dashboard-alerts"),
    dashboardAuditDetail: document.getElementById("dashboard-audit-detail"),
    dashboardAuditTotal: document.getElementById("dashboard-audit-total"),
    dashboardCpu: document.getElementById("dashboard-cpu"),
    dashboardCpuBar: document.getElementById("dashboard-cpu-bar"),
    dashboardCpuCount: document.getElementById("dashboard-cpu-count"),
    dashboardCpuTrend: document.getElementById("dashboard-cpu-trend"),
    dashboardCpuValue: document.getElementById("dashboard-cpu-value"),
    dashboardDisk: document.getElementById("dashboard-disk"),
    dashboardDiskBar: document.getElementById("dashboard-disk-bar"),
    dashboardDiskTrend: document.getElementById("dashboard-disk-trend"),
    dashboardDiskUsed: document.getElementById("dashboard-disk-used"),
    dashboardDiskValue: document.getElementById("dashboard-disk-value"),
    dashboardGenerated: document.getElementById("dashboard-generated"),
    dashboardHealth: document.getElementById("dashboard-health"),
    dashboardHealthCard: document.getElementById("dashboard-health-card"),
    dashboardHealthDetail: document.getElementById("dashboard-health-detail"),
    dashboardLoad: document.getElementById("dashboard-load"),
    dashboardMachine: document.getElementById("dashboard-machine"),
    dashboardMemory: document.getElementById("dashboard-memory"),
    dashboardMemoryBar: document.getElementById("dashboard-memory-bar"),
    dashboardMemoryTrend: document.getElementById("dashboard-memory-trend"),
    dashboardMemoryUsed: document.getElementById("dashboard-memory-used"),
    dashboardMemoryValue: document.getElementById("dashboard-memory-value"),
    dashboardNetwork: document.getElementById("dashboard-network"),
    dashboardNetworkRx: document.getElementById("dashboard-network-rx"),
    dashboardNetworkTrend: document.getElementById("dashboard-network-trend"),
    dashboardNetworkTx: document.getElementById("dashboard-network-tx"),
    dashboardPlatform: document.getElementById("dashboard-platform"),
    dashboardPython: document.getElementById("dashboard-python"),
    dashboardRefresh: document.getElementById("dashboard-refresh"),
    dashboardSourceState: document.getElementById("dashboard-source-state"),
    dashboardState: document.getElementById("dashboard-state"),
    dashboardUptime: document.getElementById("dashboard-uptime"),
    dashboardVersion: document.getElementById("dashboard-version"),
    auditDetailBody: document.getElementById("audit-detail-body"),
    auditDetailMeta: document.getElementById("audit-detail-meta"),
    auditDetailTitle: document.getElementById("audit-detail-title"),
    auditEvent: document.getElementById("audit-event"),
    auditFilterForm: document.getElementById("audit-filter-form"),
    auditLimit: document.getElementById("audit-limit"),
    auditList: document.getElementById("audit-list"),
    auditMachine: document.getElementById("audit-machine"),
    auditOperation: document.getElementById("audit-operation"),
    auditRefresh: document.getElementById("audit-refresh"),
    auditSearch: document.getElementById("audit-search"),
    auditSort: document.getElementById("audit-sort"),
    auditState: document.getElementById("audit-state"),
    auditSummary: document.getElementById("audit-summary"),
    authDetail: document.getElementById("auth-detail"),
    authForm: document.getElementById("auth-form"),
    authMode: document.getElementById("auth-mode"),
    authPanel: document.getElementById("auth-panel"),
    connectionState: document.getElementById("connection-state"),
    fileCopy: document.getElementById("file-copy"),
    fileDelete: document.getElementById("file-delete"),
    fileEdit: document.getElementById("file-edit"),
    fileEditor: document.getElementById("file-editor"),
    fileEditorCancel: document.getElementById("file-editor-cancel"),
    fileEditorForm: document.getElementById("file-editor-form"),
    fileList: document.getElementById("file-list"),
    fileMachine: document.getElementById("file-machine"),
    fileMove: document.getElementById("file-move"),
    fileNew: document.getElementById("file-new"),
    fileOpen: document.getElementById("file-open"),
    filePath: document.getElementById("file-path"),
    filePathForm: document.getElementById("file-path-form"),
    filePreviewBody: document.getElementById("file-preview-body"),
    filePreviewMeta: document.getElementById("file-preview-meta"),
    filePreviewTitle: document.getElementById("file-preview-title"),
    fileRefresh: document.getElementById("file-refresh"),
    fileRename: document.getElementById("file-rename"),
    fileShowHidden: document.getElementById("file-show-hidden"),
    fileState: document.getElementById("file-state"),
    fileUp: document.getElementById("file-up"),
    lastUpdated: document.getElementById("last-updated"),
    machineList: document.getElementById("machine-list"),
    machineOnline: document.getElementById("machine-online"),
    machineTotal: document.getElementById("machine-total"),
    oauthLogin: document.getElementById("oauth-login"),
    remoteController: document.getElementById("remote-controller"),
    remoteDetailCapabilities: document.getElementById("remote-detail-capabilities"),
    remoteDetailHostname: document.getElementById("remote-detail-hostname"),
    remoteDetailLastSeen: document.getElementById("remote-detail-last-seen"),
    remoteDetailName: document.getElementById("remote-detail-name"),
    remoteDetailPlatform: document.getElementById("remote-detail-platform"),
    remoteDetailPython: document.getElementById("remote-detail-python"),
    remoteDetailQueue: document.getElementById("remote-detail-queue"),
    remoteDetailStatus: document.getElementById("remote-detail-status"),
    remoteDetailUser: document.getElementById("remote-detail-user"),
    remoteDetailVersion: document.getElementById("remote-detail-version"),
    remoteDetailWorkdir: document.getElementById("remote-detail-workdir"),
    remoteInviteCommand: document.getElementById("remote-invite-command"),
    remoteInviteCopy: document.getElementById("remote-invite-copy"),
    remoteInviteDialog: document.getElementById("remote-invite-dialog"),
    remoteInviteDone: document.getElementById("remote-invite-done"),
    remoteInviteExpiry: document.getElementById("remote-invite-expiry"),
    remoteInviteForm: document.getElementById("remote-invite-form"),
    remoteInviteName: document.getElementById("remote-invite-name"),
    remoteInviteOpen: document.getElementById("remote-invite-open"),
    remoteInviteResultClose: document.getElementById("remote-invite-result-close"),
    remoteInviteResultDialog: document.getElementById("remote-invite-result-dialog"),
    remoteInviteTtl: document.getElementById("remote-invite-ttl"),
    remoteInviteWorkdir: document.getElementById("remote-invite-workdir"),
    remoteList: document.getElementById("remote-list"),
    remoteOffline: document.getElementById("remote-offline"),
    remoteOnline: document.getElementById("remote-online"),
    remoteRefresh: document.getElementById("remote-refresh"),
    remoteRenameDialog: document.getElementById("remote-rename-dialog"),
    remoteRenameForm: document.getElementById("remote-rename-form"),
    remoteRenameName: document.getElementById("remote-rename-name"),
    remoteRenameOpen: document.getElementById("remote-rename-open"),
    remoteRevokeDialog: document.getElementById("remote-revoke-dialog"),
    remoteRevokeForm: document.getElementById("remote-revoke-form"),
    remoteRevokeName: document.getElementById("remote-revoke-name"),
    remoteRevokeOpen: document.getElementById("remote-revoke-open"),
    remoteState: document.getElementById("remote-state"),
    remoteTotal: document.getElementById("remote-total"),
    refresh: document.getElementById("refresh"),
    signOut: document.getElementById("sign-out"),
    terminalInput: document.getElementById("terminal-input"),
    terminalInputForm: document.getElementById("terminal-input-form"),
    terminalKeyButtons: Array.from(document.querySelectorAll("[data-terminal-key]")),
    terminalKill: document.getElementById("terminal-kill"),
    terminalLatest: document.getElementById("terminal-latest"),
    terminalList: document.getElementById("terminal-list"),
    terminalMachine: document.getElementById("terminal-machine"),
    terminalName: document.getElementById("terminal-name"),
    terminalOutput: document.getElementById("terminal-output"),
    terminalPendingCount: document.getElementById("terminal-pending-count"),
    terminalXterm: document.getElementById("terminal-xterm"),
    terminalStartForm: document.getElementById("terminal-start-form"),
    terminalState: document.getElementById("terminal-state"),
    terminalTitle: document.getElementById("terminal-title"),
    sessionAuditDetailBody: document.getElementById("session-audit-detail-body"),
    sessionAuditDetailMeta: document.getElementById("session-audit-detail-meta"),
    sessionAuditDetailTitle: document.getElementById("session-audit-detail-title"),
    sessionAuditFilterForm: document.getElementById("session-audit-filter-form"),
    sessionAuditLimit: document.getElementById("session-audit-limit"),
    sessionAuditList: document.getElementById("session-audit-list"),
    sessionAuditOperation: document.getElementById("session-audit-operation"),
    sessionAuditRefresh: document.getElementById("session-audit-refresh"),
    sessionAuditSearch: document.getElementById("session-audit-search"),
    sessionAuditSort: document.getElementById("session-audit-sort"),
    sessionAuditState: document.getElementById("session-audit-state"),
    sessionAuditSummary: document.getElementById("session-audit-summary"),
    sessionDetailCreated: document.getElementById("session-detail-created"),
    sessionDetailId: document.getElementById("session-detail-id"),
    sessionDetailMachine: document.getElementById("session-detail-machine"),
    sessionDetailStatus: document.getElementById("session-detail-status"),
    sessionDetailTarget: document.getElementById("session-detail-target"),
    sessionDetailTitle: document.getElementById("session-detail-title"),
    sessionDetailUpdated: document.getElementById("session-detail-updated"),
    sessionDetailWorkdir: document.getElementById("session-detail-workdir"),
    sessionIncludeInactive: document.getElementById("session-include-inactive"),
    sessionList: document.getElementById("session-list"),
    sessionMachine: document.getElementById("session-machine"),
    sessionRefresh: document.getElementById("session-refresh"),
    sessionState: document.getElementById("session-state"),
    sessionTerminate: document.getElementById("session-terminate"),
    todoAdd: document.getElementById("todo-add"),
    todoFilter: document.getElementById("todo-filter"),
    todoList: document.getElementById("todo-list"),
    todoRefresh: document.getElementById("todo-refresh"),
    todoSave: document.getElementById("todo-save"),
    todoState: document.getElementById("todo-state"),
    todoSummary: document.getElementById("todo-summary"),
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
    const payload = await responsePayload(response);
    if (response.status === 401) {
      const error = new Error("Authentication required");
      error.authenticationRequired = true;
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    if (!response.ok || !payload.ok) {
      const error = new Error(payload.message || payload.detail || `Request failed (${response.status})`);
      error.status = response.status;
      error.payload = payload;
      throw error;
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

  function dashboardMachineOnline(machine = dashboardMachine) {
    return machine === "local" || dashboardMachineStates.get(machine) === "online";
  }

  function dashboardNumber(value) {
    if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function dashboardPercent(value) {
    const number = dashboardNumber(value);
    return number === null ? "—" : `${number.toFixed(1)}%`;
  }

  function dashboardBytes(value) {
    const number = dashboardNumber(value);
    if (number === null || number < 0) return "—";
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let scaled = number;
    let unit = 0;
    while (scaled >= 1024 && unit < units.length - 1) {
      scaled /= 1024;
      unit += 1;
    }
    const digits = scaled >= 100 || unit === 0 ? 0 : scaled >= 10 ? 1 : 2;
    return `${scaled.toFixed(digits)} ${units[unit]}`;
  }

  function dashboardRate(value) {
    const formatted = dashboardBytes(value);
    return formatted === "—" ? formatted : `${formatted}/s`;
  }

  function dashboardDuration(value) {
    let seconds = dashboardNumber(value);
    if (seconds === null || seconds < 0) return "—";
    seconds = Math.floor(seconds);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days) return `${days}d ${hours}h`;
    if (hours) return `${hours}h ${minutes}m`;
    return `${minutes}m ${seconds % 60}s`;
  }

  function dashboardTimestamp(value, fallback = "Unknown time") {
    const seconds = dashboardNumber(value);
    if (seconds === null || seconds <= 0) return fallback;
    const date = new Date(seconds * 1000);
    return Number.isNaN(date.getTime()) ? fallback : date.toLocaleString();
  }

  function setDashboardControls() {
    const online = dashboardMachineOnline();
    elements.dashboardRefresh.disabled = dashboardLoading || !online;
    elements.dashboardMachine.disabled = dashboardLoading;
  }

  function stopDashboardPolling() {
    if (dashboardTimer !== null) {
      window.clearInterval(dashboardTimer);
      dashboardTimer = null;
    }
  }

  function startDashboardPolling() {
    stopDashboardPolling();
    dashboardTimer = window.setInterval(() => {
      if ((config.authMode !== "oauth" || accessToken) && dashboardMachineOnline()) {
        refreshDashboardInBackground();
      }
    }, 5000);
  }

  function dashboardEmpty(container, message) {
    container.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = message;
    container.append(empty);
  }

  function renderDashboardSparkline(element, rawValues, fixedMaximum = null) {
    const values = Array.isArray(rawValues) ? rawValues : [];
    element.replaceChildren();
    const finite = values
      .map((value, index) => ({ index, value: dashboardNumber(value) }))
      .filter((item) => item.value !== null);
    if (finite.length < 2) return;
    const normalizedMaximum = dashboardNumber(fixedMaximum);
    const maximum = normalizedMaximum !== null
      ? Math.max(1, normalizedMaximum)
      : Math.max(1, ...finite.map((item) => item.value));
    const lastIndex = Math.max(1, values.length - 1);
    const points = finite
      .map((item) => {
        const x = (item.index / lastIndex) * 100;
        const y = 30 - Math.max(0, Math.min(1, item.value / maximum)) * 26;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("points", points);
    line.setAttribute("fill", "none");
    line.setAttribute("vector-effect", "non-scaling-stroke");
    element.append(line);
  }

  function setDashboardBar(element, value) {
    const number = dashboardNumber(value);
    const width = number === null ? 0 : Math.max(0, Math.min(100, number));
    element.style.width = `${width}%`;
    element.parentElement?.classList.toggle("dashboard-resource-missing", number === null);
  }

  function resetDashboardWorkspace(machine) {
    dashboardMachine = machine || "local";
    dashboardLoading = false;
    dashboardGeneration += 1;
    dashboardHistory = [];
    elements.dashboardMachine.value = dashboardMachine;
    elements.dashboardState.textContent = `Not loaded · ${dashboardMachine}`;
    elements.dashboardHealth.textContent = "—";
    elements.dashboardHealthDetail.textContent = "Waiting for telemetry";
    elements.dashboardHealthCard.className = "dashboard-card dashboard-health-card";
    for (const element of [
      elements.dashboardCpu,
      elements.dashboardMemory,
      elements.dashboardDisk,
      elements.dashboardNetwork,
      elements.dashboardAuditTotal,
      elements.dashboardCpuValue,
      elements.dashboardMemoryValue,
      elements.dashboardDiskValue,
      elements.dashboardVersion,
      elements.dashboardPlatform,
      elements.dashboardPython,
      elements.dashboardCpuCount,
      elements.dashboardLoad,
      elements.dashboardUptime,
      elements.dashboardMemoryUsed,
      elements.dashboardDiskUsed,
      elements.dashboardNetworkRx,
      elements.dashboardNetworkTx,
      elements.dashboardGenerated,
      elements.dashboardSourceState,
    ]) element.textContent = "—";
    elements.dashboardAuditDetail.textContent = "No activity loaded";
    elements.dashboardAlertCount.textContent = "0";
    setDashboardBar(elements.dashboardCpuBar, null);
    setDashboardBar(elements.dashboardMemoryBar, null);
    setDashboardBar(elements.dashboardDiskBar, null);
    for (const trend of [
      elements.dashboardCpuTrend,
      elements.dashboardMemoryTrend,
      elements.dashboardDiskTrend,
      elements.dashboardNetworkTrend,
    ]) trend.replaceChildren();
    dashboardEmpty(elements.dashboardAlerts, `Alerts for ${dashboardMachine} are not loaded.`);
    dashboardEmpty(elements.dashboardActivity, `Activity for ${dashboardMachine} is not loaded.`);
    setDashboardControls();
  }

  function renderDashboardMachines(machines) {
    const available = Array.isArray(machines) ? machines : [];
    dashboardMachineStates = new Map([["local", "online"]]);
    elements.dashboardMachine.replaceChildren();
    let localPresent = false;
    let currentPresent = false;
    let currentOnline = dashboardMachine === "local";
    for (const machine of available) {
      const name = text(machine.name, "");
      if (!name) continue;
      if (name === "local") localPresent = true;
      const state = name === "local" ? "online" : text(machine.status, "offline");
      const online = name === "local" || state === "online";
      dashboardMachineStates.set(name, state);
      const option = document.createElement("option");
      option.value = name;
      option.textContent = online ? name : `${name} (${state})`;
      option.disabled = !online;
      option.selected = name === dashboardMachine;
      if (option.selected) {
        currentPresent = true;
        currentOnline = online;
      }
      elements.dashboardMachine.append(option);
    }
    if (!localPresent) {
      const local = document.createElement("option");
      local.value = "local";
      local.textContent = "local";
      local.selected = dashboardMachine === "local";
      elements.dashboardMachine.prepend(local);
      if (local.selected) {
        currentPresent = true;
        currentOnline = true;
      }
    }
    if (!currentPresent && dashboardMachine !== "local") {
      const stale = document.createElement("option");
      stale.value = dashboardMachine;
      stale.textContent = `${dashboardMachine} (unavailable)`;
      stale.disabled = true;
      stale.selected = true;
      elements.dashboardMachine.append(stale);
    }
    if (!currentPresent || !currentOnline) {
      const changed = dashboardMachine !== "local";
      resetDashboardWorkspace("local");
      if (changed) refreshDashboardInBackground({ force: true });
    } else {
      elements.dashboardMachine.value = dashboardMachine;
      setDashboardControls();
    }
  }

  function dashboardListItem(kind, titleText, detailText, metaText = "") {
    const article = document.createElement("article");
    article.className = `dashboard-list-item dashboard-list-${kind}`;
    const header = document.createElement("div");
    header.className = "dashboard-list-header";
    const title = document.createElement("strong");
    title.textContent = titleText;
    const meta = document.createElement("span");
    meta.textContent = metaText;
    header.append(title, meta);
    const detail = document.createElement("p");
    detail.textContent = detailText;
    article.append(header, detail);
    return article;
  }

  function renderDashboard(payload) {
    const system = payload && payload.system && typeof payload.system === "object" ? payload.system : {};
    const version = payload && payload.version && typeof payload.version === "object" ? payload.version : {};
    const alerts = Array.isArray(payload?.alerts) ? payload.alerts : [];
    const activity = Array.isArray(payload?.activity) ? payload.activity : [];
    const sources = payload && payload.sources && typeof payload.sources === "object" ? payload.sources : {};
    const networkRx = dashboardNumber(system.network_rx_bps);
    const networkTx = dashboardNumber(system.network_tx_bps);
    const networkTotal = networkRx !== null && networkTx !== null
      ? networkRx + networkTx
      : null;
    dashboardHistory.push({
      cpu: dashboardNumber(system.cpu_percent),
      memory: dashboardNumber(system.memory_percent),
      disk: dashboardNumber(system.disk_percent),
      network: networkTotal,
    });
    dashboardHistory = dashboardHistory.slice(-60);

    const health = ["healthy", "attention", "critical"].includes(payload.health)
      ? payload.health
      : "attention";
    elements.dashboardHealth.textContent = health;
    elements.dashboardHealthCard.className = `dashboard-card dashboard-health-card dashboard-health-${health}`;
    elements.dashboardHealthDetail.textContent = alerts.length
      ? `${alerts.length} alert${alerts.length === 1 ? "" : "s"} on ${dashboardMachine}`
      : `No active alerts on ${dashboardMachine}`;
    elements.dashboardCpu.textContent = dashboardPercent(system.cpu_percent);
    elements.dashboardMemory.textContent = dashboardPercent(system.memory_percent);
    elements.dashboardDisk.textContent = dashboardPercent(system.disk_percent);
    elements.dashboardNetwork.textContent = networkTotal === null ? "—" : dashboardRate(networkTotal);
    elements.dashboardAuditTotal.textContent = text(payload.audit_total_24h, "0");
    elements.dashboardAuditDetail.textContent = `${text(payload.audit_failed_24h, "0")} failed · last 24h`;
    elements.dashboardGenerated.textContent = dashboardTimestamp(payload.generated_at, "Unknown sample time");

    elements.dashboardCpuValue.textContent = dashboardPercent(system.cpu_percent);
    elements.dashboardMemoryValue.textContent = dashboardPercent(system.memory_percent);
    elements.dashboardDiskValue.textContent = dashboardPercent(system.disk_percent);
    setDashboardBar(elements.dashboardCpuBar, system.cpu_percent);
    setDashboardBar(elements.dashboardMemoryBar, system.memory_percent);
    setDashboardBar(elements.dashboardDiskBar, system.disk_percent);
    renderDashboardSparkline(
      elements.dashboardCpuTrend,
      dashboardHistory.map((sample) => sample.cpu),
      100,
    );
    renderDashboardSparkline(
      elements.dashboardMemoryTrend,
      dashboardHistory.map((sample) => sample.memory),
      100,
    );
    renderDashboardSparkline(
      elements.dashboardDiskTrend,
      dashboardHistory.map((sample) => sample.disk),
      100,
    );
    renderDashboardSparkline(
      elements.dashboardNetworkTrend,
      dashboardHistory.map((sample) => sample.network),
    );

    elements.dashboardVersion.textContent = text(version.version, text(version.package_version));
    elements.dashboardPlatform.textContent = text(version.platform);
    elements.dashboardPython.textContent = text(version.python);
    elements.dashboardCpuCount.textContent = text(system.cpu_count);
    const load = dashboardNumber(system.load_1m);
    elements.dashboardLoad.textContent = load === null ? "—" : load.toFixed(2);
    elements.dashboardUptime.textContent = dashboardDuration(system.uptime_s);
    elements.dashboardMemoryUsed.textContent = system.memory_total_bytes === null
      ? "—"
      : `${dashboardBytes(system.memory_used_bytes)} / ${dashboardBytes(system.memory_total_bytes)}`;
    elements.dashboardDiskUsed.textContent = system.disk_total_bytes === null
      ? "—"
      : `${dashboardBytes(system.disk_used_bytes)} / ${dashboardBytes(system.disk_total_bytes)}`;
    elements.dashboardNetworkRx.textContent = dashboardRate(system.network_rx_bps);
    elements.dashboardNetworkTx.textContent = dashboardRate(system.network_tx_bps);

    elements.dashboardAlertCount.textContent = String(alerts.length);
    elements.dashboardAlerts.replaceChildren();
    if (!alerts.length) {
      dashboardEmpty(elements.dashboardAlerts, "No active alerts.");
    } else {
      for (const alert of alerts) {
        elements.dashboardAlerts.append(
          dashboardListItem(
            text(alert.severity, "info"),
            text(alert.title, "Dashboard alert"),
            text(alert.detail, ""),
            text(alert.node, dashboardMachine),
          ),
        );
      }
    }

    elements.dashboardActivity.replaceChildren();
    if (!activity.length) {
      dashboardEmpty(elements.dashboardActivity, "No recent Audit activity.");
    } else {
      for (const item of activity) {
        const durationMs = dashboardNumber(item.duration_ms);
        const duration = durationMs === null ? "" : `${durationMs.toFixed(0)} ms`;
        elements.dashboardActivity.append(
          dashboardListItem(
            text(item.kind, "success"),
            text(item.title, "MCP activity"),
            text(item.detail, ""),
            `${dashboardTimestamp(item.timestamp)}${duration ? ` · ${duration}` : ""}`,
          ),
        );
      }
    }
    elements.dashboardSourceState.textContent = `system ${text(sources.system, "unknown")} · audit ${text(sources.audit, "unknown")}`;
    elements.dashboardState.textContent = `${dashboardMachine} · ${health} · updated ${new Date().toLocaleTimeString()}`;
  }

  function dashboardQueryPath() {
    const params = new URLSearchParams({ machine: dashboardMachine });
    return `/dashboard?${params.toString()}`;
  }

  async function refreshDashboard({ force = false } = {}) {
    if ((dashboardLoading && !force) || !dashboardMachineOnline()) return null;
    const generation = ++dashboardGeneration;
    const requestedMachine = dashboardMachine;
    dashboardLoading = true;
    setDashboardControls();
    elements.dashboardState.textContent = `Loading ${requestedMachine}`;
    try {
      const payload = await request(dashboardQueryPath());
      if (generation !== dashboardGeneration || requestedMachine !== dashboardMachine) return null;
      renderDashboard(payload);
      return payload;
    } catch (error) {
      if (error.authenticationRequired) throw error;
      if (generation !== dashboardGeneration || requestedMachine !== dashboardMachine) return null;
      elements.dashboardState.textContent = error instanceof Error ? error.message : String(error);
      elements.dashboardHealth.textContent = "unavailable";
      elements.dashboardHealthCard.className = "dashboard-card dashboard-health-card dashboard-health-attention";
      elements.dashboardHealthDetail.textContent = `Telemetry for ${requestedMachine} could not be loaded`;
      return null;
    } finally {
      if (generation === dashboardGeneration) {
        dashboardLoading = false;
        setDashboardControls();
      }
    }
  }

  function refreshDashboardInBackground(options = {}) {
    void refreshDashboard(options).catch((error) => {
      if (error.authenticationRequired) void load();
    });
  }

  function selectedRemote() {
    return remoteMachines.find((machine) => machine.name === remoteSelectedName) || null;
  }

  function remoteTimestamp(value, fallback = "Never") {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds <= 0) return fallback;
    const date = new Date(seconds * 1000);
    return Number.isNaN(date.getTime()) ? fallback : date.toLocaleString();
  }

  function remoteAge(value) {
    if (value === null || value === undefined || value === "") return "unknown age";
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds < 0) return "unknown age";
    if (seconds < 5) return "just now";
    if (seconds < 60) return `${Math.floor(seconds)}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }

  function closeRemoteDialog(dialog) {
    if (dialog?.open) dialog.close();
  }

  function clearRemoteInviteResult({ close = true } = {}) {
    remoteInviteCommand = "";
    elements.remoteInviteCommand.textContent = "";
    elements.remoteInviteExpiry.textContent = "—";
    elements.remoteInviteCopy.textContent = "Copy command";
    if (close) closeRemoteDialog(elements.remoteInviteResultDialog);
  }

  function setRemoteControls() {
    elements.remoteRefresh.disabled = remoteLoading;
    elements.remoteInviteOpen.disabled = remoteLoading || !remoteEnabled;
    const selected = selectedRemote();
    elements.remoteRenameOpen.disabled = remoteLoading || !remoteEnabled || !selected;
    elements.remoteRevokeOpen.disabled = remoteLoading || !remoteEnabled || !selected;
  }

  function resetRemotes(message = "Not loaded") {
    remoteGeneration += 1;
    remoteLoading = false;
    remoteMachines = [];
    remoteSelectedName = "";
    remoteEnabled = false;
    clearRemoteInviteResult();
    closeRemoteDialog(elements.remoteInviteDialog);
    closeRemoteDialog(elements.remoteRenameDialog);
    closeRemoteDialog(elements.remoteRevokeDialog);
    elements.remoteInviteForm.reset();
    elements.remoteRenameForm.reset();
    elements.remoteState.textContent = message;
    elements.remoteOnline.textContent = "—";
    elements.remoteOffline.textContent = "—";
    elements.remoteTotal.textContent = "—";
    elements.remoteController.textContent = "—";
    renderRemoteList();
    renderRemoteDetails();
    setRemoteControls();
  }

  function renderRemoteDetails() {
    const machine = selectedRemote();
    const info = machine && machine.info && typeof machine.info === "object" ? machine.info : {};
    const values = [
      elements.remoteDetailVersion,
      elements.remoteDetailLastSeen,
      elements.remoteDetailWorkdir,
      elements.remoteDetailQueue,
      elements.remoteDetailHostname,
      elements.remoteDetailUser,
      elements.remoteDetailPlatform,
      elements.remoteDetailPython,
    ];
    if (!machine) {
      elements.remoteDetailName.textContent = "No remote selected";
      elements.remoteDetailStatus.textContent = remoteEnabled
        ? "Select a worker to inspect it"
        : "Remote workers are disabled";
      for (const element of values) element.textContent = "—";
      elements.remoteDetailCapabilities.replaceChildren();
      const empty = document.createElement("span");
      empty.className = "muted";
      empty.textContent = "—";
      elements.remoteDetailCapabilities.append(empty);
      setRemoteControls();
      return;
    }

    const online = machine.status === "online";
    elements.remoteDetailName.textContent = text(machine.name, "unnamed");
    elements.remoteDetailStatus.textContent = `${online ? "online" : "offline"} · ${remoteAge(machine.last_seen_age_s)}`;
    elements.remoteDetailVersion.textContent = text(info.lsm_version, "Not reported");
    elements.remoteDetailLastSeen.textContent = remoteTimestamp(machine.last_seen);
    elements.remoteDetailWorkdir.textContent = text(machine.workdir, text(info.workdir, "Not reported"));
    elements.remoteDetailQueue.textContent = text(machine.queue_depth, "0");
    elements.remoteDetailHostname.textContent = text(info.hostname, "Not reported");
    elements.remoteDetailUser.textContent = text(info.user, "Not reported");
    elements.remoteDetailPlatform.textContent = text(info.platform, "Not reported");
    elements.remoteDetailPython.textContent = text(info.python, "Not reported");
    elements.remoteDetailCapabilities.replaceChildren();
    const capabilities = Array.isArray(machine.capabilities) ? machine.capabilities : [];
    if (!capabilities.length) {
      const empty = document.createElement("span");
      empty.className = "muted";
      empty.textContent = "Not reported";
      elements.remoteDetailCapabilities.append(empty);
    } else {
      for (const capability of capabilities) {
        const chip = document.createElement("span");
        chip.className = "remote-capability";
        chip.textContent = text(capability, "unknown");
        elements.remoteDetailCapabilities.append(chip);
      }
    }
    setRemoteControls();
  }

  function renderRemoteList() {
    elements.remoteList.replaceChildren();
    if (!remoteEnabled) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "Remote workers are disabled.";
      elements.remoteList.append(empty);
      return;
    }
    if (!remoteMachines.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No remote workers are registered.";
      elements.remoteList.append(empty);
      return;
    }
    for (const machine of remoteMachines) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "remote-row";
      if (machine.name === remoteSelectedName) button.classList.add("remote-row-selected");
      button.setAttribute("aria-pressed", machine.name === remoteSelectedName ? "true" : "false");

      const indicator = document.createElement("span");
      indicator.className = machine.status === "online"
        ? "remote-row-status remote-row-status-online"
        : "remote-row-status";
      indicator.setAttribute("aria-label", machine.status === "online" ? "online" : "offline");

      const main = document.createElement("span");
      main.className = "remote-row-main";
      const name = document.createElement("strong");
      name.className = "remote-row-name";
      name.textContent = text(machine.name, "unnamed");
      const meta = document.createElement("span");
      meta.className = "remote-row-meta";
      meta.textContent = `${machine.status === "online" ? "online" : "offline"} · ${remoteAge(machine.last_seen_age_s)} · queue ${text(machine.queue_depth, "0")}`;
      main.append(name, meta);

      const version = document.createElement("span");
      version.className = "remote-row-version";
      version.textContent = text(machine.info?.lsm_version, "version —");
      button.append(indicator, main, version);
      button.addEventListener("click", () => {
        remoteSelectedName = machine.name;
        renderRemoteList();
        renderRemoteDetails();
      });
      elements.remoteList.append(button);
    }
  }

  function renderRemotes(payload) {
    remoteEnabled = payload?.enabled === true;
    remoteMachines = Array.isArray(payload?.machines) ? payload.machines : [];
    if (!remoteMachines.some((machine) => machine.name === remoteSelectedName)) {
      remoteSelectedName = remoteMachines[0]?.name || "";
    }
    const counts = payload && payload.counts && typeof payload.counts === "object" ? payload.counts : {};
    elements.remoteOnline.textContent = text(counts.online, "0");
    elements.remoteOffline.textContent = text(counts.offline, "0");
    elements.remoteTotal.textContent = text(counts.total, remoteMachines.length);
    elements.remoteController.textContent = remoteEnabled ? "enabled" : "disabled";
    elements.remoteState.textContent = remoteEnabled
      ? `Updated ${new Date().toLocaleTimeString()}`
      : "Remote workers disabled";
    renderRemoteList();
    renderRemoteDetails();
  }

  async function refreshRemotes({ force = false } = {}) {
    if (remoteLoading && !force) return null;
    const generation = ++remoteGeneration;
    remoteLoading = true;
    setRemoteControls();
    elements.remoteState.textContent = "Loading remote workers";
    try {
      const payload = await request("/remotes");
      if (generation !== remoteGeneration) return null;
      renderRemotes(payload);
      return payload;
    } catch (error) {
      if (error.authenticationRequired) throw error;
      if (generation !== remoteGeneration) return null;
      elements.remoteState.textContent = error instanceof Error ? error.message : String(error);
      return null;
    } finally {
      if (generation === remoteGeneration) {
        remoteLoading = false;
        setRemoteControls();
      }
    }
  }

  function refreshRemotesInBackground(options = {}) {
    void refreshRemotes(options).catch((error) => {
      if (error.authenticationRequired) void load();
    });
  }

  function stopRemotePolling() {
    if (remoteTimer !== null) {
      globalThis.clearInterval(remoteTimer);
      remoteTimer = null;
    }
  }

  function startRemotePolling() {
    stopRemotePolling();
    remoteTimer = globalThis.setInterval(() => {
      if (config.authMode !== "oauth" || accessToken) refreshRemotesInBackground();
    }, 4000);
  }

  async function remoteAction(path, body) {
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
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

  function defaultFileMutations(machine = fileMachine) {
    const local = machine === "local";
    return {
      write: true,
      delete: true,
      copy: local,
      move: local,
      rename: local,
    };
  }

  function resetFileWorkspace(machine) {
    fileMachine = machine || "local";
    filePath = ".";
    fileParentPath = ".";
    fileEntries = [];
    selectedFilePath = "";
    fileListGeneration += 1;
    filePreviewGeneration += 1;
    clearFileEditor();
    fileMutations = defaultFileMutations(fileMachine);
    elements.fileMachine.value = fileMachine;
    elements.filePath.value = ".";
    renderFileList();
    showFilePreviewMessage("No file selected", `Select a file or directory on ${fileMachine}.`);
  }

  function renderFileMachines(machines) {
    const available = Array.isArray(machines) ? machines : [];
    elements.fileMachine.replaceChildren();
    let currentAvailable = false;
    for (const machine of available) {
      const name = text(machine.name, "");
      if (!name) continue;
      const option = document.createElement("option");
      const online = name === "local" || machine.status === "online";
      option.value = name;
      option.textContent = online ? name : `${name} (${text(machine.status, "offline")})`;
      option.disabled = !online;
      option.selected = online && name === fileMachine;
      if (option.selected) currentAvailable = true;
      elements.fileMachine.append(option);
    }
    if (!elements.fileMachine.options.length) {
      const local = document.createElement("option");
      local.value = "local";
      local.textContent = "local";
      local.selected = fileMachine === "local";
      currentAvailable = local.selected;
      elements.fileMachine.append(local);
    }
    if (!currentAvailable) {
      const changed = fileMachine !== "local";
      resetFileWorkspace("local");
      if (changed) void refreshFiles();
    } else {
      elements.fileMachine.value = fileMachine;
    }
  }


  function todoMachineOnline(machine = todoMachine) {
    return machine === "local" || todoMachineStates.get(machine) === "online";
  }

  function selectedSession() {
    return todoSessions.find((session) => session.session_id === todoSessionId) || null;
  }

  function sessionTimestamp(value) {
    const date = new Date(Number(value || 0) * 1000);
    return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
  }

  function sessionTerminated(session = selectedSession()) {
    return Boolean(session && (session.termination_requested || session.termination_requested_at));
  }

  function setTodoControls() {
    const online = todoMachineOnline();
    const sessionReady = Boolean(todoSessionId);
    const session = selectedSession();
    elements.sessionMachine.disabled = sessionLoading || todoMutationBusy || sessionTerminating;
    elements.sessionIncludeInactive.disabled = sessionLoading || todoMutationBusy || sessionTerminating;
    elements.sessionRefresh.disabled = sessionLoading || todoMutationBusy || sessionTerminating || !online;
    elements.sessionTerminate.disabled =
      sessionLoading || sessionTerminating || !online || !sessionReady || sessionTerminated(session);
    elements.todoRefresh.disabled = todoMutationBusy || !online || !sessionReady;
    elements.todoAdd.disabled = todoMutationBusy || !online || !sessionReady || todoItems.length >= todoLimits.todos;
    elements.todoSave.disabled = todoMutationBusy || !online || !sessionReady || !todoDirty;
    elements.sessionAuditRefresh.disabled = sessionAuditLoading || !online || !sessionReady;
    for (const control of elements.sessionAuditFilterForm.querySelectorAll("input, select")) {
      control.disabled = sessionAuditLoading || !online || !sessionReady;
    }
    for (const control of elements.todoList.querySelectorAll("input, select, button")) {
      control.disabled = todoMutationBusy || !online || !sessionReady;
    }
    for (const row of elements.todoList.querySelectorAll(".todo-row")) {
      row.setAttribute("aria-disabled", todoMutationBusy || !online || !sessionReady ? "true" : "false");
    }
  }

  function setTodoMutationBusy(busy) {
    todoMutationBusy = busy;
    setTodoControls();
  }

  function setTodoDirty(dirty = true) {
    todoDirty = dirty;
    if (dirty) elements.todoState.textContent = `Unsaved changes · ${todoSessionId}`;
    setTodoControls();
  }

  function clearSelectedSessionResources(message = "Select a session") {
    todoItems = [];
    todoRevision = 0;
    todoDirty = false;
    todoGeneration += 1;
    renderTodos();
    elements.todoState.textContent = message;
    resetSessionAuditWorkspace(message);
  }

  function resetTodoWorkspace(machine) {
    todoMachine = machine || "local";
    todoSessionId = "";
    todoSessions = [];
    sessionLoading = false;
    sessionTerminating = false;
    elements.sessionMachine.value = todoMachine;
    elements.sessionIncludeInactive.checked = sessionIncludeInactive;
    elements.sessionList.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Loading active sessions…";
    elements.sessionList.append(empty);
    clearSelectedSessionResources("Select a session");
    elements.sessionState.textContent = `Not loaded · ${todoMachine}`;
    renderSessionDetail();
    setTodoControls();
  }

  function sessionOptionLabel(session) {
    const sessionId = text(session && session.session_id, "");
    const label = text(session && session.label, "");
    const workdir = text(session && session.workdir, "");
    return `${label || workdir || "session"} · ${sessionId}`;
  }

  function renderSessionDetail() {
    const session = selectedSession();
    if (!session) {
      elements.sessionDetailTitle.textContent = "No session selected";
      elements.sessionDetailStatus.textContent = "Select a session to inspect its state";
      elements.sessionDetailId.textContent = "—";
      elements.sessionDetailTarget.textContent = "—";
      elements.sessionDetailMachine.textContent = "—";
      elements.sessionDetailWorkdir.textContent = "—";
      elements.sessionDetailCreated.textContent = "—";
      elements.sessionDetailUpdated.textContent = "—";
      setTodoControls();
      return;
    }
    const terminated = sessionTerminated(session);
    elements.sessionDetailTitle.textContent = text(session.label, text(session.session_id, "session"));
    elements.sessionDetailStatus.textContent = terminated
      ? `Immediate termination requested ${sessionTimestamp(session.termination_requested_at)}`
      : session.active === false
        ? "Inactive · outside the recent 5 hour window"
        : "Active · responded within the last 5 hours";
    elements.sessionDetailId.textContent = text(session.session_id);
    elements.sessionDetailTarget.textContent = text(session.target);
    elements.sessionDetailMachine.textContent = text(session.machine, session.target === "local" ? "local" : "—");
    elements.sessionDetailWorkdir.textContent = text(session.workdir);
    elements.sessionDetailCreated.textContent = sessionTimestamp(session.created_at);
    elements.sessionDetailUpdated.textContent = sessionTimestamp(session.updated_at);
    setTodoControls();
  }

  function renderTodoSessions(sessions) {
    todoSessions = Array.isArray(sessions) ? sessions : [];
    if (!todoSessions.some((session) => session.session_id === todoSessionId)) {
      todoSessionId = text(todoSessions[0] && todoSessions[0].session_id, "");
      clearSelectedSessionResources(todoSessionId ? "Loading selected session" : "No sessions available");
    }
    elements.sessionList.replaceChildren();
    if (!todoSessions.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = sessionIncludeInactive
        ? `No agent sessions on ${todoMachine}.`
        : `No sessions active in the last 5 hours on ${todoMachine}.`;
      elements.sessionList.append(empty);
    } else {
      for (const session of todoSessions) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "session-entry";
        button.dataset.sessionId = text(session.session_id, "");
        button.setAttribute("aria-current", session.session_id === todoSessionId ? "true" : "false");
        const title = document.createElement("strong");
        title.textContent = sessionOptionLabel(session);
        const meta = document.createElement("span");
        meta.className = sessionTerminated(session) ? "session-entry-meta session-entry-terminated" : "session-entry-meta";
        meta.textContent = sessionTerminated(session)
          ? "termination requested"
          : session.active === false
            ? `inactive · ${sessionTimestamp(session.updated_at)}`
            : `active · ${sessionTimestamp(session.updated_at)}`;
        button.append(title, meta);
        button.addEventListener("click", () => void selectTodoSession(session.session_id));
        elements.sessionList.append(button);
      }
    }
    renderSessionDetail();
    setTodoControls();
  }

  async function refreshSelectedSessionResources() {
    if (!todoSessionId) return;
    const results = await Promise.allSettled([
      refreshTodos({ force: true }),
      refreshSessionAudit(),
    ]);
    for (const result of results) {
      if (result.status === "rejected" && result.reason?.authenticationRequired) throw result.reason;
    }
  }

  async function selectTodoSession(next) {
    if (!next || next === todoSessionId || todoMutationBusy || sessionLoading) return;
    if (todoDirty && !globalThis.confirm(`Discard unsaved changes in ${todoSessionId}?`)) return;
    todoSessionId = next;
    clearSelectedSessionResources("Loading selected session");
    renderTodoSessions(todoSessions);
    await refreshSelectedSessionResources();
  }

  async function refreshTodoSessions() {
    const requestedMachine = todoMachine;
    const previousSession = todoSessionId;
    sessionLoading = true;
    setTodoControls();
    elements.sessionState.textContent = `Loading sessions on ${requestedMachine}`;
    try {
      const params = new URLSearchParams({ machine: requestedMachine });
      if (sessionIncludeInactive) params.set("include_inactive", "true");
      const payload = await request(`/sessions?${params.toString()}`);
      if (requestedMachine !== todoMachine) return null;
      renderTodoSessions(payload.sessions);
      elements.sessionState.textContent = `${payload.count || 0} ${sessionIncludeInactive ? "total" : "active"} sessions · ${requestedMachine}`;
      if (!todoSessionId) clearSelectedSessionResources(`No agent sessions on ${requestedMachine}`);
      else if (todoSessionId !== previousSession) clearSelectedSessionResources("Loading selected session");
      return payload;
    } catch (error) {
      if (requestedMachine !== todoMachine) return null;
      renderTodoSessions([]);
      elements.sessionState.textContent = error instanceof Error ? error.message : String(error);
      throw error;
    } finally {
      if (requestedMachine === todoMachine) {
        sessionLoading = false;
        setTodoControls();
      }
    }
  }

  async function refreshTodoContext() {
    await refreshTodoSessions();
    if (!todoSessionId) return null;
    await refreshSelectedSessionResources();
    return selectedSession();
  }

  function renderTodoMachines(machines) {
    const available = Array.isArray(machines) ? machines : [];
    todoMachineStates = new Map([["local", "online"]]);
    elements.sessionMachine.replaceChildren();
    let localPresent = false;
    let currentPresent = false;
    let currentOnline = todoMachine === "local";
    for (const machine of available) {
      const name = text(machine.name, "");
      if (!name) continue;
      if (name === "local") localPresent = true;
      const state = name === "local" ? "online" : text(machine.status, "offline");
      const online = name === "local" || state === "online";
      todoMachineStates.set(name, state);
      const option = document.createElement("option");
      option.value = name;
      option.textContent = online ? name : `${name} (${state})`;
      option.disabled = !online;
      option.selected = name === todoMachine;
      if (option.selected) {
        currentPresent = true;
        currentOnline = online;
      }
      elements.sessionMachine.append(option);
    }
    if (!localPresent) {
      const local = document.createElement("option");
      local.value = "local";
      local.textContent = "local";
      local.selected = todoMachine === "local";
      elements.sessionMachine.prepend(local);
      if (local.selected) {
        currentPresent = true;
        currentOnline = true;
      }
    }
    if (!currentPresent && todoMachine !== "local") {
      const stale = document.createElement("option");
      stale.value = todoMachine;
      stale.textContent = `${todoMachine} (unavailable)`;
      stale.disabled = true;
      stale.selected = true;
      elements.sessionMachine.append(stale);
    }
    if ((!currentPresent || !currentOnline) && !todoDirty && !todoMutationBusy) {
      const changed = todoMachine !== "local";
      resetTodoWorkspace("local");
      if (changed) void refreshTodoContext();
    } else {
      elements.sessionMachine.value = todoMachine;
      if (!currentOnline) elements.sessionState.textContent = `${todoMachine} is offline`;
      setTodoControls();
    }
  }

  async function terminateSelectedSession() {
    const session = selectedSession();
    if (!session || sessionTerminated(session) || sessionTerminating) return;
    const label = sessionOptionLabel(session);
    if (!globalThis.confirm(`Immediately terminate ${label}? Any later model tool call for this session will be told to stop all work.`)) return;
    sessionTerminating = true;
    setTodoControls();
    elements.sessionState.textContent = `Requesting immediate termination for ${session.session_id}`;
    try {
      const payload = await request("/sessions/terminate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ machine: todoMachine, session_id: session.session_id }),
      });
      const updated = payload && payload.session ? payload.session : null;
      if (updated) {
        todoSessions = todoSessions.map((item) => item.session_id === updated.session_id ? updated : item);
      }
      renderTodoSessions(todoSessions);
      elements.sessionState.textContent = `${session.session_id} marked for immediate termination`;
    } catch (error) {
      elements.sessionState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      sessionTerminating = false;
      setTodoControls();
    }
  }

  function todoOption(select, value, choices) {
    const normalized = text(value, choices[0]);
    const values = choices.includes(normalized) ? choices : [...choices, normalized];
    for (const choice of values) {
      const option = document.createElement("option");
      option.value = choice;
      option.textContent = choice.replaceAll("_", " ");
      option.selected = choice === normalized;
      select.append(option);
    }
  }

  function todoField(labelText, className, control) {
    const label = document.createElement("label");
    label.className = `todo-field ${className}`;
    const caption = document.createElement("span");
    caption.textContent = labelText;
    label.append(caption, control);
    return label;
  }

  function visibleTodos() {
    const filter = elements.todoFilter.value;
    return todoItems
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => {
        if (filter === "completed") return item.status === "completed";
        if (filter === "open") return item.status !== "completed";
        return true;
      });
  }

  function renderTodoSummary() {
    const completed = todoItems.filter((item) => item.status === "completed").length;
    const open = todoItems.length - completed;
    const labels = [
      `${todoItems.length} total`,
      `${open} open`,
      `${completed} completed`,
      `revision ${todoRevision}`,
    ];
    elements.todoSummary.replaceChildren(
      ...labels.map((label) => {
        const span = document.createElement("span");
        span.textContent = label;
        return span;
      }),
    );
  }

  function renderTodos() {
    renderTodoSummary();
    const visible = visibleTodos();
    elements.todoList.replaceChildren();
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = todoItems.length ? "No todos match this filter." : "No todos in this machine session.";
      elements.todoList.append(empty);
      setTodoControls();
      return;
    }

    for (const { item, index } of visible) {
      const row = document.createElement("article");
      row.className = "todo-row";
      row.dataset.todoId = item.id;

      const content = document.createElement("input");
      content.type = "text";
      content.value = item.content;
      content.maxLength = todoLimits.content_bytes;
      content.autocomplete = "off";
      content.spellcheck = true;
      content.addEventListener("input", () => {
        todoItems[index].content = content.value;
        setTodoDirty();
      });

      const status = document.createElement("select");
      todoOption(status, item.status, ["pending", "in_progress", "completed"]);
      status.addEventListener("change", () => {
        todoItems[index].status = status.value;
        setTodoDirty();
        renderTodoSummary();
        if (elements.todoFilter.value !== "all") renderTodos();
      });

      const priority = document.createElement("select");
      todoOption(priority, item.priority, ["high", "medium", "low"]);
      priority.addEventListener("change", () => {
        todoItems[index].priority = priority.value;
        setTodoDirty();
      });

      const identifier = document.createElement("span");
      identifier.className = "todo-id";
      identifier.textContent = item.id;
      identifier.title = item.id;

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "todo-remove";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => {
        todoItems.splice(index, 1);
        setTodoDirty();
        renderTodos();
      });

      row.append(
        identifier,
        todoField("Content", "todo-field-content", content),
        todoField("Status", "todo-field-status", status),
        todoField("Priority", "todo-field-priority", priority),
        remove,
      );
      elements.todoList.append(row);
    }
    setTodoControls();
  }

  function newTodoId() {
    let candidate;
    do {
      todoSequence += 1;
      candidate = `ui-${Date.now().toString(36)}-${todoSequence.toString(36)}`;
    } while (todoItems.some((item) => item.id === candidate));
    return candidate;
  }

  function addTodo() {
    if (todoMutationBusy || !todoMachineOnline() || !todoSessionId || todoItems.length >= todoLimits.todos) return;
    const item = { id: newTodoId(), content: "", status: "pending", priority: "medium" };
    todoItems.push(item);
    elements.todoFilter.value = "all";
    setTodoDirty();
    renderTodos();
    const row = elements.todoList.querySelector(`[data-todo-id="${CSS.escape(item.id)}"]`);
    row?.querySelector("input")?.focus();
  }

  function todoQuery() {
    return `/todos?${new URLSearchParams({ machine: todoMachine, session_id: todoSessionId }).toString()}`;
  }

  async function refreshTodos({ force = false } = {}) {
    if (!todoSessionId || (!force && (todoDirty || todoMutationBusy))) return null;
    const generation = ++todoGeneration;
    const requestedMachine = todoMachine;
    const requestedSession = todoSessionId;
    elements.todoState.textContent = `Loading ${requestedSession}`;
    setTodoControls();
    try {
      const payload = await request(todoQuery());
      if (generation !== todoGeneration || requestedMachine !== todoMachine || requestedSession !== todoSessionId) return null;
      todoItems = Array.isArray(payload.todos)
        ? payload.todos.map((item) => ({
            id: text(item.id, ""),
            content: text(item.content, ""),
            status: text(item.status, "pending"),
            priority: text(item.priority, "medium"),
          }))
        : [];
      todoRevision = Number.isInteger(payload.revision) && payload.revision >= 0 ? payload.revision : 0;
      if (payload.limits && typeof payload.limits === "object") {
        todoLimits = { ...todoLimits, ...payload.limits };
      }
      todoDirty = false;
      renderTodos();
      elements.todoState.textContent = `${requestedSession} · loaded ${todoItems.length} todos`;
      return payload;
    } catch (error) {
      if (generation !== todoGeneration || requestedMachine !== todoMachine || requestedSession !== todoSessionId) return null;
      elements.todoState.textContent = error instanceof Error ? error.message : String(error);
      throw error;
    } finally {
      if (generation === todoGeneration) setTodoControls();
    }
  }

  async function saveTodos() {
    if (!todoDirty || todoMutationBusy || !todoMachineOnline() || !todoSessionId) return;
    const generation = ++todoGeneration;
    const requestedMachine = todoMachine;
    const requestedSession = todoSessionId;
    const expectedRevision = todoRevision;
    const todos = todoItems.map((item) => ({ ...item }));
    setTodoMutationBusy(true);
    elements.todoState.textContent = `Saving ${requestedSession} revision ${expectedRevision}`;
    try {
      const payload = await request("/todos", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          machine: requestedMachine,
          session_id: requestedSession,
          expected_revision: expectedRevision,
          todos,
        }),
      });
      if (generation !== todoGeneration || requestedMachine !== todoMachine || requestedSession !== todoSessionId) return;
      todoItems = Array.isArray(payload.todos) ? payload.todos.map((item) => ({ ...item })) : [];
      todoRevision = Number(payload.revision) || expectedRevision + 1;
      todoDirty = false;
      renderTodos();
      elements.todoState.textContent = `Saved ${requestedSession} · revision ${todoRevision}`;
    } catch (error) {
      if (generation !== todoGeneration || requestedMachine !== todoMachine || requestedSession !== todoSessionId) return;
      if (error && error.status === 409) {
        todoDirty = false;
        try {
          await refreshTodos({ force: true });
          elements.todoState.textContent = "Todo list changed elsewhere; reloaded the latest revision";
        } catch (reloadError) {
          elements.todoState.textContent = reloadError instanceof Error ? reloadError.message : String(reloadError);
        }
      } else {
        elements.todoState.textContent = error instanceof Error ? error.message : String(error);
      }
    } finally {
      if (requestedMachine === todoMachine && requestedSession === todoSessionId) setTodoMutationBusy(false);
    }
  }

  function auditMachineOnline(machine = auditMachine) {
    return machine === "local" || auditMachineStates.get(machine) === "online";
  }

  function setAuditControls() {
    const online = auditMachineOnline();
    elements.auditRefresh.disabled = auditLoading || !online;
    elements.auditMachine.disabled = auditLoading;
    for (const control of elements.auditFilterForm.querySelectorAll("input, select")) {
      if (control !== elements.auditMachine) control.disabled = auditLoading || !online;
    }
  }

  function clearAuditDetail(message = "Select a Global Audit record.") {
    auditDetailGeneration += 1;
    elements.auditDetailTitle.textContent = "No record selected";
    elements.auditDetailMeta.textContent = auditMachine;
    elements.auditDetailBody.textContent = message;
  }

  function resetAuditWorkspace(machine) {
    auditMachine = machine || "local";
    auditLoading = false;
    auditEntries = [];
    auditSelectedId = "";
    auditGeneration += 1;
    elements.auditMachine.value = auditMachine;
    elements.auditList.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = `Global Audit records for ${auditMachine} are not loaded.`;
    elements.auditList.append(empty);
    elements.auditSummary.textContent = "0 entries";
    elements.auditState.textContent = `Not loaded · ${auditMachine}`;
    clearAuditDetail();
    setAuditControls();
  }

  async function refreshAuditContext() {
    return refreshAudit();
  }

  function renderAuditMachines(machines) {
    const available = Array.isArray(machines) ? machines : [];
    auditMachineStates = new Map([["local", "online"]]);
    elements.auditMachine.replaceChildren();
    let localPresent = false;
    let currentPresent = false;
    let currentOnline = auditMachine === "local";
    for (const machine of available) {
      const name = text(machine.name, "");
      if (!name) continue;
      if (name === "local") localPresent = true;
      const state = name === "local" ? "online" : text(machine.status, "offline");
      const online = name === "local" || state === "online";
      auditMachineStates.set(name, state);
      const option = document.createElement("option");
      option.value = name;
      option.textContent = online ? name : `${name} (${state})`;
      option.disabled = !online;
      option.selected = name === auditMachine;
      if (option.selected) {
        currentPresent = true;
        currentOnline = online;
      }
      elements.auditMachine.append(option);
    }
    if (!localPresent) {
      const local = document.createElement("option");
      local.value = "local";
      local.textContent = "local";
      local.selected = auditMachine === "local";
      elements.auditMachine.prepend(local);
      if (local.selected) {
        currentPresent = true;
        currentOnline = true;
      }
    }
    if (!currentPresent && auditMachine !== "local") {
      const stale = document.createElement("option");
      stale.value = auditMachine;
      stale.textContent = `${auditMachine} (unavailable)`;
      stale.disabled = true;
      stale.selected = true;
      elements.auditMachine.append(stale);
    }
    if (!currentPresent || !currentOnline) {
      const changed = auditMachine !== "local";
      resetAuditWorkspace("local");
      if (changed) void refreshAudit();
    } else {
      elements.auditMachine.value = auditMachine;
      setAuditControls();
    }
  }

  function auditTimestamp(value) {
    const date = new Date(Number(value || 0) * 1000);
    return Number.isNaN(date.getTime()) ? "Unknown time" : date.toLocaleString();
  }

  function auditEntryTitle(entry) {
    return text(entry.tool, text(entry.event, "unknown"));
  }

  function auditEntryStatus(entry) {
    const raw = entry.status
      ? text(entry.status, "recorded").toLowerCase()
      : entry.ok === true
        ? "success"
        : entry.ok === false
          ? "failed"
          : "recorded";
    return ["success", "failed", "running", "unpaired", "completed", "recorded"].includes(raw)
      ? raw
      : "recorded";
  }

  function auditEntryButton(entry, selectedId, onSelect) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "audit-entry";
    button.dataset.auditId = text(entry.id, "");
    button.setAttribute("aria-current", entry.id === selectedId ? "true" : "false");

    const title = document.createElement("span");
    title.className = "audit-entry-title";
    title.textContent = auditEntryTitle(entry);

    const status = auditEntryStatus(entry);
    const meta = document.createElement("span");
    meta.className = `audit-entry-meta audit-entry-status-${status}`;
    const duration = Number.isFinite(Number(entry.duration_ms)) ? ` · ${Number(entry.duration_ms)} ms` : "";
    meta.textContent = `${auditTimestamp(entry.ts)} · ${text(entry.operation, "other")} · ${status}${duration}`;

    const session = document.createElement("span");
    session.className = "audit-entry-session";
    session.textContent = text(entry.session, text(entry.event, "record"));

    button.append(title, meta, session);
    button.addEventListener("click", onSelect);
    return button;
  }

  function renderAuditDetailInto(entry, target) {
    const detail = { ...entry };
    const preview = detail.image_preview && typeof detail.image_preview === "object"
      ? detail.image_preview
      : null;
    delete detail.image_preview;
    const fragment = document.createDocumentFragment();
    if (preview && preview.data_base64 && preview.mime_type) {
      const figure = document.createElement("figure");
      figure.className = "audit-image-preview";
      const image = document.createElement("img");
      image.alt = text(preview.path, "Audited image result");
      image.src = `data:${preview.mime_type};base64,${preview.data_base64}`;
      const caption = document.createElement("figcaption");
      caption.textContent = `${text(preview.path, "image result")} · ${formatFileBytes(preview.bytes)}`;
      figure.append(image, caption);
      fragment.append(figure);
    } else if (detail.image_preview_error) {
      const warning = document.createElement("div");
      warning.className = "audit-preview-error";
      warning.textContent = `Image preview unavailable: ${detail.image_preview_error}`;
      fragment.append(warning);
    }
    const pre = document.createElement("pre");
    pre.className = "audit-detail-json";
    const source = JSON.stringify(detail, null, 2);
    if (window.LsmSyntax) window.LsmSyntax.render(pre, source, "json");
    else pre.textContent = source;
    fragment.append(pre);
    target.replaceChildren(fragment);
  }

  function renderAuditList() {
    elements.auditList.replaceChildren();
    if (!auditEntries.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = `No Global Audit records match on ${auditMachine}.`;
      elements.auditList.append(empty);
      clearAuditDetail("No matching Global Audit record is available.");
      return;
    }
    for (const entry of auditEntries) {
      elements.auditList.append(
        auditEntryButton(entry, auditSelectedId, () => {
          auditSelectedId = text(entry.id, "");
          renderAuditList();
          void loadAuditDetail(auditSelectedId);
        }),
      );
    }
  }

  function auditQueryPath() {
    const params = new URLSearchParams({
      machine: auditMachine,
      scope: "global",
      limit: elements.auditLimit.value || "300",
      sort: elements.auditSort.value || "desc",
    });
    const filters = [
      ["operation", elements.auditOperation.value],
      ["event", elements.auditEvent.value.trim()],
      ["search", elements.auditSearch.value.trim()],
    ];
    for (const [name, value] of filters) {
      if (value) params.set(name, value);
    }
    return `/audit?${params.toString()}`;
  }

  async function loadAuditDetail(entryId) {
    if (!entryId || !auditMachineOnline()) {
      clearAuditDetail();
      return null;
    }
    const generation = ++auditDetailGeneration;
    const requestedMachine = auditMachine;
    elements.auditDetailTitle.textContent = auditEntryTitle(
      auditEntries.find((entry) => entry.id === entryId) || {},
    );
    elements.auditDetailMeta.textContent = "Loading details";
    elements.auditDetailBody.textContent = `Loading ${requestedMachine}:${entryId}`;
    try {
      const params = new URLSearchParams({
        machine: requestedMachine,
        scope: "global",
        id: entryId,
        include_full_payloads: "true",
      });
      const payload = await request(`/audit/detail?${params.toString()}`);
      if (
        generation !== auditDetailGeneration ||
        requestedMachine !== auditMachine ||
        entryId !== auditSelectedId
      ) return null;
      const entry = payload && payload.entry && typeof payload.entry === "object" ? payload.entry : null;
      if (!entry) throw new Error("Audit detail response was malformed");
      elements.auditDetailTitle.textContent = auditEntryTitle(entry);
      elements.auditDetailMeta.textContent = `${requestedMachine} · Global · ${auditTimestamp(entry.ts)}`;
      renderAuditDetailInto(entry, elements.auditDetailBody);
      return entry;
    } catch (error) {
      if (
        generation !== auditDetailGeneration ||
        requestedMachine !== auditMachine ||
        entryId !== auditSelectedId
      ) return null;
      elements.auditDetailMeta.textContent = "Details unavailable";
      elements.auditDetailBody.textContent = error instanceof Error ? error.message : String(error);
      return null;
    }
  }

  async function refreshAudit() {
    if (auditLoading || !auditMachineOnline()) return null;
    const generation = ++auditGeneration;
    const requestedMachine = auditMachine;
    const previousSelection = auditSelectedId;
    auditLoading = true;
    setAuditControls();
    elements.auditState.textContent = `Loading Global Audit · ${requestedMachine}`;
    try {
      const payload = await request(auditQueryPath());
      if (generation !== auditGeneration || requestedMachine !== auditMachine) return null;
      auditEntries = Array.isArray(payload.entries) ? payload.entries.map((entry) => ({ ...entry })) : [];
      auditSelectedId = auditEntries.some((entry) => entry.id === previousSelection)
        ? previousSelection
        : text(auditEntries[0] && auditEntries[0].id, "");
      const total = Number.isInteger(payload.total_matched) ? payload.total_matched : auditEntries.length;
      elements.auditSummary.textContent = `${auditEntries.length} shown · ${total} matched · ${requestedMachine} · Global`;
      elements.auditState.textContent = `${requestedMachine} · loaded ${auditEntries.length} global records`;
      renderAuditList();
      if (auditSelectedId) void loadAuditDetail(auditSelectedId);
      return payload;
    } catch (error) {
      if (generation !== auditGeneration || requestedMachine !== auditMachine) return null;
      auditEntries = [];
      auditSelectedId = "";
      renderAuditList();
      elements.auditState.textContent = error instanceof Error ? error.message : String(error);
      return null;
    } finally {
      if (generation === auditGeneration) {
        auditLoading = false;
        setAuditControls();
      }
    }
  }

  function clearSessionAuditDetail(message = "Select a session Audit record.") {
    sessionAuditDetailGeneration += 1;
    elements.sessionAuditDetailTitle.textContent = "No record selected";
    elements.sessionAuditDetailMeta.textContent = todoSessionId || todoMachine;
    elements.sessionAuditDetailBody.textContent = message;
  }

  function resetSessionAuditWorkspace(message = "Select a session") {
    sessionAuditEntries = [];
    sessionAuditSelectedId = "";
    sessionAuditLoading = false;
    sessionAuditGeneration += 1;
    elements.sessionAuditList.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = message;
    elements.sessionAuditList.append(empty);
    elements.sessionAuditSummary.textContent = "0 entries";
    elements.sessionAuditState.textContent = message;
    clearSessionAuditDetail();
    setTodoControls();
  }

  function renderSessionAuditList() {
    elements.sessionAuditList.replaceChildren();
    if (!sessionAuditEntries.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = todoSessionId
        ? `No local Audit records match for ${todoSessionId}.`
        : "Select a session to load its Audit records.";
      elements.sessionAuditList.append(empty);
      clearSessionAuditDetail("No matching session Audit record is available.");
      return;
    }
    for (const entry of sessionAuditEntries) {
      elements.sessionAuditList.append(
        auditEntryButton(entry, sessionAuditSelectedId, () => {
          sessionAuditSelectedId = text(entry.id, "");
          renderSessionAuditList();
          void loadSessionAuditDetail(sessionAuditSelectedId);
        }),
      );
    }
  }

  function sessionAuditQueryPath() {
    const params = new URLSearchParams({
      machine: todoMachine,
      scope: "session",
      session: todoSessionId,
      limit: elements.sessionAuditLimit.value || "300",
      sort: elements.sessionAuditSort.value || "desc",
    });
    if (elements.sessionAuditOperation.value) params.set("operation", elements.sessionAuditOperation.value);
    if (elements.sessionAuditSearch.value.trim()) params.set("search", elements.sessionAuditSearch.value.trim());
    return `/audit?${params.toString()}`;
  }

  async function loadSessionAuditDetail(entryId) {
    if (!entryId || !todoSessionId || !todoMachineOnline()) {
      clearSessionAuditDetail();
      return null;
    }
    const generation = ++sessionAuditDetailGeneration;
    const requestedMachine = todoMachine;
    const requestedSession = todoSessionId;
    elements.sessionAuditDetailTitle.textContent = auditEntryTitle(
      sessionAuditEntries.find((entry) => entry.id === entryId) || {},
    );
    elements.sessionAuditDetailMeta.textContent = "Loading details";
    elements.sessionAuditDetailBody.textContent = `Loading ${requestedSession}:${entryId}`;
    try {
      const params = new URLSearchParams({
        machine: requestedMachine,
        scope: "session",
        session: requestedSession,
        id: entryId,
        include_full_payloads: "true",
      });
      const payload = await request(`/audit/detail?${params.toString()}`);
      if (
        generation !== sessionAuditDetailGeneration ||
        requestedMachine !== todoMachine ||
        requestedSession !== todoSessionId ||
        entryId !== sessionAuditSelectedId
      ) return null;
      const entry = payload && payload.entry && typeof payload.entry === "object" ? payload.entry : null;
      if (!entry) throw new Error("Session Audit detail response was malformed");
      elements.sessionAuditDetailTitle.textContent = auditEntryTitle(entry);
      elements.sessionAuditDetailMeta.textContent = `${requestedSession} · ${auditTimestamp(entry.ts)}`;
      renderAuditDetailInto(entry, elements.sessionAuditDetailBody);
      return entry;
    } catch (error) {
      if (
        generation !== sessionAuditDetailGeneration ||
        requestedMachine !== todoMachine ||
        requestedSession !== todoSessionId ||
        entryId !== sessionAuditSelectedId
      ) return null;
      elements.sessionAuditDetailMeta.textContent = "Details unavailable";
      elements.sessionAuditDetailBody.textContent = error instanceof Error ? error.message : String(error);
      return null;
    }
  }

  async function refreshSessionAudit() {
    if (sessionAuditLoading || !todoSessionId || !todoMachineOnline()) return null;
    const generation = ++sessionAuditGeneration;
    const requestedMachine = todoMachine;
    const requestedSession = todoSessionId;
    const previousSelection = sessionAuditSelectedId;
    sessionAuditLoading = true;
    setTodoControls();
    elements.sessionAuditState.textContent = `Loading ${requestedSession}`;
    try {
      const payload = await request(sessionAuditQueryPath());
      if (
        generation !== sessionAuditGeneration ||
        requestedMachine !== todoMachine ||
        requestedSession !== todoSessionId
      ) return null;
      sessionAuditEntries = Array.isArray(payload.entries)
        ? payload.entries.map((entry) => ({ ...entry }))
        : [];
      sessionAuditSelectedId = sessionAuditEntries.some((entry) => entry.id === previousSelection)
        ? previousSelection
        : text(sessionAuditEntries[0] && sessionAuditEntries[0].id, "");
      const total = Number.isInteger(payload.total_matched) ? payload.total_matched : sessionAuditEntries.length;
      elements.sessionAuditSummary.textContent = `${sessionAuditEntries.length} shown · ${total} matched · ${requestedSession}`;
      elements.sessionAuditState.textContent = `${requestedSession} · loaded ${sessionAuditEntries.length} records`;
      renderSessionAuditList();
      if (sessionAuditSelectedId) void loadSessionAuditDetail(sessionAuditSelectedId);
      return payload;
    } catch (error) {
      if (
        generation !== sessionAuditGeneration ||
        requestedMachine !== todoMachine ||
        requestedSession !== todoSessionId
      ) return null;
      sessionAuditEntries = [];
      sessionAuditSelectedId = "";
      renderSessionAuditList();
      elements.sessionAuditState.textContent = error instanceof Error ? error.message : String(error);
      return null;
    } finally {
      if (generation === sessionAuditGeneration) {
        sessionAuditLoading = false;
        setTodoControls();
      }
    }
  }

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
    const pending = terminalMode !== "pty" && terminalPendingOutput !== null;
    elements.terminalLatest.hidden = !pending;
    elements.terminalPendingCount.textContent = pending
      ? `(${Math.max(1, terminalPendingUpdates)})`
      : "";
  }

  function renderTerminalOutput(value, { scrollToBottom = false } = {}) {
    const output = String(value ?? "");
    terminalLastOutput = output;
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
    terminalFollowOutput = true;
    terminalPendingOutput = null;
    terminalPendingUpdates = 0;
    terminalLastOutput = "";
    elements.terminalOutput.textContent = String(message ?? "");
    elements.terminalOutput.scrollTop = 0;
    updateTerminalLatestControl();
  }

  function acceptTerminalSnapshot(value) {
    activateTerminalMode("snapshot");
    const output = String(value ?? "");
    terminalLastOutput = output;
    if (!terminalAtBottom()) {
      terminalFollowOutput = false;
      terminalPendingOutput = output;
      terminalPendingUpdates = Math.min(9999, terminalPendingUpdates + 1);
      updateTerminalLatestControl();
      return;
    }
    terminalFollowOutput = true;
    terminalPendingOutput = null;
    terminalPendingUpdates = 0;
    renderTerminalOutput(output, { scrollToBottom: true });
    updateTerminalLatestControl();
  }

  function jumpToLatestTerminalOutput() {
    const output = terminalPendingOutput ?? terminalLastOutput;
    terminalFollowOutput = true;
    terminalPendingOutput = null;
    terminalPendingUpdates = 0;
    renderTerminalOutput(output, { scrollToBottom: true });
    updateTerminalLatestControl();
  }

  function rememberTerminalCommand(command) {
    if (!command) return;
    if (terminalCommandHistory[terminalCommandHistory.length - 1] !== command) {
      terminalCommandHistory.push(command);
      if (terminalCommandHistory.length > terminalHistoryLimit) {
        terminalCommandHistory = terminalCommandHistory.slice(-terminalHistoryLimit);
      }
    }
    terminalHistoryIndex = terminalCommandHistory.length;
    terminalHistoryDraft = "";
  }

  function navigateTerminalHistory(direction) {
    if (!terminalCommandHistory.length) return;
    if (terminalHistoryIndex === terminalCommandHistory.length) {
      terminalHistoryDraft = elements.terminalInput.value;
    }
    terminalHistoryIndex = Math.max(
      0,
      Math.min(terminalCommandHistory.length, terminalHistoryIndex + direction),
    );
    elements.terminalInput.value =
      terminalHistoryIndex === terminalCommandHistory.length
        ? terminalHistoryDraft
        : terminalCommandHistory[terminalHistoryIndex];
    elements.terminalInput.setSelectionRange(
      elements.terminalInput.value.length,
      elements.terminalInput.value.length,
    );
  }

  function terminalSocketCurrent() {
    return Boolean(
      terminalSocket &&
      terminalSocket.readyState === WebSocket.OPEN &&
      terminalSocketMachine === terminalMachine
    );
  }

  function sendTerminalBytes(data) {
    if (!terminalReady || !terminalSocketCurrent() || terminalMode !== "pty") return false;
    const bytes = data instanceof Uint8Array ? data : encoder.encode(String(data ?? ""));
    if (!bytes.byteLength) return false;
    for (let offset = 0; offset < bytes.byteLength; offset += 65536) {
      terminalSocket.send(bytes.slice(offset, Math.min(bytes.byteLength, offset + 65536)));
    }
    return true;
  }

  function ensureTerminalXterm() {
    if (terminalXterm) return true;
    const api = globalThis.LsmXterm;
    if (!api || typeof api.Terminal !== "function" || typeof api.FitAddon !== "function") {
      return false;
    }
    terminalXterm = new api.Terminal({
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
    terminalXterm.parser.registerOscHandler(8, () => true);
    if (typeof api.createImageAddon === "function") {
      terminalXterm.loadAddon(api.createImageAddon());
    }
    terminalFitAddon = new api.FitAddon();
    terminalXterm.loadAddon(terminalFitAddon);
    terminalXterm.open(elements.terminalXterm);
    terminalXtermData = terminalXterm.onData((data) => {
      sendTerminalBytes(encoder.encode(data));
    });
    terminalXtermBinary = terminalXterm.onBinary((data) => {
      const bytes = new Uint8Array(data.length);
      for (let index = 0; index < data.length; index += 1) {
        bytes[index] = data.charCodeAt(index) & 0xff;
      }
      sendTerminalBytes(bytes);
    });
    return true;
  }

  function activateTerminalMode(mode, { reset = false } = {}) {
    terminalMode = mode === "pty" ? "pty" : "snapshot";
    const raw = terminalMode === "pty";
    if (raw && !ensureTerminalXterm()) return false;
    elements.terminalXterm.hidden = !raw;
    elements.terminalOutput.hidden = raw;
    if (raw) {
      terminalPendingOutput = null;
      terminalPendingUpdates = 0;
      updateTerminalLatestControl();
      if (reset) terminalXterm.reset();
      window.requestAnimationFrame(() => {
        if (terminalMode !== "pty" || !terminalFitAddon) return;
        sendTerminalResize();
        terminalXterm.focus();
      });
    }
    return true;
  }

  function sendTerminalData(data, enter = false) {
    if (!data || !terminalReady || !terminalSocketCurrent()) return false;
    if (terminalMode === "pty") {
      const bytes = encoder.encode(`${data}${enter ? "\r" : ""}`);
      return sendTerminalBytes(bytes);
    }
    terminalSocket.send(JSON.stringify({ type: "input", data, enter }));
    return true;
  }

  function terminalSocketProtocols() {
    const protocols = ["lsm-ui-terminal"];
    if (accessToken) protocols.push(`bearer.${base64Url(encoder.encode(accessToken))}`);
    return protocols;
  }

  function terminalMachineOnline(machine = terminalMachine) {
    return machine === "local" || terminalMachineStates.get(machine) === "online";
  }

  function terminalSize() {
    if (terminalMode === "pty" && terminalXterm) {
      return {
        cols: Math.max(20, Math.min(300, terminalXterm.cols)),
        rows: Math.max(3, Math.min(120, terminalXterm.rows)),
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
      terminalSocketMachine === terminalMachine &&
      terminalReady &&
      terminalSocket?.readyState === WebSocket.OPEN;
    elements.terminalMachine.disabled = terminalLoading;
    elements.terminalStartForm.querySelector("button").disabled = terminalLoading || !online;
    elements.terminalName.disabled = terminalLoading || !online;
    elements.terminalInput.disabled = !connected;
    elements.terminalInputForm.querySelector("button").disabled = !connected;
    for (const button of elements.terminalKeyButtons) button.disabled = !connected;
    elements.terminalKill.disabled = terminalLoading || !online || !selectedShellId;
  }

  function closeTerminalSocket() {
    terminalGeneration += 1;
    const socket = terminalSocket;
    terminalSocket = null;
    terminalSocketMachine = "";
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close(1000, "Client changed terminal");
    }
    terminalMode = "snapshot";
    terminalReady = false;
    elements.terminalXterm.hidden = true;
    elements.terminalOutput.hidden = false;
    terminalXterm?.reset();
    terminalPendingOutput = null;
    terminalPendingUpdates = 0;
    updateTerminalLatestControl();
    elements.terminalState.textContent = selectedShellId ? "Disconnected" : "No session";
    setTerminalControls(false);
  }

  function resetTerminalWorkspace(machine) {
    closeTerminalSocket();
    terminalMachine = machine || "local";
    terminalListGeneration += 1;
    terminalSessions = [];
    selectedShellId = "";
    terminalCommandHistory = [];
    terminalHistoryIndex = 0;
    terminalHistoryDraft = "";
    elements.terminalMachine.value = terminalMachine;
    elements.terminalTitle.textContent = "No terminal selected";
    elements.terminalState.textContent = `Not loaded · ${terminalMachine}`;
    showTerminalMessage(`Select or create a terminal session on ${terminalMachine}.`);
    renderTerminalList({ shells: [] }, { emptyMessage: `Terminals for ${terminalMachine} are not loaded.` });
    setTerminalControls(false);
  }

  function renderTerminalMachines(machines) {
    const available = Array.isArray(machines) ? machines : [];
    terminalMachineStates = new Map([["local", "online"]]);
    elements.terminalMachine.replaceChildren();
    let localPresent = false;
    let currentPresent = false;
    let currentOnline = terminalMachine === "local";
    for (const machine of available) {
      const name = text(machine.name, "");
      if (!name) continue;
      if (name === "local") localPresent = true;
      const state = name === "local" ? "online" : text(machine.status, "offline");
      const online = name === "local" || state === "online";
      terminalMachineStates.set(name, state);
      const option = document.createElement("option");
      option.value = name;
      option.textContent = online ? name : `${name} (${state})`;
      option.disabled = !online;
      option.selected = name === terminalMachine;
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
      local.selected = terminalMachine === "local";
      elements.terminalMachine.prepend(local);
      if (local.selected) {
        currentPresent = true;
        currentOnline = true;
      }
    }
    if (!currentPresent && terminalMachine !== "local") {
      const stale = document.createElement("option");
      stale.value = terminalMachine;
      stale.textContent = `${terminalMachine} (unavailable)`;
      stale.disabled = true;
      stale.selected = true;
      elements.terminalMachine.append(stale);
    }
    if (!currentPresent || !currentOnline) {
      const changed = terminalMachine !== "local";
      resetTerminalWorkspace("local");
      if (changed) refreshTerminalsInBackground({ force: true });
    } else {
      elements.terminalMachine.value = terminalMachine;
      setTerminalControls(terminalSocket?.readyState === WebSocket.OPEN);
    }
  }

  function renderTerminalList(payload, { emptyMessage = "No persistent terminals are running." } = {}) {
    terminalSessions = Array.isArray(payload && payload.shells) ? payload.shells : [];
    if (selectedShellId && !terminalSessions.some((item) => item.shell_id === selectedShellId)) {
      closeTerminalSocket();
      selectedShellId = "";
      elements.terminalTitle.textContent = "No terminal selected";
      elements.terminalState.textContent = "No session";
      showTerminalMessage(`Select or create a terminal session on ${terminalMachine}.`);
    }

    elements.terminalList.replaceChildren();
    if (!terminalSessions.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = emptyMessage;
      elements.terminalList.append(empty);
      setTerminalControls(false);
      return;
    }

    for (const session of terminalSessions) {
      const shellId = text(session.shell_id, "");
      if (!shellId) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "terminal-session";
      button.textContent = text(session.name, shellId);
      const details = [terminalMachine, shellId, session.cwd, session.command].filter(Boolean);
      button.title = details.join(" · ");
      button.setAttribute("aria-current", shellId === selectedShellId ? "true" : "false");
      button.addEventListener("click", () => connectTerminal(shellId));
      elements.terminalList.append(button);
    }
    setTerminalControls(terminalSocket?.readyState === WebSocket.OPEN);
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
    if (!terminalReady || !terminalSocketCurrent()) return;
    if (terminalMode === "pty" && terminalFitAddon && !elements.terminalXterm.hidden) {
      terminalFitAddon.fit();
    }
    terminalSocket.send(JSON.stringify({ type: "resize", ...terminalSize() }));
  }

  function terminalNotice(value, fallback = "Terminal session exited.") {
    return text(value, fallback)
      .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
      .slice(0, 4096);
  }

  function connectTerminal(shellId) {
    const requestedMachine = terminalMachine;
    if (
      !shellId ||
      !terminalMachineOnline(requestedMachine) ||
      (shellId === selectedShellId &&
        terminalSocketMachine === requestedMachine &&
        terminalSocket?.readyState === WebSocket.OPEN)
    ) return;
    closeTerminalSocket();
    selectedShellId = shellId;
    const generation = terminalGeneration;
    elements.terminalTitle.textContent = `${requestedMachine} / ${shellId}`;
    elements.terminalState.textContent = "Connecting";
    terminalCommandHistory = [];
    terminalHistoryIndex = 0;
    terminalHistoryDraft = "";
    showTerminalMessage(`Connecting to ${requestedMachine}…`);
    renderTerminalList({ shells: terminalSessions });

    const socket = new WebSocket(
      terminalWebSocketUrl(shellId, requestedMachine),
      terminalSocketProtocols(),
    );
    socket.binaryType = "arraybuffer";
    terminalSocket = socket;
    terminalSocketMachine = requestedMachine;
    const current = () =>
      generation === terminalGeneration &&
      socket === terminalSocket &&
      requestedMachine === terminalMachine &&
      requestedMachine === terminalSocketMachine;
    socket.addEventListener("open", () => {
      if (!current()) return;
      elements.terminalState.textContent = `Negotiating · ${requestedMachine}`;
      terminalReady = false;
      setTerminalControls(false);
    });
    socket.addEventListener("message", (event) => {
      if (!current()) return;
      if (event.data instanceof ArrayBuffer) {
        if (terminalMode === "pty" && terminalXterm) {
          terminalXterm.write(new Uint8Array(event.data));
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
        terminalReady = true;
        elements.terminalState.textContent = `Connected · ${requestedMachine} · ${mode.toUpperCase()}`;
        setTerminalControls(true);
        sendTerminalResize();
        if (mode === "pty") terminalXterm?.focus();
        else elements.terminalInput.focus();
      } else if (message.type === "snapshot") {
        acceptTerminalSnapshot(text(message.output, ""));
        terminalReady = true;
        elements.terminalState.textContent = `Connected · ${requestedMachine} · SNAPSHOT`;
        setTerminalControls(true);
        elements.terminalInput.focus();
      } else if (message.type === "exit") {
        const detail = terminalNotice(message.message);
        terminalReady = false;
        elements.terminalState.textContent = `Exited · ${requestedMachine}`;
        if (terminalMode === "pty" && terminalXterm) {
          terminalXterm.write(`\r\n\u001b[31m[${detail}]\u001b[0m\r\n`);
        } else {
          showTerminalMessage(detail);
        }
        setTerminalControls(false);
        refreshTerminalsInBackground({ force: true });
      }
    });
    socket.addEventListener("close", (event) => {
      if (!current()) return;
      terminalSocket = null;
      terminalSocketMachine = "";
      terminalReady = false;
      setTerminalControls(false);
      if (event.code === 4401 || event.code === 4403) {
        clearAccessToken();
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

  function terminalQueryPath(machine = terminalMachine) {
    const params = new URLSearchParams({ machine });
    return `/terminals?${params.toString()}`;
  }

  async function refreshTerminals({ force = false } = {}) {
    if ((terminalLoading && !force) || !terminalMachineOnline()) return null;
    const generation = ++terminalListGeneration;
    const requestedMachine = terminalMachine;
    terminalLoading = true;
    setTerminalControls(terminalSocket?.readyState === WebSocket.OPEN);
    elements.terminalState.textContent = `Loading ${requestedMachine}`;
    try {
      const payload = await request(terminalQueryPath(requestedMachine));
      if (generation !== terminalListGeneration || requestedMachine !== terminalMachine) return null;
      if (payload.machine !== requestedMachine) throw new Error("Terminal machine response mismatch");
      renderTerminalList(payload);
      elements.terminalState.textContent = selectedShellId
        ? `${terminalSocket?.readyState === WebSocket.OPEN ? "Connected" : "Selected"} · ${requestedMachine}`
        : `${terminalSessions.length} session(s) · ${requestedMachine}`;
      return payload;
    } catch (error) {
      if (error.authenticationRequired) throw error;
      if (generation !== terminalListGeneration || requestedMachine !== terminalMachine) return null;
      terminalSessions = [];
      renderTerminalList(
        { shells: [] },
        { emptyMessage: `Terminals unavailable on ${requestedMachine}.` },
      );
      elements.terminalState.textContent = error instanceof Error ? error.message : String(error);
      return null;
    } finally {
      if (generation === terminalListGeneration) {
        terminalLoading = false;
        setTerminalControls(terminalSocket?.readyState === WebSocket.OPEN);
      }
    }
  }

  function refreshTerminalsInBackground(options = {}) {
    void refreshTerminals(options).catch((error) => {
      if (error.authenticationRequired) void load();
    });
  }

  async function terminalAction(action, body) {
    return request(`/terminals/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ machine: terminalMachine, ...body }),
    });
  }


  function formatFileBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return "size unavailable";
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KiB", "MiB", "GiB"];
    let size = bytes / 1024;
    let unit = units[0];
    for (let index = 1; index < units.length && size >= 1024; index += 1) {
      size /= 1024;
      unit = units[index];
    }
    return `${size.toFixed(size >= 10 ? 1 : 2)} ${unit}`;
  }

  function fileQuery(path, value) {
    const query = new URLSearchParams({
      machine: fileMachine,
      path: value,
    });
    return `${path}?${query.toString()}`;
  }

  function fileAction(action, body) {
    return request(`/files/${encodeURIComponent(action)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, machine: fileMachine }),
    });
  }

  function joinFilePath(parent, name) {
    const child = String(name || "").replace(/^[\\/]+/, "");
    if (!parent || parent === ".") return child;
    return `${String(parent).replace(/[\\/]+$/, "")}/${child}`;
  }

  function splitFilePath(path) {
    const normalized = String(path || ".")
      .replace(/\\/g, "/")
      .replace(/\/+$/, "");
    const separator = normalized.lastIndexOf("/");
    if (separator < 0) return { parent: ".", name: normalized };
    return {
      parent: normalized.slice(0, separator) || ".",
      name: normalized.slice(separator + 1),
    };
  }

  function setFileMutationBusy(busy) {
    fileMutationBusy = busy;
    elements.fileMachine.disabled = busy;
    elements.filePath.disabled = busy;
    elements.fileRefresh.disabled = busy;
    elements.fileShowHidden.disabled = busy;
    const goButton = elements.filePathForm.querySelector('button[type="submit"]');
    if (goButton) goButton.disabled = busy;
    setFileControls();
  }

  function currentFileEntry() {
    return fileEntries.find((entry) => entry.path === selectedFilePath) || null;
  }

  function clearFileEditor() {
    fileEditorPath = "";
    elements.fileEditor.value = "";
    elements.fileEditorForm.hidden = true;
    elements.filePreviewBody.hidden = false;
  }

  function setFileControls() {
    const entry = currentFileEntry();
    elements.fileNew.disabled = fileMutationBusy || !fileMutations.write;
    elements.fileOpen.disabled = fileMutationBusy || !entry || entry.type !== "dir";
    elements.fileEdit.disabled =
      fileMutationBusy || !fileMutations.write || !entry || entry.type !== "file";
    elements.fileCopy.disabled = fileMutationBusy || !fileMutations.copy || !entry;
    elements.fileMove.disabled = fileMutationBusy || !fileMutations.move || !entry;
    elements.fileRename.disabled = fileMutationBusy || !fileMutations.rename || !entry;
    elements.fileDelete.disabled = fileMutationBusy || !fileMutations.delete || !entry;
    elements.fileUp.disabled = fileMutationBusy || filePath === fileParentPath;
    const localOnly = fileMachine === "local" ? "" : "Only available for local Files";
    elements.fileCopy.title = fileMutations.copy ? "" : localOnly;
    elements.fileMove.title = fileMutations.move ? "" : localOnly;
    elements.fileRename.title = fileMutations.rename ? "" : localOnly;
  }

  function showFilePreviewMessage(title, detail) {
    elements.filePreviewTitle.textContent = title;
    elements.filePreviewMeta.textContent = detail || "";
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = detail || title;
    elements.filePreviewBody.replaceChildren(empty);
  }

  function fileEntryLabel(entry) {
    const icon = entry.type === "dir" ? "▰" : entry.type === "link" ? "↗" : "·";
    return `${icon} ${text(entry.name, entry.path)}`;
  }

  function visibleFileEntries() {
    return fileEntries.filter((entry) => elements.fileShowHidden.checked || !entry.hidden);
  }

  function renderFileList() {
    const visible = visibleFileEntries();
    if (selectedFilePath && !visible.some((entry) => entry.path === selectedFilePath)) {
      selectedFilePath = "";
      filePreviewGeneration += 1;
      clearFileEditor();
      showFilePreviewMessage("No file selected", "Select a file or directory.");
    }

    elements.fileList.replaceChildren();
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = fileEntries.length ? "Hidden entries are not shown." : "This directory is empty.";
      elements.fileList.append(empty);
      setFileControls();
      return;
    }

    for (const entry of visible) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "file-entry";
      button.setAttribute("aria-current", entry.path === selectedFilePath ? "true" : "false");
      button.title = entry.path;

      const label = document.createElement("span");
      label.className = "file-entry-name";
      label.textContent = fileEntryLabel(entry);
      const detail = document.createElement("span");
      detail.className = "file-entry-detail";
      detail.textContent = entry.type === "dir" ? "dir" : entry.type === "link" ? "link" : formatFileBytes(entry.size);
      button.append(label, detail);
      button.addEventListener("click", () => selectFile(entry));
      button.addEventListener("dblclick", () => {
        if (!fileMutationBusy && entry.type === "dir") void navigateFiles(entry.path);
      });
      elements.fileList.append(button);
    }
    setFileControls();
  }

  function renderDirectoryPreview(payload) {
    const list = document.createElement("div");
    list.className = "file-preview-directory";
    const entries = (Array.isArray(payload.entries) ? payload.entries : []).filter(
      (entry) => elements.fileShowHidden.checked || !entry.hidden,
    );
    if (!entries.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "Directory is empty.";
      list.append(empty);
      return list;
    }
    for (const entry of entries.slice(0, 100)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "file-preview-entry";
      button.textContent = fileEntryLabel(entry);
      button.title = entry.path;
      button.addEventListener("click", () => {
        if (!fileMutationBusy) void navigateFiles(payload.path, entry.path);
      });
      list.append(button);
    }
    return list;
  }

  function renderFilePreview(payload, entry) {
    clearFileEditor();
    elements.filePreviewTitle.textContent = text(entry.name, entry.path);
    const metadata = [payload.kind, payload.media_type, payload.bytes === undefined ? "" : formatFileBytes(payload.bytes)]
      .filter(Boolean)
      .join(" · ");
    elements.filePreviewMeta.textContent = metadata;

    if (payload.kind === "directory") {
      elements.filePreviewMeta.textContent = `${payload.count || 0} entries${payload.is_truncated ? " · truncated" : ""}`;
      elements.filePreviewBody.replaceChildren(renderDirectoryPreview(payload));
      return;
    }
    if (payload.kind === "image") {
      if (!payload.inline || !payload.data_base64) {
        showFilePreviewMessage(text(entry.name, entry.path), text(payload.message, "Image preview unavailable."));
        return;
      }
      const image = document.createElement("img");
      image.className = "file-preview-image";
      image.alt = text(entry.name, "Workspace image");
      image.src = `data:${payload.media_type};base64,${payload.data_base64}`;
      elements.filePreviewBody.replaceChildren(image);
      return;
    }

    const pre = document.createElement("pre");
    pre.className = "file-preview-text";
    if (payload.kind === "binary") {
      const hex = String(payload.preview || "");
      pre.textContent = (hex.match(/.{1,32}/g) || []).join("\n") || "No preview bytes.";
      elements.filePreviewMeta.textContent = `${formatFileBytes(payload.bytes)} · ${payload.preview_bytes || 0} preview bytes · hex`;
    } else {
      const source = text(payload.content, "");
      const language = window.LsmSyntax
        ? window.LsmSyntax.languageForPath(entry.path, payload.media_type)
        : "plain";
      if (window.LsmSyntax && language !== "plain") window.LsmSyntax.render(pre, source, language);
      else pre.textContent = source;
      if (payload.preview_truncated) elements.filePreviewMeta.textContent += " · preview truncated";
    }
    elements.filePreviewBody.replaceChildren(pre);
  }

  async function previewFile(entry) {
    const generation = ++filePreviewGeneration;
    clearFileEditor();
    elements.filePreviewTitle.textContent = text(entry.name, entry.path);
    elements.filePreviewMeta.textContent = "Loading preview…";
    showFilePreviewMessage(text(entry.name, entry.path), "Loading preview…");
    try {
      const payload = await request(fileQuery("/files/preview", entry.path));
      if (generation !== filePreviewGeneration || selectedFilePath !== entry.path) return;
      renderFilePreview(payload, entry);
    } catch (error) {
      if (generation !== filePreviewGeneration || selectedFilePath !== entry.path) return;
      elements.fileState.textContent = "Preview unavailable";
      showFilePreviewMessage(text(entry.name, entry.path), error instanceof Error ? error.message : String(error));
    }
  }

  function selectFile(entry) {
    if (fileMutationBusy) return;
    selectedFilePath = entry.path;
    renderFileList();
    void previewFile(entry);
  }

  async function refreshFiles({ previewSelection = false } = {}) {
    const generation = ++fileListGeneration;
    const requestedMachine = fileMachine;
    const requestedPath = filePath;
    elements.fileRefresh.disabled = true;
    elements.fileState.textContent = `Loading ${requestedMachine}:${requestedPath}`;
    try {
      const payload = await request(fileQuery("/files", requestedPath));
      if (generation !== fileListGeneration || requestedMachine !== fileMachine) return null;
      fileMachine = text(payload.machine, requestedMachine);
      filePath = text(payload.path, ".");
      fileParentPath = text(payload.parent, filePath);
      fileEntries = Array.isArray(payload.entries) ? payload.entries : [];
      fileMutations = {
        ...defaultFileMutations(fileMachine),
        ...(payload.mutations && typeof payload.mutations === "object" ? payload.mutations : {}),
      };
      elements.fileMachine.value = fileMachine;
      elements.filePath.value = filePath;
      const selected = currentFileEntry();
      if (!selected) {
        selectedFilePath = "";
        filePreviewGeneration += 1;
        clearFileEditor();
        showFilePreviewMessage("No file selected", `Select a file or directory on ${fileMachine}.`);
      }
      renderFileList();
      if (selected && previewSelection) void previewFile(selected);
      elements.fileState.textContent = `${fileMachine}:${filePath} · ${fileEntries.length} entries${payload.is_truncated ? " · truncated" : ""}`;
      return payload;
    } finally {
      if (generation === fileListGeneration) {
        elements.fileRefresh.disabled = fileMutationBusy;
      }
    }
  }

  async function navigateFiles(path, selection = "") {
    filePath = path || ".";
    selectedFilePath = selection;
    filePreviewGeneration += 1;
    clearFileEditor();
    showFilePreviewMessage("Loading directory", `${fileMachine}:${filePath}`);
    try {
      await refreshFiles({ previewSelection: Boolean(selection) });
      return true;
    } catch (error) {
      elements.fileState.textContent = "Directory unavailable";
      showFilePreviewMessage("Unable to open directory", error instanceof Error ? error.message : String(error));
      return false;
    }
  }

  function openSelectedFile() {
    if (fileMutationBusy) return;
    const entry = currentFileEntry();
    if (entry?.type === "dir") void navigateFiles(entry.path);
  }

  async function openFileEditor() {
    const entry = currentFileEntry();
    if (!entry || entry.type !== "file") return;
    const generation = ++filePreviewGeneration;
    elements.fileEdit.disabled = true;
    elements.fileState.textContent = `Opening ${entry.path}`;
    try {
      const payload = await request(fileQuery("/files/content", entry.path));
      if (generation !== filePreviewGeneration || selectedFilePath !== entry.path) return;
      fileEditorPath = entry.path;
      elements.fileEditor.value = text(payload.content, "");
      elements.filePreviewBody.hidden = true;
      elements.fileEditorForm.hidden = false;
      elements.filePreviewTitle.textContent = `Edit · ${text(entry.name, entry.path)}`;
      elements.filePreviewMeta.textContent = `${formatFileBytes(payload.bytes)} · complete text`;
      elements.fileState.textContent = "Editing";
      elements.fileEditor.focus();
    } catch (error) {
      if (generation !== filePreviewGeneration || selectedFilePath !== entry.path) return;
      elements.fileState.textContent = "Editor unavailable";
      showFilePreviewMessage(text(entry.name, entry.path), error instanceof Error ? error.message : String(error));
    } finally {
      setFileControls();
    }
  }

  async function createFile() {
    const name = globalThis.prompt("New file name or relative path:");
    if (name === null || !name.trim()) return;
    const path = joinFilePath(filePath, name.trim());
    setFileMutationBusy(true);
    try {
      await fileAction("write", { path, content: "", overwrite: false });
      selectedFilePath = path;
      await refreshFiles({ previewSelection: true });
      await openFileEditor();
    } catch (error) {
      elements.fileState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      setFileMutationBusy(false);
    }
  }

  async function finishFileMutation(destination, message) {
    const target = splitFilePath(destination);
    const opened = await navigateFiles(target.parent, destination);
    if (opened) elements.fileState.textContent = message;
  }

  async function copySelectedFile() {
    const entry = currentFileEntry();
    if (!entry) return;
    const current = splitFilePath(entry.path);
    const suggested = joinFilePath(current.parent, `${current.name}.copy`);
    const destination = globalThis.prompt("Copy to workspace path:", suggested);
    if (destination === null || !destination.trim()) return;
    const target = destination.trim();
    setFileMutationBusy(true);
    filePreviewGeneration += 1;
    clearFileEditor();
    try {
      const result = await fileAction("copy", {
        path: entry.path,
        destination: target,
      });
      const copied = text(result.destination, target);
      await finishFileMutation(copied, `Copied ${entry.path} to ${copied}`);
    } catch (error) {
      elements.fileState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      setFileMutationBusy(false);
    }
  }

  async function moveSelectedFile() {
    const entry = currentFileEntry();
    if (!entry) return;
    const destination = globalThis.prompt("Move to workspace path:", entry.path);
    if (destination === null || !destination.trim()) return;
    const target = destination.trim();
    setFileMutationBusy(true);
    filePreviewGeneration += 1;
    clearFileEditor();
    try {
      const result = await fileAction("move", {
        path: entry.path,
        destination: target,
      });
      const moved = text(result.destination, target);
      await finishFileMutation(moved, `Moved ${entry.path} to ${moved}`);
    } catch (error) {
      elements.fileState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      setFileMutationBusy(false);
    }
  }

  async function renameSelectedFile() {
    const entry = currentFileEntry();
    if (!entry) return;
    const current = splitFilePath(entry.path);
    const name = globalThis.prompt("New name:", current.name);
    if (name === null || !name.trim()) return;
    const nextName = name.trim();
    const destination = joinFilePath(current.parent, nextName);
    setFileMutationBusy(true);
    filePreviewGeneration += 1;
    clearFileEditor();
    try {
      const result = await fileAction("rename", {
        path: entry.path,
        name: nextName,
      });
      const renamed = text(result.destination, destination);
      await finishFileMutation(renamed, `Renamed ${entry.path} to ${renamed}`);
    } catch (error) {
      elements.fileState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      setFileMutationBusy(false);
    }
  }

  async function deleteSelectedFile() {
    const entry = currentFileEntry();
    if (!entry) return;
    const detail = entry.type === "dir" ? " and all of its contents" : "";
    if (!globalThis.confirm(`Delete ${entry.path}${detail}?`)) return;
    setFileMutationBusy(true);
    try {
      await fileAction("delete", { path: entry.path, recursive: entry.type === "dir" });
      selectedFilePath = "";
      filePreviewGeneration += 1;
      clearFileEditor();
      await refreshFiles();
      elements.fileState.textContent = `Deleted ${entry.path}`;
    } catch (error) {
      elements.fileState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      setFileMutationBusy(false);
    }
  }

  function render(data) {
    const counts = data.counts || {};
    const machines = Array.isArray(data.machines) ? data.machines : [];
    elements.version.textContent = text(data.version && data.version.version);
    elements.machineTotal.textContent = text(counts.total, machines.length);
    elements.machineOnline.textContent = text(counts.online, "0");
    elements.authMode.textContent = text(data.ui && data.ui.auth_mode, config.authMode);
    elements.lastUpdated.textContent = `Updated ${new Date().toLocaleTimeString()}`;

    renderDashboardMachines(machines);
    renderTerminalMachines(machines);
    renderFileMachines(machines);
    renderTodoMachines(machines);
    renderAuditMachines(machines);
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
      await refreshDashboard({ force: true });
      startDashboardPolling();
      await refreshRemotes({ force: true });
      startRemotePolling();
      try {
        await refreshTerminals();
      } catch (error) {
        if (error.authenticationRequired) throw error;
        elements.terminalState.textContent = "Terminal list unavailable";
        showTerminalMessage(error instanceof Error ? error.message : String(error));
      }
      try {
        await refreshFiles();
      } catch (error) {
        if (error.authenticationRequired) throw error;
        elements.fileState.textContent = "File list unavailable";
        showFilePreviewMessage("Files unavailable", error instanceof Error ? error.message : String(error));
      }
      try {
        await refreshTodoContext();
      } catch (error) {
        if (error.authenticationRequired) throw error;
        elements.sessionState.textContent = error instanceof Error ? error.message : "Session list unavailable";
        elements.todoState.textContent = "Session Todo unavailable";
        elements.sessionAuditState.textContent = "Session Audit unavailable";
      }
      await refreshAuditContext();
    } catch (error) {
      if (error.authenticationRequired) {
        terminalLoading = false;
        resetTerminalWorkspace("local");
        elements.terminalState.textContent = "Authentication required";
        stopDashboardPolling();
        stopRemotePolling();
        dashboardGeneration += 1;
        dashboardLoading = false;
        filePreviewGeneration += 1;
        todoGeneration += 1;
        auditGeneration += 1;
        auditDetailGeneration += 1;
        todoDirty = false;
        clearFileEditor();
        resetDashboardWorkspace("local");
        resetRemotes("Authentication required");
        elements.dashboardState.textContent = "Authentication required";
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
      const requestedMachine = terminalMachine;
      const name = elements.terminalName.value.trim();
      const result = await terminalAction("start", { cwd: ".", name: name || null });
      if (requestedMachine !== terminalMachine || result.machine !== requestedMachine) return;
      elements.terminalName.value = "";
      await refreshTerminals({ force: true });
      if (requestedMachine === terminalMachine) connectTerminal(result.shell_id);
    } catch (error) {
      elements.terminalState.textContent = "Unable to start terminal";
      showTerminalMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setTerminalControls(terminalSocket?.readyState === WebSocket.OPEN);
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
    if (terminalHistoryIndex !== terminalCommandHistory.length) {
      terminalHistoryIndex = terminalCommandHistory.length;
      terminalHistoryDraft = elements.terminalInput.value;
    }
  });

  elements.terminalLatest.addEventListener("click", jumpToLatestTerminalOutput);
  elements.terminalOutput.addEventListener("scroll", () => {
    if (terminalAtBottom()) {
      if (terminalPendingOutput !== null) jumpToLatestTerminalOutput();
      else terminalFollowOutput = true;
    } else {
      terminalFollowOutput = false;
    }
  });

  for (const button of elements.terminalKeyButtons) {
    button.addEventListener("click", () => {
      const data = terminalSpecialKeys[button.dataset.terminalKey || ""];
      if (data && sendTerminalData(data, false)) {
        if (terminalMode === "pty") terminalXterm?.focus();
        else elements.terminalInput.focus();
      }
    });
  }

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
      showTerminalMessage(`Terminal ${terminalMachine} / ${shellId} was terminated.`);
      await refreshTerminals({ force: true });
    } catch (error) {
      elements.terminalState.textContent = "Unable to kill terminal";
      showTerminalMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setTerminalControls(terminalSocket?.readyState === WebSocket.OPEN);
    }
  });

  elements.terminalMachine.addEventListener("change", () => {
    if (terminalLoading) return;
    resetTerminalWorkspace(elements.terminalMachine.value || "local");
    refreshTerminalsInBackground({ force: true });
  });

  elements.dashboardMachine.addEventListener("change", () => {
    if (dashboardLoading) return;
    resetDashboardWorkspace(elements.dashboardMachine.value || "local");
    refreshDashboardInBackground({ force: true });
  });
  elements.dashboardRefresh.addEventListener("click", () => {
    refreshDashboardInBackground({ force: true });
  });

  elements.auditMachine.addEventListener("change", () => {
    if (auditLoading) return;
    resetAuditWorkspace(elements.auditMachine.value || "local");
    void refreshAudit();
  });
  elements.auditFilterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void refreshAudit();
  });
  for (const control of [elements.auditOperation, elements.auditSort, elements.auditLimit]) {
    control.addEventListener("change", () => void refreshAudit());
  }

  elements.sessionMachine.addEventListener("change", () => {
    if (todoMutationBusy || sessionLoading || sessionTerminating) return;
    const next = elements.sessionMachine.value || "local";
    if (todoDirty && !globalThis.confirm(`Discard unsaved changes in ${todoSessionId}?`)) {
      elements.sessionMachine.value = todoMachine;
      return;
    }
    resetTodoWorkspace(next);
    void refreshTodoContext();
  });
  elements.sessionIncludeInactive.addEventListener("change", () => {
    if (sessionLoading || sessionTerminating) return;
    if (todoDirty && !globalThis.confirm(`Discard unsaved changes in ${todoSessionId}?`)) {
      elements.sessionIncludeInactive.checked = sessionIncludeInactive;
      return;
    }
    sessionIncludeInactive = elements.sessionIncludeInactive.checked;
    todoDirty = false;
    void refreshTodoContext();
  });
  elements.sessionRefresh.addEventListener("click", () => {
    if (sessionLoading || sessionTerminating) return;
    if (todoDirty && !globalThis.confirm(`Discard unsaved changes in ${todoSessionId}?`)) return;
    todoDirty = false;
    void refreshTodoContext();
  });
  elements.sessionTerminate.addEventListener("click", () => void terminateSelectedSession());

  elements.sessionAuditFilterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void refreshSessionAudit();
  });
  for (const control of [elements.sessionAuditOperation, elements.sessionAuditSort, elements.sessionAuditLimit]) {
    control.addEventListener("change", () => void refreshSessionAudit());
  }

  elements.todoFilter.addEventListener("change", renderTodos);
  elements.todoAdd.addEventListener("click", addTodo);
  elements.todoSave.addEventListener("click", () => void saveTodos());
  elements.todoRefresh.addEventListener("click", () => {
    if (todoMutationBusy || !todoSessionId) return;
    if (todoDirty && !globalThis.confirm(`Discard unsaved changes in ${todoSessionId}?`)) return;
    todoDirty = false;
    void refreshTodos({ force: true });
  });

  elements.fileMachine.addEventListener("change", () => {
    if (fileMutationBusy) return;
    resetFileWorkspace(elements.fileMachine.value || "local");
    void refreshFiles();
  });
  elements.filePathForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!fileMutationBusy) void navigateFiles(elements.filePath.value.trim() || ".");
  });
  elements.fileUp.addEventListener("click", () => void navigateFiles(fileParentPath));
  elements.fileRefresh.addEventListener("click", () => void refreshFiles());
  elements.fileShowHidden.addEventListener("change", () => {
    const entry = currentFileEntry();
    renderFileList();
    if (entry?.type === "dir" && selectedFilePath === entry.path) {
      void previewFile(entry);
    }
  });
  elements.fileNew.addEventListener("click", () => void createFile());
  elements.fileOpen.addEventListener("click", openSelectedFile);
  elements.fileEdit.addEventListener("click", () => void openFileEditor());
  elements.fileCopy.addEventListener("click", () => void copySelectedFile());
  elements.fileMove.addEventListener("click", () => void moveSelectedFile());
  elements.fileRename.addEventListener("click", () => void renameSelectedFile());
  elements.fileDelete.addEventListener("click", () => void deleteSelectedFile());
  elements.fileEditorCancel.addEventListener("click", () => {
    const entry = currentFileEntry();
    filePreviewGeneration += 1;
    clearFileEditor();
    elements.fileState.textContent = `${fileMachine}:${filePath}`;
    if (entry) void previewFile(entry);
    else showFilePreviewMessage("No file selected", `Select a file or directory on ${fileMachine}.`);
  });
  elements.fileEditorForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!fileEditorPath || !fileMutations.write) return;
    const path = fileEditorPath;
    const button = elements.fileEditorForm.querySelector('button[type="submit"]');
    button.disabled = true;
    setFileMutationBusy(true);
    elements.fileState.textContent = `Saving ${fileMachine}:${path}`;
    try {
      await fileAction("write", {
        path,
        content: elements.fileEditor.value,
        overwrite: true,
      });
      selectedFilePath = path;
      clearFileEditor();
      await refreshFiles();
      const entry = currentFileEntry();
      if (entry) await previewFile(entry);
      elements.fileState.textContent = `Saved ${fileMachine}:${path}`;
    } catch (error) {
      elements.fileState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      setFileMutationBusy(false);
      button.disabled = false;
    }
  });

  elements.remoteRefresh.addEventListener("click", () => refreshRemotesInBackground({ force: true }));
  elements.remoteInviteOpen.addEventListener("click", () => {
    if (!remoteEnabled || remoteLoading || elements.remoteInviteDialog.open) return;
    elements.remoteInviteForm.reset();
    elements.remoteInviteDialog.showModal();
    elements.remoteInviteName.focus();
  });
  elements.remoteRenameOpen.addEventListener("click", () => {
    const machine = selectedRemote();
    if (!machine || elements.remoteRenameDialog.open) return;
    elements.remoteRenameName.value = machine.name;
    elements.remoteRenameDialog.showModal();
    elements.remoteRenameName.select();
  });
  elements.remoteRevokeOpen.addEventListener("click", () => {
    const machine = selectedRemote();
    if (!machine || elements.remoteRevokeDialog.open) return;
    elements.remoteRevokeName.textContent = machine.name;
    elements.remoteRevokeDialog.showModal();
  });
  for (const button of document.querySelectorAll("[data-close-dialog]")) {
    button.addEventListener("click", () => {
      const dialog = document.getElementById(button.dataset.closeDialog || "");
      closeRemoteDialog(dialog);
    });
  }
  elements.remoteInviteDialog.addEventListener("close", () => {
    elements.remoteInviteForm.reset();
  });
  elements.remoteInviteResultDialog.addEventListener("close", () => {
    clearRemoteInviteResult({ close: false });
  });
  elements.remoteInviteResultClose.addEventListener("click", () => clearRemoteInviteResult());
  elements.remoteInviteDone.addEventListener("click", () => clearRemoteInviteResult());
  elements.remoteInviteCopy.addEventListener("click", async () => {
    if (!remoteInviteCommand) return;
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        throw new Error("Clipboard API is unavailable");
      }
      await navigator.clipboard.writeText(remoteInviteCommand);
      elements.remoteInviteCopy.textContent = "Copied";
    } catch (error) {
      elements.remoteInviteCopy.textContent = "Copy unavailable";
      elements.remoteState.textContent = error instanceof Error ? error.message : String(error);
    }
  });
  elements.remoteInviteForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = elements.remoteInviteForm.querySelector('button[type="submit"]');
    button.disabled = true;
    elements.remoteState.textContent = "Creating remote invite";
    try {
      const payload = await remoteAction("/remotes", {
        name: elements.remoteInviteName.value.trim() || null,
        workdir: elements.remoteInviteWorkdir.value.trim() || null,
        ttl_s: Number(elements.remoteInviteTtl.value),
      });
      remoteInviteCommand = text(payload?.command, "");
      if (!remoteInviteCommand) throw new Error("Invite response did not contain a command");
      elements.remoteInviteCommand.textContent = remoteInviteCommand;
      elements.remoteInviteExpiry.textContent = `Expires ${remoteTimestamp(payload?.expires_at, "at an unknown time")}`;
      closeRemoteDialog(elements.remoteInviteDialog);
      elements.remoteInviteResultDialog.showModal();
      elements.remoteInviteCommand.focus();
      elements.remoteState.textContent = "Remote invite created";
    } catch (error) {
      clearRemoteInviteResult();
      if (error.authenticationRequired) {
        void load();
        return;
      }
      elements.remoteState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      button.disabled = false;
    }
  });
  elements.remoteRenameForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const machine = selectedRemote();
    if (!machine) return;
    const newName = elements.remoteRenameName.value.trim();
    const button = elements.remoteRenameForm.querySelector('button[type="submit"]');
    button.disabled = true;
    elements.remoteState.textContent = `Renaming ${machine.name}`;
    try {
      const result = await remoteAction("/remotes/rename", {
        machine: machine.name,
        new_name: newName,
      });
      remoteSelectedName = text(result?.new_name, newName);
      closeRemoteDialog(elements.remoteRenameDialog);
      await load();
    } catch (error) {
      if (error.authenticationRequired) {
        void load();
        return;
      }
      elements.remoteState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      button.disabled = false;
    }
  });
  elements.remoteRevokeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const machine = selectedRemote();
    if (!machine) return;
    const button = elements.remoteRevokeForm.querySelector('button[type="submit"]');
    button.disabled = true;
    elements.remoteState.textContent = `Revoking ${machine.name}`;
    try {
      await remoteAction("/remotes/revoke", { machine: machine.name });
      remoteSelectedName = "";
      closeRemoteDialog(elements.remoteRevokeDialog);
      await load();
    } catch (error) {
      if (error.authenticationRequired) {
        void load();
        return;
      }
      elements.remoteState.textContent = error instanceof Error ? error.message : String(error);
    } finally {
      button.disabled = false;
    }
  });

  elements.oauthLogin.addEventListener("click", () => void startOAuth());
  elements.refresh.addEventListener("click", () => void load());
  elements.signOut.addEventListener("click", () => {
    terminalLoading = false;
    resetTerminalWorkspace("local");
    stopDashboardPolling();
    stopRemotePolling();
    resetDashboardWorkspace("local");
    resetRemotes("Authentication required");
    resetFileWorkspace("local");
    resetTodoWorkspace("local");
    resetAuditWorkspace("local");
    elements.terminalState.textContent = "Authentication required";
    elements.dashboardState.textContent = "Authentication required";
    elements.fileState.textContent = "Authentication required";
    elements.sessionState.textContent = "Authentication required";
    elements.todoState.textContent = "Authentication required";
    elements.sessionAuditState.textContent = "Authentication required";
    elements.auditState.textContent = "Authentication required";
    clearAccessToken();
    sessionStorage.removeItem(pendingStorageKey);
    elements.tokenInput.value = "";
    showAuthentication("Signed out", "The browser token was removed from this tab.");
  });

  window.addEventListener("resize", () => window.requestAnimationFrame(sendTerminalResize));
  window.addEventListener("beforeunload", () => {
    stopDashboardPolling();
    stopRemotePolling();
    clearRemoteInviteResult();
    closeTerminalSocket();
  });
  elements.oauthLogin.hidden = !oauthAvailable();
  elements.authMode.textContent = text(config.authMode);
  void boot();
  window.setInterval(() => {
    if (
      terminalSocket?.readyState === WebSocket.OPEN &&
      terminalSocketMachine === terminalMachine
    ) {
      terminalSocket.send(JSON.stringify({ type: "ping" }));
    }
    if (config.authMode !== "oauth" || accessToken) void load();
  }, 30000);
})();
