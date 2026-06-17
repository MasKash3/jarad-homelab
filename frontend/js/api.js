import { createNoDataState } from './empty-state.js';

function defaultBaseUrl() {
  const isTailscaleHttps = window.location.protocol === "https:" && window.location.hostname.endsWith(".ts.net");
  return isTailscaleHttps ? window.location.origin : "";
}

function effectiveSettings(settings) {
  const currentSettings = settings();
  return {
    ...currentSettings,
    baseUrl: currentSettings.baseUrl || defaultBaseUrl()
  };
}

function connectionLabel(baseUrl) {
  const url = new URL(baseUrl);
  if (url.protocol === "https:" && url.hostname.endsWith(".ts.net")) {
    return "Live via Tailscale";
  }
  if (url.hostname === "127.0.0.1" || url.hostname === "localhost") {
    return "Live local";
  }
  return "Live backend";
}

export function createApi({ addAudit, getState, setConnectionState, settings }) {
  return {
  async getState() {
    const currentSettings = effectiveSettings(settings);
    if (!currentSettings.baseUrl) {
      const reason = "Backend is not configured. Open Config and add the Jarad backend URL and token.";
      setConnectionState({ mode: "disconnected", label: "No backend" });
      return createNoDataState(reason);
    }

    try {
      const response = await fetch(`${currentSettings.baseUrl.replace(/\/$/, "")}/api/mobile/state`, {
        headers: currentSettings.token ? { Authorization: `Bearer ${currentSettings.token}` } : {}
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
    const currentSettings = effectiveSettings(settings);
    if (!currentSettings.baseUrl) {
      throw new Error("Backend is not configured");
    }

    const response = await fetch(`${currentSettings.baseUrl.replace(/\/$/, "")}/api/admin/actions/${action.id}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(currentSettings.token ? { Authorization: `Bearer ${currentSettings.token}` } : {})
      },
      body: JSON.stringify({
        source: "mobile-pwa",
        serviceId: action.serviceId,
        authMethod: auth.method,
        totpCode: auth.totpCode,
        fingerprintVerified: auth.method === "fingerprint" && auth.verified === true
      })
    });
    if (!response.ok) {
      let detail = `Action failed with ${response.status}`;
      try {
        const body = await response.json();
        detail = body.detail || detail;
      } catch {
        // Keep the status fallback when the backend returns a non-JSON error.
      }
      throw new Error(detail);
    }
    addAudit(action.title, action.target, "success", "Backend accepted action");
    return response.json();
  },
  async getServiceLogs(serviceId, limit = 100) {
    const currentSettings = effectiveSettings(settings);
    if (!currentSettings.baseUrl) {
      throw new Error("Backend is not configured");
    }

    const response = await fetch(`${currentSettings.baseUrl.replace(/\/$/, "")}/api/services/${serviceId}/logs?limit=${limit}`, {
      headers: currentSettings.token ? { Authorization: `Bearer ${currentSettings.token}` } : {}
    });
    if (!response.ok) throw new Error(`Logs returned ${response.status}`);
    return response.json();
  },
  async getServiceDiagnostics(serviceId) {
    const currentSettings = effectiveSettings(settings);
    if (!currentSettings.baseUrl) {
      throw new Error("Backend is not configured");
    }

    const response = await fetch(`${currentSettings.baseUrl.replace(/\/$/, "")}/api/services/${serviceId}/diagnostics`, {
      headers: currentSettings.token ? { Authorization: `Bearer ${currentSettings.token}` } : {}
    });
    if (!response.ok) throw new Error(`Diagnostics returned ${response.status}`);
    return response.json();
  }
};


}
