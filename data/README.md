Ce dossier est créé et peuplé automatiquement par l'application au runtime :

```
data/clients/index.json                              liste des clients
data/clients/<client_id>/mappings.json                référentiel du client
data/clients/<client_id>/history/index.jsonl          journal des conversions comptables
data/clients/<client_id>/history/files/               fichiers source + générés archivés
data/clients/<client_id>/consolidations/index.jsonl   journal des consolidations de CA
data/clients/<client_id>/consolidations/files/        rapports source + classeurs archivés
```

Conversion comptable et consolidation ont chacune leur journal et leur dossier
de fichiers : deux natures de données distinctes, aucun stockage partagé, donc
aucune possibilité que la purge ou la relecture de l'une touche aux données de
l'autre.

`data/clients/` est volontairement exclu du dépôt git (`.gitignore`) : il
contient des données comptables/financières de clients réels et ne doit
jamais être versionné. Sur un serveur dédié, prévoir un disque persistant
(et une politique de sauvegarde) pointant vers ce dossier.
