export function createDashboardController({
  elements,
  request,
  text,
  authMode,
  isAuthenticated,
  onAuthenticationRequired,
}) {
  const controllerState = {
    machine: "local",
    generation: 0,
    loading: false,
    machineStates: new Map([["local", "online"]]),
    history: [],
    timer: null,
  };

  function dashboardMachineOnline(machine = controllerState.machine) {
    return machine === "local" || controllerState.machineStates.get(machine) === "online";
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
    elements.dashboardRefresh.disabled = controllerState.loading || !online;
    elements.dashboardMachine.disabled = controllerState.loading;
  }

  function stopDashboardPolling() {
    if (controllerState.timer !== null) {
      window.clearInterval(controllerState.timer);
      controllerState.timer = null;
    }
  }

  function startDashboardPolling() {
    stopDashboardPolling();
    controllerState.timer = window.setInterval(() => {
      if ((authMode !== "oauth" || isAuthenticated()) && dashboardMachineOnline()) {
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
    controllerState.machine = machine || "local";
    controllerState.loading = false;
    controllerState.generation += 1;
    controllerState.history = [];
    elements.dashboardMachine.value = controllerState.machine;
    elements.dashboardState.textContent = `Not loaded · ${controllerState.machine}`;
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
    dashboardEmpty(elements.dashboardAlerts, `Alerts for ${controllerState.machine} are not loaded.`);
    dashboardEmpty(elements.dashboardActivity, `Activity for ${controllerState.machine} is not loaded.`);
    setDashboardControls();
  }

  function renderDashboardMachines(machines) {
    const available = Array.isArray(machines) ? machines : [];
    controllerState.machineStates = new Map([["local", "online"]]);
    elements.dashboardMachine.replaceChildren();
    let localPresent = false;
    let currentPresent = false;
    let currentOnline = controllerState.machine === "local";
    for (const machine of available) {
      const name = text(machine.name, "");
      if (!name) continue;
      if (name === "local") localPresent = true;
      const state = name === "local" ? "online" : text(machine.status, "offline");
      const online = name === "local" || state === "online";
      controllerState.machineStates.set(name, state);
      const option = document.createElement("option");
      option.value = name;
      option.textContent = online ? name : `${name} (${state})`;
      option.disabled = !online;
      option.selected = name === controllerState.machine;
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
      local.selected = controllerState.machine === "local";
      elements.dashboardMachine.prepend(local);
      if (local.selected) {
        currentPresent = true;
        currentOnline = true;
      }
    }
    if (!currentPresent && controllerState.machine !== "local") {
      const stale = document.createElement("option");
      stale.value = controllerState.machine;
      stale.textContent = `${controllerState.machine} (unavailable)`;
      stale.disabled = true;
      stale.selected = true;
      elements.dashboardMachine.append(stale);
    }
    if (!currentPresent || !currentOnline) {
      const changed = controllerState.machine !== "local";
      resetDashboardWorkspace("local");
      if (changed) refreshDashboardInBackground({ force: true });
    } else {
      elements.dashboardMachine.value = controllerState.machine;
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
    controllerState.history.push({
      cpu: dashboardNumber(system.cpu_percent),
      memory: dashboardNumber(system.memory_percent),
      disk: dashboardNumber(system.disk_percent),
      network: networkTotal,
    });
    controllerState.history = controllerState.history.slice(-60);

    const health = ["healthy", "attention", "critical"].includes(payload.health)
      ? payload.health
      : "attention";
    elements.dashboardHealth.textContent = health;
    elements.dashboardHealthCard.className = `dashboard-card dashboard-health-card dashboard-health-${health}`;
    elements.dashboardHealthDetail.textContent = alerts.length
      ? `${alerts.length} alert${alerts.length === 1 ? "" : "s"} on ${controllerState.machine}`
      : `No active alerts on ${controllerState.machine}`;
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
      controllerState.history.map((sample) => sample.cpu),
      100,
    );
    renderDashboardSparkline(
      elements.dashboardMemoryTrend,
      controllerState.history.map((sample) => sample.memory),
      100,
    );
    renderDashboardSparkline(
      elements.dashboardDiskTrend,
      controllerState.history.map((sample) => sample.disk),
      100,
    );
    renderDashboardSparkline(
      elements.dashboardNetworkTrend,
      controllerState.history.map((sample) => sample.network),
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
            text(alert.node, controllerState.machine),
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
    elements.dashboardState.textContent = `${controllerState.machine} · ${health} · updated ${new Date().toLocaleTimeString()}`;
  }

  function dashboardQueryPath() {
    const params = new URLSearchParams({ machine: controllerState.machine });
    return `/dashboard?${params.toString()}`;
  }

  async function refreshDashboard({ force = false } = {}) {
    if ((controllerState.loading && !force) || !dashboardMachineOnline()) return null;
    const generation = ++controllerState.generation;
    const requestedMachine = controllerState.machine;
    controllerState.loading = true;
    setDashboardControls();
    elements.dashboardState.textContent = `Loading ${requestedMachine}`;
    try {
      const payload = await request(dashboardQueryPath());
      if (generation !== controllerState.generation || requestedMachine !== controllerState.machine) return null;
      renderDashboard(payload);
      return payload;
    } catch (error) {
      if (error.authenticationRequired) throw error;
      if (generation !== controllerState.generation || requestedMachine !== controllerState.machine) return null;
      elements.dashboardState.textContent = error instanceof Error ? error.message : String(error);
      elements.dashboardHealth.textContent = "unavailable";
      elements.dashboardHealthCard.className = "dashboard-card dashboard-health-card dashboard-health-attention";
      elements.dashboardHealthDetail.textContent = `Telemetry for ${requestedMachine} could not be loaded`;
      return null;
    } finally {
      if (generation === controllerState.generation) {
        controllerState.loading = false;
        setDashboardControls();
      }
    }
  }

  function refreshDashboardInBackground(options = {}) {
    void refreshDashboard(options).catch((error) => {
      if (error.authenticationRequired) onAuthenticationRequired();
    });
  }


  function invalidate() {
    controllerState.generation += 1;
    controllerState.loading = false;
    setDashboardControls();
  }

  function bind() {
    elements.dashboardMachine.addEventListener("change", () => {
      if (controllerState.loading) return;
      resetDashboardWorkspace(elements.dashboardMachine.value || "local");
      refreshDashboardInBackground({ force: true });
    });
    elements.dashboardRefresh.addEventListener("click", () => {
      refreshDashboardInBackground({ force: true });
    });
  }

  return {
    bind,
    invalidate,
    refresh: refreshDashboard,
    renderMachines: renderDashboardMachines,
    reset: resetDashboardWorkspace,
    startPolling: startDashboardPolling,
    stopPolling: stopDashboardPolling,
  };
}
