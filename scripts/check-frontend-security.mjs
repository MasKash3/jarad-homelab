#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const frontendDir = path.join(rootDir, "frontend");
const reviewMarker = "xss-reviewed: dynamic template values use escaping or whitelist helpers.";
const expectedHtmlSinks = 13;
const utilsSource = readFileSync(path.join(frontendDir, "js", "utils.js"), "utf8");
const { escapeAttr, escapeHtml } = await import(`data:text/javascript;base64,${Buffer.from(utilsSource).toString("base64")}`);

const maliciousValues = [
  `<script>alert("xss")</script>`,
  `<img src=x onerror=alert(1)>`,
  `"><svg onload=alert(1)>`,
  `' onmouseover='alert(1)`,
  "` autofocus onfocus=alert(1) x=`",
  `&lt;/strong&gt;<iframe srcdoc="<script>alert(1)</script>"></iframe>`
];

for (const value of maliciousValues) {
  const escapedHtml = escapeHtml(value);
  assert.equal(/[<>"']/.test(escapedHtml), false, `escapeHtml left markup characters in: ${value}`);

  const escapedAttr = escapeAttr(value);
  assert.equal(/[<>"'`]/.test(escapedAttr), false, `escapeAttr left attribute delimiters in: ${value}`);
}

const frontendFiles = [
  path.join(frontendDir, "app.js"),
  ...["api.js", "auth.js", "config.js", "empty-state.js", "utils.js"].map((name) => path.join(frontendDir, "js", name))
];
const dangerousSinkPatterns = [
  [/\.outerHTML\s*=/, "outerHTML assignment"],
  [/\.insertAdjacentHTML\s*\(/, "insertAdjacentHTML"],
  [/\bdocument\.write\s*\(/, "document.write"],
  [/\beval\s*\(/, "eval"],
  [/\bnew\s+Function\s*\(/, "new Function"],
  [/\.srcdoc\s*=/, "srcdoc assignment"],
  [/setAttribute\s*\(\s*["']on/i, "event-handler attribute"]
];

let htmlSinkCount = 0;
for (const filePath of frontendFiles) {
  const source = readFileSync(filePath, "utf8");
  for (const [pattern, label] of dangerousSinkPatterns) {
    assert.equal(pattern.test(source), false, `${label} is not allowed in ${path.relative(rootDir, filePath)}`);
  }

  const lines = source.split(/\r?\n/);
  lines.forEach((line, index) => {
    if (!/\.innerHTML\s*=/.test(line)) return;
    htmlSinkCount += 1;
    assert.equal(
      lines[index - 1]?.trim(),
      `// ${reviewMarker}`,
      `Unreviewed innerHTML sink at ${path.relative(rootDir, filePath)}:${index + 1}`
    );
  });
}

assert.equal(
  htmlSinkCount,
  expectedHtmlSinks,
  `Expected ${expectedHtmlSinks} reviewed innerHTML sinks, found ${htmlSinkCount}; review and update the inventory`
);

const caddyfile = readFileSync(path.join(rootDir, "deploy", "caddy", "jarad.Caddyfile"), "utf8");
const csp = caddyfile.match(/Content-Security-Policy\s+"([^"]+)"/)?.[1] || "";
assert.ok(csp, "Caddy Content-Security-Policy header is missing");
assert.match(csp, /script-src 'self'/, "CSP must restrict scripts to the app origin");
assert.match(csp, /object-src 'none'/, "CSP must disable plugins");
assert.match(csp, /base-uri 'none'/, "CSP must block base URL injection");
assert.match(csp, /frame-ancestors 'none'/, "CSP must block framing");
assert.doesNotMatch(csp, /'unsafe-inline'|'unsafe-eval'/, "CSP must not allow inline or evaluated scripts");
assert.match(caddyfile, /not remote_ip 100\.64\.0\.0\/10 fd7a:115c:a1e0::\/48/, "Caddy must reject non-tailnet source ranges");
assert.match(caddyfile, /respond @outsideTailnet 403/, "Caddy must fail closed for non-tailnet clients");

const indexSource = readFileSync(path.join(frontendDir, "index.html"), "utf8");
for (const [assetPath, pattern] of [
  ["styles.css", /href="styles\.css\?v=[^"]+"\s+integrity="([^"]+)"/],
  ["js/error-handler.js", /src="js\/error-handler\.js\?v=[^"]+"\s+integrity="([^"]+)"/],
  ["app.js", /src="app\.js\?v=[^"]+"[^>]*\sintegrity="([^"]+)"/]
]) {
  const declared = indexSource.match(pattern)?.[1];
  assert.ok(declared, `Missing Subresource Integrity for ${assetPath}`);
  const expected = `sha384-${createHash("sha384").update(readFileSync(path.join(frontendDir, assetPath))).digest("base64")}`;
  assert.equal(declared, expected, `Stale Subresource Integrity for ${assetPath}`);
}

console.log(`Frontend security check passed (${htmlSinkCount} reviewed HTML sinks).`);
