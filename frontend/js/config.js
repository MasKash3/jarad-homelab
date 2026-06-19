export const APP_VERSION = "2026.06.19.3";

export const storageKeys = {
  audit: "jarad.audit",
  settings: "jarad.settings",
  authMethod: "jarad.authMethod",
  fingerprintCredential: "jarad.fingerprintCredential"
};

export const legacyStorageKeys = {
  audit: "homelab.audit",
  settings: "homelab.settings",
  authMethod: "homelab.authMethod",
  fingerprintCredential: "homelab.fingerprintCredential"
};

export const serviceActions = [
  { kind: "logs", title: "View Logs", detail: "Protected log access", icon: "icon-log", protected: true },
  { kind: "diagnostics", title: "Diagnostics", detail: "Protected diagnostics", icon: "icon-activity", protected: true },
  { kind: "start", title: "Start", detail: "Protected Docker start", icon: "icon-power", protected: true },
  { kind: "restart", title: "Restart", detail: "Protected Docker restart", icon: "icon-refresh", protected: true },
  { kind: "stop", title: "Stop", detail: "Protected stop action", icon: "icon-power", protected: true, danger: true }
];

export const configActions = [
  { title: "Backend", detail: "FastAPI URL and bootstrap token", target: "Private API" },
  { title: "Devices", detail: "Revocable per-device access tokens", target: "Backend" },
  { title: "Authentication", detail: "Choose fingerprint or TOTP for protected actions", target: "Local device" },
  { title: "Audit", detail: "Recent app and action records", target: "Local log" }
];
