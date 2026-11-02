import { Capacitor, CapacitorHttp } from '@capacitor/core';
import { normalizeSessionCsv } from '../../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
import type { LocalState } from './journal';
import { sha256 } from '@noble/hashes/sha2.js';

export function piOrigin(value: string) {
  const url = new URL(value);
  if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash ||
      !/^(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|[a-zA-Z0-9-]+\.local)$/.test(url.hostname)) throw new Error('Enter the Pi private-network origin, for example http://10.42.0.1:8000.');
  return url.origin;
}
export async function readPi(state: LocalState, confirmedReal: boolean) {
  if (!Capacitor.isNativePlatform()) throw new Error('Direct Pi connection runs in the installed iPhone app. Use the computer test server for browser testing.');
  const response=await CapacitorHttp.get({url:piOrigin(state.piOrigin)+'/session.csv',connectTimeout:3000,readTimeout:3000});
  if (response.status !== 200 || typeof response.data !== 'string') throw new Error('Pi CSV was not received. Stay connected to MODUS Wi-Fi; internet is not required.');
  const disposition=Object.entries(response.headers).find(([key]) => key.toLowerCase() === 'content-disposition')?.[1] ?? '';
  const filename=/filename="(session_\d{8}_\d{6}\.csv)"/.exec(disposition)?.[1];
  if (!filename) throw new Error('Pi must supply its original session CSV filename.');
  return normalizeSessionCsv(response.data,{deviceId:state.deviceId,profileId:state.profileId,filename,confirmedReal,timezone:null,hashBytes:sha256});
}
