import { useState } from "react";
import { firebaseConfigurationError } from "@/lib/firebase";
import { useAuth } from "./AuthContext";

export default function SignIn() {
  const { signIn } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSignIn = async () => {
    setBusy(true);
    setError(null);
    try {
      await signIn();
    } catch {
      setError("Google sign-in did not complete. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 py-12">
      <section className="w-full max-w-md rounded-2xl border border-border bg-card p-8 shadow-xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-lg font-extrabold text-primary-foreground">
            M
          </div>
          <div>
            <h1 className="text-xl font-bold text-card-foreground">Meridian AI</h1>
            <p className="text-sm text-muted-foreground">Procurement Intelligence</p>
          </div>
        </div>
        <h2 className="text-lg font-semibold text-card-foreground">Sign in to continue</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Use an approved Google account to access the shared document workspace.
        </p>
        {firebaseConfigurationError && (
          <p role="alert" className="mt-5 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {firebaseConfigurationError}
          </p>
        )}
        {error && (
          <p role="alert" className="mt-5 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        )}
        <button
          type="button"
          onClick={() => void handleSignIn()}
          disabled={busy || Boolean(firebaseConfigurationError)}
          className="mt-7 flex w-full items-center justify-center gap-3 rounded-lg bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Connecting to Google…" : "Continue with Google"}
        </button>
        <p className="mt-5 text-center text-xs text-muted-foreground">
          Your Google password is never shared with this application.
        </p>
      </section>
    </main>
  );
}
