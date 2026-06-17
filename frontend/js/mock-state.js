export const mockState = {
  updatedAt: new Date(),
  server: {
    name: "Jarad",
    host: "home.example",
    lan: "10.0.0.10",
    uptime: "18 days, 7 hours",
    healthScore: 96,
    status: "Operational"
  },
  metrics: [
    { label: "CPU", value: 22, unit: "%", state: "good" },
    { label: "RAM", value: 61, unit: "%", state: "good" },
    { label: "Disk", value: 70, unit: "%", state: "warn", badge: "70% used" },
    { label: "Temp", value: 48, unit: "C", state: "good" }
  ],
  storage: {
    usedPct: 70,
    label: "1.28 TB used of 1.82 TB",
    cloudBackup: "Cloud backup 342 GB",
    raid: "RAID clean"
  },
  backups: {
    state: "Healthy",
    quick: "Today 18:00",
    full: "Today 06:00",
    next: "Tonight 00:00"
  },
  services: [
    {
      id: "nextcloud",
      name: "Nextcloud",
      type: "Files",
      icon: "NC",
      container: "nextcloud-app-1",
      image: "nextcloud:latest",
      status: "running",
      health: "healthy",
      restarts: 0,
      cpu: 3,
      ram: 420,
      url: "https://home.example",
      color: "#2563a6",
      lastError: "No recent errors",
      diagnostics: [
        ["Container", "Running"],
        ["Database", "Reachable"],
        ["Redis", "Reachable"],
        ["External storage", "Mounted"],
        ["Recent errors", "None"]
      ],
      resources: { cpu: 3, memory: 420, memoryLimit: 1536, disk: 4.2, diskLimit: 50 }
    },
    {
      id: "immich",
      name: "Immich",
      type: "Photos",
      icon: "IM",
      container: "immich_server",
      image: "ghcr.io/immich-app/immich-server:release",
      status: "running",
      health: "healthy",
      restarts: 0,
      cpu: 8,
      ram: 890,
      url: "https://home.example:2283",
      color: "#0f766e",
      lastError: "No recent errors",
      diagnostics: [
        ["Server", "Running"],
        ["Postgres", "Reachable"],
        ["Upload path", "/srv/data/photos"],
        ["Background jobs", "Normal"],
        ["Recent errors", "None"]
      ],
      resources: { cpu: 8, memory: 890, memoryLimit: 2048, disk: 218, diskLimit: 1400 }
    },
    {
      id: "jellyfin",
      name: "Jellyfin",
      type: "Media",
      icon: "JF",
      container: "jellyfin",
      image: "jellyfin/jellyfin:latest",
      status: "running",
      health: "healthy",
      restarts: 1,
      cpu: 11,
      ram: 760,
      url: "https://home.example:8096",
      color: "#7c3aed",
      lastError: "Transcode warning yesterday",
      diagnostics: [
        ["Container", "Running"],
        ["Media path", "Mounted"],
        ["Port", "18096 internal"],
        ["Recent errors", "1 warning"],
        ["Suggested fix", "Check transcode cache if repeated"]
      ],
      resources: { cpu: 11, memory: 760, memoryLimit: 2048, disk: 38, diskLimit: 500 }
    },
    {
      id: "portainer",
      name: "Portainer",
      type: "Docker UI",
      icon: "PT",
      container: "portainer",
      image: "portainer/portainer-ce:latest",
      status: "running",
      health: "healthy",
      restarts: 0,
      cpu: 1,
      ram: 120,
      url: "https://home.example:9000",
      color: "#0ea5e9",
      lastError: "No recent errors",
      diagnostics: [
        ["Container", "Running"],
        ["Docker socket", "Mounted"],
        ["Binding", "Private network IP"],
        ["Recent errors", "None"]
      ],
      resources: { cpu: 1, memory: 120, memoryLimit: 512, disk: 1.1, diskLimit: 10 }
    },
    {
      id: "pihole",
      name: "Pi-hole",
      type: "DNS",
      icon: "PH",
      container: "pihole",
      image: "pihole/pihole:latest",
      status: "running",
      health: "degraded",
      restarts: 0,
      cpu: 2,
      ram: 170,
      url: "https://home.example:8053",
      color: "#dc2626",
      lastError: "Upstream latency spike",
      diagnostics: [
        ["Container", "Running"],
        ["DNS test", "Pass"],
        ["Unbound", "Reachable"],
        ["Latency", "Elevated"],
        ["Suggested fix", "Retest upstream resolver"]
      ],
      resources: { cpu: 2, memory: 170, memoryLimit: 512, disk: 0.8, diskLimit: 10 }
    },
    {
      id: "dozzle",
      name: "Dozzle",
      type: "Logs",
      icon: "DZ",
      container: "dozzle",
      image: "amir20/dozzle:latest",
      status: "running",
      health: "healthy",
      restarts: 0,
      cpu: 1,
      ram: 95,
      url: "https://home.example:8082",
      color: "#334155",
      lastError: "No recent errors",
      diagnostics: [
        ["Container", "Running"],
        ["Docker socket", "Mounted"],
        ["Live logs", "Available"],
        ["Recent errors", "None"]
      ],
      resources: { cpu: 1, memory: 95, memoryLimit: 256, disk: 0.2, diskLimit: 5 }
    },
    {
      id: "uptime-kuma",
      name: "Uptime Kuma",
      type: "Monitor",
      icon: "UK",
      container: "uptime-kuma",
      image: "louislam/uptime-kuma:latest",
      status: "running",
      health: "healthy",
      restarts: 0,
      cpu: 2,
      ram: 210,
      url: "https://home.example:3001",
      color: "#16a34a",
      lastError: "No recent errors",
      diagnostics: [
        ["Container", "Running"],
        ["Monitors", "All active"],
        ["Notifications", "Enabled"],
        ["Recent errors", "None"]
      ],
      resources: { cpu: 2, memory: 210, memoryLimit: 512, disk: 0.6, diskLimit: 10 }
    },
    {
      id: "stirling-pdf",
      name: "Stirling PDF",
      type: "Tools",
      icon: "SP",
      container: "stirling-pdf",
      image: "frooodle/s-pdf:latest",
      status: "running",
      health: "healthy",
      restarts: 0,
      cpu: 1,
      ram: 260,
      url: "https://home.example:8081",
      color: "#ca8a04",
      lastError: "No recent errors",
      diagnostics: [
        ["Container", "Running"],
        ["OCR data", "Mounted"],
        ["Security mode", "Disabled"],
        ["Recent errors", "None"]
      ],
      resources: { cpu: 1, memory: 260, memoryLimit: 1024, disk: 0.5, diskLimit: 10 }
    }
  ],
  logs: [
    { level: "info", service: "backup", time: "18:04", message: "Quick backup complete - Cloud backup usage 342.0 GB" },
    { level: "info", service: "nextcloud", time: "17:52", message: "External storage scan completed" },
    { level: "warn", service: "dns", time: "16:41", message: "Pi-hole upstream latency elevated for 2 checks" },
    { level: "info", service: "immich", time: "15:19", message: "Background jobs normal" },
    { level: "error", service: "jellyfin", time: "Yesterday", message: "Transcode warning: fallback codec selected" },
    { level: "info", service: "raid", time: "Yesterday", message: "md0 state clean [UU]" }
  ],
  alerts: [
    { state: "warn", title: "Disk usage is climbing", time: "Active", body: "/srv/data is at 70%. Monitor Immich uploads and Nextcloud versions." },
    { state: "warn", title: "DNS latency elevated", time: "Active", body: "Pi-hole is responding, but upstream lookup time has been higher than usual." },
    { state: "good", title: "Full backup recovered", time: "Today 06:48", body: "Full cloud sync completed successfully after the previous warning." }
  ],
  network: [
    ["DNS", "OK"],
    ["Gateway", "Reachable"],
    ["Private network", "Connected"],
    ["Cloud backup", "Reachable"]
  ]
};

export function cloneMockState() {
  return {
    ...JSON.parse(JSON.stringify(mockState)),
    updatedAt: new Date()
  };
}
