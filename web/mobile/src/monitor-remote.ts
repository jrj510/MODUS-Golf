import { ballStatus } from './readiness.ts';

export const monitorClubs = ['driver','3w','hybrid','5i','6i','7i','8i','9i','pw','52','56','60'] as const;
export const monitorScreens = {main:'Dashboard', camera:'Camera', range:'Range'} as const;
type Club = typeof monitorClubs[number];
type Screen = keyof typeof monitorScreens;
export type Command = {kind:'club'; value:Club} | {kind:'light'; value:'day'|'night'} |
  {kind:'zoom'; value:boolean} | {kind:'sleep'|'wake'} | {kind:'screen'; value:Screen};

export function monitorState(data:unknown) {
  const s = typeof data === 'string' ? JSON.parse(data) : data;
  const label = ballStatus(s);
  if (label === 'Status unavailable') return null;
  // Launcher pages and older kiosks may omit the hardware settings.
  const kiosk = Number.isInteger(s.rev) && Number.isInteger(s.shot) && typeof s.metrics === 'object' && !!s.metrics;
  return {label, kiosk, club:monitorClubs.includes(s.club) ? s.club as Club : null,
    light:s.light === 'day' || s.light === 'night' ? s.light as 'day'|'night' : null,
    zoom:typeof s.view?.zoomed === 'boolean' && s.view?.can_zoom === true ? s.view.zoomed as boolean : null,
    screenControl:s.display?.version === 1, displayed:typeof s.display?.applied === 'string' ? s.display.applied as string : null};
}
export type MonitorState = NonNullable<ReturnType<typeof monitorState>>;
export function commandPath(command:Command) {
  switch (command.kind) {
    case 'club': return '/club?c='+command.value;
    case 'light': return '/light?mode='+command.value;
    case 'zoom': return '/view?zoom='+(command.value ? '1' : '0');
    case 'screen': return '/display/'+command.value;
    case 'sleep': return '/sleep';
    case 'wake': return '/wake';
  }
}
export function commandConfirmed(state:MonitorState, command:Command, receipt:string) {
  switch (command.kind) {
    case 'club': return state.club === command.value;
    case 'light': return state.light === command.value;
    case 'zoom': return state.zoom === command.value;
    case 'screen': return !!receipt && state.displayed === receipt;
    case 'sleep': return state.label === 'Asleep';
    case 'wake': return state.label !== 'Asleep' && state.label !== 'Waking up';
  }
}
