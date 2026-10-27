# Rapport de validation — Konstellation Publisher 0.2.0-alpha.2

Date : 27 octobre 2026.

## Changements réalisés

- Remplacement de l'ancien script distant (contenant du code opérationnel mort) par un précontrôle v2.1 strict **sans méthode de déploiement**.
- Ajout d'une orchestration transactionnelle à base de journal fsync + remplacement atomique du journal, garde d'écrivain, conservation des journaux terminaux.
- Ajout de la préparation du candidat, readiness avant bascule, intention durable de bascule, vérification après bascule et rollback au moindre échec.
- Si un rollback échoue, l'état `RECOVERY_REQUIRED` empêche toute nouvelle publication simulée tant que la restauration n'a pas été vérifiée.
- Interface GUI : bouton **Simulation rollback (locale)**, sans SSH/Docker/Traefik.
- Manifeste du paquet v2.1 : empreintes SHA-256 obligatoires pour les deux archives, Dockerfile, Compose, deployer et transaction script. Les paquets v2 sont refusés : pas de mise à niveau implicite.
- Les contrôles C1/C2/C3 sont toujours manquants ; le déploiement réel reste **interdit**.

## Tests réellement exécutés dans ce conteneur

- `python -m unittest discover -s tests -v` : **21 tests sur 21 réussis**.
- `python -m compileall -q ...` : compilation syntaxique OK.
- `python Konstellation_Publisher.pyw --self-test` : `SELF_TEST_OK`.
- Préparation réelle d'un ZIP local sur **fixture synthétique** → extraction → vérification du manifeste, des deux archives et des fichiers runtime : OK.
- Défaillances injectées avant/après bascule, readiness refusée, rollback échoué, recovery relancé, lock concurrent, immutabilité des historiques : OK.

## Ce que les tests ne prouvent PAS

- Aucun lancement de conteneur Docker réel, aucun serveur de préproduction, SSH/SCP, DNS/TLS public, Traefik partagé ou bascule VPS.
- Aucun émetteur de preuve C1/C2/C3 réellement configuré ni autorisation signée vérifiée.
- Aucun test Windows GUI interactif ni coupure d'alimentation physique.
- Le backend inclus est **uniquement** un simulateur de route JSON temporaire. Le noyau transactionnel sera réutilisable pour un adaptateur réel, mais il n'existe pas encore de restauration Docker/Traefik qualifiée.

## Critères pour l'étape suivante

- Définir les contrats de reçus et les clés publiques confiées à l'émetteur adéquat ; refuser les approbations non vérifiables.
- Implémenter l'adaptateur de staging réel uniquement derrière cette porte de contrôle.
- Tester sur VPS de staging, restaurer l'ancienne release après chaque erreur injectée.
- Qualifier l'absence de régression des services Konnaxion qui partagent Traefik.
