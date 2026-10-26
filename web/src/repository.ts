import { collection, doc, getDocsFromServer, limit, orderBy, query, startAfter,
  addDoc, updateDoc, serverTimestamp, type DocumentData, type QueryDocumentSnapshot,
  onSnapshot } from 'firebase/firestore';
import { auth } from './firebase';
import { db } from './firestore';
import { uniqueShots, validateCloudShot, type Shot } from './domain';

export interface Profile { id: string; display_name: string }
export type RecordPage = { records: DocumentData[]; next: QueryDocumentSnapshot | null };

// A repository belongs to one authenticated account. Never accept owner UIDs
// from form inputs, import files, or a selected golfer profile.
export class FirebaseRepository {
  constructor(readonly uid: string) { this.assertOwner(); }
  private assertOwner() {
    if (auth.currentUser?.uid !== this.uid) throw new Error('Sign in again to access this account.');
  }
  watchProfiles(next: (profiles: Profile[]) => void, error: (error: Error) => void) {
    this.assertOwner();
    return onSnapshot(collection(db, 'users', this.uid, 'profiles'), snapshot => {
      if (auth.currentUser?.uid !== this.uid) return;
      next(snapshot.docs.map(item => ({ id: item.id, display_name: item.data().display_name })));
    }, error);
  }
  async createProfile(name: string) {
    this.assertOwner();
    const display_name = validateName(name);
    return addDoc(collection(db, 'users', this.uid, 'profiles'), {
      display_name, created_at: serverTimestamp(), updated_at: serverTimestamp(),
    });
  }
  async renameProfile(id: string, name: string) {
    this.assertOwner();
    return updateDoc(doc(db, 'users', this.uid, 'profiles', id), {
      display_name: validateName(name), updated_at: serverTimestamp(),
    });
  }
  async readPage(kind: 'shots' | 'sessions', cursor: QueryDocumentSnapshot | null = null): Promise<RecordPage> {
    this.assertOwner();
    const base = collection(db, 'users', this.uid, kind);
    const constraints = [orderBy('__name__'), limit(100)];
    const page = await getDocsFromServer(query(base, ...constraints, ...(cursor ? [startAfter(cursor)] : [])));
    this.assertOwner();
    return { records: page.docs.map(item => ({ ...item.data(), id: item.id })),
      next: page.size === 100 ? page.docs.at(-1)! : null };
  }
  watchShots(next: (shots: Shot[], fromCache: boolean) => void, error: (error: Error) => void) {
    this.assertOwner();
    // A capstone dataset is small enough to subscribe to the complete owner
    // collection. This intentionally has no first-page limit on statistics.
    return onSnapshot(collection(db, 'users', this.uid, 'shots'), { includeMetadataChanges: true }, snapshot => {
      if (auth.currentUser?.uid !== this.uid) return;
      try { next(uniqueShots(snapshot.docs.map(item => validateCloudShot({ ...item.data(), id: item.id }))), snapshot.metadata.fromCache); }
      catch (failure) { error(failure instanceof Error ? failure : new Error('Invalid shot records.')); }
    }, error);
  }
}
function validateName(value: string) {
  const name = value.trim();
  if (!name || name.length > 80) throw new Error('Use a golfer name between 1 and 80 characters.');
  return name;
}
