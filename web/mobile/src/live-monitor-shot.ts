// Match the physical kiosk's eight tiles, units, and displayed precision.
const tiles = [
  ['ball_speed', 'Ball speed', 'mph', 1],
  ['club_speed', 'Club speed', 'mph', 1],
  ['smash', 'Smash factor', '', 2],
  ['carry', 'Carry', 'yd', 0],
  ['launch_angle', 'Launch angle', '°', 1],
  ['launch_dir', 'Launch direction', '°', 1],
  ['spin', 'Spin rate', 'rpm', 0],
  ['total', 'Total', 'yd', 0],
] as const;

export function readLiveShot(sequence: unknown, metrics: unknown) {
  if (typeof sequence !== 'number' || !Number.isSafeInteger(sequence) || sequence <= 0 ||
      !metrics || typeof metrics !== 'object' || Array.isArray(metrics)) return null;
  const data = metrics as Record<string, unknown>;
  const estimates = Array.isArray(data.estimated) ? data.estimated : [];
  return {
    sequence,
    test: data.test === true,
    pending: data.radar_pending === true,
    readings: tiles.map(([key, label, unit, digits]) => {
      const raw = data[key];
      const value = typeof raw === 'number' && Number.isFinite(raw) ? raw.toFixed(digits) : null;
      return {label, value, unit, estimated: value !== null && estimates.includes(key)};
    }),
  };
}
