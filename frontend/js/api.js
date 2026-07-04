import { createNoDataState } from './empty-state.js';

const LOCAL_HOSTNAMES = new Set(["localhost", "127.0.0.1"]);
const BROWSER_SESSION_KEY = "jarad.browserSession";
const SESSION_REFRESH_SKEW_MS = 30_000;

export function isProductionFrontend() {
  return window.location.protocol === "https:" && !LOCAL_HOSTNAMES.has(window.location.hostname);
}

function defaultBaseUrl() {
  const isTailscaleHttps = window.location.protocol === "https:" && window.location.hostname.endsWith(".ts.net");
  const isHttpsCustomDomain = isProductionFrontend();
  return isTailscaleHttps || isHttpsCustomDomain ? window.location.origin : "";
}

export function validateBackendBaseUrl(baseUrl) {
  const rawBaseUrl = String(baseUrl || "").trim();
  if (!rawBaseUrl) {
    return { ok: true, baseUrl: "" };
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(rawBaseUrl, window.location.origin);
  } catch {
    return { ok: false, message: "Enter a valid backend URL." };
  }

  if (isProductionFrontend()) {
    if (parsedUrl.protocol !== "https:" || parsedUrl.origin !== window.location.origin) {
      return {
        ok: false,
        message: "Production uses the same HTTPS origin for the backend. Leave this blank unless you are on a local dev page."
      };
    }
  }

  if (!["http:", "https:"].includes(parsedUrl.protocol)) {
    return { ok: false, message: "Backend URL must use HTTP or HTTPS." };
  }

  return { ok: true, baseUrl: parsedUrl.href.replace(/\/$/, "") };
}

function effectiveSettings(settings) {
  const currentSettings = settings();
  const validation = validateBackendBaseUrl(currentSettings.baseUrl);
  return {
    ...currentSettings,
    baseUrl: validation.ok && validation.baseUrl ? validation.baseUrl : defaultBaseUrl()
  };
}

function readBrowserSession() {
  try {
    return JSON.parse(sessionStorage.getItem(BROWSER_SESSION_KEY)) || {};
  } catch {
    return {};
  }
}

function writeBrowserSession(session) {
  sessionStorage.setItem(BROWSER_SESSION_KEY, JSON.stringify(session));
}

export function clearBrowserSession() {
  sessionStorage.removeItem(BROWSER_SESSION_KEY);
}

function hasUsableBrowserSession(session) {
  if (!session.token || !session.expiresAt) return false;
  return Date.parse(session.expiresAt) > Date.now() + SESSION_REFRESH_SKEW_MS;
}

async function createBrowserSession(currentSettings) {
  if (!currentSettings.baseUrl) return null;
  const response = await fetch(`${currentSettings.baseUrl.replace(/\/$/, "")}/api/auth/session`, {
    method: "POST",
    credentials: "include",
    headers: currentSettings.token ? { Authorization: `Bearer ${currentSettings.token}` } : {}
  });
  if (!response.ok) return null;
  const payload = await response.json();
  if (!payload.token || !payload.session?.expiresAt) return null;
  const session = {
    token: payload.token,
    expiresAt: payload.session.expiresAt,
    sessionId: payload.session.sessionId,
    deviceId: payload.session.deviceId
  };
  writeBrowserSession(session);
  if (currentSettings.token) {
    window.dispatchEvent(new CustomEvent("jarad-device-token-migrated"));
  }
  return session;
}

async function authTokenFor(currentSettings, authMode = "session") {
  if (authMode === "device") return currentSettings.token;
  if (authMode === "cookie") return "";

  const existingSession = readBrowserSession();
  if (hasUsableBrowserSession(existingSession)) return existingSession.token;

  const nextSession = await createBrowserSession(currentSettings);
  return nextSession?.token || currentSettings.token;
}

function connectionLabel(baseUrl) {
  const url = new URL(baseUrl);
  if (url.protocol === "https:" && url.hostname.endsWith(".ts.net")) {
    return "Live via Tailscale";
  }
  if (url.protocol === "https:") {
    return "Live via private domain";
  }
  if (url.hostname === "127.0.0.1" || url.hostname === "localhost") {
    return "Live local";
  }
  return "Live backend";
}

