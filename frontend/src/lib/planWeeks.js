import { addDays } from "./workout.js";

export const MAX_WEEKS = 16; // the API's limit for one plan

// First day of the week holding `iso` (week_start: 0 = Monday … 6 = Sunday), like backend first_week_start.
export function weekStartOf(iso, weekStart = 0) {
  const dow = (new Date(`${iso}T12:00:00`).getDay() + 6) % 7; // 0 = Monday
  return addDays(iso, -((dow - weekStart + 7) % 7));
}

// The plan's first day: the week of `start`, or the next week to begin (today if a week starts today).
export function planStart(start, today, weekStart = 0) {
  if (start) return weekStartOf(start, weekStart);
  const dow = (new Date(`${today}T12:00:00`).getDay() + 6) % 7;
  return addDays(today, (weekStart - dow + 7) % 7);
}

// Weeks from the plan's first week up to and including the event's week.
// Returns {weeks, start} with start moved later when the event is more than MAX_WEEKS away,
// or {error} when the event is before the plan would start.
export function weeksToEvent(eventDate, start, today, weekStart = 0) {
  const first = planStart(start, today, weekStart);
  const eventWeek = weekStartOf(eventDate, weekStart);
  const days = Math.round((new Date(`${eventWeek}T12:00:00`) - new Date(`${first}T12:00:00`)) / 86400000);
  if (days < 0) return { error: "The event is before the plan would start: pick an earlier start week." };
  const weeks = days / 7 + 1;
  if (weeks <= MAX_WEEKS) return { weeks, start: first, moved: false };
  return { weeks: MAX_WEEKS, start: addDays(eventWeek, -7 * (MAX_WEEKS - 1)), moved: true, away: weeks };
}
