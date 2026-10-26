import { before, after, beforeEach, test } from 'node:test';
import { readFileSync } from 'node:fs';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import { doc, collection, getDoc, getDocs, setDoc, updateDoc, deleteDoc, serverTimestamp, Timestamp } from 'firebase/firestore';
import assert from 'node:assert/strict';
import { validateCloudShot } from '../src/domain.ts';

let env;
before(async () => {
  if (!process.env.FIRESTORE_EMULATOR_HOST) throw new Error('Run using firebase emulators:exec --only firestore. Never run against production.');
  const [host, port] = process.env.FIRESTORE_EMULATOR_HOST.split(':');
  env = await initializeTestEnvironment({ projectId: 'demo-modus-golf', firestore: {
    host, port: Number(port), rules: readFileSync('MODUS_Golf_Firebase_AI_Starter/firebase/firestore.rules', 'utf8'),
  } });
});
beforeEach(async () => env.clearFirestore());
after(async () => { await env?.cleanup(); });
const profile = () => ({ display_name: 'Golfer', created_at: serverTimestamp(), updated_at: serverTimestamp() });
const own = () => env.authenticatedContext('account-a').firestore();
async function seed(path, data = { example: true }) {
  await env.withSecurityRulesDisabled(async context => setDoc(doc(context.firestore(), path), data));
}

test('a backend-authored path persists as Firestore maps and decodes for the owner', async () => {
  const example = JSON.parse(readFileSync('MODUS_Golf_Firebase_AI_Starter/contracts/fixtures/demo_shots.json', 'utf8'))[0];
  const record = { ...example, record_kind: 'real', source: { kind: 'pi_live' }, trajectory: [
    { forward_yards: 0, height_yards: 0, right_yards: 0 },
    { forward_yards: 100, height_yards: 0, right_yards: -3 },
  ] };
  await seed(`users/account-a/shots/${record.shot_id}`, record);
  const snapshot = await assertSucceeds(getDoc(doc(own(), `users/account-a/shots/${record.shot_id}`)));
  const decoded = validateCloudShot({ ...snapshot.data(), id: snapshot.id });
  assert.deepEqual(decoded.trajectory, [[0,0,0],[100,0,-3]]);
});

test('signed-out users cannot read or write private records', async () => {
  const db = env.unauthenticatedContext().firestore();
  for (const path of ['users/account-a/profiles/p', 'users/account-a/shots/s', 'users/account-a/sessions/s', 'users/account-a/summaries/s', 'devices/device', 'device_credentials/device']) {
    await seed(path);
    await assertFails(getDoc(doc(db, path)));
    await assertFails(setDoc(doc(db, path), profile()));
  }
});
test('another account cannot read or write any owner collection', async () => {
  const db = own();
  for (const kind of ['profiles', 'shots', 'sessions', 'summaries', 'imports']) {
    const path = `users/account-b/${kind}/record`;
    await seed(path);
    await assertFails(getDoc(doc(db, path)));
    await assertFails(getDocs(collection(db, `users/account-b/${kind}`)));
    await assertFails(setDoc(doc(db, path), profile()));
  }
});
test('owner can create and rename a validated profile, preserving created_at', async () => {
  const ref = doc(own(), 'users/account-a/profiles/golfer');
  await assertSucceeds(setDoc(ref, profile()));
  await assertSucceeds(getDoc(ref));
  await assertSucceeds(updateDoc(ref, { display_name: 'Renamed', updated_at: serverTimestamp() }));
  await assertFails(deleteDoc(ref));
});
test('blank, overlong, invalid and unknown profile fields are rejected', async () => {
  const ref = doc(own(), 'users/account-a/profiles/golfer');
  for (const display_name of ['', 'x'.repeat(81), 42, null]) {
    await assertFails(setDoc(ref, { ...profile(), display_name }));
  }
  await assertFails(setDoc(ref, { ...profile(), admin: true }));
  await assertFails(setDoc(ref, { display_name: 'Golfer' }));
  await assertFails(setDoc(ref, { ...profile(), created_at: Timestamp.fromMillis(0) }));
});
test('profile creation timestamp is immutable and update must use server time', async () => {
  const ref = doc(own(), 'users/account-a/profiles/golfer');
  await setDoc(ref, profile());
  await assertFails(updateDoc(ref, { created_at: Timestamp.fromMillis(0), updated_at: serverTimestamp() }));
  await assertFails(updateDoc(ref, { display_name: 'Changed', updated_at: Timestamp.fromMillis(0) }));
  await assertFails(updateDoc(ref, { owner_uid: 'account-a', updated_at: serverTimestamp() }));
});
test('owner may read but never create, update, or delete shot/session/summary/import data', async () => {
  const db = own();
  for (const kind of ['shots', 'sessions', 'summaries', 'imports']) {
    const path = `users/account-a/${kind}/existing`;
    await seed(path);
    await assertSucceeds(getDoc(doc(db, path)));
    await assertSucceeds(getDocs(collection(db, `users/account-a/${kind}`)));
    await assertFails(setDoc(doc(db, `users/account-a/${kind}/new`), { value: 1 }));
    await assertFails(updateDoc(doc(db, path), { value: 2 }));
    await assertFails(deleteDoc(doc(db, path)));
  }
});
test('device registration is readable only by registered owner; client transfers and lists denied', async () => {
  await seed('devices/device-a', { owner_uid: 'account-a', display_name: 'MODUS' });
  const db = own();
  await assertSucceeds(getDoc(doc(db, 'devices/device-a')));
  await assertFails(getDoc(doc(env.authenticatedContext('account-b').firestore(), 'devices/device-a')));
  await assertFails(getDocs(collection(db, 'devices')));
  await assertFails(updateDoc(doc(db, 'devices/device-a'), { owner_uid: 'account-b' }));
  await assertFails(setDoc(doc(db, 'devices/new'), { owner_uid: 'account-a' }));
});
test('credentials and account-root documents are inaccessible even to their owner', async () => {
  await seed('device_credentials/device-a', { owner_uid: 'account-a', token: 'synthetic-emulator-token' });
  await seed('users/account-a');
  for (const path of ['device_credentials/device-a', 'users/account-a']) {
    await assertFails(getDoc(doc(own(), path)));
    await assertFails(setDoc(doc(own(), path), { admin: true }));
  }
});
