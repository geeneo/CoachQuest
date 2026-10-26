import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Logo from "../components/Logo.jsx";
import { api } from "../lib/api.js";

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      setMsg({ ok: (await api("/api/auth/forgot", { method: "POST", body: { email } })).message });
    } catch (err) {
      setMsg({ error: err.message });
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
        <p className="muted">Forgot your password? Enter your email and we'll send you a reset link.</p>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        {msg?.ok && <div className="ok">{msg.ok}</div>}
        {msg?.error && <div className="error">{msg.error}</div>}
        <button className="btn primary" disabled={busy || !!msg?.ok}>
          Send reset link
        </button>
        <p className="small muted">
          <Link to="/login">Back to sign in</Link> · No email arriving? Ask your CoachQuest administrator.
        </p>
      </form>
    </div>
  );
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [form, setForm] = useState({ password: "", repeat: "" });
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if (form.password !== form.repeat) {
      setMsg({ error: "The passwords don't match." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      await api("/api/auth/reset", { method: "POST", body: { token, new_password: form.password } });
      setMsg({ ok: "Password changed. You've been signed out everywhere; sign in with the new password." });
    } catch (err) {
      setMsg({ error: err.message });
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
        <p className="muted">Choose a new password.</p>
        {!token && <div className="error">This link is missing its token. Use the full link from the email.</div>}
        <label>
          New password
          <input type="password" minLength={12} autoComplete="new-password" value={form.password} onChange={set("password")} required />
          <span className="hint">At least 12 characters.</span>
        </label>
        <label>
          New password again
          <input type="password" minLength={12} autoComplete="new-password" value={form.repeat} onChange={set("repeat")} required />
        </label>
        {msg?.ok && <div className="ok">{msg.ok}</div>}
        {msg?.error && <div className="error">{msg.error}</div>}
        {msg?.ok ? (
          <a className="btn primary" href="/login">
            Sign in
          </a>
        ) : (
          <button className="btn primary" disabled={busy || !token}>
            Set new password
          </button>
        )}
        <p className="small muted">
          <Link to="/forgot-password">Need a new link?</Link>
        </p>
      </form>
    </div>
  );
}
