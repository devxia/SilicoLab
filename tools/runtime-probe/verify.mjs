import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = dirname(fileURLToPath(import.meta.url));
const lockBytes = readFileSync(join(directory, 'package-lock.json'));
const lock = JSON.parse(lockBytes);
const cleanEnvironment = { PATH: process.env.PATH, TMPDIR: process.env.TMPDIR, LANG: 'en_US.UTF-8' };
const run = (args) => {
  const result = spawnSync(process.execPath, args, { cwd: directory, env: cleanEnvironment, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
};
run(['node_modules/typescript/bin/tsc', '-p', 'tsconfig.json']);
run(['--test', '--test-concurrency=1', 'test/failures.test.mjs', 'test/ownership.test.mjs', 'test/recovery.test.mjs']);
console.log(JSON.stringify({
  scope: 'issue-2-synthetic-runtime-probe',
  result: 'passed',
  node: process.version,
  platform: process.platform,
  arch: process.arch,
  sqlite: process.versions.sqlite,
  lockSha256: createHash('sha256').update(lockBytes).digest('hex'),
  packages: Object.fromEntries(['pi-durable', 'pi-ai', 'chord'].map((name) => {
    const key = `@earendil-works/${name}`;
    const entry = lock.packages[`node_modules/${key}`];
    return [key, { version: entry.version, integrity: entry.integrity }];
  })),
  limitations: [
    'Synthetic model and artificial effects only; no real provider, scientific computation, or authentication.',
    'No macOS app/background/distribution verification, user-decision UI, Python sandbox, or multi-project scheduler.',
    'A killed model request can be reissued after selection; external effect/result commit is not one atomic transaction.',
    'Advisory owner lock is for cooperating local POSIX processes, not hostile writers, remote filesystems or power loss.',
  ],
}, null, 2));
