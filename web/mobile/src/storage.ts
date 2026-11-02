import { Capacitor } from '@capacitor/core';
import { Directory, Encoding, Filesystem } from '@capacitor/filesystem';
import type { StoragePort } from './journal';

export function storagePort(): StoragePort {
  if (Capacitor.isNativePlatform()) return {
    async read(slot) {
      try { return String((await Filesystem.readFile({path:`modus-local-${slot}.json`,directory:Directory.Data,encoding:Encoding.UTF8})).data); }
      catch (error) {
        if ((error as {code?:string}).code === 'OS-PLUG-FILE-0008' || /not found|does not exist|no such file|ENOENT/i.test(String((error as Error).message))) return null;
        throw error;
      }
    },
    async write(slot,data) { await Filesystem.writeFile({path:`modus-local-${slot}.json`,directory:Directory.Data,encoding:Encoding.UTF8,data}); }
  };
  const database = new Promise<IDBDatabase>((resolve,reject) => {
    const request = indexedDB.open('modus-mobile-local-preview',1);
    request.onupgradeneeded=() => request.result.createObjectStore('slots');
    request.onsuccess=() => resolve(request.result);request.onerror=() => reject(request.error);
  });
  return {
    async read(slot) {const db=await database;return new Promise((resolve,reject) => {const request=db.transaction('slots').objectStore('slots').get(slot);request.onsuccess=() => resolve(request.result ?? null);request.onerror=() => reject(request.error);});},
    async write(slot,data) {const db=await database;return new Promise<void>((resolve,reject) => {const transaction=db.transaction('slots','readwrite');transaction.objectStore('slots').put(data,slot);transaction.oncomplete=() => resolve();transaction.onerror=() => reject(transaction.error);transaction.onabort=() => reject(transaction.error ?? new Error('Local save aborted'));});}
  };
}
