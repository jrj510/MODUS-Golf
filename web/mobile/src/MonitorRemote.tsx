import {useEffect, useRef, useState} from 'react';
import {CapacitorHttp} from '@capacitor/core';
import {clubName} from '../../src/domain';
import {piOrigin} from './pi';
import {commandConfirmed, commandPath, monitorClubs, monitorScreens, type Command, type MonitorState} from './monitor-remote';

export function MonitorRemote({state,origin}: {state:MonitorState | null; origin:string}) {
  const [enabled,setEnabled] = useState(false);
  const [pending,setPending] = useState<{command:Command; receipt:string} | null>(null);
  const [message,setMessage] = useState('');
  const sending = useRef(false);
  const mounted = useRef(false);
  useEffect(() => {mounted.current=true; return () => {mounted.current=false;};},[]);
  useEffect(() => {
    if (!pending) return;
    const timer=setTimeout(() => {
      setMessage('No confirmation yet. Check the monitor before trying again.');
      setPending(null);sending.current=false;
    },12000);
    return () => clearTimeout(timer);
  },[pending]);
  useEffect(() => {
    if (pending && state && commandConfirmed(state,pending.command,pending.receipt)) {
      setMessage(pending.command.kind === 'screen' ? 'Monitor opened '+monitorScreens[pending.command.value]+'.' : 'Monitor confirmed the change.');
      setPending(null);sending.current=false;
    }
  },[state,pending]);
  async function send(command:Command) {
    if (!enabled || !state?.kiosk || sending.current) return;
    sending.current=true; setMessage('Sending to monitor…');
    try {
      const screen=command.kind === 'screen';
      const response=await CapacitorHttp.post({url:piOrigin(origin)+commandPath(command),disableRedirects:true,
        connectTimeout:2500,readTimeout:3000, ...(screen ? {headers:{'X-MODUS-Display':'1'},responseType:'text' as const} : {})});
      const receipt=screen ? String(response.data) : '';
      if (screen ? response.status !== 200 || !/^d\d{1,24}$/.test(receipt) : response.status !== 204) throw Error();
      if (mounted.current) {setPending({command,receipt});setMessage('Waiting for monitor confirmation…');}
    } catch {
      if (mounted.current) {sending.current=false;setMessage('Command unconfirmed. Check MODUS Wi-Fi and the monitor.');}
    }
  }
  const awake=state?.kiosk && ['Ready','Looking for Ball','Get Set'].includes(state.label);
  const disabled=!awake || !!pending || sending.current;
  return <section className="panel"><h2>Monitor remote</h2>
    <label className="checkbox"><input type="checkbox" checked={enabled} disabled={!state?.kiosk && !enabled}
      onChange={e => setEnabled(e.target.checked)}/>Enable phone controls</label>
    {enabled && state?.kiosk ? <>
      {state.club && <label>Monitor club<select disabled={disabled} value={state.club}
        onChange={e => void send({kind:'club',value:e.target.value as typeof monitorClubs[number]})}>
        {monitorClubs.map(c => <option key={c} value={c}>{clubName(c)}</option>)}</select></label>}
      <div className="button-row">
        {state.light && <button disabled={disabled} aria-pressed={state.light==='night'}
          onClick={() => void send({kind:'light',value:state.light==='night'?'day':'night'})}>Low light {state.light==='night'?'on':'off'}</button>}
        {state.zoom !== null && <button disabled={disabled} onClick={() => void send({kind:'zoom',value:!state.zoom})}>{state.zoom?'Use wide view':'Zoom camera in'}</button>}
        {state.label === 'Asleep' ? <button disabled={!!pending || sending.current} onClick={() => void send({kind:'wake'})}>Wake monitor</button> :
          <button disabled={disabled} onClick={() => void send({kind:'sleep'})}>Sleep monitor</button>}
      </div>
      {state.screenControl ? <><h3>Show on monitor screen</h3><div className="button-row">
        {(Object.keys(monitorScreens) as (keyof typeof monitorScreens)[]).map(screen =>
          <button disabled={disabled} key={screen} onClick={() => void send({kind:'screen',value:screen})}>{monitorScreens[screen]}</button>)}
      </div></> : <p>Switching the touchscreen page requires the monitor display update.</p>}
    </> : !state?.kiosk ? <p>Waiting for live kiosk settings. Open practice on the monitor and join its Wi-Fi.</p> :
      <small>The touchscreen stays active while you use the phone.</small>}
    {message && <p role="status">{message}</p>}
  </section>;
}
