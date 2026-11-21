import type { Shot } from '../../src/domain';
import { acceptReceipt, payloadDigest, type Outcome } from './sync-queue.ts';

// The production ingestion endpoint accepts up to 20 shots and 96,000 UTF-8 bytes.
export async function sendShotBatch(
  candidates: Shot[], installationId: string, profileId: string,
  send: (body: string) => Promise<Response>
) {
  if (!candidates.length) throw new Error('Cannot upload an empty batch.');
  let shots = candidates.slice(0, 20);
  const encoder = new TextEncoder();
  while (true) {
    const body = JSON.stringify({version: 1, installationId, profileId, shots});
    const outcomes = new Map<string, Outcome>();
    if (encoder.encode(body).byteLength <= 96_000) {
      const response = await send(body);
      if (response.status !== 413) {
        if (!response.ok) throw new Error('Cloud did not confirm the upload.');
        const result = await response.json();
        if (result.version !== 1 || !Array.isArray(result.receipts) || result.receipts.length !== shots.length)
          throw new Error('Invalid cloud receipt.');
        for (const [index, shot] of shots.entries()) {
          const receipt = acceptReceipt(shot, result.receipts[index]);
          if (receipt) outcomes.set(shot.shot_id, receipt);
        }
        if (!outcomes.size) throw new Error('Cloud did not confirm the upload.');
        return {shots, outcomes};
      }
    }
    if (shots.length === 1) {
      const [shot] = shots;
      outcomes.set(shot.shot_id, {
        status: 'rejected', code: 'upload_too_large', revision: shot.revision,
        digest: payloadDigest(shot), receivedAt: new Date().toISOString()
      });
      return {shots, outcomes};
    }
    shots = shots.slice(0, Math.ceil(shots.length / 2));
  }
}
