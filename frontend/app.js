import { APP_VERSION, configActions, legacyStorageKeys, serviceActions, storageKeys } from './js/config.js?v=2026.07.16.4';
import { createNoDataState } from './js/empty-state.js?v=2026.07.16.4';
import { clearBrowserSession, createApi, validateBackendBaseUrl } from './js/api.js?v=2026.07.16.4';
import { defaultDeviceLabel, registerPasskey, verifyPasskeyForAction } from './js/auth.js?v=2026.07.16.4';
import { $, $$, diagnosticState, emptyState, escapeAttr, escapeHtml, formatFuture, formatHealth, formatUpdated, labelForState, resourceRow, safeUrl, serviceColorClass, stateClass, toneClass } from './js/utils.js?v=2026.07.16.4';

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
let dnsAccess = createNoDataState().dnsAccess;
let dnsAccessMessage = "";
let dnsAccessMessageState = "muted";
let pendingTotpResolve = null;
let state = createNoDataState();
let connectionState = {
  mode: "disconnected",
  label: "No backend"
};
const DEVICE_RENEWAL_WARNING_DAYS = 14;

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

function clearSavedProductionBackendUrls() {
  if (!hasAutoBackend()) return;
  let cleared = false;
  [storageKeys.settings, legacyStorageKeys.settings].forEach((key) => {
    try {
      const settings = JSON.parse(localStorage.getItem(key)) || {};
      if (!settings.baseUrl) return;
      localStorage.setItem(key, JSON.stringify({ ...settings, baseUrl: "" }));
      cleared = true;
    } catch {
      localStorage.removeItem(key);
      cleared = true;
    }
  });
  if (cleared) {
    clearBrowserSession();
    addAudit("Cleared custom backend URL", "backend", "warning", "Production now uses this HTTPS origin");
  }
}

function readSettings() {
  try {
    return JSON.parse(localStorage.getItem(storageKeys.settings)) || {};
  } catch {
    return {};
  }
}

function writeSettings(settings) {
  const previous = readSettings();
  if (previous.token !== settings.token || previous.baseUrl !== settings.baseUrl) {
    clearBrowserSession();
  }
  localStorage.setItem(storageKeys.settings, JSON.stringify(settings));
}

function clearStoredDeviceToken(expectedToken = null) {
  [storageKeys.settings, legacyStorageKeys.settings].forEach((key) => {
    try {
      const settings = JSON.parse(localStorage.getItem(key)) || {};
      if (!settings.token || (expectedToken && settings.token !== expectedToken)) return;
      localStorage.setItem(key, JSON.stringify({ ...settings, token: "" }));
    } catch {
      // Ignore malformed legacy settings; they are not used for authentication.
    }
  });
  renderSettings();
}

function renderSettingsError(message = "") {
  const error = $("#settingsError");
  error.textContent = message;
  error.hidden = !message;
}

