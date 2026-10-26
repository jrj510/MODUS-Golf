import { useState, type FormEvent } from 'react';
import { normalizeSessionCsv } from '../MODUS_Golf_Firebase_AI_Starter/app-core/shot.mjs';
import { type Shot } from './domain';
import { download } from './components';
import { type Profile } from './repository';
export function ImportPreview({ profiles, onUse, onClose }: { profiles: Profile[]; onUse: (shots: Shot[], profile: Profile) => void; onClose: () => void }) {
  const [preview, setPreview] = useState<Shot[] | null>(null);
  const [selected, setSelected] = useState<Profile | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [fileName, setFileName] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setPreview(null); setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      const file = data.get('file');
      if (!(file instanceof File) || !file.size) throw new Error('Choose a complete session CSV exported from the Pi.');
      if (file.size > 1048576) throw new Error('The CSV must be no larger than 1 MiB.');
      const profile = profiles.find(item => item.id === data.get('profile'));
      if (!profile) throw new Error('Create a golfer profile in Settings before previewing a file.');
      const timezone = String(data.get('timezone')).trim();
      if (!timezone) throw new Error('Enter the Pi’s IANA timezone. Do not guess it from this phone.');
      const shots = await normalizeSessionCsv(await file.text(), { filename: file.name, deviceId: String(data.get('device')).trim(), profileId: profile.id, timezone, confirmedReal: data.get('real') === 'on' });
      if (!shots.length) throw new Error('This CSV contains a header but no shot records.');
      setPreview(shots); setSelected(profile); setFileName(file.name);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not preview this file.'); }
    finally { setBusy(false); }
  }
  return <section className="panel import-panel" aria-label="CSV import preview"><div className="panel-heading"><div><p className="eyebrow">FROM YOUR LAUNCH MONITOR</p><h2>Preview a session CSV</h2></div><button onClick={onClose}>Close preview</button></div>
    <p>Local preview only. Your file stays in this browser tab and is cleared when you leave or switch accounts. Nothing is uploaded.</p>
    <form onSubmit={submit} onChange={() => { setPreview(null); setSelected(null); }}><fieldset disabled={busy}>
      <div className="form-grid"><label>Original session CSV<input type="file" name="file" required accept=".csv,text/csv"/></label><label>Golfer profile<select name="profile" required defaultValue=""><option value="" disabled>Select golfer</option>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.display_name}</option>)}</select></label><label>Physical device ID<input name="device" required maxLength={120} pattern="[A-Za-z0-9_-]+" placeholder="Your device’s assigned ID"/></label><label>Pi timezone<input name="timezone" required placeholder="e.g. America/Chicago — confirm on Pi"/></label></div>
      <label className="checkbox"><input name="real" type="checkbox"/>I confirm these are real captured shots, not synthetic or test data.</label><small>Unchecked records remain unconfirmed and are excluded from golfer statistics. Device attribution here is not device pairing or ownership verification. Keep the original session_YYYYMMDD_HHMMSS.csv filename. Local log times are preserved; no UTC impact time is invented.</small><button className="primary">{busy ? 'Validating complete file…' : 'Validate & preview'}</button>
    </fieldset></form>{error && <p className="error" role="alert">{error}</p>}
    {preview && selected && <div className="preview-result" role="status"><h3>{preview.length} records ready for local preview</h3><p>{fileName} · {selected.display_name} · {preview[0].record_kind === 'real' ? 'User-confirmed real shots' : 'Unconfirmed shots'}</p><div className="button-row"><button className="primary" onClick={() => onUse(preview, selected)}>View this local session</button><button onClick={() => download('modus-normalized-preview.json', JSON.stringify(preview, null, 2))}>Download normalized JSON</button></div></div>}
    <button disabled title="An authenticated ingestion backend is not deployed.">Cloud upload not available</button><small>The future backend must verify account/device ownership and acknowledge each stable shot ID and revision before uploads can be enabled.</small>
  </section>;
}
