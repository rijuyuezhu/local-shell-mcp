export function createAuditController({
  elements,
  request,
  text,
  auditEntryButton,
  auditEntryTitle,
  auditTimestamp,
  renderAuditDetailInto,
  renderAuditDetailMessage,
}) {
  const controllerState = {
    auditMachine: "local",
    auditEntries: [],
    auditSelectedId: "",
    auditGeneration: 0,
    auditDetailGeneration: 0,
    auditLoading: false,
    auditMachineStates: new Map([["local", "online"]]),
  };

  function auditMachineOnline(machine = controllerState.auditMachine) {
    return machine === "local" || controllerState.auditMachineStates.get(machine) === "online";
  }

  function setAuditControls() {
    const online = auditMachineOnline();
    elements.auditRefresh.disabled = controllerState.auditLoading || !online;
    elements.auditMachine.disabled = controllerState.auditLoading;
    for (const control of elements.auditFilterForm.querySelectorAll("input, select")) {
      if (control !== elements.auditMachine) control.disabled = controllerState.auditLoading || !online;
    }
  }

  function clearAuditDetail(message = "Select a Global Audit record.") {
    controllerState.auditDetailGeneration += 1;
    elements.auditDetailTitle.textContent = "No record selected";
    elements.auditDetailMeta.textContent = controllerState.auditMachine;
    renderAuditDetailMessage(elements.auditDetailBody, message);
  }

  function resetAuditWorkspace(machine) {
    controllerState.auditMachine = machine || "local";
    controllerState.auditLoading = false;
    controllerState.auditEntries = [];
    controllerState.auditSelectedId = "";
    controllerState.auditGeneration += 1;
    elements.auditMachine.value = controllerState.auditMachine;
    elements.auditList.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = `Global Audit records for ${controllerState.auditMachine} are not loaded.`;
    elements.auditList.append(empty);
    elements.auditSummary.textContent = "0 entries";
    elements.auditState.textContent = `Not loaded · ${controllerState.auditMachine}`;
    clearAuditDetail();
    setAuditControls();
  }

  async function refreshAuditContext() {
    return refreshAudit();
  }

  function renderAuditMachines(machines) {
    const available = Array.isArray(machines) ? machines : [];
    controllerState.auditMachineStates = new Map([["local", "online"]]);
    elements.auditMachine.replaceChildren();
    let localPresent = false;
    let currentPresent = false;
    let currentOnline = controllerState.auditMachine === "local";
    for (const machine of available) {
      const name = text(machine.name, "");
      if (!name) continue;
      if (name === "local") localPresent = true;
      const state = name === "local" ? "online" : text(machine.status, "offline");
      const online = name === "local" || state === "online";
      controllerState.auditMachineStates.set(name, state);
      const option = document.createElement("option");
      option.value = name;
      option.textContent = online ? name : `${name} (${state})`;
      option.disabled = !online;
      option.selected = name === controllerState.auditMachine;
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
      local.selected = controllerState.auditMachine === "local";
      elements.auditMachine.prepend(local);
      if (local.selected) {
        currentPresent = true;
        currentOnline = true;
      }
    }
    if (!currentPresent && controllerState.auditMachine !== "local") {
      const stale = document.createElement("option");
      stale.value = controllerState.auditMachine;
      stale.textContent = `${controllerState.auditMachine} (unavailable)`;
      stale.disabled = true;
      stale.selected = true;
      elements.auditMachine.append(stale);
    }
    if (!currentPresent || !currentOnline) {
      const changed = controllerState.auditMachine !== "local";
      resetAuditWorkspace("local");
      if (changed) void refreshAudit();
    } else {
      elements.auditMachine.value = controllerState.auditMachine;
      setAuditControls();
    }
  }

  function renderAuditList() {
    elements.auditList.replaceChildren();
    if (!controllerState.auditEntries.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = `No Global Audit records match on ${controllerState.auditMachine}.`;
      elements.auditList.append(empty);
      clearAuditDetail("No matching Global Audit record is available.");
      return;
    }
    for (const entry of controllerState.auditEntries) {
      elements.auditList.append(
        auditEntryButton(entry, controllerState.auditSelectedId, () => {
          controllerState.auditSelectedId = text(entry.id, "");
          renderAuditList();
          void loadAuditDetail(controllerState.auditSelectedId);
        }),
      );
    }
  }

  function auditQueryPath() {
    const params = new URLSearchParams({
      machine: controllerState.auditMachine,
      scope: "global",
      limit: elements.auditLimit.value || "300",
      sort: elements.auditSort.value || "desc",
      include_selected: "true",
    });
    if (controllerState.auditSelectedId) params.set("selected_id", controllerState.auditSelectedId);
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
    const generation = ++controllerState.auditDetailGeneration;
    const requestedMachine = controllerState.auditMachine;
    elements.auditDetailTitle.textContent = auditEntryTitle(
      controllerState.auditEntries.find((entry) => entry.id === entryId) || {},
    );
    elements.auditDetailMeta.textContent = "Loading details";
    renderAuditDetailMessage(elements.auditDetailBody, `Loading ${requestedMachine}:${entryId}`);
    try {
      const params = new URLSearchParams({
        machine: requestedMachine,
        scope: "global",
        id: entryId,
      });
      const payload = await request(`/audit/detail?${params.toString()}`);
      if (
        generation !== controllerState.auditDetailGeneration ||
        requestedMachine !== controllerState.auditMachine ||
        entryId !== controllerState.auditSelectedId
      ) return null;
      const entry = payload && payload.entry && typeof payload.entry === "object" ? payload.entry : null;
      if (!entry) throw new Error("Audit detail response was malformed");
      elements.auditDetailTitle.textContent = auditEntryTitle(entry);
      elements.auditDetailMeta.textContent = `${requestedMachine} · Global · ${auditTimestamp(entry.ts)}`;
      renderAuditDetailInto(entry, elements.auditDetailBody);
      return entry;
    } catch (error) {
      if (
        generation !== controllerState.auditDetailGeneration ||
        requestedMachine !== controllerState.auditMachine ||
        entryId !== controllerState.auditSelectedId
      ) return null;
      elements.auditDetailMeta.textContent = "Details unavailable";
      renderAuditDetailMessage(
        elements.auditDetailBody,
        error instanceof Error ? error.message : String(error),
      );
      return null;
    }
  }

  async function refreshAudit() {
    if (controllerState.auditLoading || !auditMachineOnline()) return null;
    const generation = ++controllerState.auditGeneration;
    const requestedMachine = controllerState.auditMachine;
    const previousSelection = controllerState.auditSelectedId;
    controllerState.auditLoading = true;
    setAuditControls();
    elements.auditState.textContent = `Loading Global Audit · ${requestedMachine}`;
    try {
      const payload = await request(auditQueryPath());
      if (generation !== controllerState.auditGeneration || requestedMachine !== controllerState.auditMachine) return null;
      controllerState.auditDetailGeneration += 1;
      controllerState.auditEntries = Array.isArray(payload.entries) ? payload.entries.map((entry) => ({ ...entry })) : [];
      controllerState.auditSelectedId = controllerState.auditEntries.some((entry) => entry.id === previousSelection)
        ? previousSelection
        : text(controllerState.auditEntries[0] && controllerState.auditEntries[0].id, "");
      const total = Number.isInteger(payload.total_matched) ? payload.total_matched : controllerState.auditEntries.length;
      elements.auditSummary.textContent = `${controllerState.auditEntries.length} shown · ${total} matched · ${requestedMachine} · Global`;
      elements.auditState.textContent = `${requestedMachine} · loaded ${controllerState.auditEntries.length} global records`;
      renderAuditList();
      const selected = payload && payload.entry && typeof payload.entry === "object" ? payload.entry : null;
      if (selected && selected.id === controllerState.auditSelectedId) {
        elements.auditDetailTitle.textContent = auditEntryTitle(selected);
        elements.auditDetailMeta.textContent = `${requestedMachine} · Global · ${auditTimestamp(selected.ts)}`;
        renderAuditDetailInto(selected, elements.auditDetailBody);
      } else if (payload && payload.entry_error) {
        elements.auditDetailMeta.textContent = "Details unavailable";
        renderAuditDetailMessage(elements.auditDetailBody, text(payload.entry_error));
      } else if (controllerState.auditSelectedId) {
        void loadAuditDetail(controllerState.auditSelectedId);
      }
      return payload;
    } catch (error) {
      if (generation !== controllerState.auditGeneration || requestedMachine !== controllerState.auditMachine) return null;
      controllerState.auditEntries = [];
      controllerState.auditSelectedId = "";
      renderAuditList();
      elements.auditState.textContent = error instanceof Error ? error.message : String(error);
      return null;
    } finally {
      if (generation === controllerState.auditGeneration) {
        controllerState.auditLoading = false;
        setAuditControls();
      }
    }
  }

  function invalidate() {
    controllerState.auditGeneration += 1;
    controllerState.auditDetailGeneration += 1;
  }

  function bind() {
    elements.auditMachine.addEventListener("change", () => {
      if (controllerState.auditLoading) return;
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
  }

  return {
    bind,
    invalidate,
    refresh: refreshAudit,
    renderMachines: renderAuditMachines,
    reset: resetAuditWorkspace,
  };
}
