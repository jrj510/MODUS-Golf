import { uniqueShots, validateCloudShot, type Shot } from '../../src/domain.ts';

export const historyPageSize=100;
type Snapshot={id:string;path:string;data:Record<string,unknown> | null;metadata:{fromCache:boolean}};

export function decodeHistoryPage(snapshots:Snapshot[]) {
  const page=snapshots.slice(0,historyPageSize);
  const items:Shot[]=[];
  let skipped=0;
  for (const snapshot of page) {
    try {items.push(validateCloudShot({...snapshot.data,id:snapshot.id}));}
    catch {skipped++;}
  }
  return {
    items:uniqueShots(items),skipped,
    // Empty query metadata is unavailable through this plugin. Do not claim
    // server completeness based on an empty cache result.
    cached:page.length === 0 || page.some(item => item.metadata.fromCache),
    // Advance past malformed rows too, or an invalid boundary can trap paging.
    nextCursor:snapshots.length > historyPageSize ? page[page.length-1].path : null
  };
}
