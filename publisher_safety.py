"""Non-destructive, fail-closed safety checks for Konstellation Publisher.

This does NOT approve public data publication. No C1/C2/C3 trusted verifier is
currently wired; a live deployment MUST remain disabled.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile


class PublicationBlocked(RuntimeError):
    pass


REQUIRED_FILES = (
    'package.json', 'package-lock.json', 'astro.config.mjs',
    'svelte.config.js', 'server/index.mjs', 'server/config.mjs',
    'src/pages/index.astro',
)
# Package allowlist for the actual Konstellation source tree, not directories
# containing arbitrary local/private build output.
ALLOWED_ROOT_FILES = {
    'package.json', 'package-lock.json', 'astro.config.mjs',
    'svelte.config.js',
}
ALLOWED_TOP_DIRECTORIES = {'server', 'src', 'public', 'contracts'}
BLOCKED_NAMES = {'.env', '.git', '.ssh', '.npmrc', 'secrets', 'private',
                 'node_modules', '__pycache__', '.DS_Store'}
BLOCKED_SUFFIXES = {'.key', '.pem', '.p12', '.pfx', '.sqlite', '.db',
                    '.bak', '.log', '.tmp'}


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def audit_checkout(root: Path) -> dict:
    root = root.resolve(strict=True)
    for rel in REQUIRED_FILES:
        f = root / rel
        if not f.is_file() or f.is_symlink():
            raise PublicationBlocked(f'Fichier indispensable absent ou lien symbolique: {rel}')
    try:
        package = json.loads((root / 'package.json').read_text(encoding='utf-8'))
        lock = json.loads((root / 'package-lock.json').read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise PublicationBlocked('package.json / lockfile non valide') from exc
    version = package.get('version')
    if not isinstance(version, str) or not version.startswith('1.'):
        raise PublicationBlocked('Publisher v0.2 exige Konstellation 1.x; aucun ancien moteur accepté')
    if lock.get('name') != package.get('name') or lock.get('version') != version:
        raise PublicationBlocked('package-lock.json incohérent avec package.json')
    rootlock = (lock.get('packages') or {}).get('', {})
    if rootlock.get('version') != version or rootlock.get('name') != package.get('name'):
        raise PublicationBlocked('Lockfile racine incohérent')
    scripts = package.get('scripts') or {}
    if not all(isinstance(scripts.get(k), str) and scripts[k] for k in ('build','start','release:check')):
        raise PublicationBlocked('Scripts de release obligatoires absents')
    return {'version': version, 'package_lock_sha256': digest_file(root/'package-lock.json'),
            'qualification': 'NOT_VERIFIED', 'publication_authorization': 'NOT_VERIFIED'}


def _include_file(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    parts = rel.parts
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] in ALLOWED_ROOT_FILES
    if parts[0] not in ALLOWED_TOP_DIRECTORIES:
        return False
    if any(x in BLOCKED_NAMES or x.lower().startswith('.env') or x.startswith('.backup') for x in parts):
        raise PublicationBlocked(f'Fichier sensible sous chemin de source autorisé: {rel.as_posix()}')
    if any(x in path.name.lower() for x in ('secret', 'credential', 'password', 'private')) or path.name.lower().endswith(('.local.json','.private.json')):
        raise PublicationBlocked(f'Nom sensible sous source autorisée: {rel.as_posix()}')
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        raise PublicationBlocked(f'Extension sensible sous source autorisée: {rel.as_posix()}')
    return True


def build_code_tar(root: Path, output: Path) -> dict:
    root = root.resolve(strict=True)
    summary = audit_checkout(root)
    selected = []
    for base_name in sorted(ALLOWED_TOP_DIRECTORIES):
        base = root/base_name
        if not base.exists():
            continue
        if base.is_symlink():
            raise PublicationBlocked(f'Dossier source symbolique interdit: {base_name}')
        for item in base.rglob('*'):
            if item.is_symlink():
                raise PublicationBlocked(f'Lien symbolique interdit: {item.relative_to(root)}')
            if item.is_file() and _include_file(root,item):
                selected.append(item)
    selected.extend(root/name for name in sorted(ALLOWED_ROOT_FILES))
    if not all(x.is_file() for x in selected):
        raise PublicationBlocked('Fichier racine requis manquant dans allowlist')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output,'w:gz') as tf:
        for item in sorted(selected,key=lambda f:f.relative_to(root).as_posix()):
            tf.add(item,arcname=item.relative_to(root).as_posix(),recursive=False)
    return {**summary,'included_files':len(selected),'archive_sha256':digest_file(output)}


def assert_no_unqualified_content(pack_file: str | None, lenses_dir: str | None) -> None:
    if pack_file or lenses_dir:
        raise PublicationBlocked('Import de données/Lens bloqué: aucun vérificateur C1/C2/C3 fiable raccordé. Rien ne sera empaqueté.')


def assert_live_deploy_permitted() -> None:
    raise PublicationBlocked('Déploiement public désactivé dans 0.2.0-alpha.2: autorisation C1/C2/C3 et staging/rollback VPS non qualifiés. Aucun SSH/Docker/Traefik exécuté.')
