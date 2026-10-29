import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Logo from "../components/Logo.jsx";
import { useAuth } from "../lib/auth.jsx";

export default function AuthPage({ mode }) {
  const { login, register } = useAuth();
  const [form, setForm] = useState({ email: "", password: "", display_name: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(null);
  const isRegister = mode === "register";
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  // "This is an alpha version…", when a super admin has switched the notice on.
  const [notice, setNotice] = useState(null);
  useEffect(() => {
    if (!isRegister) return;
    fetch("/api/auth/notice")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setNotice(d?.message || null))
      .catch(() => {});
  }, [isRegister]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (isRegister) {
        const r = await register(form);
        if (r?.pending) setPending(r.message);
      } else await login(form.email, form.password);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <form className="card auth-card" onSubmit={submit}>
        <h1 className="auth-logo">
          <Logo variant="full" />
        </h1>
        <p className="muted">{isRegister ? "Create your account" : "Sign in to your training portal"}</p>
        {isRegister && notice && <div className="notice">{notice}</div>}
        {isRegister && (
          <label>
            Name
            <input value={form.display_name} onChange={set("display_name")} required maxLength={100} autoComplete="name" />
          </label>
        )}
        <label>
          Email
          <input type="email" value={form.email} onChange={set("email")} required autoComplete="email" />
        </label>
        <label>
          Password
          <input
            type="password"
            value={form.password}
            onChange={set("password")}
            required
            minLength={isRegister ? 12 : 1}
            autoComplete={isRegister ? "new-password" : "current-password"}
          />
          {isRegister && <span className="hint">At least 12 characters.</span>}
        </label>
        {!isRegister && (
          <Link to="/forgot-password" className="small">
            Forgot password?
          </Link>
        )}
        {error && <div className="error">{error}</div>}
        {pending && <div className="ok">{pending}</div>}
        {isRegister && (
          <p className="small muted">
            ⚕️ CoachQuest is not medical advice. Always consult a doctor before starting or changing training,
            especially with a medical condition or injury.
          </p>
        )}
        <button className="btn primary" disabled={busy}>
          {busy ? "…" : isRegister ? "Create account" : "Sign in"}
        </button>
        <p className="small muted">
          {isRegister ? (
            <>
              Already registered? <Link to="/login">Sign in</Link>
            </>
          ) : (
            <>
              New here? <Link to="/register">Create an account</Link>
            </>
          )}
        </p>
      </form>
    </div>
  );
}
