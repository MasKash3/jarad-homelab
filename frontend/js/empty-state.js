export function createNoDataState(reason = "Connect to the Jarad backend to load live server data.") {
  return {
    isEmpty: true,
    emptyReason: reason,
    updatedAt: new Date().toISOString(),
    server: {
      name: "Jarad",
      host: "",
      lan: "",
      uptime: "No live data",
      healthScore: "--",
      status: "No connection",
      platform: ""
    },
    metrics: [],
    storage: {
      usedPct: 0,
      label: "Storage unavailable",
      cloudBackup: "Backup status unavailable",
      raid: "Unavailable"
    },
    backups: {
      state: "Unavailable",
      quick: "No data",
      full: "No data",
      next: "No data"
    },
    services: [],
    logs: [],
    dnsAccess: {
      enabled: false,
      lanSubnet: "",
      serverIp: "",
      clients: [],
      summary: {
        pending: 0,
        approved: 0,
        denied: 0,
        expired: 0
      }
    },
    alerts: [
      {
        state: "warn",
        title: "No live backend connection",
        time: "Active",
        body: reason
      }
    ],
    network: [
      ["Backend", "Disconnected"],
      ["Data source", "No live data"]
    ]
  };
}
