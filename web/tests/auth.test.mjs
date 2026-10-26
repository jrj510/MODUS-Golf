import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initializeApp, deleteApp } from 'firebase/app';
import { getAuth, connectAuthEmulator, createUserWithEmailAndPassword, signInWithEmailAndPassword, signOut,
  GoogleAuthProvider, signInWithCredential } from 'firebase/auth';

test('email/password account creation, sign-out, failed login, and account switching', async () => {
  assert.ok(process.env.FIREBASE_AUTH_EMULATOR_HOST, 'Run inside Auth emulator; never production.');
  const app = initializeApp({ apiKey: 'demo-key', projectId: 'demo-modus-golf' }, `test-${Date.now()}`);
  const auth = getAuth(app);
  connectAuthEmulator(auth, `http://${process.env.FIREBASE_AUTH_EMULATOR_HOST}`, { disableWarnings: true });
  const email = `golfer-${Date.now()}@example.test`;
  try {
    const first = await createUserWithEmailAndPassword(auth, email, 'example-password-123');
    const firstUid = first.user.uid;
    assert.equal(auth.currentUser.uid, firstUid);
    await signOut(auth);
    assert.equal(auth.currentUser, null);
    await assert.rejects(signInWithEmailAndPassword(auth, email, 'incorrect-password'));
    assert.equal(auth.currentUser, null);
    const returned = await signInWithEmailAndPassword(auth, email, 'example-password-123');
    assert.equal(returned.user.uid, firstUid);
    await signOut(auth);
    const second = await createUserWithEmailAndPassword(auth, `second-${email}`, 'example-password-456');
    assert.notEqual(second.user.uid, firstUid);
    await signOut(auth);
  } finally { await deleteApp(app); }
});

test('Google credential is accepted by Auth emulator without calling a real provider', async () => {
  assert.ok(process.env.FIREBASE_AUTH_EMULATOR_HOST, 'Run inside Auth emulator; never production.');
  const app = initializeApp({ apiKey: 'demo-key', projectId: 'demo-modus-golf' }, `google-${Date.now()}`);
  const auth = getAuth(app);
  connectAuthEmulator(auth, `http://${process.env.FIREBASE_AUTH_EMULATOR_HOST}`, { disableWarnings: true });
  try {
    const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
    const now = Math.floor(Date.now() / 1000);
    const token = `${encode({ alg: 'none', typ: 'JWT' })}.${encode({ iss: 'https://accounts.google.com', sub: `synthetic-google-${Date.now()}`, aud: 'demo-key', email: 'synthetic-google@example.test', email_verified: true, iat: now, exp: now + 3600 })}.`;
    const result = await signInWithCredential(auth, GoogleAuthProvider.credential(token));
    assert.equal(result.user.providerData[0].providerId, 'google.com');
    await signOut(auth);
    assert.equal(auth.currentUser, null);
  } finally { await deleteApp(app); }
});
