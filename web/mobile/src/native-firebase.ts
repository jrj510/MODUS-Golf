import { Capacitor } from '@capacitor/core';
import { FirebaseAuthentication } from '@capacitor-firebase/authentication';
import { FieldValue, FirebaseFirestore } from '@capacitor-firebase/firestore';
import type { Shot } from '../../src/domain';
import { firebaseProjectId } from './firebase-project';
import { decodeHistoryPage, historyPageSize } from './cloud-history';
import { authDiagnostics, authFailure, type AuthStage } from './auth-diagnostics';

function authLog(details:Record<string,unknown>) {
  // Explicit allowlisted diagnostics only; never log plugin results or errors.
  if (import.meta.env.DEV || Capacitor.isNativePlatform()) console.info('[MODUS Auth]',JSON.stringify(details));
}
async function authenticate<T extends {user:unknown;additionalUserInfo?:{isNewUser?:boolean} | null}>(stage:AuthStage,work:() => Promise<T>) {
  try {
    const result=await work();
    authLog({stage:'firebase-authenticated',authenticated:!!result.user,isNewUser:result.additionalUserInfo?.isNewUser ?? null,profileInitialization:'separate-user-action'});
    return result;
  } catch(error) {
    authLog(authDiagnostics(error,stage));
    throw authFailure(error,stage);
  }
}

export type AccountUser = {uid:string;email:string | null};
export type Profile = {id:string;display_name:string};
let persistence: Promise<void> | undefined;
function nativeOnly() {if (!Capacitor.isNativePlatform()) throw new Error('Firebase account actions run in the installed iPhone app. Browser preview keeps local practice available.');}
async function owner(uid: string) {nativeOnly();const {user}=await FirebaseAuthentication.getCurrentUser();if (!user || user.uid !== uid) throw new Error('Sign in again to access this account.');}
async function firestoreReady() {persistence ??= FirebaseFirestore.enablePersistence();await persistence;}
export async function observeAccount(next: (user:AccountUser | null) => void) {
  nativeOnly();
  let observed=false;
  const listener=await FirebaseAuthentication.addListener('authStateChange',event => {observed=true;next(event.user);});
  const {user}=await FirebaseAuthentication.getCurrentUser();if (!observed) next(user);
  return () => {void listener.remove();};
}
export async function accountToken(uid: string, forceRefresh: boolean) {
  await owner(uid);
  const {token}=await FirebaseAuthentication.getIdToken({forceRefresh});
  await owner(uid);
  const encoded=token.split('.')[1].replaceAll('-','+').replaceAll('_','/');
  const claims=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(encoded),char => char.charCodeAt(0))));
  if (claims.sub !== uid) throw new Error('The signed-in account changed.');
  if (claims.aud !== firebaseProjectId || claims.iss !== `https://securetoken.google.com/${firebaseProjectId}`) {
    throw new Error('Sign out and sign in again to connect to the current MODUS account service.');
  }
  return token;
}
export async function signInEmail(email:string,password:string,create=false) {
  nativeOnly();
  return authenticate(create ? 'email-registration' : 'email-sign-in',() => create ? FirebaseAuthentication.createUserWithEmailAndPassword({email,password}) : FirebaseAuthentication.signInWithEmailAndPassword({email,password}));
}
export async function signInGoogle() {nativeOnly();return authenticate('google-sign-in',() => FirebaseAuthentication.signInWithGoogle());}
export async function signOut() {nativeOnly();await FirebaseAuthentication.signOut();}
export async function resetPassword(email:string) {nativeOnly();await FirebaseAuthentication.sendPasswordResetEmail({email});}
export async function createProfile(uid:string,name:string) {
  await owner(uid);await firestoreReady();const display_name=name.trim();
  if (!display_name || display_name.length > 80) throw new Error('Use a golfer name between 1 and 80 characters.');
  return FirebaseFirestore.addDocument({reference:`users/${uid}/profiles`,data:{display_name,created_at:FieldValue.serverTimestamp(),updated_at:FieldValue.serverTimestamp()}});
}
export async function observeHistory(uid:string,shots:(items:Shot[],cached:boolean,skipped:number,nextCursor:string | null) => void,profiles:(items:Profile[]) => void,failure:(error:Error) => void,after?:string) {
  await owner(uid);await firestoreReady();let active=true;
  const ids: string[]=[];
  const reference=`users/${uid}/shots`;
  if (after && (!after.startsWith(reference+'/') || after.slice(reference.length+1).includes('/'))) throw new Error('Invalid cloud history cursor. Refresh history.');
  try {
    // Firestore's default document-ID order is stable and indexed. It includes
    // historical records that do not have a server ingestion timestamp.
    ids.push(await FirebaseFirestore.addCollectionSnapshotListener({reference,includeMetadataChanges:true,
      queryConstraints:[{type:'limit',limit:historyPageSize+1},...(after ? [{type:'startAfter' as const,reference:after}] : [])]
    },(event,error) => {
      if (!active) return;
      if (error) return failure(new Error('Cloud history could not be loaded. Local shots remain available.'));
      if (!event) return;
      const page=decodeHistoryPage(event.snapshots);
      shots(page.items,page.cached,page.skipped,page.nextCursor);
    }));
    ids.push(await FirebaseFirestore.addCollectionSnapshotListener({reference:`users/${uid}/profiles`},(event,error) => {
      if (!active) return;
      if (error) return failure(new Error('Golfer profiles could not be loaded.'));
      if (event) profiles(event.snapshots.map(item => ({id:item.id,display_name:String(item.data?.display_name ?? 'Unnamed golfer')})));
    }));
  } catch(error) {
    active=false;await Promise.all(ids.map(callbackId => FirebaseFirestore.removeSnapshotListener({callbackId})));
    throw error;
  }
  return () => {active=false;for(const callbackId of ids) void FirebaseFirestore.removeSnapshotListener({callbackId});};
}
// Shot writes intentionally belong to the authenticated ingest service. The
// existing rules deny browser/native client shot writes. Never bypass them.
