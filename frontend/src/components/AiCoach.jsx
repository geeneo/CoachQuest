import { Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime, formatDate } from "../lib/format.js";
import Markdown from "./Markdown.jsx";
import { Stat } from "./WellnessPanel.jsx";
import { CommentsToggle } from "./PlanComments.jsx";

const VERDICT = {
  go: ["GO", "Train as planned", "verdict-go"],
  easy: ["EASY", "Keep it easy today", "verdict-easy"],
  rest: ["REST", "Rest or recover today", "verdict-rest"],
};

export default function AiCoach({ id, isMe }) {
  const res = useApi(`/api/athletes/${id}/coach`);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const generate = async (kind) => {
    setBusy(kind);
    setError(null);
    try {
      await api(`/api/athletes/${id}/coach/assessments`, { method: "POST", body: { kind } });
      res.reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  };
  if (res.error) return <div className="error">{res.error.message}</div>;
  const d = res.data;
  if (!d) return <p className="muted">Loading…</p>;
  return (
    <>
      {error && <div className="error">{error}</div>}
      <Readiness id={id} daily={d.latest_daily} busy={busy === "daily"} onRun={() => generate("daily")} />
      {d.progress && <Progress p={d.progress} />}
      <AskCoach id={id} />
      <WeeklyReviews id={id} reviews={d.weekly} busy={busy === "weekly"} onRun={() => generate("weekly")} />
      {isMe && d.ai_settings && <Schedule settings={d.ai_settings} />}
    </>
  );
}

function Readiness({ id, daily, busy, onRun }) {
  const today = new Date().toISOString().slice(0, 10);
  const fresh = daily && daily.period_start === today;
  const [label, text, cls] = daily ? VERDICT[daily.verdict] || [] : [];
  return (
    <section className="card">
      <div className="row between">
        <h2>Today's readiness</h2>
        <button className="btn" disabled={busy} onClick={onRun}>
          {busy ? "Checking…" : fresh ? "Check again" : "Check today's readiness"}
        </button>
      </div>
      {daily ? (
        <div className="readiness">
          <div className={`verdict ${cls}`}>
            <strong>{label}</strong>
            <span>{text}</span>
          </div>
          <div>
            {!fresh && <p className="muted small">From {formatDate(daily.period_start, { weekday: "short" })}. Run a new check for today.</p>}
            <Markdown>{daily.content_md}</Markdown>
            {daily.facts?.reasons?.length > 0 && (
              <p className="hint">Decided by CoachQuest from: {daily.facts.reasons.join(" · ")}</p>
            )}
            <CommentsToggle
              key={daily.id}
              athleteId={id}
              target="assessment"
              targetId={daily.id}
              count={daily.comments}
            />
          </div>
        </div>
      ) : (
        <p className="muted">
          CoachQuest checks last night's HRV, resting HR, sleep and Body Battery against your own 30-day baseline, plus
          your form, and decides go / easy / rest. The AI coach explains it and adjusts today's planned session.
        </p>
      )}
    </section>
  );
}

function Progress({ p }) {
  const r = p.next_race;
  return (
    <section className="card">
      <h2>Progress</h2>
      <div className="stats">
        <Stat label="Fitness (CTL) now" value={p.ctl.now} sub={`${p.ctl["4_weeks_ago"]} four weeks ago`} />
        <Stat
          label="Ramp"
          value={`${p.ctl.weekly_ramp > 0 ? "+" : ""}${p.ctl.weekly_ramp}`}
          unit="/wk"
          sub={`${p.ctl["12_weeks_ago"]} twelve weeks ago`}
        />
        <Stat label="Longest ride" value={p.bests_12_weeks.longest_ride_km} unit="km" sub="last 12 weeks" />
        <Stat label="Most climbing" value={p.bests_12_weeks.most_climbing_m?.toLocaleString()} unit="m" sub="one activity" />
        <Stat label="Best NP (1h+)" value={p.bests_12_weeks.best_np_1h_plus_w} unit="W" sub="last 12 weeks" />
      </div>
      {r && (
        <p className={r.on_track === false ? "warn-text" : r.on_track ? "ok-text" : "muted"}>
          {r.name} in {r.days_to_go} days: at this ramp, fitness reaches about <strong>{r.projected_ctl}</strong>
          {r.target_ctl ? ` (target ${r.target_ctl}) — ${r.on_track ? "on track" : "behind; build a bit more"}` : ""}.
        </p>
      )}
    </section>
  );
}

function WeeklyReviews({ id, reviews, busy, onRun }) {
  const [open, setOpen] = useState(reviews[0]?.id);
  return (
    <section className="card">
      <div className="row between">
        <h2>Weekly reviews</h2>
        <button className="btn" disabled={busy} onClick={onRun}>
          {busy ? "Writing…" : "Review last week"}
        </button>
      </div>
      {reviews.length === 0 && <p className="muted">No reviews yet. They compare last week's plan with what you did.</p>}
      {reviews.map((r) => (
        <details key={r.id} open={open === r.id} onToggle={(e) => e.target.open && setOpen(r.id)} className="review">
          <summary>
            Week of {formatDate(r.period_start)} <span className="muted small">· {dateTime(r.created_at)}</span>
          </summary>
          <Markdown>{r.content_md}</Markdown>
          <CommentsToggle athleteId={id} target="assessment" targetId={r.id} count={r.comments} />
        </details>
      ))}
    </section>
  );
}

function AskCoach({ id }) {
  const chats = useApi(`/api/athletes/${id}/coach/chats`);
  const [chat, setChat] = useState(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const end = useRef(null);
  // Block body: scrollIntoView returns a Promise in newer browsers, and an effect
  // must not return anything but a cleanup function.
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [chat, busy]);

  const send = async (e) => {
    e.preventDefault();
    if (!question.trim()) return;
    const q = question;
    setBusy(true);
    setError(null);
    setQuestion("");
    setChat((c) => ({ ...(c || {}), messages: [...(c?.messages || []), { role: "user", text: q }] }));
    try {
      const updated = await api(`/api/athletes/${id}/coach/chats`, {
        method: "POST",
        body: { question: q, chat_id: chat?.id ?? null },
      });
      setChat(updated);
      chats.reload();
    } catch (err) {
      setError(err.message);
      setQuestion(q);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="row between">
        <h2>Ask the coach</h2>
        <div className="row">
          {chats.data?.length > 0 && (
            <select
              aria-label="Previous conversations"
              value={chat?.id ?? ""}
              onChange={(e) => setChat(chats.data.find((c) => c.id === Number(e.target.value)) || null)}
            >
              <option value="">New conversation</option>
              {chats.data.map((c) => (
                <option key={c.id} value={c.id}>
                  {(c.messages[0]?.text || "Conversation").slice(0, 40)} · {dateTime(c.updated_at)}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>
      <div className="chat">
        {!chat?.messages?.length && (
          <p className="muted small">
            Ask about your training, recovery or plan, e.g. "Why did Tuesday feel so hard?" or "Am I ready for the DC?".
            The coach looks up only the data shared with you; each lookup shows in the athlete's access log.
          </p>
        )}
        {chat?.messages?.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.role === "assistant" ? <Markdown>{m.text}</Markdown> : m.text}
          </div>
        ))}
        {busy && <div className="bubble assistant muted">Looking at the data…</div>}
        <div ref={end} />
      </div>
      {error && <div className="error">{error}</div>}
      <form className="row chat-input" onSubmit={send}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask the coach…"
          maxLength={2000}
          disabled={busy}
        />
        <button className="btn primary" disabled={busy || !question.trim()} aria-label="Send">
          <Send size={16} />
        </button>
      </form>
    </section>
  );
}

function Schedule({ settings }) {
  const [s, setS] = useState(settings);
  const toggle = async (k) => {
    const next = { ...s, [k]: !s[k] };
    setS(next);
    try {
      setS(await api("/api/me/ai-settings", { method: "PUT", body: next }));
    } catch {
      setS(s);
    }
  };
  return (
    <section className="card">
      <h2>Automatic notes</h2>
      <div className="stack tight">
        <label className="check">
          <input type="checkbox" checked={s.daily} onChange={() => toggle("daily")} /> Readiness every morning (after the
          Garmin sync)
        </label>
        <label className="check">
          <input type="checkbox" checked={s.weekly} onChange={() => toggle("weekly")} /> Weekly review every Monday
        </label>
        <label className="check">
          <input type="checkbox" checked={s.email} onChange={() => toggle("email")} /> Also email them to me (needs email
          set up by the admin)
        </label>
      </div>
      <p className="hint">Each note is one AI request and counts toward your monthly allowance.</p>
    </section>
  );
}
