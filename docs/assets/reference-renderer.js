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

  function renderMarkdownInline(value) {
    return String(value ?? "")
      .split(/(`[^`]*`)/g)
      .map((part) => {
        if (part.startsWith("`") && part.endsWith("`")) {
          return `<code>${escapeHtml(part.slice(1, -1))}</code>`;
        }
        return escapeHtml(part);
      })
      .join("");
  }

  function renderMarkdown(markdown) {
    const lines = String(markdown ?? "").split(/\r?\n/);
    const html = [];
    let paragraph = [];
    let listOpen = false;
    let codeFence = null;
    let codeLines = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      html.push(`<p>${renderMarkdownInline(paragraph.join(" "))}</p>`);
      paragraph = [];
    };

    const closeList = () => {
      if (!listOpen) return;
      html.push("</ul>");
      listOpen = false;
    };

    const flushCode = () => {
      if (codeFence === null) return;
      html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
      codeFence = null;
      codeLines = [];
    };

    for (const line of lines) {
      const fence = line.match(/^```/);
      if (fence) {
        if (codeFence === null) {
          flushParagraph();
          closeList();
          codeFence = line;
        } else {
          flushCode();
        }
        continue;
      }

      if (codeFence !== null) {
        codeLines.push(line);
        continue;
      }

      if (!line.trim()) {
        flushParagraph();
        closeList();
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        closeList();
        const level = Math.min(6, heading[1].length + 1);
        html.push(`<h${level}>${renderMarkdownInline(heading[2])}</h${level}>`);
        continue;
      }

      const bullet = line.match(/^[-*]\s+(.+)$/);
      if (bullet) {
        flushParagraph();
        if (!listOpen) {
          html.push("<ul>");
          listOpen = true;
        }
        html.push(`<li>${renderMarkdownInline(bullet[1])}</li>`);
        continue;
      }

      paragraph.push(line.trim());
    }

    flushCode();
    flushParagraph();
    closeList();
    return html.join("");
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
    } else if (section.kind === "markdown") {
      html += renderMarkdown(section.markdown || "");
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
