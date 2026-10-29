// How a plan day went (plan_tracker._status), the same way the calendar shows workouts:
// an emoji, a word, and a tint (cls) for the card.
export const DAY_STATUS = {
  goal_met: { emoji: "✅", label: "Done", cls: "good" },
  partial: { emoji: "⚠️", label: "Partly done", cls: "warn" },
  missed: { emoji: "❌", label: "Missed", cls: "bad" },
  extra: { emoji: "💪", label: "Extra session", cls: "good" },
  rest: { emoji: "😴", label: "Rested", cls: "" },
  today: { emoji: "🎯", label: "Today", cls: "" },
};
