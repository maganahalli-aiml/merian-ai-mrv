import {
  browserLocalPersistence,
  GoogleAuthProvider,
  onAuthStateChanged,
  setPersistence,
  signInWithPopup,
  signOut as firebaseSignOut,
  type User,
} from "@firebase/auth";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getCurrentUser, type CurrentUserProfile } from "@/lib/api";
import { firebaseAuth } from "@/lib/firebase";

interface AuthContextValue {
  user: User | null;
  profile: CurrentUserProfile | null;
  loading: boolean;
  error: string | null;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<CurrentUserProfile | null>(null);
  const [loading, setLoading] = useState(Boolean(firebaseAuth));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!firebaseAuth) {
      setLoading(false);
      return;
    }

    return onAuthStateChanged(firebaseAuth, async (nextUser) => {
      setUser(nextUser);
      setProfile(null);
      setError(null);
      if (!nextUser) {
        setLoading(false);
        return;
      }

      setLoading(true);
      try {
        await nextUser.getIdToken();
        setProfile(await getCurrentUser());
      } catch (verificationError) {
        setError(
          verificationError instanceof Error
            ? verificationError.message
            : "Unable to verify your account due to an unexpected error.",
        );
      } finally {
        setLoading(false);
      }
    });
  }, []);

  const signIn = useCallback(async () => {
    if (!firebaseAuth) throw new Error("Firebase sign-in is not configured.");
    setError(null);
    await setPersistence(firebaseAuth, browserLocalPersistence);
    await signInWithPopup(firebaseAuth, new GoogleAuthProvider());
  }, []);

  const signOut = useCallback(async () => {
    if (firebaseAuth) await firebaseSignOut(firebaseAuth);
    setUser(null);
    setProfile(null);
    setError(null);
  }, []);

  const value = useMemo(
    () => ({ user, profile, loading, error, signIn, signOut }),
    [user, profile, loading, error, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider.");
  return context;
}
