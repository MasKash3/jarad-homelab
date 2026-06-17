import { configActions, legacyStorageKeys, serviceActions, storageKeys } from './js/config.js';
import { cloneMockState } from './js/mock-state.js';
import { createApi } from './js/api.js';
import { verifyFingerprint } from './js/auth.js';
import { $, $$, colorForState, diagnosticState, emptyState, escapeAttr, escapeHtml, formatHealth, formatUpdated, labelForState, resourceRow, safeCssColor, safeUrl, stateClass } from './js/utils.js';

let serviceFilter = "all";
let logFilter = "all";
let liveTail = false;
let pendingAction = null;
let pendingService = null;
let activeServiceId = null;
let pendingAuth = null;
let state = cloneMockState();
let connectionState = {
  mode: "mock",
  label: "Mock mode"
};

const api = createApi({
  addAudit,
  getState: () => state,
  setConnectionState: (nextConnectionState) => {
    connectionState = nextConnectionState;
  },
  settings: readSettings
});

function migrateLegacyStorage() {
  Object.entries(storageKeys).forEach(([key, nextKey]) => {
    const legacyKey = legacyStorageKeys[key];
    if (!legacyKey || localStorage.getItem(nextKey) !== null) return;
    const legacyValue = localStorage.getItem(legacyKey);
    if (legacyValue !== null) localStorage.setItem(nextKey, legacyValue);
  });
}

function readSettings() {
  try {
    return JSON.parse(localStorage.getItem(storageKeys.settings)) || {};
  } catch {
    return {};
  }
}

function hasAutoBackend() {
  return window.location.protocol === "https:" && window.location.hostname.endsWith(".ts.net");
}

function render() {
  renderDashboard();
  renderServices();
  renderLogs();
  renderAlerts();
  renderAdmin();
  renderSettings();
}

function renderDashboard() {
  $("#overallStatus").textContent = state.server.status;
  $("#connectionState").textContent = connectionState.label;
  $("#connectionState").className = `connection-chip ${connectionState.mode}`;
  $("#lastUpdated").textContent = `Updated ${formatUpdated(state.updatedAt)}`;
  $("#dashboardTitle").textContent = state.server.uptime;
  $("#healthScore").textContent = state.server.healthScore;
  $("#metricGrid").innerHTML = state.metrics.map((metric) => `
    <article class="metric">
      <div class="metric-top">
        <span>${escapeHtml(metric.label)}</span>
        <span class="pill ${escapeAttr(metric.state)}">${escapeHtml(metric.badge || labelForState(metric.state))}</span>
      </div>
      <strong>${escapeHtml(metric.value)}${escapeHtml(metric.unit)}</strong>
      <div class="mini-bar" style="--bar-color:${colorForState(metric.state)}">
        <span style="--value:${Number(metric.value) || 0}%"></span>
      </div>
    </article>
  `).join("");
  $("#raidState").textContent = state.storage.raid;
  $("#storageUsedBar").style.setProperty("--value", `${state.storage.usedPct}%`);
  $("#storageUsedBar").style.setProperty("--bar-color", colorForState(state.storage.usedPct > 80 ? "bad" : state.storage.usedPct > 65 ? "warn" : "good"));
  $("#storageLabel").textContent = state.storage.label;
  $("#cloudBackupLabel").textContent = state.storage.cloudBackup;
  $("#backupState").textContent = state.backups.state;
  $("#quickBackup").textContent = state.backups.quick;
  $("#fullBackup").textContent = state.backups.full;
  $("#nextBackup").textContent = state.backups.next;

  $("#launcherGrid").innerHTML = state.services.map((service) => `
    <a class="launcher" href="${escapeAttr(safeUrl(service.url))}" target="_blank" rel="noreferrer" style="--app-color:${safeCssColor(service.color)}">
      <b>${escapeHtml(service.icon)}</b>
      <span>${escapeHtml(service.name)}</span>
    </a>
  `).join("");
}

function renderServices() {
  const services = state.services.filter((service) => {
    if (serviceFilter === "all") return true;
    if (serviceFilter === "degraded") return service.health === "degraded";
    if (serviceFilter === "down") return service.status !== "running" || service.health === "down";
    return true;
  });

  $("#serviceList").innerHTML = services.map((service) => `
    <button class="service-card" type="button" data-service-id="${escapeAttr(service.id)}">
      <span class="service-icon" style="--app-color:${safeCssColor(service.color)}">${escapeHtml(service.icon)}</span>
      <div>
        <h3>${escapeHtml(service.name)}</h3>
        <p>${escapeHtml(service.container)}</p>
      </div>
      <span class="pill ${escapeAttr(stateClass(service))}">${escapeHtml(formatHealth(service.health))}</span>
      <svg class="row-chevron"><use href="#icon-link"></use></svg>
    </button>
  `).join("") || emptyState("No services match this filter.");

  $$("#serviceList [data-service-id]").forEach((button) => {
    button.addEventListener("click", () => openService(button.dataset.serviceId));
  });
}

