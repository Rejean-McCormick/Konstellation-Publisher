# Validation prévue : Publisher 0.2.0-alpha.1

- Refus strict des anciens Konstellation 0.5 et des lockfiles incohérents.
- Tarball source construit par allowlist; aucun rapport, secret, dump ou lien symbolique ne peut entrer dans le paquet.
- Pack et lenses externes bloqués sans chaîne d'autorisation.
- Dockerfile utilise `npm ci`; Compose choisit `public` et son healthcheck interroge la readiness.
- Vérification SHA-256 des deux archives reçues **avant** toute action distante.
- Le lancement distant refuse volontairement toutes les opérations, même avec un manifest valide.

Non testés : compilation Docker réelle, réseau, SSH, TLS, Traefik, Windows GUI, charge, coupure électrique, restauration après panne. Pas de qualification de publication réelle.
