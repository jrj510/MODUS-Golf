import { Capacitor, CapacitorHttp } from '@capacitor/core';
import { normalizeSessionCsv, parseSessionCsv } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
import type { LocalState } from './journal';
import { sha256 } from '@noble/hashes/sha2.js';

export function piOrigin(value: string) {
  const url = new URL(value);
  if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash ||
      !/^(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|[a-zA-Z0-9-]+\.local)$/.test(url.hostname)) throw new Error('Enter the Pi private-network origin, for example http://10.42.0.1:8000.');
  return url.origin;
}

export function selectMonitor(state: LocalState, address: string): LocalState {
  const origin=piOrigin(address);
  const monitors=state.monitors ?? {[state.piOrigin]:state.deviceId};
  if (monitors[origin]) return {...state,piOrigin:origin,deviceId:monitors[origin],monitors};
  const digest=sha256(new TextEncoder().encode(origin));
  const id='local_'+Array.from(digest,byte => byte.toString(16).padStart(2,'0')).join('');
  return {...state,piOrigin:origin,deviceId:id,monitors:{...monitors,[origin]:id}};
}
export async function readPi(state: LocalState, confirmedFilename: string | null) {
  if (!Capacitor.isNativePlatform()) throw new Error('To connect to your launch monitor, open the installed MODUS Golf iPhone app and join MODUS Wi-Fi.');
  const response=await CapacitorHttp.get({url:piOrigin(state.piOrigin)+'/session.csv',connectTimeout:3000,readTimeout:3000,disableRedirects:true});
  if (response.status !== 200 || typeof response.data !== 'string') throw new Error('Pi CSV was not received. Stay connected to MODUS Wi-Fi; internet is not required.');
  const disposition=Object.entries(response.headers).find(([key]) => key.toLowerCase() === 'content-disposition')?.[1] ?? '';
  return decodePiSnapshot(response.data, disposition, state, confirmedFilename);
}

export async function decodePiSnapshot(csv: string, disposition: string, state: Pick<LocalState, 'deviceId' | 'profileId'>, confirmedFilename: string | null) {
  const filename=/(?:^|;\s*)filename="(session(?:_\d{8}_\d{6})?\.csv)"(?:;|$)/i.exec(disposition)?.[1];
  if (filename === 'session.csv' && parseSessionCsv(csv).length === 0) return {filename:null, shots:[]};
  if (!filename || filename === 'session.csv') throw new Error('Pi must supply its original session CSV filename.');
  const shots = await normalizeSessionCsv(csv, {
    deviceId:state.deviceId, profileId:state.profileId, filename,
    confirmedReal:filename === confirmedFilename, timezone:null, hashBytes:sha256
  });
  return {filename, shots};
}
