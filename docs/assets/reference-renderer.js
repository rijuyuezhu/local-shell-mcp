(function () {
  const toolGroups = [
    ["Read-only connector tools", ["search", "fetch"]],
    ["Environment and safety", ["environment_info", "secret_scan"]],
    [
      "Shell and Python",
      [
        "run_shell_command",
        "run_python_code",
        "start_persistent_shell",
        "send_persistent_shell_input",
        "read_persistent_shell_output",
        "kill_persistent_shell",
        "list_persistent_shells",
      ],
    ],
    [
      "Filesystem and search",
      [
        "list_files",
        "tree_view",
        "glob_search",
        "grep_search",
        "read_file",
        "read_many_files",
        "write_file",
        "edit_file",
        "multi_edit_file",
        "delete_file_or_dir",
        "apply_patch",
      ],
    ],
    ["File download links", ["create_file_link", "list_file_links", "revoke_file_link"]],
    ["Todo state", ["read_todos", "write_todos"]],
    [
      "Remote worker management",
      [
        "remote_invite",
        "remote_list_machines",
        "remote_revoke_machine",
        "remote_rename_machine",
        "remote_environment_info",
      ],
    ],
    [
      "Remote shell and Python",
      [
        "run_remote_shell_command",
        "run_remote_python_code",
        "start_remote_persistent_shell",
        "send_remote_persistent_shell_input",
        "read_remote_persistent_shell_output",
        "kill_remote_persistent_shell",
        "list_remote_persistent_shells",
      ],
    ],
    [
      "Remote filesystem and search",
      [
        "remote_list_files",
        "remote_tree_view",
        "remote_glob_search",
        "remote_grep_search",
        "remote_read_file",
        "remote_read_many_files",
        "remote_write_file",
        "remote_edit_file",
        "remote_multi_edit_file",
        "remote_delete_file_or_dir",
        "remote_apply_patch",
      ],
    ],
    [
      "Remote file transfer",
      [
        "remote_push_file",
        "remote_pull_file",
        "remote_copy_file",
        "remote_push_dir",
        "remote_pull_dir",
        "remote_copy_dir",
      ],
    ],
  ];

  const escapeHtml = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const code = (value) => `<code>${escapeHtml(value)}</code>`;

  const compact = (value) => escapeHtml(String(value ?? "").replace(/\s+/g, " ").trim());

  function schemaType(schema) {
    if (!schema || typeof schema !== "object") return "value";
    if (Array.isArray(schema.enum)) return schema.enum.map(String).join(" / ");
    if (Array.isArray(schema.type)) return schema.type.join(" / ");
    if (schema.type) return String(schema.type);
    const variants = schema.anyOf || schema.oneOf;
    if (Array.isArray(variants)) return variants.map(schemaType).join(" / ");
    if (schema.items) return "array";
    if (schema.$ref) return String(schema.$ref).split("/").pop();
    return "object";
  }

  function renderParameterList(tool) {
    const schema = tool.inputSchema || {};
    const properties = schema.properties || {};
    const required = new Set(schema.required || []);
    const names = Object.keys(properties).sort();
    if (!names.length) return "none";
    return names
      .map((name) => {
        const prop = properties[name] || {};
        const marker = required.has(name) ? "required" : "optional";
        const description = prop.description ? `<br><small>${compact(prop.description)}</small>` : "";
        return `${code(name)} <small>(${escapeHtml(schemaType(prop))}, ${marker})</small>${description}`;
      })
      .join("<br>");
  }

  function table(headers, rows) {
    return `<table><thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
  }

  function renderConfiguration(data) {
    const settings = data.settings || [];
    const order = data.section_order || [...new Set(settings.map((s) => s.section))];
    let html = "";
    for (const section of order) {
      const rows = settings
        .filter((setting) => setting.section === section)
        .map((setting) => {
          const cli = [setting.cli, setting.unset_cli ? `${setting.unset_cli} clears the value` : null]
            .filter(Boolean)
            .map(code)
            .join("<br>");
          return `<tr><td>${code(setting.name)}</td><td>${cli}</td><td>${code(setting.env)}</td><td>${compact(setting.type)}</td><td>${code(setting.default_display)}</td><td>${compact(setting.description)}</td></tr>`;
        });
      if (!rows.length) continue;
      html += `<h2>${escapeHtml(section)}</h2>`;
      html += table(["Setting", "CLI", "Environment", "Type", "Default", "Description"], rows);
    }
    if (data.docker_entrypoint_settings?.length) {
      html += "<h2>Docker entrypoint settings</h2>";
      html += "<p>These variables are consumed by the Docker entrypoint before the Python application starts.</p>";
      html += envTable(data.docker_entrypoint_settings);
    }
    if (data.sidecar_settings?.length) {
      html += "<h2>Optional sidecar settings</h2>";
      html += envTable(data.sidecar_settings);
    }
    return html;
  }

  function envTable(items) {
    return table(
      ["Environment", "Default", "Description"],
      items.map((item) => `<tr><td>${code(item.env)}</td><td>${code(item.default || "unset")}</td><td>${compact(item.description)}</td></tr>`),
    );
  }

  function groupForTool(name) {
    for (const [group, names] of toolGroups) {
      if (names.includes(name)) return group;
    }
    if (name.startsWith("agent_") || name.startsWith("list_agent_") || ["activate_agent_skill", "call_agent_mcp_tool"].includes(name)) {
      return "Agent capability bridge";
    }
    return "Other tools";
  }

  function renderTools(data) {
    const tools = data.tools || [];
    const groups = new Map();
    for (const tool of tools) {
      const group = groupForTool(String(tool.name || ""));
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(tool);
    }

    let html = `<p>Generated tool count: <strong>${escapeHtml(data.count ?? tools.length)}</strong>.</p>`;
    const orderedGroups = [...toolGroups.map(([group]) => group), "Agent capability bridge", "Other tools"];
    for (const group of orderedGroups) {
      const groupedTools = (groups.get(group) || []).sort((a, b) => String(a.name).localeCompare(String(b.name)));
      if (!groupedTools.length) continue;
      html += `<h2>${escapeHtml(group)}</h2>`;
      html += table(
        ["Tool", "Parameters", "Description"],
        groupedTools.map((tool) => `<tr><td>${code(tool.name)}</td><td>${renderParameterList(tool)}</td><td>${compact(tool.description)}</td></tr>`),
      );
    }
    return html;
  }

  async function renderReference(target) {
    if (target.dataset.referenceRendered === "true") return;
    target.dataset.referenceRendered = "true";
    const source = target.dataset.referenceJson;
    const kind = target.dataset.referenceKind;
    try {
      const response = await fetch(source, { credentials: "same-origin" });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const data = await response.json();
      target.innerHTML = kind === "configuration" ? renderConfiguration(data) : renderTools(data);
    } catch (error) {
      target.innerHTML = `<p><strong>Could not load generated reference data.</strong></p><p>${compact(error.message)}</p>`;
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
