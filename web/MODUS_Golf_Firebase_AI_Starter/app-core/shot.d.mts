export interface Shot {
  schema_version: 1;
  shot_id: string; session_id: string; device_id: string; profile_id: string;
  sequence_number: number; revision: number; timestamp: string | null;
  club: string; record_kind: 'real' | 'synthetic' | 'unknown';
  processing_state: 'final' | 'processing' | 'failed';
  ball_speed_mph: number | null; club_speed_mph: number | null;
  smash_factor: number | null; vertical_launch_angle_deg: number | null;
  horizontal_launch_angle_deg: number | null; carry_yards: number | null;
  carry_kind: 'model'; spin_rpm: number | null; club_path_deg: number | null;
  trajectory: [number, number, number][] | null;
  model_inputs: {vertical_launch_angle_deg: number | null; spin_rpm: number | null; horizontal_launch_angle_deg: number | null};
  quality_flags: string[];
  source: {kind: 'legacy_csv' | 'pi_live' | 'synthetic_demo'; filename?: string;
    local_log_time?: string; timezone?: string | null; row_sha256?: string;
    ti_radar?: string; ball_speed_raw_mph?: number | null; apex_yards?: number | null;
    csv_format?: 'modus_csv_34'; csv_extra?: Record<string, string>};
}
export interface MetricSummary {n: number; mean: number | null; min: number | null; max: number | null; sample_sd: number | null}
export interface ImportContext {deviceId: string; profileId: string; filename: string; timezone?: string | null; confirmedReal?: boolean; hashBytes?: (bytes: Uint8Array) => Uint8Array | Promise<Uint8Array>}
export const CSV_COLUMNS: readonly string[];
export const CSV_EXTRA_COLUMNS: readonly string[];
export const CSV_EXTENDED_COLUMNS: readonly string[];
export function stableId(prefix: string, parts: string[], hashBytes?: (bytes: Uint8Array) => Uint8Array | Promise<Uint8Array>): Promise<string>;
export function parseSessionCsv(text: string): Record<string, string>[];
export function normalizeSessionCsv(text: string, context: ImportContext): Promise<Shot[]>;
export function mergeRevision(previous: Shot | undefined | null, incoming: Shot): Shot;
export function summarizeShots(shots: Shot[], options: {profileId: string; club?: string | null; sessionId?: string | null; allowSynthetic?: boolean}): {
  shot_count: number; metrics: Record<'ball_speed_mph' | 'club_speed_mph' | 'smash_factor' |
    'vertical_launch_angle_deg' | 'horizontal_launch_angle_deg' | 'carry_yards', MetricSummary>;
  carry_kind: 'model'; statistics_source: 'app'; includes_synthetic: boolean;
};
