import { useEffect, useState } from 'react';
import { CapacitorHttp } from '@capacitor/core';
import { piOrigin } from './pi';
import { watchReadiness } from './readiness';
import { monitorState, type MonitorState } from './monitor-remote';
import { MonitorRemote } from './MonitorRemote';

type Props = {
  origin:string; connected:boolean; foreground:boolean; onPractice:boolean;
  onReady:() => void; canConnect:boolean; connect:() => void; settings:() => void;
};
function ReadinessView({origin,connected,foreground,onPractice,canConnect,connect,settings,onReady}: Props) {
  const [state,setState] = useState<MonitorState | null>(null);
  const [read,setRead] = useState(false);
  const live = connected && foreground;
  useEffect(() => {
    if (!live) return;
    return watchReadiness(async () => {
      const response=await CapacitorHttp.get({url:piOrigin(origin)+'/state', disableRedirects:true,
        connectTimeout:2000, readTimeout:2000});
      return response.status === 200 ? monitorState(response.data) : null;
    }, value => {setState(value);setRead(true);});
  },[origin,live]);
  const label = !connected ? 'Monitor disconnected' : !foreground ? 'Paused' : state?.label ?? (read ? 'Status unavailable' : 'Connecting…');
  useEffect(() => {if (label === 'Ready') onReady();},[label,onReady]);
  return <><section className="ball-readiness" aria-label="Live ball readiness">
    <div><span>Ball readiness</span><strong role="status" data-state={label}>{label}</strong>
      {label === 'Status unavailable' && <small>Check MODUS Wi-Fi and the monitor address. Retrying automatically.</small>}
    </div>
    {onPractice && <div className="readiness-actions">
      {!connected && <button className="primary" disabled={!canConnect} onClick={connect}>Connect monitor</button>}
      <button onClick={settings}>Monitor settings</button>
    </div>}
  </section>
    {live && state?.liveShot && <section className="panel" aria-label="Live monitor metrics">
      <h2>Live monitor · {state.liveShot.test ? 'Test shot' : 'Shot'} {state.liveShot.sequence}</h2>
      <p>Live readings use the monitor’s units.</p>
      {state.liveShot.pending && <p>Waiting for final radar readings…</p>}
      <div className="secondary-metrics">{state.liveShot.readings.map(reading =>
        <div key={reading.label}><span>{reading.label}</span>
          <strong>{reading.value ?? '—'}{reading.value !== null && <small> {reading.unit}{reading.estimated ? ' est.' : ''}</small>}</strong>
        </div>
      )}</div>
    </section>}
    {!onPractice && live && <MonitorRemote state={state} origin={origin}/>}
  </>;
}
export function BallReadiness(props: Props) {
  return <ReadinessView key={JSON.stringify([props.origin,props.connected,props.foreground])} {...props}/>;
}
