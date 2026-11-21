// Same state names and labels as the monitor's kiosk display.
const states = new Map([
  ['STARTING', 'Starting'], ['SEARCHING', 'Looking for Ball'], ['BALL', 'Looking for Ball'],
  ['READY', 'Ready'], ['SWINGTEST', 'Ready'], ['CAPTURING', 'Recording'],
  ['WAIT', 'Get Set'], ['MEASURING', 'Measuring'], ['CHECKING', 'Checking'],
  ['SLEEPING', 'Asleep'], ['WAKING', 'Waking up'],
]);

export function ballStatus(data: unknown): string {
  const payload = typeof data === 'string' ? JSON.parse(data) : data;
  return states.get(payload?.state) ?? 'Status unavailable';
}

/** Poll while visible. A slow or failed read must clear a previous Ready signal. */
export function watchReadiness<T>(read: () => Promise<T | null>, show: (state: T | null) => void) {
  let active = true;
  let next: ReturnType<typeof setTimeout>;
  let deadline: ReturnType<typeof setTimeout>;
  async function poll() {
    let expired = false;
    deadline = setTimeout(() => {
      expired = true;
      if (active) show(null);
    }, 2500);
    let state: T | null = null;
    try {
      state = await read();
    } catch { /* Retry even if the monitor's network drops. */ }
    clearTimeout(deadline);
    if (!active) return;
    show(expired ? null : state);
    next = setTimeout(poll, state === null ? 2000 : 750);
  }
  void poll();
  return () => {
    active = false;
    clearTimeout(next);
    clearTimeout(deadline);
  };
}