function renderLogs() {
  renderLiveTailButton();
  const search = $("#logSearch").value.trim().toLowerCase();
  const logs = state.logs.filter((log) => {
    const matchesFilter = logFilter === "all" || log.level === logFilter || log.service === logFilter;
    const matchesSearch = !search || `${log.service} ${log.message}`.toLowerCase().includes(search);
    return matchesFilter && matchesSearch;
  });

  $("#logList").innerHTML = logs.map((log) => `
    <article class="log-entry ${log.level === "error" ? "error" : ""}">
      <header>
        <strong>${escapeHtml(String(log.service).toUpperCase())} / ${escapeHtml(log.level)}</strong>
        <time>${escapeHtml(log.time)}</time>
      </header>
      <p>${escapeHtml(log.message)}</p>
    </article>
  `).join("") || emptyState("No log entries found.");
}

function renderLiveTailButton() {
  const button = $("#liveTailButton");
  if (!button) return;
  button.classList.toggle("is-selected", liveTail);
  button.setAttribute("aria-label", liveTail ? "Pause live tail" : "Start live tail");
  button.setAttribute("title", liveTail ? "Pause live tail" : "Start live tail");
  const use = button.querySelector("use");
  if (use) use.setAttribute("href", liveTail ? "#icon-pause" : "#icon-play");
}

function renderAlerts() {
  const active = state.alerts.filter((alert) => alert.time === "Active").length;
  $("#activeAlertCount").textContent = `${active} active`;
  $("#alertList").innerHTML = state.alerts.map((alert) => `
    <article class="alert-card ${escapeAttr(alert.state)}">
      <header>
        <strong>${escapeHtml(alert.title)}</strong>
        <time>${escapeHtml(alert.time)}</time>
      </header>
      <p>${escapeHtml(alert.body)}</p>
    </article>
  `).join("");
  $("#networkGrid").innerHTML = state.network.map(([label, value]) => `
    <div>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `).join("");
}

function renderAdmin() {
  renderConfig();
}

function renderConfig() {
  const settings = readSettings();
  $("#authMethodState").textContent = authMethodLabel();
  $("#authMethodHelp").textContent = "TOTP is active for protected actions.";
  $("#backendState").textContent = settings.baseUrl || hasAutoBackend() ? "Configured" : "Mock data";
  $("#configList").innerHTML = configActions.map((item) => `
    <article class="config-card">
      <div>
        <strong>${escapeHtml(item.title)}</strong>
        <p>${escapeHtml(item.detail)}</p>
      </div>
      <span class="pill info">${escapeHtml(item.target)}</span>
    </article>
  `).join("");

  $$("[data-auth-method]").forEach((button) => {
    button.classList.toggle("is-selected", button.dataset.authMethod === getAuthMethod());
  });
  renderAudit();
}

function renderAudit() {
  const audit = readAudit();
  $("#auditList").innerHTML = audit.slice(0, 12).map((item) => `
    <article class="audit-item">
      <header>
        <strong>${escapeHtml(item.action)}</strong>
        <time>${escapeHtml(item.time)}</time>
      </header>
      <p>${escapeHtml(item.status)} - ${escapeHtml(item.target)}${item.details ? ` - ${escapeHtml(item.details)}` : ""}</p>
    </article>
  `).join("") || emptyState("No local audit entries yet.");
}

function renderSettings() {
  const settings = readSettings();
  $("#apiBaseInput").value = settings.baseUrl || "";
  $("#apiTokenInput").value = settings.token || "";
}

function actionsForService(service) {
  const always = serviceActions.filter((action) => action.kind === "logs" || action.kind === "diagnostics");
  if (service.status !== "running" || service.health === "down") {
    return [...always, serviceActions.find((action) => action.kind === "start")].filter(Boolean);
  }
  return [...always, ...serviceActions.filter((action) => action.kind === "restart" || action.kind === "stop")];
}

