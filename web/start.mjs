import { spawn } from 'node:child_process';
import { cpSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const runtime = join(root, '.next/standalone/web');
const server = join(runtime, 'server.js');
if (!existsSync(server)) throw new Error('Run pnpm build before pnpm start');
const args = process.argv.slice(2);
if (args.length && (args.length !== 2 || args[0] !== '--port')) throw new Error('Only --port is supported');
const port = args[1] ?? process.env.PORT ?? '3000';
if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) throw new Error('Invalid port');
cpSync(join(root, '.next/static'), join(runtime, '.next/static'), { recursive: true });
if (existsSync(join(root, 'public'))) cpSync(join(root, 'public'), join(runtime, 'public'), { recursive: true });
const child = spawn(process.execPath, [server], {
  cwd: runtime,
  env: { ...process.env, HOSTNAME: '127.0.0.1', PORT: port },
  stdio: 'inherit',
});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('error', (error) => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code, signal) => { process.exitCode = code ?? (signal === 'SIGINT' ? 130 : 1); });