function hasAutoBackend() {
  return window.location.protocol === "https:" && !["localhost", "127.0.0.1"].includes(window.location.hostname);
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

function percentValue(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
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
  const healthScore = percentValue(state.server.healthScore);
  $("#healthScore").textContent = state.server.healthScore;
  $(".score-ring").className = `score-ring ${healthScore >= 80 ? "good" : healthScore >= 60 ? "warn" : "bad"}`;
  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
  $("#metricGrid").innerHTML = state.metrics.map((metric) => `
    <article class="metric">
      <div class="metric-top">
        <span>${escapeHtml(metric.label)}</span>
        <span class="pill ${escapeAttr(metric.state)}">${escapeHtml(metric.badge || labelForState(metric.state))}</span>
      </div>
      <strong>${escapeHtml(metric.value)}${escapeHtml(metric.unit)}</strong>
      <progress class="mini-bar ${escapeAttr(toneClass(metric.state))}" value="${percentValue(metric.value)}" max="100">${percentValue(metric.value)}%</progress>
    </article>
  `).join("") || noDataPanel("No Metrics", state.emptyReason || "Live server metrics are unavailable.");
  $("#raidState").textContent = state.storage.raid;
  $("#raidState").className = `pill ${state.isEmpty ? "warn" : raidStateClass(state.storage.raid)}`;
  const storageUsed = percentValue(state.storage.usedPct);
  $("#storageUsedBar").value = storageUsed;
  $("#storageUsedBar").textContent = `${storageUsed}%`;
  $("#storageUsedBar").className = `storage-bar ${storageUsed > 80 ? "bad" : storageUsed > 65 ? "warn" : "good"}`;
  $("#storageLabel").textContent = state.storage.label;
  $("#cloudBackupLabel").textContent = state.storage.cloudBackup;
  $("#backupState").textContent = state.backups.state;
  $("#backupState").className = `pill ${backupStateClass(state.backups.state)}`;
  $("#quickBackup").textContent = state.backups.quick;
  $("#fullBackup").textContent = state.backups.full;
  $("#nextBackup").textContent = state.backups.next;

  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
  $("#launcherGrid").innerHTML = state.services.map((service) => `
    <a class="launcher ${escapeAttr(serviceColorClass(service.id))}" href="${escapeAttr(safeUrl(service.url))}" target="_blank" rel="noreferrer">
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

  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
  $("#serviceList").innerHTML = services.map((service) => `
    <button class="service-card" type="button" data-service-id="${escapeAttr(service.id)}">
      <span class="service-icon ${escapeAttr(serviceColorClass(service.id))}">${escapeHtml(service.icon)}</span>
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

  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
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
  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
  $("#alertList").innerHTML = state.alerts.map((alert) => `
    <article class="alert-card ${escapeAttr(alert.state)}">
      <header>
        <strong>${escapeHtml(alert.title)}</strong>
        <time>${escapeHtml(alert.time)}</time>
      </header>
      <p>${escapeHtml(alert.body)}</p>
    </article>
  `).join("");
  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
  $("#networkGrid").innerHTML = state.network.map(([label, value]) => `
    <div>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `).join("");
  renderDnsAccess();
}

function renderDnsAccess() {
  const clients = dnsAccess.clients || [];
  const pendingCount = dnsAccess.summary?.pending || 0;
  const approvedCount = dnsAccess.summary?.approved || 0;
  const stateLabel = dnsAccess.enabled ? `${approvedCount} approved` : "Disabled";
  $("#dnsAccessState").textContent = pendingCount ? `${pendingCount} pending` : stateLabel;
  $("#dnsAccessState").className = `pill ${pendingCount ? "warn" : dnsAccess.enabled ? "good" : "muted"}`;
  const firewallWarning = dnsAccess.firewall?.enabled && !dnsAccess.firewall.applied
    ? `Firewall rules were not applied: ${dnsAccess.firewall.detail || "helper failed"}.`
    : "";
  $("#dnsAccessHelp").textContent = dnsAccessMessage || firewallWarning || "DNS approvals sync automatically. Temporary access expires in the background.";
  $("#dnsAccessHelp").className = `config-help ${dnsAccessMessage ? dnsAccessMessageState : firewallWarning ? "bad" : dnsAccessMessageState}`;

  const orderedClients = [...clients].sort((left, right) => {
    const rank = { pending: 0, expired: 1, approved: 2, denied: 3 };
    return (rank[left.effectiveStatus] ?? 4) - (rank[right.effectiveStatus] ?? 4)
      || String(right.lastSeenAt || "").localeCompare(String(left.lastSeenAt || ""));
  });

  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
  $("#dnsClientList").innerHTML = orderedClients.map((client) => {
    const status = client.effectiveStatus || client.status || "pending";
    const clientLabel = client.displayName || client.hostname || "Unnamed device";
    const meta = [
      client.clientIp || "",
      client.macAddress || "",
      client.approvedUntil ? `expires ${formatFuture(client.approvedUntil)}` : "",
      client.lastSeenAt ? `last seen ${formatUpdated(client.lastSeenAt)}` : ""
    ].filter(Boolean).join(" / ");
    const actions = status === "approved"
      ? `<button class="text-button" type="button" data-dns-action="revoke" data-client-ip="${escapeAttr(client.clientIp)}">Revoke</button>`
      : status === "denied"
      ? `<button class="text-button" type="button" data-dns-action="approve-permanent" data-client-ip="${escapeAttr(client.clientIp)}">Approve</button>`
      : `
        <button class="text-button" type="button" data-dns-action="approve-2h" data-client-ip="${escapeAttr(client.clientIp)}">2h</button>
        <button class="text-button" type="button" data-dns-action="approve-permanent" data-client-ip="${escapeAttr(client.clientIp)}">Always</button>
        <button class="text-button" type="button" data-dns-action="deny" data-client-ip="${escapeAttr(client.clientIp)}">Deny</button>
      `;
    return `
      <article class="config-card dns-client-card">
        <div>
          <div class="dns-client-title-row">
            <strong>${escapeHtml(clientLabel)}</strong>
            <button class="text-button compact" type="button" data-dns-label="${escapeAttr(client.clientIp)}">${escapeHtml(client.displayName ? "Rename" : "Name")}</button>
          </div>
          <p>${escapeHtml(meta || "No recent DNS attempts recorded")}</p>
        </div>
        <div class="dns-client-actions">
          <span class="pill ${escapeAttr(statusTone(status))}">${escapeHtml(status)}</span>
          ${actions}
        </div>
      </article>
    `;
  }).join("") || emptyState("No DNS clients recorded yet.");

  $$("#dnsClientList [data-dns-action]").forEach((button) => {
    button.addEventListener("click", () => runDnsClientAction(button.dataset.clientIp, button.dataset.dnsAction));
  });
  $$("#dnsClientList [data-dns-label]").forEach((button) => {
    button.addEventListener("click", () => renameDnsClient(button.dataset.dnsLabel));
  });
}

function statusTone(status) {
  if (status === "approved") return "good";
  if (status === "denied" || status === "expired") return "bad";
  if (status === "pending") return "warn";
  return "muted";
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
  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
  $("#passkeyList").innerHTML = passkeyCredentials.map((credential) => `
    <article class="config-card">
      <div>
        <strong>${escapeHtml(credential.deviceLabel || "Registered passkey")}</strong>
        <p>${escapeHtml(
          credential.lastUsedAt
            ? `Last used ${formatUpdated(credential.lastUsedAt)}`
            : credential.createdAt
            ? `Created ${formatUpdated(credential.createdAt)}`
            : "Usage metadata hidden"
        )}</p>
      </div>
      <button class="text-button" type="button" data-delete-passkey="${escapeAttr(credential.credentialId)}">Remove</button>
    </article>
  `).join("") || emptyState("No passkeys registered on this backend yet.");
  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
  $("#deviceTokenList").innerHTML = deviceTokens.map((device) => {
    const expiresAtMs = Date.parse(device.expiresAt || "");
    const renewalWarning = device.isCurrent
      && Number.isFinite(expiresAtMs)
      && expiresAtMs <= Date.now() + DEVICE_RENEWAL_WARNING_DAYS * 24 * 60 * 60 * 1000;
    const deviceStatus = device.revokedAt
      ? `Revoked ${formatUpdated(device.revokedAt)}`
      : `${
          device.lastUsedAt
            ? `Last used ${formatUpdated(device.lastUsedAt)}`
            : device.createdAt
            ? `Created ${formatUpdated(device.createdAt)}`
            : "Usage metadata hidden"
        }${device.expiresAt ? `; expires ${formatFuture(device.expiresAt)}` : ""}`;
    return `
    <article class="config-card device-token-card ${device.revokedAt ? "is-muted" : ""}">
      <div>
        <strong>${escapeHtml(device.deviceLabel || "Registered device")}${device.isCurrent ? ` <span class="inline-muted">(current)</span>` : ""}</strong>
        <p>${escapeHtml(deviceStatus)}</p>
      </div>
      ${device.revokedAt ? `<span class="pill warn">Revoked</span>` : `
        <div class="device-token-actions">
          ${renewalWarning ? `<span class="pill warn">Renew soon</span>` : ""}
          ${device.isCurrent ? `<button class="text-button" type="button" data-rotate-device>Rotate</button>` : ""}
          <button class="text-button" type="button" data-revoke-device="${escapeAttr(device.deviceId)}">Revoke</button>
        </div>
      `}
    </article>
  `;
  }).join("") || emptyState("No per-device tokens registered yet.");
  $("#deviceTokenHelp").textContent = deviceTokenMessage;
  $("#deviceTokenHelp").hidden = !deviceTokenMessage;
  $("#deviceTokenHelp").className = `config-help ${deviceTokenMessageState}`;
  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
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
  $$("[data-rotate-device]").forEach((button) => {
    button.addEventListener("click", rotateCurrentDeviceToken);
  });
  renderAudit();
}

function renderAudit() {
  const audit = readAudit();
  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
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
  const productionSameOrigin = hasAutoBackend();
  $("#apiBaseInput").value = productionSameOrigin ? "" : settings.baseUrl || "";
  $("#apiBaseInput").disabled = productionSameOrigin;
  $("#apiBaseInput").placeholder = productionSameOrigin
    ? "Using this HTTPS origin"
    : "Leave blank to use this origin";
  $("#apiTokenInput").value = settings.token || "";
  const validation = validateBackendBaseUrl(settings.baseUrl);
  renderSettingsError(validation.ok ? "" : `${validation.message} The app is using this HTTPS origin instead.`);
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
  // xss-reviewed: dynamic template values use escaping or whitelist helpers.
  $("#serviceDetailBody").innerHTML = `
    <div class="service-detail-hero">
      <span class="service-icon large ${escapeAttr(serviceColorClass(service.id))}">${escapeHtml(service.icon)}</span>
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
    // xss-reviewed: dynamic template values use escaping or whitelist helpers.
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

  if (completedAction.danger && !confirmDestructiveAction(completedAction)) {
    addAudit(completedAction.title, completedAction.target, "cancelled", "Final confirmation was not completed");
    pendingAction = null;
    pendingService = null;
    pendingAuth = null;
    return;
  }

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
      if (completedAction.kind?.startsWith("dns-")) {
        await executeDnsClientAction(completedAction, completedAuth);
      } else {
        await api.executeAction(completedAction, completedAuth);
      }
      state.logs.unshift({
        level: "info",
        service: "admin",
        time: "Now",
        message: `${completedAction.title} requested from mobile app`
      });
      if (completedAction.kind?.startsWith("dns-")) {
        await refreshDnsAccess();
      } else {
        await refreshState({ preserveServiceSheet: true });
        renderInlineNotice(`${completedAction.title} completed.`, "good");
      }
    }
  } catch (error) {
    addAudit(completedAction.title, completedAction.target, "failure", error.message);
    if (completedAction.kind?.startsWith("dns-")) {
      dnsAccessMessage = error.message;
      dnsAccessMessageState = "bad";
      renderDnsAccess();
    } else {
      renderInlineNotice(`Action failed: ${error.message}`);
    }
  }

  pendingAction = null;
  pendingService = null;
  pendingAuth = null;
}

function confirmDestructiveAction(action) {
  const confirmationWord = action.kind === "stop"
    ? "STOP"
    : action.kind === "dns-deny"
    ? "DENY"
    : "REVOKE";
  const response = window.prompt(
    `${action.title}\nTarget: ${action.target}\n\nType ${confirmationWord} to execute this destructive action.`
  );
  return response === confirmationWord;
}

async function executeDnsClientAction(action, auth) {
  let result = null;
  if (action.kind === "dns-approve") {
    result = await api.approveDnsClient(action.clientIp, action.duration, auth);
    dnsAccessMessage = `${action.clientIp} approved ${action.duration === "permanent" ? "permanently" : `for ${action.duration}`}.`;
  } else if (action.kind === "dns-deny") {
    result = await api.denyDnsClient(action.clientIp, auth);
    dnsAccessMessage = `${action.clientIp} denied.`;
  } else if (action.kind === "dns-revoke") {
    result = await api.revokeDnsClient(action.clientIp, auth);
    dnsAccessMessage = `${action.clientIp} revoked.`;
  }
  if (result?.firewall?.enabled && !result.firewall.applied) {
    dnsAccessMessage = `${dnsAccessMessage} Firewall rules were not applied: ${result.firewall.detail || "helper failed"}.`;
    dnsAccessMessageState = "warn";
  } else {
    dnsAccessMessageState = "good";
  }
  addAudit(action.title, "dns-access", "success", action.clientIp);
}

function runDnsClientAction(clientIp, actionName) {
  const actionMap = {
    "approve-2h": { kind: "dns-approve", title: "Approve DNS Client", detail: "Temporary DNS access", duration: "2h" },
    "approve-permanent": { kind: "dns-approve", title: "Approve DNS Client", detail: "Permanent DNS access", duration: "permanent" },
    deny: { kind: "dns-deny", title: "Deny DNS Client", detail: "Block DNS access" },
    revoke: { kind: "dns-revoke", title: "Revoke DNS Client", detail: "Remove DNS approval" }
  };
  const action = actionMap[actionName];
  if (!action) return;
  pendingService = null;
  pendingAction = {
    id: `${action.kind.replace("dns-", "dns-")}-${clientIp}`,
    title: `${action.title} ${clientIp}`,
    target: clientIp,
    serviceId: "dns-access",
    clientIp,
    kind: action.kind,
    duration: action.duration,
    detail: action.detail,
    danger: action.kind !== "dns-approve"
  };
  openAuthSheet();
}

async function renameDnsClient(clientIp) {
  const client = (dnsAccess.clients || []).find((item) => item.clientIp === clientIp);
  const currentName = client?.displayName || "";
  const nextName = window.prompt("Device name", currentName);
  if (nextName === null) return;
  try {
    await api.updateDnsClientLabel(clientIp, nextName.trim());
    dnsAccessMessage = nextName.trim() ? `${nextName.trim()} saved.` : "Device name cleared.";
    dnsAccessMessageState = "good";
    addAudit("Renamed DNS client", "dns-access", "success", clientIp);
    await refreshDnsAccess();
  } catch (error) {
    dnsAccessMessage = error.message;
    dnsAccessMessageState = "bad";
    addAudit("Rename DNS client failed", "dns-access", "failure", error.message);
    renderDnsAccess();
  }
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
  dnsAccess = state.dnsAccess || dnsAccess;
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

async function handleRefreshClick(event) {
  const button = event.currentTarget;
  if (button.dataset.refreshing === "true") return;

  button.dataset.refreshing = "true";
  button.disabled = true;
  button.classList.add("is-refreshing");
  button.setAttribute("aria-busy", "true");
  $("#lastUpdated").textContent = "Refreshing…";

  try {
    await Promise.all([
      refreshState({ preserveServiceSheet: true }),
      refreshDnsAccess()
    ]);
  } finally {
    button.disabled = false;
    button.classList.remove("is-refreshing");
    button.removeAttribute("aria-busy");
    button.removeAttribute("data-refreshing");
    button.blur();
  }
}

async function refreshDnsAccess() {
  try {
    dnsAccess = await api.listDnsClients();
  } catch (error) {
    dnsAccessMessage = error.message;
    dnsAccessMessageState = "bad";
  }
  renderDnsAccess();
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
    deviceTokens = (payload.devices || [])
      .filter((device) => !device.revokedAt)
      .map((device) => ({
        ...device,
        isCurrent: device.deviceId === payload.currentDeviceId
      }));
    const currentDevice = deviceTokens.find((device) => device.isCurrent);
    const expiresAtMs = Date.parse(currentDevice?.expiresAt || "");
    if (currentDevice && Number.isFinite(expiresAtMs)
        && expiresAtMs <= Date.now() + DEVICE_RENEWAL_WARNING_DAYS * 24 * 60 * 60 * 1000) {
      deviceTokenMessage = `This device access expires ${formatFuture(currentDevice.expiresAt)}. Rotate it now to renew access.`;
      deviceTokenMessageState = "warn";
    }
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
    clearStoredDeviceToken(settings.token);
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

async function rotateCurrentDeviceToken() {
  try {
    const settings = readSettings();
    const totpCode = await requestTotpForPasskeyManagement("Rotate Device Token", "Enter your TOTP code to replace this browser's device token.");
    if (!totpCode) {
      throw new Error("TOTP is required to rotate this device token.");
    }
    const result = await api.rotateDeviceToken(totpCode);
    clearStoredDeviceToken(settings.token);
    deviceTokenMessage = "This browser's device token was rotated.";
    deviceTokenMessageState = "good";
    addAudit("Rotated device token", "config", "success", result.device?.deviceLabel || "This device");
    await refreshDeviceTokens();
    renderSettings();
    refreshState();
  } catch (error) {
    deviceTokenMessage = error.message;
    deviceTokenMessageState = "bad";
    addAudit("Device token rotation failed", "config", "failure", error.message);
    renderConfig();
  }
}

async function revokeDeviceToken(deviceId) {
  try {
    const device = deviceTokens.find((item) => item.deviceId === deviceId);
    const confirmation = window.prompt(
      `Revoke access for ${device?.deviceLabel || "this device"}? Type REVOKE to continue.`
    );
    if (confirmation !== "REVOKE") return;
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

async function lockCurrentDevice() {
  const confirmation = window.prompt(
    "Lock this phone and revoke its Jarad access? Type LOCK to continue."
  );
  if (confirmation !== "LOCK") return;

  try {
    await api.lockCurrentDevice();
    clearStoredDeviceToken();
    addAudit("Locked current device", "config", "success", "Persistent access revoked");
    window.location.reload();
  } catch (error) {
    deviceTokenMessage = error.message;
    deviceTokenMessageState = "bad";
    addAudit("Device lock failed", "config", "failure", error.message);
    renderConfig();
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
    const credential = passkeyCredentials.find((item) => item.credentialId === credentialId);
    const confirmation = window.prompt(
      `Remove ${credential?.deviceLabel || "this passkey"}? Type REMOVE to continue.`
    );
    if (confirmation !== "REMOVE") return;
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

async function resetLocalAppData() {
  const confirmed = window.confirm(
    "Reset this browser's Jarad app data? You will need to reconnect and authenticate again."
  );
  if (!confirmed) return;

  if ("serviceWorker" in navigator) {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
  }
  if ("caches" in window) {
    const cacheNames = await caches.keys();
    await Promise.all(cacheNames.map((cacheName) => caches.delete(cacheName)));
  }
  sessionStorage.clear();
  localStorage.clear();
  const recoveryUrl = new URL(window.location.href);
  recoveryUrl.searchParams.set("recovered", Date.now().toString());
  window.location.replace(recoveryUrl.href);
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

  $("#refreshButton").addEventListener("click", handleRefreshClick);
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
  $("#lockCurrentDeviceButton")?.addEventListener("click", lockCurrentDevice);
  $("#resetLocalAppButton")?.addEventListener("click", () => {
    resetLocalAppData().catch((error) => {
      addAudit("PWA recovery failed", "local app", "failure", error.message);
      window.alert("Local app reset failed. Clear this site's data in your browser settings.");
    });
  });

  $("#clearAuditButton").addEventListener("click", () => {
    localStorage.removeItem(storageKeys.audit);
    renderAudit();
  });

  $("#settingsForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const baseUrlValidation = validateBackendBaseUrl($("#apiBaseInput").value);
    if (!baseUrlValidation.ok) {
      renderSettingsError(baseUrlValidation.message);
      addAudit("Rejected backend URL", "backend", "warning", baseUrlValidation.message);
      return;
    }
    writeSettings({
      baseUrl: baseUrlValidation.baseUrl,
      token: $("#apiTokenInput").value.trim()
    });
    addAudit("Saved settings", "backend", "success");
    $("#settingsSheet").close();
    refreshState();
  });
  $("#apiBaseInput").addEventListener("input", () => renderSettingsError(""));
  window.addEventListener("jarad-device-token-migrated", () => {
    clearStoredDeviceToken();
  });
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js", { scope: "./", updateViaCache: "none" }).catch(() => {});
}

migrateLegacyStorage();
clearSavedProductionBackendUrls();
bindEvents();
refreshState();
refreshPasskeys();
refreshDeviceTokens();
refreshDnsAccess();
