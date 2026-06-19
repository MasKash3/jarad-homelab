import { APP_VERSION, configActions, legacyStorageKeys, serviceActions, storageKeys } from './js/config.js?v=2026.06.19.12';
import { createNoDataState } from './js/empty-state.js?v=2026.06.19.12';
import { createApi } from './js/api.js?v=2026.06.19.12';
import { defaultDeviceLabel, registerPasskey, verifyPasskeyForAction } from './js/auth.js?v=2026.06.19.12';
import { $, $$, colorForState, diagnosticState, emptyState, escapeAttr, escapeHtml, formatHealth, formatUpdated, labelForState, resourceRow, safeCssColor, safeUrl, stateClass } from './js/utils.js?v=2026.06.19.12';

let serviceFilter = "all";
let logFilter = "all";
let logContext = null;
let serviceLogRows = [];
let liveTail = false;
let pendingAction = null;
let pendingService = null;
let activeServiceId = null;
let pendingAuth = null;
let passkeyCredentials = [];
let deviceTokens = [];
let deviceTokenMessage = "";
let deviceTokenMessageState = "muted";
let pendingTotpResolve = null;
let state = createNoDataState();
let connectionState = {
  mode: "disconnected",
  label: "No backend"
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

function writeSettings(settings) {
  localStorage.setItem(storageKeys.settings, JSON.stringify(settings));
}

function hasAutoBackend() {
  return window.location.protocol === "https:" && window.location.hostname.endsWith(".ts.net");
}

function noDataPanel(title, message) {
  return `
    <article class="no-data-panel">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(message)}</span>
    </article>
  `;
}

function backupStateClass(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("healthy") || text.includes("ok") || text.includes("clean")) return "good";
  if (text.includes("failed") || text.includes("error")) return "bad";
  return "warn";
}

function raidStateClass(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("clean") || text.includes("healthy") || text.includes("ok")) return "good";
  if (text.includes("degraded") || text.includes("failed") || text.includes("error")) return "bad";
  return "warn";
}

function render() {
  renderAppVersion();
  renderDashboard();
  renderServices();
  renderLogs();
  renderAlerts();
  renderAdmin();
  renderSettings();
}

function renderAppVersion() {
  $("#appVersion").textContent = `v${APP_VERSION}`;
}

function renderDashboard() {
  $("#overallStatus").textContent = state.server.status;
  $(".status-strip .status-dot").className = `status-dot ${state.isEmpty ? "warn" : "good"}`;
  $("#connectionState").textContent = connectionState.label;
  $("#connectionState").className = `connection-chip ${connectionState.mode}`;
  $("#lastUpdated").textContent = state.isEmpty ? "No live update" : `Updated ${formatUpdated(state.updatedAt)}`;
  $("#dashboardKicker").textContent = state.isEmpty ? "Connection" : "Server uptime";
  $("#dashboardTitle").textContent = state.server.uptime;
  $("#healthScore").textContent = state.server.healthScore;
  $(".score-ring").style.setProperty("--score-progress", `${Math.max(0, Math.min(100, Number(state.server.healthScore) || 0))}%`);
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
  `).join("") || noDataPanel("No Metrics", state.emptyReason || "Live server metrics are unavailable.");
  $("#raidState").textContent = state.storage.raid;
  $("#raidState").className = `pill ${state.isEmpty ? "warn" : raidStateClass(state.storage.raid)}`;
  $("#storageUsedBar").style.setProperty("--value", `${state.storage.usedPct}%`);
  $("#storageUsedBar").style.setProperty("--bar-color", colorForState(state.storage.usedPct > 80 ? "bad" : state.storage.usedPct > 65 ? "warn" : "good"));
  $("#storageLabel").textContent = state.storage.label;
  $("#cloudBackupLabel").textContent = state.storage.cloudBackup;
  $("#backupState").textContent = state.backups.state;
  $("#backupState").className = `pill ${backupStateClass(state.backups.state)}`;
  $("#quickBackup").textContent = state.backups.quick;
  $("#fullBackup").textContent = state.backups.full;
  $("#nextBackup").textContent = state.backups.next;

  $("#launcherGrid").innerHTML = state.services.map((service) => `
    <a class="launcher" href="${escapeAttr(safeUrl(service.url))}" target="_blank" rel="noreferrer" style="--app-color:${safeCssColor(service.color)}">
      <b>${escapeHtml(service.icon)}</b>
      <span>${escapeHtml(service.name)}</span>
    </a>
  `).join("") || noDataPanel("No Apps Loaded", "Service launchers appear after the backend responds.");
}

function renderServices() {
  const services = state.services.filter((service) => {
    if (serviceFilter === "all") return true;
    if (serviceFilter === "healthy") return service.health === "healthy";
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
  `).join("") || emptyState(state.isEmpty ? "No live services loaded. Connect to the backend to view containers." : "No services match this filter.");

  $$("#serviceList [data-service-id]").forEach((button) => {
    button.addEventListener("click", () => openService(button.dataset.serviceId));
  });
}

