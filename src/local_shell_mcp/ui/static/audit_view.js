export function createAuditView({ text, formatFileBytes }) {
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

  function isAuditRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function cleanAuditValue(value) {
    if (value === undefined) return undefined;
    if (Array.isArray(value)) {
      return value.map(cleanAuditValue);
    }
    if (isAuditRecord(value)) {
      const entries = Object.entries(value)
        .map(([key, item]) => [key, cleanAuditValue(item)])
        .filter(([, item]) => item !== undefined);
      return Object.fromEntries(entries);
    }
    return value;
  }

  function parseAuditJsonString(value) {
    const trimmed = value.trim();
    if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return value;
    try {
      return JSON.parse(trimmed);
    } catch {
      return value;
    }
  }

  function unwrapAuditToolEnvelope(value) {
    if (!isAuditRecord(value) || !("data" in value)) return value;
    const allowed = new Set(["ok", "message", "data", "error", "error_type"]);
    if (Object.keys(value).some((key) => !allowed.has(key))) return value;
    const data = cleanAuditValue(value.data);
    const message = cleanAuditValue(value.message);
    const error = cleanAuditValue(value.error);
    const errorType = cleanAuditValue(value.error_type);
    if (
      value.ok === false ||
      (error !== undefined && error !== null) ||
      (errorType !== undefined && errorType !== null)
    ) {
      return cleanAuditValue({ message, error, error_type: errorType, data });
    }
    return data === undefined ? message : data;
  }

  function auditInput(entry) {
    if (entry.input !== undefined) return entry.input;
    if (isAuditRecord(entry.arguments)) {
      return entry.arguments.keyword_args ?? entry.arguments;
    }
    const fallback = {};
    for (const key of ["command", "cwd", "path", "url", "session", "machine"]) {
      if (entry[key] !== undefined) fallback[key] = entry[key];
    }
    return Object.keys(fallback).length ? cleanAuditValue(fallback) : undefined;
  }

  const AUDIT_DETAIL_METADATA_FIELDS = new Set([
    "id",
    "ts",
    "event",
    "tool",
    "node",
    "operation",
    "paired",
    "status",
    "source_events",
    "call_id",
    "session",
    "input",
    "arguments",
    "output",
    "result",
    "related_events",
    "image_preview",
    "image_preview_error",
    "command",
    "cwd",
    "path",
    "url",
    "machine",
    "ok",
    "error",
    "error_type",
    "exit_code",
    "timed_out",
    "duration_ms",
    "stdout",
    "stderr",
    "truncated",
  ]);

  function auditSupplementalDetails(entry) {
    const details = {};
    for (const [key, value] of Object.entries(entry)) {
      if (!AUDIT_DETAIL_METADATA_FIELDS.has(key)) details[key] = value;
    }
    const cleaned = cleanAuditValue(details);
    return isAuditRecord(cleaned) && Object.keys(cleaned).length ? cleaned : undefined;
  }

  function auditOutput(entry) {
    let output;
    if (entry.output !== undefined) output = entry.output;
    else if (entry.result !== undefined) output = entry.result;
    else {
      const fallback = {};
      for (const key of [
        "ok",
        "error",
        "error_type",
        "exit_code",
        "timed_out",
        "duration_ms",
        "stdout",
        "stderr",
        "truncated",
      ]) {
        if (entry[key] !== undefined) fallback[key] = entry[key];
      }
      output = Object.keys(fallback).length ? cleanAuditValue(fallback) : undefined;
    }
    const related = cleanAuditValue(entry.related_events);
    const details = auditSupplementalDetails(entry);
    if (related === undefined && details === undefined) return output;
    if (output === undefined && related === undefined) return details;
    return cleanAuditValue({
      result: unwrapAuditToolEnvelope(output),
      related_events: related,
      details,
    });
  }

  function auditValueSource(value, emptyLabel) {
    const parsed = typeof value === "string" ? parseAuditJsonString(value) : value;
    const cleaned = cleanAuditValue(unwrapAuditToolEnvelope(parsed));
    if (cleaned === undefined) return { source: emptyLabel, language: "plain" };
    if (typeof cleaned === "string") return { source: cleaned, language: "plain" };
    return { source: JSON.stringify(cleaned, null, 2), language: "json" };
  }

  function renderAuditValue(target, value, emptyLabel) {
    const pre = document.createElement("pre");
    pre.className = "audit-detail-json";
    const { source, language } = auditValueSource(value, emptyLabel);
    if (window.LsmSyntax) window.LsmSyntax.render(pre, source, language);
    else pre.textContent = source;
    target.append(pre);
  }

  function renderAuditDetailMessage(target, message) {
    const empty = document.createElement("div");
    empty.className = "empty-state audit-detail-message";
    empty.textContent = message;
    target.replaceChildren(empty);
  }

  function auditCallPanel(title) {
    const panel = document.createElement("section");
    panel.className = "audit-call-panel";
    panel.setAttribute("aria-label", title);
    const heading = document.createElement("div");
    heading.className = "audit-call-panel-heading";
    heading.textContent = title;
    const body = document.createElement("div");
    body.className = "audit-call-panel-body";
    body.tabIndex = 0;
    body.setAttribute("aria-label", `${title} content`);
    panel.append(heading, body);
    return { panel, body };
  }

  function renderAuditDetailInto(entry, target) {
    const requestPanel = auditCallPanel("Call request");
    renderAuditValue(requestPanel.body, auditInput(entry), "No input recorded");

    const resultPanel = auditCallPanel("Call result");
    const preview = isAuditRecord(entry.image_preview) ? entry.image_preview : null;
    if (preview && preview.data_base64 && preview.mime_type) {
      const figure = document.createElement("figure");
      figure.className = "audit-image-preview";
      const image = document.createElement("img");
      image.alt = text(preview.path, "Audited image result");
      image.src = `data:${preview.mime_type};base64,${preview.data_base64}`;
      const caption = document.createElement("figcaption");
      caption.textContent = `${text(preview.path, "image result")} · ${formatFileBytes(preview.bytes)}`;
      figure.append(image, caption);
      resultPanel.body.append(figure);
    } else if (entry.image_preview_error) {
      const warning = document.createElement("div");
      warning.className = "audit-preview-error";
      warning.textContent = `Image preview unavailable: ${entry.image_preview_error}`;
      resultPanel.body.append(warning);
    }
    renderAuditValue(resultPanel.body, auditOutput(entry), "No output recorded");
    target.replaceChildren(requestPanel.panel, resultPanel.panel);
  }


  return {
    auditEntryButton,
    auditEntryTitle,
    auditTimestamp,
    renderAuditDetailInto,
    renderAuditDetailMessage,
  };
}
