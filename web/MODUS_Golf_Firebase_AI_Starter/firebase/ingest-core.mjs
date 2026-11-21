import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { stableId } from '../app-core/shot.mjs';
import { canonicalJson } from '../app-core/sync-wire.mjs';

const ajv = new Ajv2020();
addFormats(ajv);
const validateShot = ajv.compile(JSON.parse(readFileSync(new URL('../contracts/shot.schema.json',import.meta.url),'utf8')));
const opaqueId = /^[A-Za-z0-9_-]{1,120}$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const hash = value => createHash('sha256').update(value).digest();
const id = (prefix, parts) => stableId(prefix, parts, hash);
export const shotDigest = shot => hash(canonicalJson(shot)).toString('hex');

export function validBatch(body) {
  return body && Object.keys(body).length === 4 && body.version === 1 &&
    typeof body.installationId === 'string' && uuid.test(body.installationId) &&
    typeof body.profileId === 'string' && opaqueId.test(body.profileId) &&
    Array.isArray(body.shots) && body.shots.length > 0 && body.shots.length <= 20;
}

export async function prepareShot(shot, installationId, profileId) {
  if (!validateShot(shot) || shot.record_kind !== 'real' || shot.processing_state !== 'final' ||
      shot.source.kind !== 'legacy_csv' || !shot.source.row_sha256 || !shot.source.local_log_time ||
      !shot.source.filename || shot.trajectory !== null || shot.timestamp !== null ||
      shot.spin_rpm !== null || shot.club_path_deg !== null ||
      shot.model_inputs.horizontal_launch_angle_deg !== 0 ||
      !Number.isSafeInteger(shot.sequence_number) || !Number.isSafeInteger(shot.revision)) return null;
  const source = [shot.device_id, shot.source.filename];
  if (shot.session_id !== await id('session',source) ||
      shot.shot_id !== await id('shot',[...source,String(shot.sequence_number)])) return null;
  const cloudSessionId = await id('session',[installationId,shot.session_id]);
  const cloudShotId = await id('shot',[installationId,shot.shot_id]);
  const digest = shotDigest(shot);
  const record = {
    ...shot, shot_id:cloudShotId, session_id:cloudSessionId, profile_id:profileId,
    quality_flags:['legacy_csv','sensor_values_unverified','spin_assumed','flight_direction_assumed',
      'no_impact_timestamp',...(shot.vertical_launch_angle_deg === null ? ['launch_assumed'] : [])],
    import_provenance:'user_confirmed_legacy_csv', original_shot_id:shot.shot_id,
    original_session_id:shot.session_id, import_digest:digest
  };
  return {record,digest,cloudSessionId,cloudShotId};
}

export function decideRevision(existing, incoming) {
  if (!existing) return 'write';
  if (existing.profile_id !== incoming.profile_id || existing.original_shot_id !== incoming.original_shot_id ||
      existing.session_id !== incoming.session_id) return 'ownership_conflict';
  if (existing.deleted_at) return 'deleted';
  if (existing.revision > incoming.revision) return 'stale_revision';
  if (existing.revision === incoming.revision) return existing.import_digest === incoming.import_digest ? 'replay' : 'revision_conflict';
  return 'write';
}
