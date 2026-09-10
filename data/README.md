Ce dossier est créé et peuplé automatiquement par l'application au runtime :

```
data/clients/index.json                              liste des clients
data/clients/<client_id>/mappings.json                référentiel du client
data/clients/<client_id>/conversions/index.jsonl       journal des conversions comptables
data/clients/<client_id>/conversions/files/           fichiers source + générés archivés
data/clients/<client_id>/consolidations/index.jsonl   journal des consolidations de CA
data/clients/<client_id>/consolidations/files/        rapports source + classeurs archivés
data/clients/<client_id>/consolidations/en_attente/   rapports reçus par mail, en attente de leur binôme
```

Conversion comptable et consolidation ont chacune leur journal et leur dossier
de fichiers : deux natures de données distinctes, aucun stockage partagé, donc
aucune possibilité que la purge ou la relecture de l'une touche aux données de
l'autre.

Les chemins de fichiers enregistrés dans les journaux sont **relatifs au
dossier du client** : l'arborescence peut donc être restaurée sur une machine
où l'application n'est pas installée au même endroit sans perdre l'accès aux
fichiers archivés. Les journaux écrits avant la v1.1 portent des chemins
absolus, rattrapés à la lecture. Le dossier `conversions/` s'appelait
`history/` jusque-là : il est renommé automatiquement au premier accès.

**Pour sauvegarder l'ensemble** : page Réglages > Sauvegarde > « Sauvegarde
complète des données » produit un ZIP de `data/clients/` **et** de
`data/app_config.json` (code d'accès, URL de l'application), avec sa notice de
restauration. C'est ce qu'il faut conserver hors du serveur pour pouvoir
remettre l'outil en service ailleurs.

`data/clients/` est volontairement exclu du dépôt git (`.gitignore`) : il
contient des données comptables/financières de clients réels et ne doit
jamais être versionné. Sur un serveur dédié, prévoir un disque persistant
(et une politique de sauvegarde) pointant vers ce dossier.
