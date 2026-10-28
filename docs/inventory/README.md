# Inventaire courant des dépôts kOA

Ce dossier décrit **ce qui figure actuellement dans le périmètre kOA**, sans mélanger l'inventaire avec des archives de relevés, des clones tiers ou des projets personnels.

- [`repositories.json`](repositories.json) — **source de référence machine**, 49 dépôts retenus.
- [`repositories.md`](repositories.md) — vue humaine générée du même périmètre.
- [`GITHUB_DESCRIPTIONS.md`](GITHUB_DESCRIPTIONS.md) — descriptions proposées pour les applications concernées.
- [`apps-skope-ekole.json`](apps-skope-ekole.json) — métadonnées applicatives Skope / Ékole.

## Règle de périmètre

Une entrée est conservée si elle appartient au portefeuille kOA déclaré, dispose d'une identité GitHub et d'un chemin local déclaré, et n'est pas explicitement exclue ou retirée. Les projets hors périmètre, les espaces de textes et d'expérimentation, les clones Wiki/tiers, les chemins introuvables et les relevés historiques ne font pas partie du registre.

Le statut de vérification repris dans chaque ligne décrit **la qualité de la dernière observation disponible** ; il ne certifie pas que le disque ou `origin` sont inchangés aujourd'hui. Une remote locale non vérifiée est signalée telle quelle, pas présentée comme vérifiée.

## Sécurité de synchronisation

L'inventaire est **descriptif, non prescriptif**. Une entrée `scope=PUBLIC` ne vaut ni autorisation GitSink ni preuve que le dépôt est prêt au push. La sélection explicite, le contrôle de la racine Git, la comparaison directe de `origin`, et les contrôles de publication s'appliquent au moment de toute opération.

Pour l'état des intégrations, voir [`../status/current.md`](../status/current.md) et la [carte d'autorité](../2-Technical-Reference/10-system/authority-map.md).
