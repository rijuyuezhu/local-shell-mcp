void (async () => {
  "use strict";

  const config = JSON.parse(document.body.dataset.lsmConfig || "{}");
  const uiPath = String(config.uiPath || "/ui").replace(/\/$/, "");
  const { createDashboardController } = await import(`${uiPath}/assets/dashboard.js`);
  const { createRemotesController } = await import(`${uiPath}/assets/remotes.js`);
  const { createAuditView } = await import(`${uiPath}/assets/audit_view.js`);
  const { createAuditController } = await import(`${uiPath}/assets/audit.js`);
  const { createTerminalController } = await import(`${uiPath}/assets/terminal.js`);
  const { createSessionsController } = await import(`${uiPath}/assets/sessions.js`);
  const apiPrefix = String(config.apiPrefix || "/api/ui").replace(/\/$/, "");
  const oauth = config.oauth && typeof config.oauth === "object" ? config.oauth : null;
  const wallpaper = ["aurora", "grid", "none"].includes(String(config.wallpaper || ""))
    ? String(config.wallpaper)
    : "aurora";
  document.body.dataset.wallpaper = wallpaper;
  const legacyTokenStorageKey = "local-shell-mcp-ui-access-token";
  const pendingStorageKey = "local-shell-mcp-ui-oauth-pending";
  const pendingMaxAgeMs = 10 * 60 * 1000;
  const csrfCookieName = String(config.csrfCookieName || "");
  const csrfHeaderName = String(config.csrfHeaderName || "x-local-shell-mcp-ui-csrf");
  const sessionBindingHeaderName = String(
    config.sessionBindingHeaderName || "x-local-shell-mcp-ui-binding",
  );
  const sessionBindingProtocolPrefix = String(
    config.sessionBindingProtocolPrefix || "lsm-ui-binding.",
  );
  const sessionBindingStorageKey = String(
    config.sessionBindingStorageKey || "local-shell-mcp-ui-session-binding",
  );
  const sessionEstablishedStorageKey = String(
    config.sessionEstablishedStorageKey || "local-shell-mcp-ui-session-established",
  );
  sessionStorage.removeItem(legacyTokenStorageKey);
  const viewDefinitions = Object.freeze({
    overview: {
      title: "Overview",
      description: "System health across local and remote coding environments.",
    },
    machines: {
      title: "Machines",
      description: "Controller and worker targets available to the Human UI.",
    },
    remotes: {
      title: "Remotes",
      description: "Enroll, inspect, rename, and revoke outbound remote workers.",
    },
    sessions: {
      title: "Sessions",
      description: "Inspect agent sessions, todos, lifecycle state, and scoped Audit records.",
    },
    terminals: {
      title: "Terminals",
      description: "Persistent local and remote tmux terminals with interactive streaming.",
    },
    files: {
      title: "Files",
      description: "Browse and edit workspace-scoped files on the selected machine.",
    },
    audit: {
      title: "Audit",
      description: "Search machine-wide activity and control-plane events.",
    },
    console: {
      title: "OpenTUI",
      description: "Run the optional terminal-native interface inside the browser.",
    },
  });
  const encoder = new TextEncoder();
  let authenticated = config.authMode !== "oauth";
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
  const elements = {
    appNavItems: Array.from(document.querySelectorAll(".nav-item[data-view]")),
    appViews: Array.from(document.querySelectorAll("[data-app-view]")),
    pageDescription: document.getElementById("page-description"),
    pageTitle: document.getElementById("page-title"),
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
    remoteDetailProfile: document.getElementById("remote-detail-profile"),
    remoteDetailPython: document.getElementById("remote-detail-python"),
    remoteDetailQueue: document.getElementById("remote-detail-queue"),
    remoteDetailReconnect: document.getElementById("remote-detail-reconnect"),
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
    remoteReconnectCopy: document.getElementById("remote-reconnect-copy"),
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

  const {
    auditEntryButton,
    auditEntryTitle,
    auditTimestamp,
    renderAuditDetailInto,
    renderAuditDetailMessage,
  } = createAuditView({ text, formatFileBytes });

  const audit = createAuditController({
    elements,
    request,
    text,
    auditEntryButton,
    auditEntryTitle,
    auditTimestamp,
    renderAuditDetailInto,
    renderAuditDetailMessage,
  });
  audit.bind();

  const terminal = createTerminalController({
    elements,
    request,
    text,
    encoder,
    uiPath,
    sessionBindingToken,
    sessionBindingProtocolPrefix,
    showAuthentication,
    onAuthenticationRequired: () => void load(),
  });
  terminal.bind();


  const sessions = createSessionsController({
    elements,
    request,
    text,
    auditEntryButton,
    auditEntryTitle,
    auditTimestamp,
    renderAuditDetailInto,
    renderAuditDetailMessage,
  });
  sessions.bind();

  const dashboard = createDashboardController({
    elements,
    request,
    text,
    authMode: config.authMode,
    isAuthenticated: () => authenticated,
    onAuthenticationRequired: () => void load(),
  });
  dashboard.bind();

  const remotes = createRemotesController({
    elements,
    request,
    text,
    authMode: config.authMode,
    isAuthenticated: () => authenticated,
    reloadApp: () => load(),
  });
  remotes.bind();

  function normalizeView(value) {
    const candidate = String(value || "").replace(/^#/, "");
    if (!Object.prototype.hasOwnProperty.call(viewDefinitions, candidate)) return "overview";
    if (candidate === "console" && !config.opentuiAvailable) return "overview";
    return candidate;
  }

  function viewFromLocation() {
    return normalizeView(location.hash.slice(1));
  }

  function setActiveView(value, { syncHash = true, replaceHash = false } = {}) {
    const view = normalizeView(value);
    const definition = viewDefinitions[view];
    document.body.dataset.activeView = view;
    elements.pageTitle.textContent = definition.title;
    elements.pageDescription.textContent = definition.description;
    document.title = `${definition.title} · local-shell-mcp`;

    for (const item of elements.appNavItems) {
      const active = item.dataset.view === view;
      item.classList.toggle("active", active);
      if (active) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    }
    for (const panel of elements.appViews) {
      panel.hidden = panel.dataset.appView !== view;
    }

    if (syncHash && location.hash !== `#${view}`) {
      const url = `${location.pathname}${location.search}#${view}`;
      if (replaceHash) history.replaceState({}, "", url);
      else history.pushState({}, "", url);
    }
    window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }

  function setConnection(label, state) {
    elements.connectionState.textContent = label;
    elements.connectionState.className = `status status-${state}`;
  }

  function cookieValue(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    for (const part of document.cookie.split(";")) {
      const item = part.trim();
      if (item.startsWith(prefix)) return decodeURIComponent(item.slice(prefix.length));
    }
    return "";
  }

  function oauthAvailable() {
    return config.authMode === "oauth" && oauth !== null;
  }

  function showAuthentication(message, detail) {
    authenticated = false;
    elements.authPanel.hidden = false;
    elements.oauthLogin.hidden = !oauthAvailable();
    elements.oauthLogin.disabled = false;
    elements.signOut.hidden = true;
    elements.tokenInput.setAttribute("aria-invalid", "true");
    elements.authDetail.textContent = detail || "Sign in through the local-shell-mcp OAuth approval page.";
    setConnection(message || "Authentication required", "error");
  }

  function hideAuthentication() {
    authenticated = true;
    elements.authPanel.hidden = true;
    elements.tokenInput.removeAttribute("aria-invalid");
    elements.signOut.hidden = config.authMode !== "oauth";
  }

  async function responsePayload(response) {
    try {
      return await response.json();
    } catch {
      return {};
    }
  }

  function validSessionBindingToken(value) {
    return /^[A-Za-z0-9_-]{43,128}$/.test(String(value || ""));
  }

  function sessionBindingToken() {
    if (config.authMode !== "oauth") return "";
    try {
      const value = localStorage.getItem(sessionBindingStorageKey) || "";
      return validSessionBindingToken(value) ? value : "";
    } catch {
      return "";
    }
  }

  function ensureSessionBindingToken() {
    const existing = sessionBindingToken();
    if (existing) return existing;
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    const created = base64Url(bytes);
    try {
      localStorage.setItem(sessionBindingStorageKey, created);
    } catch {
      throw new Error("Persistent browser storage is unavailable for secure session binding.");
    }
    return created;
  }

  function clearSessionBindingToken() {
    try {
      localStorage.removeItem(sessionBindingStorageKey);
    } catch {
      // The server-side session is still cleared when browser storage is unavailable.
    }
  }

  function announceSessionEstablished() {
    try {
      const bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      localStorage.setItem(
        sessionEstablishedStorageKey,
        `${Date.now()}.${base64Url(bytes)}`,
      );
    } catch {
      // The current tab can still use the new cookie when cross-tab signaling is unavailable.
    }
  }

  async function request(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    const bindingToken = sessionBindingToken();
    if (bindingToken) headers[sessionBindingHeaderName] = bindingToken;
    const method = String(options.method || "GET").toUpperCase();
    if (!new Set(["GET", "HEAD", "OPTIONS"]).has(method)) {
      const csrfToken = cookieValue(csrfCookieName);
      if (csrfToken) headers[csrfHeaderName] = csrfToken;
    }
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
      ensureSessionBindingToken();
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
    const response = await fetch(oauthEndpoint("sessionOAuthEndpoint"), {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/json",
        [sessionBindingHeaderName]: ensureSessionBindingToken(),
      },
      body: form,
      cache: "no-store",
      credentials: "same-origin",
    });
    const result = await responsePayload(response);
    if (!response.ok || !result.ok) {
      throw new Error(
        result.error_description || result.error || result.detail || "OAuth session exchange failed.",
      );
    }
    announceSessionEstablished();
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

    dashboard.renderMachines(machines);
    terminal.renderMachines(machines);
    renderFileMachines(machines);
    sessions.renderMachines(machines);
    audit.renderMachines(machines);
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
      await dashboard.refresh({ force: true });
      dashboard.startPolling();
      await remotes.refresh({ force: true });
      remotes.startPolling();
      try {
        await terminal.refresh();
      } catch (error) {
        if (error.authenticationRequired) throw error;
        elements.terminalState.textContent = "Terminal list unavailable";
        terminal.showMessage(error instanceof Error ? error.message : String(error));
      }
      try {
        await refreshFiles();
      } catch (error) {
        if (error.authenticationRequired) throw error;
        elements.fileState.textContent = "File list unavailable";
        showFilePreviewMessage("Files unavailable", error instanceof Error ? error.message : String(error));
      }
      try {
        await sessions.refresh();
      } catch (error) {
        if (error.authenticationRequired) throw error;
        elements.sessionState.textContent = error instanceof Error ? error.message : "Session list unavailable";
        elements.todoState.textContent = "Session Todo unavailable";
        elements.sessionAuditState.textContent = "Session Audit unavailable";
      }
      await audit.refresh();
    } catch (error) {
      if (error.authenticationRequired) {
        terminal.reset("local");
        elements.terminalState.textContent = "Authentication required";
        dashboard.stopPolling();
        remotes.stopPolling();
        dashboard.invalidate();
        filePreviewGeneration += 1;
        sessions.invalidate();
        audit.invalidate();
        clearFileEditor();
        dashboard.reset("local");
        remotes.reset("Authentication required");
        elements.dashboardState.textContent = "Authentication required";
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
      await load();
      if (elements.authPanel.hidden) {
        elements.lastUpdated.textContent = `OAuth callback ignored: ${message}`;
      } else {
        showAuthentication("Unable to sign in", message);
      }
      return;
    }
    await load();
  }

  elements.authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    terminal.close();
    const token = elements.tokenInput.value.trim();
    if (!token) {
      showAuthentication("Access token required", "Paste a valid OAuth access token.");
      return;
    }
    elements.tokenInput.disabled = true;
    try {
      const response = await fetch(oauthEndpoint("sessionTokenEndpoint"), {
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${token}`,
          [sessionBindingHeaderName]: ensureSessionBindingToken(),
        },
        cache: "no-store",
        credentials: "same-origin",
      });
      const result = await responsePayload(response);
      if (!response.ok || !result.ok) {
        throw new Error(result.message || result.detail || "Unable to establish Human UI session.");
      }
      announceSessionEstablished();
      elements.tokenInput.value = "";
      await load();
    } catch (error) {
      showAuthentication(
        "Unable to sign in",
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      elements.tokenInput.disabled = false;
    }
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

  elements.oauthLogin.addEventListener("click", () => void startOAuth());
  elements.refresh.addEventListener("click", () => void load());
  elements.signOut.addEventListener("click", async () => {
    try {
      await request("/session/logout", { method: "POST" });
    } catch {
      // Local UI state is still cleared when the server session already expired.
    }
    terminal.reset("local");
    dashboard.stopPolling();
    remotes.stopPolling();
    dashboard.reset("local");
    remotes.reset("Authentication required");
    resetFileWorkspace("local");
    sessions.reset("local");
    audit.reset("local");
    elements.terminalState.textContent = "Authentication required";
    elements.dashboardState.textContent = "Authentication required";
    elements.fileState.textContent = "Authentication required";
    elements.sessionState.textContent = "Authentication required";
    elements.todoState.textContent = "Authentication required";
    elements.sessionAuditState.textContent = "Authentication required";
    elements.auditState.textContent = "Authentication required";
    sessionStorage.removeItem(pendingStorageKey);
    clearSessionBindingToken();
    elements.tokenInput.value = "";
    showAuthentication("Signed out", "The persistent browser session was cleared.");
  });

  for (const item of elements.appNavItems) {
    item.addEventListener("click", () => setActiveView(item.dataset.view));
  }
  if (!config.opentuiAvailable) {
    const consoleNav = elements.appNavItems.find((item) => item.dataset.view === "console");
    if (consoleNav) consoleNav.hidden = true;
  }
  const restoreViewFromLocation = () => setActiveView(viewFromLocation(), { syncHash: false });
  window.addEventListener("popstate", restoreViewFromLocation);
  window.addEventListener("hashchange", restoreViewFromLocation);
  window.addEventListener("storage", (event) => {
    if (event.key === sessionBindingStorageKey) {
      if (event.oldValue === null && event.newValue !== null) return;
    } else if (event.key !== sessionEstablishedStorageKey) {
      return;
    }
    terminal.close();
    void load();
  });

  window.addEventListener("resize", () => window.requestAnimationFrame(terminal.resize));
  window.addEventListener("beforeunload", () => {
    dashboard.stopPolling();
    remotes.stopPolling();
    remotes.clearInviteResult();
    terminal.close();
  });
  elements.oauthLogin.hidden = !oauthAvailable();
  elements.authMode.textContent = text(config.authMode);
  setActiveView(viewFromLocation(), { replaceHash: true });
  void boot();
  window.setInterval(() => {
    terminal.ping();
    if (config.authMode !== "oauth" || authenticated) void load();
  }, 30000);
})();
