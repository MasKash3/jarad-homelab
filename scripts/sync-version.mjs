#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const versionPath = path.join(rootDir, "frontend", "version.json");
const VERSION_PATTERN = /^\d{4}\.\d{2}\.\d{2}\.\d+$/;
const VERSION_ANYWHERE_PATTERN = /\d{4}\.\d{2}\.\d{2}\.\d+/g;

const targets = [
  "frontend/js/config.js",
  "frontend/app.js",
  "frontend/index.html",
  "frontend/sw.js"
];

function readVersionFile() {
  const data = JSON.parse(readFileSync(versionPath, "utf8"));
  if (!data.version || !VERSION_PATTERN.test(data.version)) {
    throw new Error(`Invalid version in ${versionPath}: expected YYYY.MM.DD.N`);
  }
  return data.version;
}

function writeVersionFile(version) {
  writeFileSync(versionPath, `${JSON.stringify({ version }, null, 2)}\n`);
}

function parseArgs(argv) {
  const options = {
    check: false,
    next: false,
    print: false,
    set: null
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--check") {
      options.check = true;
    } else if (arg === "--next") {
      options.next = true;
    } else if (arg === "--print") {
      options.print = true;
    } else if (arg === "--set") {
      options.set = argv[index + 1];
      index += 1;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  if (options.next && options.set) {
    throw new Error("Use either --next or --set, not both.");
  }

  if (options.set && !VERSION_PATTERN.test(options.set)) {
    throw new Error("--set must use YYYY.MM.DD.N, for example 2026.06.20.3");
  }

  return options;
}

function todayPrefix() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}.${month}.${day}`;
}

function nextVersion(currentVersion) {
  const prefix = todayPrefix();
  if (currentVersion.startsWith(`${prefix}.`)) {
    const patch = Number(currentVersion.split(".").at(-1));
    return `${prefix}.${patch + 1}`;
  }
  return `${prefix}.1`;
}

function updateContent(filePath, content, version) {
  const relativePath = filePath.replaceAll("\\", "/");
  if (relativePath === "frontend/js/config.js") {
    return content.replace(
      /export const APP_VERSION = "[^"]+";/,
      `export const APP_VERSION = "${version}";`
    );
  }
  return content.replace(VERSION_ANYWHERE_PATTERN, version);
}

function printHelp() {
  console.log(`Usage:
  node scripts/sync-version.mjs              Sync frontend files from frontend/version.json
  node scripts/sync-version.mjs --next       Bump to today's next YYYY.MM.DD.N version and sync
  node scripts/sync-version.mjs --set <ver>  Set an explicit YYYY.MM.DD.N version and sync
  node scripts/sync-version.mjs --check      Verify derived frontend files match frontend/version.json
  node scripts/sync-version.mjs --print      Print the current source-of-truth version`);
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const currentVersion = readVersionFile();
  const version = options.next ? nextVersion(currentVersion) : options.set || currentVersion;

  if (options.print) {
    console.log(version);
  }

  if (!options.check && version !== currentVersion) {
    writeVersionFile(version);
  }

  const changed = [];
  for (const target of targets) {
    const filePath = path.join(rootDir, target);
    const currentContent = readFileSync(filePath, "utf8");
    const nextContent = updateContent(target, currentContent, version);
    if (currentContent !== nextContent) {
      changed.push(target);
      if (!options.check) {
        writeFileSync(filePath, nextContent);
      }
    }
  }

  if (options.check && changed.length > 0) {
    throw new Error(`Version sync check failed for: ${changed.join(", ")}`);
  }

  if (!options.print) {
    const action = options.check ? "checked" : changed.length > 0 ? "synced" : "already synced";
    console.log(`Frontend version ${version} ${action}.`);
  }
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
