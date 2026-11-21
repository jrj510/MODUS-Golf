import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
// Shared React development remains available on Windows.
if (process.platform === 'darwin') {
  const result=spawnSync('swift',[fileURLToPath(new URL('./patch-auth.swift',import.meta.url))],{stdio:'inherit'});
  if(result.error) console.error('Native auth diagnostics require the installed Swift toolchain.');
  process.exitCode=result.status ?? 1;
}
