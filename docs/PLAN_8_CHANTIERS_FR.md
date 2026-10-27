# Alignement Kristal : 8 chantiers — travail séquentiel

## Convention

- Un seul dépôt est modifié à la fois; aucun commit distant ou migration automatique.
- Les tests sur fixtures ne qualifient pas les corpus, le réseau, les clés, ni les accès réels.
- Une preuve SHA-256 établit l'intégrité des octets, **pas** le droit de publication ou l'autorité sémantique.
- Tous les chantiers doivent conserver le modèle KQ/KP/KA/KS et séparer preuve physique, autorité canonique et surface dérivée.

## 1. Konstellation Publisher (EN COURS)

**Sources :** Publisher 0.1.3, Konstellation 1.0 RC2, contrats du Pack.

**Livraison 0.2 alpha :** prévol et packaging en liste blanche; `npm ci`; Compose public; readiness; vérification SHA-256; fermeture de toute mutation distante.

**À terminer pour 0.3 :** signer ou vérifier de façon indépendante les reçus C1/C2/C3; faire passer les release gates sur Node qualifié; staging Docker; test de rollback par injection de pannes; configuration Traefik sans redémarrage partagé implicite; tests Windows/VPS.

**Acceptation :** aucun paquet non approuvé ne peut être exposé; après tout échec, l'ancien service et le corpus restent accessibles; les ressources partagées ne sont pas perturbées.

## 2. kristal-public

**Sources :** workflow C3 en lecture seule, Framework v10/v11, GitHub host profile.

**Changement :** spécifier les émetteurs de preuves C1, la liste de confiance et les portées/révocations C2, construire des bundles C3 immuables liés à un contenu/version/source déterminés. Conserver le workflow de publication **désactivé** tant que cette chaîne n'est pas qualifiée. Réexaminer l'index de collection.

**Manque :** véritables clés/émetteurs de qualification, administrateurs d'autorisation et environnement de publication. Ne pas créer de signatures factices.

## 3. Konstellation — lecteur v11

**Sources :** Framework draft.4, Integration Pack 0.3, Konstellation 1.0 RC2.

**Changement :** ajouter un lecteur dérivé v11 qui consomme strictement les vues autorisées (KQ/KP/KA/KS + couche lexicale), applique la Reader Policy **avant** la sélection/projection et expose les couvertures `direct/fallback/missing` sans créer de vérités ou identités.

**Acceptation :** tests négatifs de masquage des assertions, séparation des langues, rôle/permission, comparaisons identiques de la vue Pack, tests Node/Playwright et serveur public.

## 4. Skope ↔ Médiathèque

**Sources :** Skope 1.0 RC1, EncyK source-evidence-handoff/2.0.0, Médiathèque 0.5.

**Changement :** fixtures de QIDs, preuve source intégrale, revue humaine, reçu d'import, dédoublonnage, contenu adressé par SHA-256 et audit d'idempotence; rejeter les lots incomplets ou différents sous la même clé.

**Manque :** exemple réel expurgé, autorisation de transfert et validation Windows avec les index existants. Ne pas demander le dump de 120 Go.

## 5. Kompiler — contexte v11

**Sources :** Kompiler 0.8, Framework draft.4, Integration Pack.

**Changement :** adaptateur en lecture seule d'une vue v11 déjà qualifiée; assembler Context Pack sans inventer KQ/KP ni rendre les fallback linguistiques canoniques. Tests déterministes et sources de provenance.

**Acceptation :** test identique pour mêmes entrées, refus des droits manquants, préservation des anciens lecteurs v6–v10.

## 6. Kristal GitHub Bootstrap

**Sources :** snapshot 1.1.1-alpha.1; profil GitHub du Framework.

**Changement :** classifier les opérations hôtes v10 qui restent correctes, ajouter la reconnaissance des références v11 sans réécrire les engagements historiques et comparer les plans `doctor/plan/apply`.

**Manque :** source Git officielle à identifier, droits de staging et confirmation des changements de visibilité.

## 7. SemantiK / Phrase Ops

**Sources :** Phrase Ops 0.4.1, SemantiK Architect, Runtime Orchestrator 1.2.

**Changement :** compiler les PGF GF par langue, valider les preuves de couverture et les artefacts immuables, faire passer les gates de conformité par RuntimeSet et tester activation/rollback. Une langue ne devient pas 'active' parce qu'un dictionnaire existe.

**Manque :** environnements GF réels, corpus de validation et artefacts des langues ciblées.

## 8. Kontainer

**Sources :** Kontainer 1.0rc1, contrats proposés.

**Changement :** audit indépendant de format de conteneur, de la gestion des clés et d'implémentation crypto; tests falsification/corruption/récupération/migration croisée, politiques de révocation et KMS/TPM/WebAuthn uniquement si les implémentations réelles sont disponibles.

**Manque :** audit cryptographique externe et tests d'infrastructure. Aucun label 'production-secure' avant leur conclusion.