function openService(serviceId, options = {}) {
  const service = state.services.find((item) => item.id === serviceId);
  if (!service) return;
  activeServiceId = service.id;
  if (options.audit !== false) {
    addAudit("Viewed service", service.name, "success", "Details opened");
  }
  $("#sheetServiceName").textContent = service.name;
  $("#sheetServiceType").textContent = service.container;
  $("#serviceDetailBody").innerHTML = `
    <div class="service-detail-hero">
      <span class="service-icon large" style="--app-color:${safeCssColor(service.color)}">${escapeHtml(service.icon)}</span>
      <div>
        <h3>${escapeHtml(service.name)}</h3>
        <p>${escapeHtml(service.image)}</p>
      </div>
      <span class="pill ${escapeAttr(stateClass(service))}">${escapeHtml(formatHealth(service.health))}</span>
    </div>
    <div class="detail-grid">
      <div><span>Status</span><strong>${escapeHtml(service.status)}</strong></div>
      <div><span>Uptime</span><strong>${escapeHtml(state.server.uptime)}</strong></div>
      <div><span>Auto restarts</span><strong>${escapeHtml(service.restarts)}</strong></div>
      <div><span>Last issue</span><strong>${escapeHtml(service.lastError)}</strong></div>
    </div>
    <h3 class="subhead">Quick Actions</h3>
    <div class="quick-actions">
      ${actionsForService(service).map((action) => `
        <button class="quick-action ${action.danger ? "danger" : ""}" type="button" data-service-action="${escapeAttr(action.kind)}" data-service-id="${escapeAttr(service.id)}">
          <svg><use href="#${escapeAttr(action.icon)}"></use></svg>
          <strong>${escapeHtml(action.title)}</strong>
          <span data-action-label>${escapeHtml(action.protected ? `${authMethodLabel()} required` : action.detail)}</span>
        </button>
      `).join("")}
    </div>
    <h3 class="subhead">Resources</h3>
    <div class="resource-list">
      ${resourceRow("CPU Usage", service.resources.cpu, 100, "%", "good")}
      ${resourceRow("Memory Usage", service.resources.memory, service.resources.memoryLimit, "MB", "info")}
      ${resourceRow("Container Disk", service.resources.disk, service.resources.diskLimit, "GB", service.resources.disk && service.resources.diskLimit && service.resources.disk / service.resources.diskLimit > .75 ? "warn" : "good")}
    </div>
    <h3 class="subhead">Diagnostics</h3>
    <div class="diagnostic-list">
      ${service.diagnostics.map(([label, value, diagnosticStatus]) => `
        <div class="diagnostic-step">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
          <b class="status-dot ${diagnosticState(value, diagnosticStatus)}"></b>
        </div>
      `).join("")}
    </div>
  `;
  if (!$("#serviceSheet").open) {
    $("#serviceSheet").showModal();
  }
  $$("#serviceDetailBody [data-service-action]").forEach((button) => {
    button.addEventListener("click", () => runServiceAction(service.id, button.dataset.serviceAction));
  });
}

async function runServiceAction(serviceId, actionKind) {
  const service = state.services.find((item) => item.id === serviceId);
  const action = serviceActions.find((item) => item.kind === actionKind);
  if (!service || !action) return;

  if (action.kind === "logs") {
    await loadServiceLogs(service);
    return;
  }

  if (action.kind === "diagnostics") {
    await loadServiceDiagnostics(service, $(`[data-service-action="diagnostics"][data-service-id="${service.id}"]`));
    return;
  }

  pendingService = service;
  pendingAction = {
    id: `${action.kind}-${service.id}`,
    title: `${action.title} ${service.name}`,
    target: service.container,
    detail: action.detail,
    serviceId: service.id,
    kind: action.kind,
    danger: action.danger
  };
  openAuthSheet();
}

async function loadServiceLogs(service) {
  try {
    const payload = await api.getServiceLogs(service.id, 100);
    state.logs = (payload.logs || []).map((log) => ({
      level: log.level || "info",
      service: service.id,
      time: log.time || "Recent",
      message: log.message || ""
    }));
    $("#serviceSheet").close();
    setActiveScreen("logs");
    $("#logSearch").value = "";
    addAudit("Viewed logs", service.name, "success", "Fetched from backend");
    renderLogs();
  } catch (error) {
    addAudit("Viewed logs", service.name, "failure", error.message);
    renderInlineNotice(`Could not load logs: ${error.message}`);
  }
}

