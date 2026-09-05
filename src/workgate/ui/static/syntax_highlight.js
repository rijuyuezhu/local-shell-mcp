(() => {
  "use strict";

  const KEYWORDS = {
    javascript: new Set(
      "as async await break case catch class const continue debugger default delete do else export extends finally for from function get if import in instanceof let new of return set static super switch this throw try typeof var void while with yield true false null undefined".split(
        " ",
      ),
    ),
    python: new Set(
      "and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield match case".split(
        " ",
      ),
    ),
    shell: new Set(
      "case do done elif else esac export fi for function if in local readonly return set then unset until while".split(
        " ",
      ),
    ),
  };

  const EXTENSIONS = new Map([
    [".c", "c"],
    [".cc", "c"],
    [".cpp", "c"],
    [".css", "css"],
    [".diff", "diff"],
    [".go", "go"],
    [".h", "c"],
    [".hpp", "c"],
    [".htm", "html"],
    [".html", "html"],
    [".java", "java"],
    [".js", "javascript"],
    [".json", "json"],
    [".jsx", "javascript"],
    [".md", "markdown"],
    [".patch", "diff"],
    [".py", "python"],
    [".rs", "rust"],
    [".sh", "shell"],
    [".toml", "toml"],
    [".ts", "javascript"],
    [".tsx", "javascript"],
    [".xml", "html"],
    [".yaml", "yaml"],
    [".yml", "yaml"],
  ]);

  function languageForPath(path, mediaType = "") {
    const normalizedType = String(mediaType || "").toLowerCase();
    if (normalizedType.includes("json")) return "json";
    if (normalizedType.includes("javascript") || normalizedType.includes("typescript")) return "javascript";
    if (normalizedType.includes("python")) return "python";
    if (normalizedType.includes("html") || normalizedType.includes("xml")) return "html";
    if (normalizedType.includes("css")) return "css";
    if (normalizedType.includes("yaml")) return "yaml";
    const normalizedPath = String(path || "").toLowerCase();
    const filename = normalizedPath.split(/[\\/]/).at(-1) || "";
    if (["dockerfile", "makefile"].includes(filename)) return "shell";
    const dot = filename.lastIndexOf(".");
    return dot >= 0 ? EXTENSIONS.get(filename.slice(dot)) || "plain" : "plain";
  }

  function pushToken(tokens, type, value) {
    if (!value) return;
    const previous = tokens.at(-1);
    if (previous && previous.type === type) previous.text += value;
    else tokens.push({ type, text: value });
  }

  function tokenizeDiff(source) {
    const tokens = [];
    for (const line of source.match(/.*(?:\n|$)/g) || []) {
      const type = line.startsWith("+") && !line.startsWith("+++")
        ? "diff-add"
        : line.startsWith("-") && !line.startsWith("---")
          ? "diff-delete"
          : line.startsWith("@@")
            ? "keyword"
            : "plain";
      pushToken(tokens, type, line);
    }
    return tokens;
  }

  function tokenize(source, language = "plain") {
    const text = String(source ?? "");
    const normalized = String(language || "plain").toLowerCase();
    if (normalized === "diff") return tokenizeDiff(text);
    if (normalized === "plain") return [{ type: "plain", text }];

    const tokens = [];
    const keywordSet = KEYWORDS[normalized] || KEYWORDS.javascript;
    const patterns = [
      { type: "comment", regex: normalized === "python" || normalized === "shell" ? /#[^\n]*/y : /\/\*[\s\S]*?\*\/|\/\/[^\n]*/y },
      { type: "string", regex: /`(?:\\.|[^`])*`|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/y },
      { type: "number", regex: /\b(?:0x[\da-f]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b/iy },
      { type: "identifier", regex: /[A-Za-z_$][\w$-]*/y },
      { type: "punctuation", regex: /[{}[\](),.:;<>+=*\/%!?&|^-]+/y },
      { type: "whitespace", regex: /\s+/y },
    ];
    let index = 0;
    while (index < text.length) {
      let matched = false;
      for (const pattern of patterns) {
        pattern.regex.lastIndex = index;
        const match = pattern.regex.exec(text);
        if (!match) continue;
        let type = pattern.type;
        if (type === "identifier") {
          type = keywordSet.has(match[0]) ? "keyword" : "plain";
        } else if (type === "whitespace") {
          type = "plain";
        } else if (
          normalized === "json" &&
          type === "string" &&
          /^\s*:/.test(text.slice(index + match[0].length))
        ) {
          type = "key";
        }
        pushToken(tokens, type, match[0]);
        index += match[0].length;
        matched = true;
        break;
      }
      if (!matched) {
        pushToken(tokens, "plain", text[index]);
        index += 1;
      }
    }
    return tokens;
  }

  function render(element, source, language = "plain") {
    if (!element || typeof document === "undefined") return;
    const code = document.createElement("code");
    code.className = `syntax-code language-${language}`;
    for (const token of tokenize(source, language)) {
      if (token.type === "plain") code.append(document.createTextNode(token.text));
      else {
        const span = document.createElement("span");
        span.className = `syntax-token syntax-${token.type}`;
        span.textContent = token.text;
        code.append(span);
      }
    }
    element.replaceChildren(code);
  }

  const api = { languageForPath, render, tokenize };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.LsmSyntax = api;
})();
