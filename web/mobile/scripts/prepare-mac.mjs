import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const checkOnly = process.argv.slice(2).includes('--check');
const expected = {
  PROJECT_ID: 'modus-golf-ea469', BUNDLE_ID: 'com.modusgolf.app',
  GOOGLE_APP_ID: '1:759125763752:ios:7e7aacf0f2e63d32dc449d',
};
function assert(condition, message) { if (!condition) throw new Error(message); }
function read(relative) {
  const path = join(root, relative);
  assert(existsSync(path), `Missing ${relative}. Extract the complete source folder, including its parent shared code.`);
  return readFileSync(path, 'utf8');
}
function command(executable, args, capture = false) {
  const result = spawnSync(executable, args, { cwd: root, stdio: capture ? 'pipe' : 'inherit', encoding: 'utf8' });
  if (result.error || result.status !== 0) {
    throw new Error(`${executable} ${args.join(' ')} failed. ${result.error?.message ?? (capture ? result.stderr : '')}`);
  }
  return result.stdout ?? '';
}
function sourceCheck() {
  assert(Number(process.versions.node.split('.')[0]) >= 24, 'Install Node 24 LTS before preparing this source.');
  const metadata = JSON.parse(read('firebase/apple-app.json'));
  const plist = read('firebase/GoogleService-Info.plist');
  for (const [key, value] of Object.entries(expected)) {
    assert(metadata[key] === value, `Firebase ${key} does not match the registered MODUS app.`);
    assert(plist.includes(`<key>${key}</key>`) && plist.includes(`<string>${value}</string>`), `Native Firebase plist does not contain the expected ${key}.`);
  }
  const entries = JSON.parse(read('firebase/Info.plist.required-entries.json'));
  assert(entries.CFBundleURLTypes?.some(item => item.CFBundleURLSchemes?.includes(metadata.REVERSED_CLIENT_ID)), 'Google callback URL scheme does not match the Firebase Apple app.');
  assert(entries.GIDClientID === metadata.CLIENT_ID, 'Google client ID does not match the Firebase Apple app.');
  assert(entries.NSAppTransportSecurity?.NSAllowsLocalNetworking === true, 'Missing local-network ATS setting.');
  assert(!entries.NSAppTransportSecurity?.NSAllowsArbitraryLoads, 'The required settings must not disable ATS for all internet requests.');
  const config = read('capacitor.config.ts');
  assert(config.includes("appId: 'com.modusgolf.app'"), 'Capacitor bundle identifier does not match Firebase.');
  assert(!/\bserver\s*:\s*\{[\s\S]*?\burl\s*:/.test(config), 'Release assets must be bundled; remove the remote server.url.');
  assert(config.includes("['Google']") && config.includes('symlink:true'), 'Keep the Google-only SPM trait and authentication package symlink configuration.');
  for (const relative of [
    '../src/components.tsx', '../src/domain.ts', '../src/bag.tsx', '../src/style.css',
    '../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs',
    '../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json',
    '../MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/pi_history.json',
    'firebase/PrivacyInfo.xcprivacy', 'scripts/configure-ios.swift',
  ]) read(relative);
  console.log('Source/configuration check passed for MODUS Golf and its existing Firebase Apple registration.');
}

try {
  sourceCheck();
  if (checkOnly) {
    console.log('No native project was generated or changed. This check does not compile iOS code.');
  } else {
    // All platform/toolchain checks precede any build or native-file changes.
    assert(process.platform === 'darwin', 'Run npm run ios:prepare on the MacBook. Windows can run npm run ios:check and npm run build.');
    const swift = command('swift', ['--version'], true);
    const xcode = command('xcodebuild', ['-version'], true);
    assert(Number(/Xcode\s+(\d+)/.exec(xcode)?.[1] ?? 0) >= 26, 'Install/select Xcode 26 or newer and finish its first-run components.');
    command('xcrun', ['--sdk', 'iphoneos', '--show-sdk-path'], true);
    console.log(swift.trim(), '\n', xcode.trim());
    const cli = join(root, 'node_modules/@capacitor/cli/bin/capacitor');
    assert(existsSync(cli), 'Run npm ci in mobile/ first.');
    const ios = join(root, 'ios');
    const project = join(ios, 'App/App.xcodeproj/project.pbxproj');
    assert(!existsSync(ios) || existsSync(project), 'An incomplete or custom ios/ directory exists. Inspect it before platform generation; nothing will be overwritten automatically.');
    if (existsSync(project)) {
      assert(existsSync(join(ios, 'App/CapApp-SPM/Package.swift')), 'The existing native project is not the expected SPM layout. Follow the checklist to inspect/migrate it first.');
    }
    command('npm', ['test']);
    command('npm', ['run', 'build']);
    if (!existsSync(project)) command(process.execPath, [cli, 'add', 'ios', '--packagemanager', 'SPM']);
    command(process.execPath, [cli, 'sync', 'ios']);
    command('swift', [join(root, 'scripts/configure-ios.swift'), root]);
    console.log('\nPrepared native files. Complete the two resource target memberships, -ObjC linker setting and signing in MAC_BUILD_CHECKLIST.md.');
    console.log('Then run npm run ios:open and build/run on the connected iPhone. No signed IPA or device test is implied by this preparation step.');
  }
} catch (error) {
  console.error(`\nMODUS preparation stopped: ${error.message}`);
  process.exitCode = 1;
}
