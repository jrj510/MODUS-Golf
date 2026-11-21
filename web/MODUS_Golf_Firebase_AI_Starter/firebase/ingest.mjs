import { initializeApp } from 'firebase-admin/app';
import { getAuth } from 'firebase-admin/auth';
import { FieldValue, getFirestore } from 'firebase-admin/firestore';
import { onRequest } from 'firebase-functions/v2/https';
import { decideRevision, prepareShot, shotDigest, validBatch } from './ingest-core.mjs';

initializeApp();

export const ingestLegacyShots = onRequest({
  region:'us-central1', maxInstances:3, concurrency:8, timeoutSeconds:30,
  // The native app sends a Firebase ID token; authorization is enforced below.
  // Cloud Run IAM must allow the request to reach that verifier.
  invoker:'public',
  cors:['capacitor://localhost','https://localhost']
}, async (request,response) => {
  response.set('Cache-Control','no-store');
  if (request.method !== 'POST') return response.status(405).end();
  if ((request.rawBody?.length ?? 0) > 96_000) return response.status(413).end();
  const token = /^Bearer ([^ ]+)$/.exec(request.get('Authorization') ?? '')?.[1];
  if (!token) return response.status(401).end();
  let uid;
  try { ({uid}=await getAuth().verifyIdToken(token,true)); }
  catch { return response.status(401).end(); }
  const body=request.body;
  if (!validBatch(body)) return response.status(400).end();
  const {installationId, profileId, shots}=body;
  const db=getFirestore();
  const user=db.collection('users').doc(uid);
  const profile=user.collection('profiles').doc(profileId);
  const receipts=[];
  try {
    const quota=db.collection('legacy_import_quotas').doc(uid);
    const allowed=await db.runTransaction(async transaction => {
      const minute=Math.floor(Date.now()/60_000);
      const previous=await transaction.get(quota);
      const count=previous.get('minute') === minute ? previous.get('count') : 0;
      if (count+shots.length > 120) return false;
      transaction.set(quota,{minute,count:count+shots.length});
      return true;
    });
    if (!allowed) return response.set('Retry-After','60').status(429).end();
    for (const shot of shots) {
      const prepared=await prepareShot(shot,installationId,profileId);
      if (!prepared) {
        receipts.push({
          status:'rejected',code:'invalid_shot',
          shotId:typeof shot?.shot_id === 'string' && shot.shot_id.length <= 120 ? shot.shot_id : null,
          revision:Number.isSafeInteger(shot?.revision) ? shot.revision : null,
          digest:shotDigest(shot)
        });
        continue;
      }
      const {record,digest,cloudSessionId,cloudShotId}=prepared;
      const binding=db.collection('legacy_import_bindings').doc(cloudSessionId);
      const session=user.collection('sessions').doc(cloudSessionId);
      const destination=user.collection('shots').doc(cloudShotId);
      const status=await db.runTransaction(async transaction => {
        const [golfer,owner,prior]=await transaction.getAll(profile,binding,destination);
        if (!golfer.exists) return 'profile_missing';
        if (owner.exists && (owner.get('uid') !== uid || owner.get('profile_id') !== profileId)) return 'ownership_conflict';
        const decision=decideRevision(prior.data(),record);
        if (decision !== 'write') return decision;
        if (!owner.exists) {
          transaction.create(binding,{uid,profile_id:profileId});
          transaction.create(session,{
            profile_id:profileId, device_id:shot.device_id, source_filename:shot.source.filename,
            import_provenance:'user_confirmed_legacy_csv', original_session_id:shot.session_id,
            created_at:FieldValue.serverTimestamp()
          });
        }
        transaction.set(destination,{...record,ingested_at:FieldValue.serverTimestamp()});
        return 'write';
      });
      const accepted=status === 'write' || status === 'replay';
      receipts.push({
        status:accepted?'accepted':'rejected', code:status, shotId:shot.shot_id,
        revision:shot.revision, digest, cloudSessionId, cloudShotId
      });
    }
    return response.json({version:1,receipts});
  } catch {
    // A prior item may have committed. Retrying the batch returns replay receipts.
    return response.status(503).end();
  }
});
