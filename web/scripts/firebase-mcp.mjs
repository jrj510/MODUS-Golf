// Small stdio client for the official Firebase MCP server. No credentials are
// read by this script; the server uses the Firebase CLI's existing login.
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
const child = spawn(process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', 'npx -y firebase-tools@latest mcp --only core,firestore,auth'], { stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true });
let id = 0;
const pending = new Map();
createInterface({ input: child.stdout }).on('line', line => {
  let message;
  try { message = JSON.parse(line); } catch { return; }
  if (pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
});
const request = (method, params) => new Promise(resolve => {
  const current = ++id; pending.set(current, resolve);
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: current, method, params }) + '\n');
});
const timer = setTimeout(() => { child.kill(); process.exit(1); }, 60000);
try {
  await request('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'modus-local-setup', version: '1.0.0' } });
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  const name = process.argv[2];
  const response = name ? await request('tools/call', { name, arguments: JSON.parse(process.argv[3] || '{}') }) : await request('tools/list', {});
  if (name) console.log(JSON.stringify(response.result ?? response.error, null, 2));
  else console.log(JSON.stringify(response.result?.tools?.filter(tool => /security_rules|auth.*config|auth.*provider|environment/.test(tool.name)).map(tool => ({ name: tool.name, description: tool.description, inputSchema: tool.inputSchema })), null, 2));
} finally { clearTimeout(timer); child.stdin.end(); child.kill(); }

