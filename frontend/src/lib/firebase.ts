import { initializeApp, getApps, getApp, type FirebaseApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider, type Auth } from 'firebase/auth';

export function isFirebaseConfigured(): boolean {
  return Boolean(
    import.meta.env.VITE_FIREBASE_API_KEY &&
    import.meta.env.VITE_FIREBASE_PROJECT_ID
  );
}

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY || '',
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || '',
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || '',
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || '',
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || '',
  appId: import.meta.env.VITE_FIREBASE_APP_ID || '',
};

let _app: FirebaseApp | null = null;
let _auth: Auth | null = null;
let _googleProvider: GoogleAuthProvider | null = null;

if (isFirebaseConfigured()) {
  try {
    _app = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);
    _auth = getAuth(_app);
    _googleProvider = new GoogleAuthProvider();
    _googleProvider.setCustomParameters({ prompt: 'select_account' });
  } catch (err) {
    console.warn('Firebase initialization skipped or failed:', err);
  }
}

export const auth: Auth | null = _auth;
export const googleProvider: GoogleAuthProvider | null = _googleProvider;