async function loadServiceDiagnostics(service, button) {
  const label = button?.querySelector("[data-action-label]");
  const originalLabel = label?.textContent || "Run health checks";
  if (button) button.disabled = true;
  if (label) label.textContent = "Running...";
  renderInlineNotice(`Running diagnostics for ${service.name}...`, "info");

  try {
    const payload = await api.getServiceDiagnostics(service.id);
    const checks = payload.checks || [];
    service.diagnostics = checks.map((check) => [check.label, check.detail, check.state]);
    const list = $("#serviceDetailBody .diagnostic-list");
    list.innerHTML = service.diagnostics.map(([label, value, diagnosticStatus]) => `
      <div class="diagnostic-step">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
        <b class="status-dot ${diagnosticState(value, diagnosticStatus)}"></b>
      </div>
    `).join("");
    list.classList.remove("pulse-once");
    requestAnimationFrame(() => list.classList.add("pulse-once"));
    addAudit("Ran diagnostics", service.name, "success", "Fetched from backend");
    const failed = checks.filter((check) => check.state === "fail").length;
    const warned = checks.filter((check) => check.state === "warn").length;
    const summary = failed
      ? `${failed} check${failed === 1 ? "" : "s"} failed`
      : warned
      ? `${warned} check${warned === 1 ? "" : "s"} need attention`
      : `${checks.length} checks passed`;
    renderInlineNotice(`${summary}. Last run ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.${payload.suggestedFix ? ` ${payload.suggestedFix}` : ""}`, failed ? "bad" : warned ? "warn" : "good");
    if (label) label.textContent = "Completed";
  } catch (error) {
    addAudit("Ran diagnostics", service.name, "failure", error.message);
    renderInlineNotice(`Could not run diagnostics: ${error.message}`, "bad");
    if (label) label.textContent = "Failed";
  } finally {
    if (button) button.disabled = false;
    if (label) {
      window.setTimeout(() => {
        label.textContent = originalLabel;
      }, 2200);
    }
  }
}

function renderInlineNotice(message, tone = "warn") {
  let notice = $("#serviceDetailBody .inline-notice");
  if (!notice) {
    notice = document.createElement("div");
    $("#serviceDetailBody").prepend(notice);
  }
  notice.className = `inline-notice ${tone}`;
  notice.textContent = message;
}

function openAuthSheet() {
  const method = getAuthMethod();
  $("#authTitle").textContent = method === "fingerprint" ? "Fingerprint Required" : "TOTP Required";
  $("#authCopy").textContent = pendingAction
    ? `${pendingAction.title} requires ${authMethodLabel().toLowerCase()}.`
    : "Protected action requires authentication.";
  renderAuthError("");
  $("#authTotpInput").value = "";
  $("#fingerprintAuthButton").hidden = method !== "fingerprint";
  $("#totpAuthBlock").hidden = method !== "totp";
  $("#authSheet").showModal();
}

