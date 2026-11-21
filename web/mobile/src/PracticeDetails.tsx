import { useState } from 'react';
import { clubName } from '../../src/domain';

export type SessionDetails = {name:string; notes:string};
export type BagClub = {id:string; name:string; monitorLabel:string; archived:boolean};

export function SessionEditor({details,busy,save}: {
  details?:SessionDetails; busy:boolean; save:(details:SessionDetails) => void;
}) {
  return <details className="panel">
    <summary>Session name and notes</summary>
    <form onSubmit={event => {
      event.preventDefault();
      const data=new FormData(event.currentTarget);
      save({name:String(data.get('name')).trim(),notes:String(data.get('notes')).trim()});
    }}>
      <label>Session name<input name="name" maxLength={80} defaultValue={details?.name}/></label>
      <label>Notes<textarea name="notes" rows={3} maxLength={1000} defaultValue={details?.notes}/></label>
      <button disabled={busy}>Save session details</button>
    </form>
  </details>;
}

export function ClubInventory({clubs,reported,busy,save}: {
  clubs:BagClub[]; reported:string[]; busy:boolean;
  save:(club:BagClub) => Promise<boolean>;
}) {
  const [editing,setEditing]=useState<string | null>(null);
  const current=clubs.find(club => club.id === editing);
  const labels=[...new Set([...reported,...clubs.map(club => club.monitorLabel).filter(Boolean)])].sort();
  return <section className="panel">
    <h2>My clubs</h2>
    {clubs.length > 0 && <ul>{clubs.map(club => <li key={club.id}>
      <strong>{club.name}</strong>{club.archived ? ' · Archived' : club.monitorLabel ? ' · Monitor label '+club.monitorLabel : ''}
      {' '}<button disabled={busy} onClick={() => setEditing(club.id)}>Edit {club.name}</button>
    </li>)}</ul>}
    <form key={editing ?? 'new'} onSubmit={async event => {
      event.preventDefault();
      const form=event.currentTarget;
      const fields=new FormData(form);
      const name=String(fields.get('name')).trim();
      if (!name) return;
      const saved=await save({
        id:current?.id ?? '',
        name,
        monitorLabel:String(fields.get('monitorLabel')),
        archived:fields.has('archived')
      });
      if (!saved) return;
      setEditing(null);
      form.reset();
    }}>
      <fieldset disabled={busy}>
      <label>Club name<input name="name" required maxLength={60} defaultValue={current?.name}/></label>
      <label>Match monitor label<select name="monitorLabel" defaultValue={current?.monitorLabel ?? ''}>
        <option value="">Choose a label after capture</option>
        {labels.map(label => <option key={label} value={label}>{clubName(label)}</option>)}
      </select></label>
      {current && <label className="checkbox"><input name="archived" type="checkbox" defaultChecked={current.archived}/>Archive this club</label>}
      <div className="button-row"><button disabled={busy}>{current ? 'Save club' : 'Add club'}</button>
        {current && <button type="button" onClick={() => setEditing(null)}>Cancel edit</button>}</div>
      </fieldset>
    </form>
  </section>;
}

export function GolferForm({busy,save}:{busy:boolean;save:(name:string) => Promise<boolean>}) {
  const [name,setName]=useState('');
  return <form onSubmit={async event => {
    event.preventDefault();
    if(await save(name.trim())) setName('');
  }}><fieldset disabled={busy}>
    <label>New golfer name<input value={name} onChange={event => setName(event.target.value)} maxLength={80} required/></label>
    <button disabled={!name.trim()}>Add golfer</button>
  </fieldset></form>;
}
