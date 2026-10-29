import { getApp, getApps, initializeApp } from "@firebase/app";
import { getAuth, type Auth } from "@firebase/auth";

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

const missingKeys = Object.entries(config)
  .filter(([, value]) => !value)
  .map(([key]) => key);

export const firebaseConfigurationError = missingKeys.length
  ? `Firebase sign-in is not configured. Missing: ${missingKeys.join(", ")}.`
  : null;

export const firebaseAuth: Auth | null = firebaseConfigurationError
  ? null
  : getAuth(getApps().length ? getApp() : initializeApp(config));
