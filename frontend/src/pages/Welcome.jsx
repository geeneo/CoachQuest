import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";
import Logo from "../components/Logo.jsx";
import { useAuth } from "../lib/auth.jsx";

const DIAGRAM = "[[how-it-works]]";

// The shareable information page (backend welcome.py), at /welcome/<key>, without signing in.
// Screenshots admins add are written as ![…](welcome-img/NAME) and come through the page's link.
export default function Welcome() {
  const { key } = useParams();
  const { user } = useAuth();
  const [page, setPage] = useState(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    // Plain fetch: no sign-in, and a 404 here is an answer, not an error to show.
    fetch(`/api/welcome/${encodeURIComponent(key)}`, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((p) => {
        setPage(p);
        document.title = p.title;
      })
      .catch(() => setMissing(true));
  }, [key]);

  if (missing) {
    return (
      <div className="auth-page">
        <div className="card auth-card">
          <h1 className="auth-logo">
            <Logo variant="full" />
          </h1>
          <p>This page isn't available. Ask whoever sent you the link for a new one.</p>
          <Link to="/login">Sign in to CoachQuest</Link>
        </div>
      </div>
    );
  }
  if (!page) return <div className="center muted">Loading…</div>;

  const img = ({ src = "", alt }) => {
    const own = src.startsWith("welcome-img/");
    const url = own ? `/api/welcome/${encodeURIComponent(key)}/img/${src.slice(12)}` : src;
    return (
      <figure className="welcome-shot">
        <img src={url} alt={alt || ""} loading="lazy" />
        {alt && <figcaption>{alt}</figcaption>}
      </figure>
    );
  };
  const md = (text) => (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ img, p: Paragraph }}>
      {text}
    </ReactMarkdown>
  );
  const [before, ...after] = page.body_md.split(DIAGRAM);
  const actions = (
    <div className="row wrap welcome-actions">
      {user ? (
        <Link className="btn primary" to="/">
          Open CoachQuest
        </Link>
      ) : (
        <>
          {page.signup && (
            <Link className="btn primary" to="/register">
              {page.approval ? "Request access" : "Create an account"}
            </Link>
          )}
          <Link className="btn" to="/login">
            Sign in
          </Link>
        </>
      )}
    </div>
  );
  return (
    <div className="welcome">
      <header className="welcome-hero">
        <Logo variant="full" />
        <h1>{page.title}</h1>
        {actions}
        {page.approval && !user && (
          <p className="small muted">New accounts are checked by an administrator before they can sign in.</p>
        )}
      </header>
      <article className="markdown welcome-body">
        {md(before)}
        {after.length > 0 && <HowItWorks />}
        {after.length > 0 && md(after.join(""))}
      </article>
      <footer className="welcome-foot">{actions}</footer>
    </div>
  );
}

// An image alone in a paragraph becomes a <figure>; keep it out of the <p> (a figure can't be in one).
function Paragraph({ children, node }) {
  const onlyImage = node?.children?.length === 1 && node.children[0].tagName === "img";
  return onlyImage ? <>{children}</> : <p>{children}</p>;
}

const FLOW = [
  ["Your apps", ["Strava", "Garmin", "Intervals.icu"], "rides, runs, wellness"],
  ["CoachQuest", ["fitness, fatigue, form", "your week and races", "health and strength"], "works it out"],
  ["AI coach", ["writes your plan", "re-plans a day or the rest", "your coach approves"], "Claude, by Anthropic"],
  ["Your training", ["plan and calendar", "routes and segments", "strength sessions"], "day by day"],
  ["On the bike", ["Zwift and MyWhoosh", "via Intervals.icu", ".zwo download"], "and back to Strava"],
];

// The "how it works" diagram: where data comes from, what CoachQuest and the AI coach do with it, and
// where the workouts go.
function HowItWorks() {
  return (
    <div className="how-it-works" role="img" aria-label="Your apps, then CoachQuest, then the AI coach, then your training, then Zwift and MyWhoosh">
      {FLOW.map(([title, items, note], i) => (
        <div key={title} className="hiw-step">
          <div className="hiw-box">
            <strong>{title}</strong>
            <ul>
              {items.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
            <span className="muted small">{note}</span>
          </div>
          {i < FLOW.length - 1 && (
            <span className="hiw-arrow" aria-hidden="true">
              →
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