async function completeFingerprintAuth() {
  renderAuthError("");
  const button = $("#fingerprintAuthButton");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Waiting...";

  try {
    await verifyFingerprint();
    pendingAuth = { method: "fingerprint", verified: true };
    addAudit("Authentication success", pendingAction?.target || "service action", "success", "Fingerprint");
    $("#authSheet").close();
    executePendingAction();
  } catch (error) {
    addAudit("Authentication failure", pendingAction?.target || "service action", "failure", error.message);
    renderAuthError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function completeTotpAuth() {
  const method = getAuthMethod();
  if (method !== "totp") return;
  const code = $("#authTotpInput").value.trim();
  if (!code) {
    addAudit("Authentication failure", pendingAction?.target || "service action", "failure", "Missing TOTP code");
    renderAuthError("Enter the 6-digit TOTP code before verifying.");
    return;
  }
  if (!/^\d{6}$/.test(code)) {
    addAudit("Authentication failure", pendingAction?.target || "service action", "failure", "Invalid TOTP format");
    renderAuthError("TOTP must be exactly 6 digits.");
    return;
  }
  pendingAuth = { method: "totp", totpCode: code };
  addAudit("Authentication submitted", pendingAction?.target || "service action", "success", "TOTP");
  $("#authSheet").close();
  executePendingAction();
}

async function executePendingAction() {
  if (!pendingAction) return;
  const completedAction = pendingAction;
  const completedAuth = pendingAuth || {};

  try {
    await api.executeAction(completedAction, completedAuth);
    state.logs.unshift({
      level: "info",
      service: "admin",
      time: "Now",
      message: `${completedAction.title} requested from mobile app`
    });
    await refreshState({ preserveServiceSheet: true });
    renderInlineNotice(`${completedAction.title} completed. Status refreshed.`, "good");
  } catch (error) {
    addAudit(completedAction.title, completedAction.target, "failure", error.message);
    renderInlineNotice(`Action failed: ${error.message}`);
  }

  pendingAction = null;
  pendingService = null;
  pendingAuth = null;
}

function renderAuthError(message) {
  const error = $("#authError");
  error.textContent = message;
  error.hidden = !message;
}

function setActiveScreen(screenName) {
  $$(".screen").forEach((screen) => screen.classList.toggle("is-active", screen.id === `screen-${screenName}`));
  $$(".bottom-nav [data-nav]").forEach((button) => button.classList.toggle("is-active", button.dataset.nav === screenName));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function refreshState(options = {}) {
  const openServiceId = options.preserveServiceSheet && $("#serviceSheet").open ? activeServiceId : null;
  state = await api.getState();
  state.updatedAt = new Date(state.updatedAt || Date.now());
  render();
  if (openServiceId) {
    if (state.services.some((service) => service.id === openServiceId)) {
      openService(openServiceId, { audit: false });
    } else {
      $("#serviceSheet").close();
      activeServiceId = null;
    }
  }
}

function addAudit(action, target, status, details = "") {
  const audit = readAudit();
  audit.unshift({
    time: new Date().toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    action,
    target,
    status,
    details
  });
  localStorage.setItem(storageKeys.audit, JSON.stringify(audit.slice(0, 80)));
}

function readAudit() {
  try {
    return JSON.parse(localStorage.getItem(storageKeys.audit)) || [];
  } catch {
    return [];
  }
}

function getAuthMethod() {
  return "totp";
}

function authMethodLabel() {
  return getAuthMethod() === "fingerprint" ? "Fingerprint" : "TOTP";
}

function bindEvents() {
  $$(".bottom-nav [data-nav], [data-nav]").forEach((button) => {
    button.addEventListener("click", () => setActiveScreen(button.dataset.nav));
  });

  $("[data-close-sheet]").addEventListener("click", () => $("#serviceSheet").close());
  $("#serviceSheet").addEventListener("close", () => {
    activeServiceId = null;
  });
  $("[data-close-settings]").addEventListener("click", () => $("#settingsSheet").close());
  $("[data-close-auth]").addEventListener("click", () => $("#authSheet").close());

  $("#refreshButton").addEventListener("click", () => refreshState({ preserveServiceSheet: true }));
  $("#settingsButton").addEventListener("click", () => $("#settingsSheet").showModal());
  $("#fingerprintAuthButton").addEventListener("click", completeFingerprintAuth);
  $("#totpAuthButton").addEventListener("click", completeTotpAuth);
  $("#authTotpInput").addEventListener("input", () => renderAuthError(""));

  $$("[data-service-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      serviceFilter = button.dataset.serviceFilter;
      $$("[data-service-filter]").forEach((item) => item.classList.toggle("is-selected", item === button));
      renderServices();
    });
  });

  $$("[data-log-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      logFilter = button.dataset.logFilter;
      $$("[data-log-filter]").forEach((item) => item.classList.toggle("is-selected", item === button));
      renderLogs();
    });
  });

  $("#logSearch").addEventListener("input", renderLogs);
  $("#liveTailButton").addEventListener("click", () => {
    liveTail = !liveTail;
    renderLiveTailButton();
    state.logs.unshift({
      level: "info",
      service: "live",
      time: "Now",
      message: liveTail ? "Live tail connected" : "Live tail paused"
    });
    addAudit(liveTail ? "Started live tail" : "Stopped live tail", "logs", "success");
    renderLogs();
  });

  $$("[data-auth-method]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.authUnavailable === "true") {
        $("#authMethodHelp").textContent = "Fingerprint needs server-side WebAuthn before it can protect real Docker actions. Use TOTP for now.";
        addAudit("Fingerprint unavailable", "config", "warn", "Server-side WebAuthn is not enabled");
        renderAudit();
        return;
      }
      localStorage.setItem(storageKeys.authMethod, button.dataset.authMethod);
      addAudit("Changed auth method", "config", "success", authMethodLabel());
      renderConfig();
    });
  });

  $("#clearAuditButton").addEventListener("click", () => {
    localStorage.removeItem(storageKeys.audit);
    renderAudit();
  });

  $("#settingsForm").addEventListener("submit", (event) => {
    event.preventDefault();
    localStorage.setItem(storageKeys.settings, JSON.stringify({
      baseUrl: $("#apiBaseInput").value.trim(),
      token: $("#apiTokenInput").value.trim()
    }));
    addAudit("Saved settings", "backend", "success");
    $("#settingsSheet").close();
    refreshState();
  });
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

migrateLegacyStorage();
bindEvents();
refreshState();
