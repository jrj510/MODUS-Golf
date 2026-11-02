import { Capacitor } from '@capacitor/core';
import { FirebaseAuthentication } from '@capacitor-firebase/authentication';
import { FieldValue, FirebaseFirestore } from '@capacitor-firebase/firestore';
import { uniqueShots, validateCloudShot, type Shot } from '../../src/domain';

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
export async function signInEmail(email:string,password:string,create=false) {
  nativeOnly();
  return create ? FirebaseAuthentication.createUserWithEmailAndPassword({email,password}) : FirebaseAuthentication.signInWithEmailAndPassword({email,password});
}
export async function signInGoogle() {nativeOnly();return FirebaseAuthentication.signInWithGoogle();}
export async function signOut() {nativeOnly();await FirebaseAuthentication.signOut();}
export async function resetPassword(email:string) {nativeOnly();await FirebaseAuthentication.sendPasswordResetEmail({email});}
export async function createProfile(uid:string,name:string) {
  await owner(uid);await firestoreReady();const display_name=name.trim();
  if (!display_name || display_name.length > 80) throw new Error('Use a golfer name between 1 and 80 characters.');
  return FirebaseFirestore.addDocument({reference:`users/${uid}/profiles`,data:{display_name,created_at:FieldValue.serverTimestamp(),updated_at:FieldValue.serverTimestamp()}});
}
export async function observeHistory(uid:string,shots:(items:Shot[],cached:boolean) => void,profiles:(items:Profile[]) => void,failure:(error:Error) => void) {
  await owner(uid);await firestoreReady();let active=true;
  const ids: string[]=[];
  try {
    ids.push(await FirebaseFirestore.addCollectionSnapshotListener({reference:`users/${uid}/shots`,includeMetadataChanges:true},(event,error) => {
      if (!active) return;
      if (error) return failure(new Error('Cloud history could not be loaded. Local shots remain available.'));
      // The plugin exposes document metadata but not an empty query's source.
      // Treat an empty snapshot conservatively rather than claim server proof.
      try {if (event) shots(uniqueShots(event.snapshots.map(item => validateCloudShot({...item.data,id:item.id}))),event.snapshots.length === 0 || event.snapshots.some(item => item.metadata.fromCache));}
      catch (error) {failure(error instanceof Error ? error : new Error('Invalid cloud shot contract.'));}
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
