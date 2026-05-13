#!/usr/bin/env node
/**
 * Phase 5.7 — Brand-compliance scanner.
 *
 * The LogikIntake rebrand binds every UI surface to six tokens:
 *   --brand-teal, --brand-purple, --brand-orange, --brand-charcoal,
 *   --brand-gray, --brand-white
 * (declared in `src/app/globals.css` and surfaced as Tailwind tokens
 * `brand-teal`, `brand-purple`, … in `tailwind.config.ts`).
 *
 * The matching ESLint rule (`no-restricted-syntax` in `.eslintrc.json`)
 * already prevents new raw hex literals from landing in `className=` or
 * `style=` props at lint time. This script gives CI an additional, more
 * permissive guardrail: it scans every TS/JS source file under `src/`
 * for raw `#RRGGBB` (or `#RGB`, `#RRGGBBAA`) literals and reports them.
 *
 * Allowlisted files (where hex tokens are *intended* to live):
 *   - `src/app/globals.css`        — CSS variable declarations
 *   - `tailwind.config.ts`         — Tailwind theme map
 *   - `next.config.js` / `postcss.config.js` — build tooling
 *
 * Exit code:
 *   0 — clean
 *   1 — at least one violation found
 *
 * Usage:
 *   node scripts/check-brand-tokens.mjs              (CI)
 *   node scripts/check-brand-tokens.mjs --quiet      (only summary)
 */

import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  ".."
);
const SRC_DIR = path.join(ROOT, "src");

const SCAN_EXTS = new Set([".ts", ".tsx", ".js", ".jsx"]);

// Files where hex literals are *expected* — these define the brand tokens
// themselves or live in build-tooling glue that doesn't render UI.
const ALLOWLIST = new Set([
  path.join(ROOT, "src", "app", "globals.css"),
  path.join(ROOT, "tailwind.config.ts"),
  path.join(ROOT, "tailwind.config.js"),
  path.join(ROOT, "next.config.js"),
  path.join(ROOT, "postcss.config.js"),
]);

// Skip directories we can't fix (vendor / generated).
const SKIP_DIRS = new Set([
  "node_modules",
  ".next",
  "dist",
  "build",
  ".turbo",
  ".git",
]);

const HEX_RE = /#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3,4})\b/g;

const args = new Set(process.argv.slice(2));
const QUIET = args.has("--quiet");

async function* walk(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name.startsWith(".") && entry.name !== ".eslintrc.json") {
      // Skip hidden files (e.g. .next, .git). Top-level dotfiles are
      // explicitly skipped via SKIP_DIRS too.
      continue;
    }
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      yield* walk(full);
    } else if (entry.isFile()) {
      const ext = path.extname(entry.name);
      if (!SCAN_EXTS.has(ext)) continue;
      if (ALLOWLIST.has(full)) continue;
      yield full;
    }
  }
}

/**
 * Strip block + line comments so we don't false-positive on documentation
 * that mentions hex codes. Heuristic only — close enough for a guardrail
 * but not a parser.
 */
function stripComments(text) {
  // Remove /* … */ blocks (non-greedy, multiline).
  let out = text.replace(/\/\*[\s\S]*?\*\//g, "");
  // Remove // … line comments.
  out = out.replace(/(^|[^:"'])\/\/[^\n]*/g, (m, prefix) => prefix);
  return out;
}

async function main() {
  const violations = [];
  for await (const file of walk(SRC_DIR)) {
    const raw = await fs.readFile(file, "utf8");
    const stripped = stripComments(raw);
    const lines = stripped.split(/\r?\n/);
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const matches = line.match(HEX_RE);
      if (!matches) continue;
      for (const m of matches) {
        violations.push({
          file: path.relative(ROOT, file),
          line: i + 1,
          token: m,
          snippet: line.trim().slice(0, 160),
        });
      }
    }
  }

  if (violations.length === 0) {
    if (!QUIET) {
      console.log("brand:check — no raw hex literals found in src/. Clean.");
    }
    process.exit(0);
  }

  console.error(
    `brand:check — found ${violations.length} raw hex literal${
      violations.length === 1 ? "" : "s"
    } outside the brand-token allowlist:\n`
  );
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line}  ${v.token}`);
    if (!QUIET) {
      console.error(`    ${v.snippet}`);
    }
  }
  console.error(
    "\nUse brand-* Tailwind tokens (brand-teal, brand-purple, brand-orange, brand-charcoal, brand-gray, brand-white) or var(--brand-*) instead."
  );
  process.exit(1);
}

main().catch((err) => {
  console.error("brand:check — fatal:", err);
  process.exit(2);
});
