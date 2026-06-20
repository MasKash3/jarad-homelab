export function resourceRow(label, value, max, unit, stateName) {
  const safeLabel = escapeHtml(label);
  const safeUnit = escapeHtml(unit);
  if (value === null || value === undefined || max === null || max === undefined || max === 0) {
    return `
      <div class="resource-row">
        <div>
          <span>${safeLabel}</span>
          <strong>Unavailable</strong>
        </div>
        <progress class="mini-bar muted" value="0" max="100">0%</progress>
      </div>
    `;
  }
  const pct = Math.min(100, Math.round((value / max) * 100));
  return `
    <div class="resource-row">
      <div>
        <span>${safeLabel}</span>
        <strong>${escapeHtml(formatResource(value, max, safeUnit))}</strong>
      </div>
      <progress class="mini-bar ${escapeAttr(toneClass(stateName))}" value="${pct}" max="100">${pct}%</progress>
    </div>
  `;
}

export function toneClass(stateName) {
  return ["good", "warn", "bad", "info", "muted"].includes(stateName) ? stateName : "good";
}

export function formatResource(value, max, unit) {
  if (unit === "%") return `${value}%`;
  return `${value} ${unit} / ${max} ${unit}`;
}

export function diagnosticState(value, explicitState) {
  if (explicitState === "fail") return "bad";
  if (explicitState === "warn") return "warn";
  if (explicitState === "pass") return "good";
  const text = String(value).toLowerCase();
  if (text.includes("stopped") || text.includes("failed") || text.includes("unavailable") || text.includes("error") || text.includes("not running")) return "bad";
  if (text.includes("degraded") || text.includes("elevated") || text.includes("warning") || text.includes("unchecked") || text.includes("unknown")) return "warn";
  return "good";
}

export function formatUpdated(value) {
  const date = value instanceof Date ? value : new Date(value);
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 8) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 14) return `${days}d ago`;
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function stateClass(service) {
  if (service.status !== "running" || service.health === "down") return "bad";
  if (service.health === "degraded") return "warn";
  return "good";
}

export function formatHealth(health) {
  return {
    healthy: "Healthy",
    degraded: "Degraded",
    down: "Down",
    running: "Running"
  }[health] || String(health);
}

export function labelForState(stateName) {
  return stateName === "good" ? "OK" : stateName === "warn" ? "Monitor" : "High";
}

export function colorForState(stateName) {
  return { good: "#138a53", warn: "#b7791f", bad: "#bd2b2b" }[stateName] || "#138a53";
}

export function serviceColorClass(serviceId) {
  const id = String(serviceId || "").toLowerCase();
  return [
    "nextcloud",
    "immich",
    "jellyfin",
    "portainer",
    "pihole",
    "dozzle",
    "uptime-kuma",
    "stirling-pdf"
  ].includes(id) ? `app-color-${id}` : "app-color-default";
}

export function emptyState(message) {
  return `<div class="audit-item"><p>${escapeHtml(message)}</p></div>`;
}
export const $ = (selector) => document.querySelector(selector);
export const $$ = (selector) => Array.from(document.querySelectorAll(selector));

export function readJsonStorage(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) || fallback;
  } catch {
    return fallback;
  }
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  }[char]));
}

export function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

export function safeCssColor(value) {
  const text = String(value || "").trim();
  return /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(text) ? text : "#138a53";
}

export function safeUrl(value) {
  try {
    const url = new URL(String(value), window.location.origin);
    if (url.protocol === "http:" || url.protocol === "https:") return url.href;
  } catch {
    // Fall through to the inert fallback.
  }
  return "#";
}
