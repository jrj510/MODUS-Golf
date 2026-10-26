import { getFirestore, connectFirestoreEmulator } from 'firebase/firestore';
import { app } from './firebase';

// Loaded with the workspace so sign-in does not download Firestore first.
export const db = getFirestore(app);
if (import.meta.env.DEV && import.meta.env.VITE_USE_EMULATORS === 'true') {
  connectFirestoreEmulator(db, '127.0.0.1', 8080);
}