export function createApi({ addAudit, getState, setConnectionState, settings }) {
  async function request(path, options = {}) {
    const currentSettings = effectiveSettings(settings);
    if (!currentSettings.baseUrl) {
      throw new Error("Backend is not configured");
    }
    const { authMode = "session", ...fetchOptions } = options;
    const authToken = await authTokenFor(currentSettings, authMode);

    const response = await fetch(`${currentSettings.baseUrl.replace(/\/$/, "")}${path}`, {
      ...fetchOptions,
      credentials: "include",
      headers: {
        ...(fetchOptions.body ? { "Content-Type": "application/json" } : {}),
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        ...(fetchOptions.headers || {})
      }
    });
    if (!response.ok) {
      let detail = `Request failed with ${response.status}`;
      try {
        const body = await response.json();
        detail = body.detail || detail;
      } catch {
        // Keep the status fallback when the backend returns a non-JSON error.
      }
      throw new Error(detail);
    }
    return response.json();
  }

  return {
  async getState() {
    const currentSettings = effectiveSettings(settings);
    if (!currentSettings.baseUrl) {
      const reason = "Backend is not configured. Open Config and add the Jarad backend URL and token.";
      setConnectionState({ mode: "disconnected", label: "No backend" });
      return createNoDataState(reason);
    }

    try {
      const authToken = await authTokenFor(currentSettings);
      const response = await fetch(`${currentSettings.baseUrl.replace(/\/$/, "")}/api/mobile/state`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {}
      });
      if (!response.ok) throw new Error(`Backend returned ${response.status}`);
      const data = await response.json();
      setConnectionState({
        mode: "live",
        label: connectionLabel(currentSettings.baseUrl)
      });
      return data;
    } catch (error) {
      const reason = `Could not load live data: ${error.message}`;
      addAudit("API unavailable", "app", "warning", error.message);
      setConnectionState({
        mode: "disconnected",
        label: "No live data"
      });
      return createNoDataState(reason);
    }
  },
  async executeAction(action, auth = {}) {
    const payload = await request(`/api/admin/actions/${action.id}`, {
      method: "POST",
      body: JSON.stringify({
        source: "mobile-pwa",
        serviceId: action.serviceId,
        authMethod: auth.method,
        totpCode: auth.totpCode,
        actionAuthToken: auth.actionAuthToken
      })
    });
    addAudit(action.title, action.target, "success", "Backend accepted action");
    return payload;
  },
  async listPasskeys() {
    return request("/api/auth/webauthn/credentials");
  },
  async listDevices() {
    return request("/api/auth/devices");
  },
  async registerDeviceToken(deviceLabel, totpCode) {
    return request("/api/auth/devices/register", {
      method: "POST",
      body: JSON.stringify({ deviceLabel, totpCode }),
      authMode: "device"
    });
  },
  async rotateDeviceToken(totpCode) {
    const result = await request("/api/auth/devices/current/rotate", {
      method: "POST",
      body: JSON.stringify({ totpCode }),
      authMode: "cookie"
    });
    clearBrowserSession();
    return result;
  },
  async revokeDeviceToken(deviceId, totpCode) {
    return request(`/api/auth/devices/${encodeURIComponent(deviceId)}`, {
      method: "DELETE",
      body: JSON.stringify({ totpCode })
    });
  },
  async deletePasskey(credentialId, totpCode) {
    return request(`/api/auth/webauthn/credentials/${encodeURIComponent(credentialId)}`, {
      method: "DELETE",
      body: JSON.stringify({ totpCode })
    });
  },
  async getPasskeyRegistrationOptions(deviceLabel, totpCode) {
    return request("/api/auth/webauthn/register/options", {
      method: "POST",
      body: JSON.stringify({ deviceLabel, totpCode })
    });
  },
  async verifyPasskeyRegistration(challengeId, credential, deviceLabel, totpCode) {
    return request("/api/auth/webauthn/register/verify", {
      method: "POST",
      body: JSON.stringify({ challengeId, credential, deviceLabel, totpCode })
    });
  },
  async getPasskeyAuthenticationOptions(action) {
    return request("/api/auth/webauthn/authenticate/options", {
      method: "POST",
      body: JSON.stringify({
        actionId: action?.id,
        serviceId: action?.serviceId
      })
    });
  },
  async verifyPasskeyAuthentication(challengeId, credential, action) {
    return request("/api/auth/webauthn/authenticate/verify", {
      method: "POST",
      body: JSON.stringify({
        challengeId,
        credential,
        actionId: action?.id,
        serviceId: action?.serviceId
      })
    });
  },
  async getServiceLogs(serviceId, limit = 100, auth = {}) {
    return request(`/api/services/${serviceId}/logs?limit=${limit}`, {
      method: "POST",
      body: JSON.stringify({
        source: "mobile-pwa",
        serviceId,
        authMethod: auth.method,
        totpCode: auth.totpCode,
        actionAuthToken: auth.actionAuthToken
      })
    });
  },
  async getServiceDiagnostics(serviceId, auth = {}) {
    return request(`/api/services/${serviceId}/diagnostics`, {
      method: "POST",
      body: JSON.stringify({
        source: "mobile-pwa",
        serviceId,
        authMethod: auth.method,
        totpCode: auth.totpCode,
        actionAuthToken: auth.actionAuthToken
      })
    });
  },
  async listDnsClients() {
    return request("/api/dns/clients");
  },
  async approveDnsClient(clientIp, duration, auth = {}) {
    return request(`/api/dns/clients/${encodeURIComponent(clientIp)}/approve`, {
      method: "POST",
      body: JSON.stringify({
        source: "mobile-pwa",
        serviceId: "dns-access",
        duration,
        authMethod: auth.method,
        totpCode: auth.totpCode,
        actionAuthToken: auth.actionAuthToken
      })
    });
  },
  async denyDnsClient(clientIp, auth = {}) {
    return request(`/api/dns/clients/${encodeURIComponent(clientIp)}/deny`, {
      method: "POST",
      body: JSON.stringify({
        source: "mobile-pwa",
        serviceId: "dns-access",
        authMethod: auth.method,
        totpCode: auth.totpCode,
        actionAuthToken: auth.actionAuthToken
      })
    });
  },
  async revokeDnsClient(clientIp, auth = {}) {
    return request(`/api/dns/clients/${encodeURIComponent(clientIp)}/revoke`, {
      method: "POST",
      body: JSON.stringify({
        source: "mobile-pwa",
        serviceId: "dns-access",
        authMethod: auth.method,
        totpCode: auth.totpCode,
        actionAuthToken: auth.actionAuthToken
      })
    });
  },
  async updateDnsClientLabel(clientIp, displayName) {
    return request(`/api/dns/clients/${encodeURIComponent(clientIp)}/label`, {
      method: "POST",
      body: JSON.stringify({ displayName })
    });
  }
};


}
