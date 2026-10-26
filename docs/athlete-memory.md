# Decision: an athlete "memory" for the AI coach

Status: **decided 26 Oct 2026; step 1 built.** Owner's answers: notes can't be hidden from the AI, and nobody is emailed about note changes.

## What the AI coach knows today

Every plan, re-plan, readiness note, weekly review and chat answer starts from:

| Source | What it gives | Who writes it |
| --- | --- | --- |
| Synced data | Activities, load (CTL/ATL/TSB), wellness, weekly volume, computed flags | Strava / Garmin / Intervals.icu |
| Profile | FTP, LTHR, max HR, weight, age, one free-text **goal** | Athlete |
| Races | Upcoming events, target CTL | Athlete |
| Weekday preferences | Which session types fit which day | Athlete |
| Activity note tags | "sick", "travel"… on single activities | Athlete |
| Comments | On plans, plan days, AI notes, workouts (recent ones only) | Athlete and coaches |
| **Coach instructions** | Standing rules the AI must follow, ranked above its own judgement | Coaches (and athlete) |
| Plan request notes / coach's notes | Context for one plan or re-plan | Whoever asks / the coach |

Chats are separate conversations: one chat doesn't know what was said in another.

## What is still missing

Context that the data can't show, isn't a rule, and lasts longer than one plan or comment:

- **Health:** injuries and niggles, and how they're going ("left knee sore after long climbs since Sept").
- **Equipment:** bikes, the trainer, power meter on the road bike only, no trainer when travelling.
- **Life and schedule:** shift work, travel weeks, family days, a usual weekly rhythm.
- **What works:** responds well to sweet spot, hates long Z2 indoors, motivated by group rides.
- **History:** past events and results, a previous injury, seasons that went well.

Today this ends up crammed into the one-line goal, repeated in every plan's notes, or buried in old comments the AI no longer sees. Comments fade out after a few days or weeks. Coach instructions are the wrong place too: they are rules ("no intervals on Mondays"), not facts ("works night shifts every second week").

So **yes**: the data plus instructions aren't enough. The coach and athlete keep re-typing the same background, and the AI forgets it between requests.

## The decision

**Build "Athlete notes": one shared set of short notes per athlete, kept in the database.**

1. **Short entries, not one long memory.md.** Each note is one fact (max ~300 characters) with:
   - a category: Health, Equipment, Life & schedule, What works, History, Other;
   - an optional "review by" date. Health notes default to 6 weeks, so an old niggle doesn't haunt plans forever.

   Short entries are easier to keep current, to edit or delete one at a time, and to keep the AI's input small. A single document goes stale and grows without limit.
2. **One shared set per athlete, not per coach.** The athlete and every coach with the Training plans permission read and edit the same notes.
   - Coach-private notes about an athlete would be at odds with the transparency of the rest of CoachQuest.
   - The athlete has a right under POPIA to see what's held about them.
3. **The AI uses them, within the sharing permissions.**
   - Current notes go into every plan, re-plan, readiness note, weekly review and chat, as context to take into account. They are not rules: instructions stay the rules.
   - Only for viewers with the Training plans permission.
   - Notes past their "review by" date are shown greyed out and are left out until someone confirms them.
4. **Each note has a history.** Each change records who changed it and when, like the instructions do.
5. **The AI may only suggest notes (step 2).** A chat answer or weekly review can propose "Remember: knee sore after long climbs?". The suggestion waits in the notes card, and the athlete or a coach accepts, edits or dismisses it. Nothing is saved without a person agreeing.
6. **Health notes are sensitive personal information.**
   - Shown only to the athlete and their Training-plans coaches.
   - Never shown on the dashboard or in admin views. Admin sees counts only.
   - Removed with the account, and included in the future account export.
7. **Limits:** at most 40 current notes per athlete, to keep the AI's input and cost small.

## What it is not

- **No files on the server.** A memory.md per athlete would sit outside backups, permissions and account deletion.
- **No automatic memory.** The AI never writes notes by itself, for example quietly from chat transcripts.
- **No separate coach memory.** Coach-only notes are not part of this decision. If a coach needs one later, that is a separate decision.
- **Not a replacement for coach instructions, comments or plan notes.** Those stay as they are.

## Steps

1. **Athlete notes** (about the size of coach instructions):
   - model, API and card under the AI coach and Plans tabs;
   - categories and "review by" dates;
   - passed to every AI request, with a prompt rule;
   - emails like the instructions;
   - tests.
2. **AI-suggested notes:**
   - chat answers and weekly reviews may return up to 3 suggestions in a structured field;
   - they are shown as "Suggested by the AI coach" with Accept / Edit / Dismiss;
   - dismissed suggestions aren't repeated.

## Open questions for the owner

- Should the athlete be able to mark a note as hidden from the AI, kept for themselves and their coaches only? Suggested answer: no; keep it simple.
- Should coaches be emailed about every note change, or only about Health notes? Suggested answer: Health only, plus the weekly review mentions changes.
