#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const versionPath = path.join(rootDir, "frontend", "version.json");
const VERSION_PATTERN = /^\d{4}\.\d{2}\.\d{2}\.\d+$/;

function git(args, options = {}) {
  const result = spawnSync("git", args, {
    cwd: rootDir,
    encoding: "utf8",
    stdio: options.stdio || "pipe"
  });
  if (!options.allowFailure && result.status !== 0) {
    throw new Error(result.stderr.trim() || result.stdout.trim() || `git ${args.join(" ")} failed`);
  }
  return result;
}

function readVersion() {
  const { version } = JSON.parse(readFileSync(versionPath, "utf8"));
  if (!VERSION_PATTERN.test(version)) {
    throw new Error(`Invalid version in ${versionPath}: expected YYYY.MM.DD.N`);
  }
  return version;
}

function main() {
  if (process.argv.includes("--help") || process.argv.includes("-h")) {
    console.log(`Usage:
  node scripts/tag-release.mjs           Create annotated tag v<frontend/version.json>
  node scripts/tag-release.mjs --print   Print the tag and push commands only`);
    return;
  }

  const version = readVersion();
  const tagName = `v${version}`;
  const branch = git(["branch", "--show-current"]).stdout.trim() || "HEAD";

  if (process.argv.includes("--print")) {
    console.log(`git tag -a ${tagName} -m "Release ${tagName}"`);
    console.log(`git push origin ${branch}`);
    console.log(`git push origin ${tagName}`);
    return;
  }

  const existingTag = git(["rev-parse", "-q", "--verify", `refs/tags/${tagName}`], {
    allowFailure: true
  });
  if (existingTag.status === 0) {
    throw new Error(`Tag already exists: ${tagName}`);
  }

  git(["tag", "-a", tagName, "-m", `Release ${tagName}`], { stdio: "inherit" });
  console.log(`Created annotated tag ${tagName}.`);
  console.log(`Push with: git push origin ${branch} && git push origin ${tagName}`);
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
