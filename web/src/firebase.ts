import { initializeApp } from 'firebase/app';
import { getAuth, connectAuthEmulator, GoogleAuthProvider } from 'firebase/auth';

// Public web configuration retrieved from the existing registered Firebase app.
export const app = initializeApp({
  projectId: 'modus-golf-ea469',
  appId: '1:759125763752:web:e9b34abb7e38f8b0dc449d',
  storageBucket: 'modus-golf-ea469.firebasestorage.app',
  apiKey: 'AIzaSyDlZkq5By1nz_4dalMQydxIjwkczcAAPLY',
  authDomain: 'modus-golf-ea469.firebaseapp.com',
  messagingSenderId: '759125763752',
});
export const auth = getAuth(app);
export const googleProvider = new GoogleAuthProvider();
googleProvider.setCustomParameters({ prompt: 'select_account' });

// Emulators are explicitly opt-in and restricted to localhost. Never implicitly
// select a demo or an emulator when production authentication fails.
if (import.meta.env.DEV && import.meta.env.VITE_USE_EMULATORS === 'true') {
  connectAuthEmulator(auth, 'http://127.0.0.1:9099', { disableWarnings: true });
}