function renderLogs() {
  renderLiveTailButton();
  $("#logsKicker").textContent = logContext ? "Service logs" : "Recent events";
  $("#logsTitle").textContent = logContext ? `${logContext.name} Logs` : "Logs";
  $("#backToServicesButton").hidden = !logContext;
  const search = $("#logSearch").value.trim().toLowerCase();
  const sourceLogs = logContext ? serviceLogRows : state.logs;
  const logs = sourceLogs.filter((log) => {
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
  `).join("") || emptyState(state.isEmpty ? "No live logs loaded. Connect to the backend to view recent events." : "No log entries found.");
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
  const hasCritical = state.alerts.some((alert) => alert.time === "Active" && alert.state === "bad");
  const hasWarning = state.alerts.some((alert) => alert.time === "Active" && alert.state === "warn");
  $("#activeAlertCount").textContent = `${active} active`;
  $("#activeAlertCount").className = `pill ${hasCritical ? "bad" : hasWarning ? "warn" : "good"}`;
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
  $("#authMethodHelp").textContent = getAuthMethod() === "fingerprint"
    ? "Passkey is active for protected actions. TOTP remains available as a fallback."
    : "TOTP is active for protected actions.";
  $("#backendState").textContent = settings.baseUrl || hasAutoBackend() ? "Configured" : "Not connected";
  $("#passkeyList").innerHTML = passkeyCredentials.map((credential) => `
    <article class="config-card">
      <div>
        <strong>${escapeHtml(credential.deviceLabel || "Registered passkey")}</strong>
        <p>${escapeHtml(credential.lastUsedAt ? `Last used ${formatUpdated(credential.lastUsedAt)}` : `Created ${formatUpdated(credential.createdAt)}`)}</p>
      </div>
      <button class="text-button" type="button" data-delete-passkey="${escapeAttr(credential.credentialId)}">Remove</button>
    </article>
  `).join("") || emptyState("No passkeys registered on this backend yet.");
  $("#deviceTokenList").innerHTML = deviceTokens.map((device) => `
    <article class="config-card ${device.revokedAt ? "is-muted" : ""}">
      <div>
        <strong>${escapeHtml(device.deviceLabel || "Registered device")}${device.isCurrent ? ` <span class="inline-muted">(current)</span>` : ""}</strong>
        <p>${escapeHtml(device.revokedAt ? `Revoked ${formatUpdated(device.revokedAt)}` : device.lastUsedAt ? `Last used ${formatUpdated(device.lastUsedAt)}` : `Created ${formatUpdated(device.createdAt)}`)}</p>
      </div>
      ${device.revokedAt ? `<span class="pill warn">Revoked</span>` : `<button class="text-button" type="button" data-revoke-device="${escapeAttr(device.deviceId)}">Revoke</button>`}
    </article>
  `).join("") || emptyState("No per-device tokens registered yet.");
  $("#deviceTokenHelp").textContent = deviceTokenMessage;
  $("#deviceTokenHelp").hidden = !deviceTokenMessage;
  $("#deviceTokenHelp").className = `config-help ${deviceTokenMessageState}`;
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
  $$("[data-delete-passkey]").forEach((button) => {
    button.addEventListener("click", () => deletePasskey(button.dataset.deletePasskey));
  });
  $$("[data-revoke-device]").forEach((button) => {
    button.addEventListener("click", () => revokeDeviceToken(button.dataset.revokeDevice));
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
      <div><span>Uptime</span><strong>${escapeHtml(service.uptime || service.status)}</strong></div>
      <div><span>Auto restarts</span><strong>${escapeHtml(service.restarts)}</strong></div>
      <div><span>Last issue</span><strong>${escapeHtml(service.lastError)}</strong></div>
    </div>
    <h3 class="subhead">Quick Actions</h3>
    <p class="action-auth-note">${escapeHtml(authMethodLabel())} required for all quick actions.</p>
    <div class="quick-actions">
      ${actionsForService(service).map((action) => `
        <button class="quick-action ${action.danger ? "danger" : ""}" type="button" data-service-action="${escapeAttr(action.kind)}" data-service-id="${escapeAttr(service.id)}">
          <svg><use href="#${escapeAttr(action.icon)}"></use></svg>
          <strong>${escapeHtml(action.title)}</strong>
          <span data-action-label>${escapeHtml(action.detail)}</span>
        </button>
      `).join("")}
    </div>
    <h3 class="subhead">Resources</h3>
    <div class="resource-list">
      ${resourceRow("CPU Usage", service.resources.cpu, 100, "%", "good")}
      ${resourceRow("Memory Usage", service.resources.memory, service.resources.memoryLimit, "MB", "info")}
      ${service.resources.disk !== null && service.resources.diskLimit ? resourceRow("Container Disk", service.resources.disk, service.resources.diskLimit, "GB", service.resources.disk / service.resources.diskLimit > .75 ? "warn" : "good") : ""}
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

  pendingService = service;
  pendingAction = {
    id: actionIdForServiceAction(action.kind, service.id),
    title: `${action.title} ${service.name}`,
    target: service.container,
    detail: action.detail,
    serviceId: service.id,
    kind: action.kind,
    danger: action.danger
  };
  openAuthSheet();
}

function actionIdForServiceAction(actionKind, serviceId) {
  if (actionKind === "logs") return `view-logs-${serviceId}`;
  if (actionKind === "diagnostics") return `view-diagnostics-${serviceId}`;
  return `${actionKind}-${serviceId}`;
}

async function loadServiceLogs(service, auth = {}) {
  try {
    const payload = await api.getServiceLogs(service.id, 100, auth);
    serviceLogRows = (payload.logs || []).map((log) => ({
      level: log.level || "info",
      service: service.id,
      time: log.time || "Recent",
      message: log.message || ""
    }));
    logContext = { serviceId: service.id, name: service.name };
    $("#serviceSheet").close();
    setActiveScreen("logs", { preserveLogContext: true });
    $("#logSearch").value = "";
    addAudit("Viewed logs", service.name, "success", "Fetched from backend");
    renderLogs();
  } catch (error) {
    addAudit("Viewed logs", service.name, "failure", error.message);
    renderInlineNotice(`Could not load logs: ${error.message}`);
  }
}

async function loadServiceDiagnostics(service, button, auth = {}) {
  const label = button?.querySelector("[data-action-label]");
  const originalLabel = label?.textContent || "Run health checks";
  if (button) button.disabled = true;
  if (label) label.textContent = "Running...";
  renderInlineNotice(`Running diagnostics for ${service.name}...`, "info");

  try {
    const payload = await api.getServiceDiagnostics(service.id, auth);
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
    const result = await verifyPasskeyForAction(api, pendingAction);
    pendingAuth = { method: "fingerprint", actionAuthToken: result.actionAuthToken };
    addAudit("Authentication success", pendingAction?.target || "service action", "success", "Passkey");
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
  const completedService = pendingService;

  try {
    let handledSensitiveView = false;
    if (completedAction.kind === "logs" && completedService) {
      await loadServiceLogs(completedService, completedAuth);
      handledSensitiveView = true;
    }
    if (completedAction.kind === "diagnostics" && completedService) {
      await loadServiceDiagnostics(completedService, null, completedAuth);
      handledSensitiveView = true;
    }
    if (!handledSensitiveView) {
      await api.executeAction(completedAction, completedAuth);
      state.logs.unshift({
        level: "info",
        service: "admin",
        time: "Now",
        message: `${completedAction.title} requested from mobile app`
      });
      await refreshState({ preserveServiceSheet: true });
      renderInlineNotice(`${completedAction.title} completed. Status refreshed.`, "good");
    }
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

function setActiveScreen(screenName, options = {}) {
  const shouldResetLogContext = screenName !== "logs" || !options.preserveLogContext;
  if (screenName !== "logs" || !options.preserveLogContext) {
    logContext = null;
    serviceLogRows = [];
  }
  if (shouldResetLogContext) {
    renderLogs();
  }
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
  return localStorage.getItem(storageKeys.authMethod) || "totp";
}

function authMethodLabel() {
  return getAuthMethod() === "fingerprint" ? "Passkey" : "TOTP";
}

async function refreshPasskeys() {
  try {
    const payload = await api.listPasskeys();
    passkeyCredentials = payload.credentials || [];
  } catch {
    passkeyCredentials = [];
  }
  renderConfig();
}

async function refreshDeviceTokens() {
  try {
    const payload = await api.listDevices();
    deviceTokens = (payload.devices || []).map((device) => ({
      ...device,
      isCurrent: device.deviceId === payload.currentDeviceId
    }));
  } catch {
    deviceTokens = [];
  }
  renderConfig();
}

async function registerThisDeviceToken() {
  const button = $("#registerDeviceTokenButton");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Registering...";
  try {
    const settings = readSettings();
    if (!settings.token) {
      throw new Error("Open Backend settings and enter the bootstrap app token before registering this device.");
    }
    const totpCode = await requestTotpForPasskeyManagement("Register Device", "Enter your TOTP code to create a revocable token for this device.");
    if (!totpCode) {
      throw new Error("TOTP is required to register this device.");
    }
    const result = await api.registerDeviceToken(defaultDeviceLabel().replace(/ passkey$/i, ""), totpCode);
    writeSettings({
      ...settings,
      token: result.token
    });
    deviceTokenMessage = "This browser is registered with a revocable device token.";
    deviceTokenMessageState = "good";
    addAudit("Registered device token", "config", "success", result.device?.deviceLabel || "This device");
    await refreshDeviceTokens();
    renderSettings();
    refreshState();
  } catch (error) {
    deviceTokenMessage = error.message;
    deviceTokenMessageState = "bad";
    addAudit("Device token registration failed", "config", "failure", error.message);
    renderConfig();
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function revokeDeviceToken(deviceId) {
  try {
    const totpCode = await requestTotpForPasskeyManagement("Revoke Device", "Enter your TOTP code to revoke this device token.");
    if (!totpCode) {
      throw new Error("TOTP is required to revoke a device token.");
    }
    await api.revokeDeviceToken(deviceId, totpCode);
    addAudit("Revoked device token", "config", "success");
    await refreshDeviceTokens();
  } catch (error) {
    addAudit("Device token revocation failed", "config", "failure", error.message);
    $("#authMethodHelp").textContent = error.message;
  }
}

async function registerThisDevicePasskey() {
  const button = $("#registerPasskeyButton");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Registering...";
  try {
    const totpCode = passkeyCredentials.length
      ? await requestTotpForPasskeyManagement("Register Passkey", "Enter your TOTP code to register another passkey.")
      : null;
    if (passkeyCredentials.length && !totpCode) {
      throw new Error("TOTP is required to register another passkey.");
    }
    const result = await registerPasskey(api, totpCode);
    addAudit("Registered passkey", "config", "success", result.deviceLabel || "This device");
    await refreshPasskeys();
  } catch (error) {
    addAudit("Passkey registration failed", "config", "failure", error.message);
    $("#authMethodHelp").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function deletePasskey(credentialId) {
  try {
    const totpCode = await requestTotpForPasskeyManagement("Remove Passkey", "Enter your TOTP code to remove this passkey.");
    if (!totpCode) {
      throw new Error("TOTP is required to remove a passkey.");
    }
    await api.deletePasskey(credentialId, totpCode);
    addAudit("Removed passkey", "config", "success");
    await refreshPasskeys();
  } catch (error) {
    addAudit("Remove passkey failed", "config", "failure", error.message);
    $("#authMethodHelp").textContent = error.message;
  }
}

function requestTotpForPasskeyManagement(title, message) {
  return new Promise((resolve) => {
    pendingTotpResolve = resolve;
    $("#totpManageTitle").textContent = title;
    $("#totpManageCopy").textContent = message;
    $("#totpManageError").textContent = "";
    $("#totpManageError").hidden = true;
    $("#totpManageInput").value = "";
    $("#totpManageSheet").showModal();
    window.setTimeout(() => $("#totpManageInput").focus(), 0);
  });
}

function resolveTotpManagement(value) {
  if (!pendingTotpResolve) return;
  const resolve = pendingTotpResolve;
  pendingTotpResolve = null;
  resolve(value);
}

function submitTotpManagement() {
  const value = $("#totpManageInput").value.trim();
  if (!/^\d{6}$/.test(value)) {
    $("#totpManageError").textContent = "TOTP must be exactly 6 digits.";
    $("#totpManageError").hidden = false;
    return;
  }
  resolveTotpManagement(value);
  $("#totpManageSheet").close();
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
  $("#totpManageCancelButton").addEventListener("click", () => $("#totpManageSheet").close());
  $("#totpManageSheet").addEventListener("close", () => resolveTotpManagement(null));
  $("#totpManageForm").addEventListener("submit", (event) => {
    event.preventDefault();
    submitTotpManagement();
  });
  $("#totpManageInput").addEventListener("input", () => {
    $("#totpManageError").textContent = "";
    $("#totpManageError").hidden = true;
  });

  $("#refreshButton").addEventListener("click", () => refreshState({ preserveServiceSheet: true }));
  $("#settingsButton").addEventListener("click", () => $("#settingsSheet").showModal());
  $("#backToServicesButton").addEventListener("click", () => setActiveScreen("services"));
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
    logContext = null;
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
      localStorage.setItem(storageKeys.authMethod, button.dataset.authMethod);
      addAudit("Changed auth method", "config", "success", authMethodLabel());
      renderConfig();
    });
  });
  $("#registerPasskeyButton")?.addEventListener("click", registerThisDevicePasskey);
  $("#registerDeviceTokenButton")?.addEventListener("click", registerThisDeviceToken);

  $("#clearAuditButton").addEventListener("click", () => {
    localStorage.removeItem(storageKeys.audit);
    renderAudit();
  });

  $("#settingsForm").addEventListener("submit", (event) => {
    event.preventDefault();
    writeSettings({
      baseUrl: $("#apiBaseInput").value.trim(),
      token: $("#apiTokenInput").value.trim()
    });
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
refreshPasskeys();
refreshDeviceTokens();
