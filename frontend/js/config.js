export const APP_VERSION = "2026.07.16.8";

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
