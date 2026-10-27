# Konstellation Publisher 0.2.0-alpha.2 — transaction rehearsal (NO LIVE DEPLOY)

**Complete Publisher code repository, with a local transactional rollback simulator.** The original Konstellation Publisher 0.1.3 path to live Docker / shared Traefik mutation has been **removed from the remote entrypoint**. This release cannot publish remotely. A Python-only simulation does NOT prove the real VPS deployment or C1/C2/C3 authorization.

## Windows — installation and start

1. Back up your Publisher code and separately retain your existing private `konstellation_publisher.config.json`.
2. Extract the files directly into the Publisher code directory (repository root contains `Konstellation_Publisher.pyw`). Do not place files into your corpus directory.
3. Open `Start_Konstellation_Publisher.bat`.
4. Select an existing Konstellation **1.x checkout at a matching commit with `package-lock.json`**.
5. `Vérifier Konstellation` and `Préparer le paquet` work locally. `Simulation rollback (locale)` rehearses a failure after traffic cutover and checks restoration in a **temporary sandbox**.
6. **Publier** remains blocked before SSH/Docker/Traefik. A prepared ZIP does **not** grant permission to deploy it.

The previous local `Konstellation-1.0.0-rc.2-LOT1.zip` lacked `package-lock.json`. That checkout must fail closed. Do **not** copy an unrelated lockfile: use a consistent, qualified version.

## Test commands

```powershell
py -3.12 Konstellation_Publisher.pyw --self-test
py -3.12 -m unittest discover -s tests -v
py -3.12 publisher_transaction.py --simulate
py -3.12 publisher_transaction.py --simulate --fail public
```

Simulated failure points: `stage`, `candidate`, `switch_before`, `switch_after`, `public`, `restore`, and `restore_probe`. `switch_after` represents an exception after the route changed; tests additionally emulate a `KeyboardInterrupt` before the journal records completion. Any ambiguous or unverifiable rollback becomes `RECOVERY_REQUIRED` and blocks further transactions.

## Technical boundaries

- `publisher_bundle.py`: allowlisted local code packaging; returns `konstellation-publisher/v2.1` manifest. The public data archive is empty and publication authorization remains `NOT_VERIFIED`.
- `deploy_remote.py`: validates full SHA-256 of source archive, empty content archive, runtime Dockerfile and Compose template, deployer and transaction script. Rejects unsafe tar entries, duplicate paths and incompatible schema. **No live deployment methods remain.**
- `publisher_transaction.py`: implementation-independent journal/lock, readiness before cutover, durable `CUTOVER_INTENT`, post-cutover validation, rollback and recovery. Its only included backend is `SandboxBackend`, which simulates an atomic routing file in an ephemeral directory. Historic terminal journals are archived before a new transaction.
- `templates/`: public profile explicitly configured; Dockerfile uses `npm ci`; readiness requires `/api/ready`, not merely an open HTTP port.

No SSH credentials, VPS addresses, `.git/`, private reports, old packages, Wikidata dump, content collections or secrets are bundled. Existing data on D: is untouched.

## Still REQUIRED before live publication

1. Independent trustworthy C1 qualification, C2 scoped authorization/revocation and C3 immutable-publication receipts bound to the **exact same** release/data/permissions and issuer trust roots.
2. Actual Docker **candidate deployment** independent of production traffic, image digests, readiness and policy checks.
3. Traefik staging/cutover/restore behind a controlled lock without restarting the shared Konnaxion edge; rollback of previous application image, environment, content and route.
4. Tests with a staging VPS, DNS/TLS, negative failure injection including reboot/power interruption, secret management, and Windows GUI validation.

**Do not use this alpha to replace an operational production deployment tool.** Keep the old version backed up until these gates pass. See `docs/VALIDATION_0_2_ALPHA2_FR.md`.
