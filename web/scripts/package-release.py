"""Package only reviewed web sources and handoff files, never local reviews/secrets."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json

root = Path(__file__).resolve().parents[1]
output = root / 'MODUS_Golf_Web_App_Refined_2026-10-23.zip'
folders = ['src', 'public', 'tests', 'scripts', 'handoff', 'MODUS_Golf_Firebase_AI_Starter']
names = ['package.json', 'package-lock.json', 'tsconfig.json', 'index.html',
         'firebase.json', 'firebase.emulator-test.json', '.firebaserc', '.gitignore',
         'AGENTS.md', 'README.md', 'WEB_APP_RELEASE_2026-10-23.md',
         'WEB_APP_REFINEMENT_2026-10-23.md', 'MODUS_Golf_GitHub_Integration_Handoff.md']
files = [root / name for name in names]
for folder in folders:
    files.extend(p for p in (root / folder).rglob('*') if p.is_file()
                 and not any(part in {'node_modules', '__pycache__', '.git'} for part in p.parts)
                 and p.suffix not in {'.pyc', '.zip'})
manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}
with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
    for relative in manifest:
        archive.write(root / relative, relative)
    archive.writestr('RELEASE_SOURCE_SHA256.json', json.dumps(manifest, indent=2) + '\n')
with ZipFile(output) as archive:
    assert archive.testzip() is None
    assert len(archive.namelist()) == len(manifest) + 1
    assert not any(n.startswith(('reviews/', '.tools/', '.agents/')) for n in archive.namelist())
print(f'{output.name}: {len(manifest)} source files + SHA-256 manifest; {output.stat().st_size:,} bytes')
