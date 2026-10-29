// Date math in the user's IANA time zone (users.timezone). The API speaks UTC instants; people see local time.

/** Monday = 1 ... Sunday = 7, per locale (Mexico and the US start weeks on Sunday). */
function firstDayOfWeek(intl: string): number {
  const locale = new Intl.Locale(intl) as Intl.Locale & { getWeekInfo?: () => { firstDay: number } };
  return locale.getWeekInfo?.().firstDay ?? 7;
}

/** Whole weeks covering the month, starting on the locale's first weekday. */
export function monthGrid(month: Temporal.PlainYearMonth, intl: string): Temporal.PlainDate[] {
  const first = month.toPlainDate({ day: 1 });
  const start = first.subtract({ days: (first.dayOfWeek - firstDayOfWeek(intl) + 7) % 7 });
  const weeks = Math.ceil(((first.dayOfWeek - firstDayOfWeek(intl) + 7) % 7 + month.daysInMonth) / 7);
  return Array.from({ length: weeks * 7 }, (_, i) => start.add({ days: i }));
}

/** Weekday names in grid order, e.g. ['dom', 'lun', ...]. */
export function weekdayNames(intl: string, style: 'short' | 'long'): string[] {
  const sunday = Temporal.PlainDate.from('2026-01-04'); // any Sunday
  const offset = firstDayOfWeek(intl) % 7;
  return Array.from({ length: 7 }, (_, i) =>
    sunday.add({ days: offset + i }).toLocaleString(intl, { weekday: style }),
  );
}

/** Start of a local day as a UTC instant string. */
export function startOfDay(date: Temporal.PlainDate, tz: string): string {
  return date.toZonedDateTime({ timeZone: tz }).toInstant().toString();
}

/** 'YYYY-MM-DDTHH:mm' from a datetime-local input, read as wall time in tz, to a UTC instant string. */
export function localInputToInstant(value: string, tz: string): string {
  return Temporal.PlainDateTime.from(value).toZonedDateTime(tz).toInstant().toString();
}

export function zoned(instant: string, tz: string): Temporal.ZonedDateTime {
  return Temporal.Instant.from(instant).toZonedDateTimeISO(tz);
}

/** Value for a datetime-local input. */
export function toLocalInput(instant: string, tz: string): string {
  return zoned(instant, tz).toPlainDateTime().toString({ smallestUnit: 'minute' });
}

/** Does the event [start, end) touch this local day? Multi-day events appear on every day they cover. */
export function coversDay(event: { start_at: string; end_at: string }, day: Temporal.PlainDate, tz: string): boolean {
  const dayStart = day.toZonedDateTime({ timeZone: tz }).toInstant();
  const dayEnd = day.add({ days: 1 }).toZonedDateTime({ timeZone: tz }).toInstant();
  const start = Temporal.Instant.from(event.start_at);
  const end = Temporal.Instant.from(event.end_at);
  return Temporal.Instant.compare(start, dayEnd) < 0 && Temporal.Instant.compare(end, dayStart) > 0;
}
