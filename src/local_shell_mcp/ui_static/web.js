(() => {
  "use strict";

  const config = JSON.parse(document.body.dataset.lsmConfig || "{}");
  const apiPrefix = config.apiPrefix || "/api/ui";
  const tokenStorageKey = "local-shell-mcp-ui-access-token";
  let accessToken = sessionStorage.getItem(tokenStorageKey) || "";

  const elements = {
    authForm: document.getElementById("auth-form"),
    authMode: document.getElementById("auth-mode"),
    authPanel: document.getElementById("auth-panel"),
    connectionState: document.getElementById("connection-state"),
    lastUpdated: document.getElementById("last-updated"),
    machineList: document.getElementById("machine-list"),
    machineOnline: document.getElementById("machine-online"),
    machineTotal: document.getElementById("machine-total"),
    refresh: document.getElementById("refresh"),
    tokenInput: document.getElementById("access-token"),
    version: document.getElementById("version"),
  };

  function setConnection(label, state) {
    elements.connectionState.textContent = label;
    elements.connectionState.className = `status status-${state}`;
  }

  function showAuthentication(message) {
    elements.authPanel.hidden = false;
    elements.tokenInput.setAttribute("aria-invalid", "true");
    setConnection(message || "Authentication required", "error");
  }

  function hideAuthentication() {
    elements.authPanel.hidden = true;
    elements.tokenInput.removeAttribute("aria-invalid");
  }

  async function request(path) {
    const headers = { Accept: "application/json" };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const response = await fetch(`${apiPrefix}${path}`, {
      headers,
      cache: "no-store",
      credentials: "same-origin",
    });
    if (response.status === 401 || response.status === 403) {
      const error = new Error("Authentication required");
      error.authenticationRequired = true;
      throw error;
    }
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || `Request failed (${response.status})`);
    }
    return payload.data;
  }

  function text(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
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
    } catch (error) {
      if (error.authenticationRequired) {
        showAuthentication("Authentication required");
      } else {
        setConnection("Unavailable", "error");
        elements.lastUpdated.textContent = error instanceof Error ? error.message : String(error);
      }
    } finally {
      elements.refresh.disabled = false;
    }
  }

  elements.authForm.addEventListener("submit", (event) => {
    event.preventDefault();
    accessToken = elements.tokenInput.value.trim();
    if (accessToken) sessionStorage.setItem(tokenStorageKey, accessToken);
    else sessionStorage.removeItem(tokenStorageKey);
    void load();
  });

  elements.refresh.addEventListener("click", () => void load());
  elements.authMode.textContent = text(config.authMode);
  void load();
  window.setInterval(() => void load(), 30000);
})();
