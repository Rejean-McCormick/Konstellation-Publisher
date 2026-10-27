#!/usr/bin/env python3
"""Remote verifier. Public deployment deliberately sealed (Publisher alpha.2).

Every path from a received bundle is checked BEFORE operations. This file
contains no operational Docker/Traefik rollout route; no argument or environment
variable can enable public publication until a separately reviewed release.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile


class BundleRejected(RuntimeError):
    pass


def _digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _file(bundle: Path, rel: str, expected: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
        raise BundleRejected(f"Empreinte non valide: {rel}")
    path = bundle / rel
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(bundle.resolve()):
        raise BundleRejected(f"Fichier requis absent ou dangereux: {rel}")
    if _digest_file(path) != expected:
        raise BundleRejected(f"Empreinte non conforme: {rel}")
    return path


def _archive(path: Path, *, empty_content: bool) -> None:
    if path.stat().st_size > 500 * 1024 * 1024:
        raise BundleRejected(f"Archive trop volumineuse: {path.name}")
    seen: set[str] = set()
    count = 0
    total_size = 0
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                count += 1
                if count > 15000:
                    raise BundleRejected("Trop d'entrées dans le paquet")
                normalized = PurePosixPath(member.name)
                raw_parts = member.name.rstrip("/").split("/")
                if (normalized.is_absolute() or not member.name or "\\" in member.name
                    or any(x in ("..", ".", "") for x in raw_parts)
                    or normalized.as_posix() != member.name.rstrip("/")
                    or not (member.isfile() or member.isdir())):
                    raise BundleRejected(f"Entrée archive interdite: {member.name}")
                if member.name in seen:
                    raise BundleRejected(f"Entrée archive dupliquée: {member.name}")
                seen.add(member.name)
                if empty_content and member.isfile():
                    raise BundleRejected("Contenu de publication non autorisé dans content.tar.gz")
                total_size += member.size
                if total_size > 500 * 1024 * 1024:
                    raise BundleRejected("Archive décompressée trop volumineuse")
                if member.size > 50 * 1024 * 1024:
                    raise BundleRejected("Un fichier archivé dépasse la limite")
    except (OSError, tarfile.TarError) as exc:
        raise BundleRejected(f"Archive illisible: {path.name}") from exc


def verify_bundle(bundle_dir: Path, expected_release_id: str) -> dict:
    if not isinstance(expected_release_id, str) or not re.fullmatch(r"[0-9]{8}-[0-9]{6}", expected_release_id):
        raise BundleRejected("Identifiant release invalide")
    bundle = Path(bundle_dir)
    if bundle.is_symlink() or not bundle.is_dir():
        raise BundleRejected("Répertoire paquet invalide")
    mpath = bundle / "manifest.json"
    if not mpath.is_file() or mpath.is_symlink():
        raise BundleRejected("Manifest manquant")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    if manifest.get("schema") != "konstellation-publisher/v2.1" or manifest.get("release_id") != expected_release_id:
        raise BundleRejected("Manifeste schema/release incompatible")
    if manifest.get("deployment_profile") != "public":
        raise BundleRejected("Profil public doit être explicite")
    if manifest.get("pack_included") is not False or manifest.get("lenses_included") is not False:
        raise BundleRejected("Contenu non qualifié interdit")
    if manifest.get("content_authorization") != "NOT_VERIFIED":
        raise BundleRejected("Statut d'autorisation non crédible; aucun émetteur fiable configuré")
    code = _file(bundle, "code.tar.gz", manifest.get("code_sha256"))
    content = _file(bundle, "content.tar.gz", manifest.get("content_sha256"))
    hashes = manifest.get("runtime_sha256")
    if not isinstance(hashes, dict) or set(hashes) != {"Dockerfile", "docker-compose.yml"}:
        raise BundleRejected("Empreintes des fichiers runtime absentes")
    for name in sorted(hashes):
        _file(bundle, "runtime/"+name, hashes[name])
    _file(bundle, "deploy_remote.py", manifest.get("deployer_sha256"))
    _file(bundle, "publisher_transaction.py", manifest.get("transaction_sha256"))
    _archive(code, empty_content=False)
    _archive(content, empty_content=True)
    return manifest


def main() -> int:
    payload = json.load(sys.stdin)
    verify_bundle(Path(payload["bundle_dir"]), payload["release_id"])
    raise BundleRejected(
        "PUBLISH_BLOCKED: C1/C2/C3 authorization, Docker/Traefik staging and live rollback are not independently qualified"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("KONSTELLATION_PUBLISH_RESULT=ERROR", file=sys.stderr, flush=True)
        print(f"ERROR={exc}", file=sys.stderr, flush=True)
        raise SystemExit(3)
