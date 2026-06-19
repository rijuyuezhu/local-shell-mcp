(function () {
  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  function renderInline(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      return escapeHtml(value);
    }
    if (Array.isArray(value)) return value.map(renderInline).join("");
    if (value.code !== undefined) return `<code>${escapeHtml(value.code)}</code>`;
    if (value.small !== undefined) return `<small>${escapeHtml(value.small)}</small>`;
    if (value.text !== undefined) return escapeHtml(value.text);
    if (value.lines) return value.lines.map(renderInline).join("<br>");
    if (value.parts) return value.parts.map(renderInline).join("");
    return escapeHtml(JSON.stringify(value));
  }

  function renderCell(value) {
    if (value && value.items) {
      const items = value.items;
      if (!items.length) return "none";
      return items
        .map((item) => {
          const head = renderInline(item.head);
          const note = item.note ? ` ${renderInline({ small: item.note })}` : "";
          const description = item.description ? `<br><small>${escapeHtml(item.description)}</small>` : "";
          return `${head}${note}${description}`;
        })
        .join("<br>");
    }
    return renderInline(value);
  }

  function renderTable(section) {
    const headers = section.headers || [];
    const rows = section.rows || [];
    return `<table><thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${rows
      .map((row) => `<tr>${row.map((cell) => `<td>${renderCell(cell)}</td>`).join("")}</tr>`)
      .join("")}</tbody></table>`;
  }

  function renderSection(section) {
    let html = section.heading ? `<h2>${escapeHtml(section.heading)}</h2>` : "";
    if (section.body) html += `<p>${renderInline(section.body)}</p>`;
    if (section.kind === "code") {
      html += `<pre><code>${escapeHtml(section.code || "")}</code></pre>`;
    } else if (section.kind === "table") {
      html += renderTable(section);
    }
    return html;
  }

  async function renderReference(target) {
    if (target.dataset.referenceRendered === "true") return;
    target.dataset.referenceRendered = "true";
    try {
      const response = await fetch(target.dataset.referenceJson, { credentials: "same-origin" });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const data = await response.json();
      target.innerHTML = (data.sections || []).map(renderSection).join("");
    } catch (error) {
      target.innerHTML = `<p><strong>Could not load generated reference data.</strong></p><p>${escapeHtml(error.message)}</p>`;
    }
  }

  function initGeneratedReferences() {
    document.querySelectorAll("[data-reference-json]").forEach(renderReference);
  }

  if (typeof document$ !== "undefined") {
    document$.subscribe(initGeneratedReferences);
  } else {
    document.addEventListener("DOMContentLoaded", initGeneratedReferences);
  }
})();
