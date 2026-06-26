#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const extensionRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(extensionRoot, '..');
const pkg = require(path.join(extensionRoot, 'package.json'));
const out = path.join(repoRoot, 'dist', `local-shell-mcp-vscode-${pkg.version}.vsix`);
const vsce = require.resolve('@vscode/vsce/vsce');

fs.mkdirSync(path.dirname(out), { recursive: true });
execFileSync(process.execPath, [vsce, 'package', '--no-dependencies', '--out', out], {
  cwd: extensionRoot,
  stdio: 'inherit',
});
