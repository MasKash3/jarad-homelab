import { cloneMockState } from './mock-state.js';

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
      setConnectionState({ mode: "mock", label: "Mock mode" });
      return cloneMockState();
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
      addAudit("API fallback", "app", "warning", error.message);
      setConnectionState({
        mode: "fallback",
        label: `Fallback: ${error.message}`
      });
      return cloneMockState();
    }
  },
  async executeAction(action, auth = {}) {
    const currentSettings = effectiveSettings(settings);
    if (!currentSettings.baseUrl) {
      addAudit(action.title, action.target, "simulated", "No backend configured");
      return { simulated: true };
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
      return {
        service: serviceId,
        logs: getState().logs.filter((log) => log.service === serviceId || log.service === "backup")
      };
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
      const service = getState().services.find((item) => item.id === serviceId);
      return {
        service: serviceId,
        checks: (service?.diagnostics || []).map(([label, detail]) => ({
          label,
          state: String(detail).toLowerCase().includes("failed") ? "fail" : "pass",
          detail
        })),
        suggestedFix: null
      };
    }

    const response = await fetch(`${currentSettings.baseUrl.replace(/\/$/, "")}/api/services/${serviceId}/diagnostics`, {
      headers: currentSettings.token ? { Authorization: `Bearer ${currentSettings.token}` } : {}
    });
    if (!response.ok) throw new Error(`Diagnostics returned ${response.status}`);
    return response.json();
  }
};


}
