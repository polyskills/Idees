# Déploiement sur serveur Windows (service, disque persistant)

Cette option héberge l'application en continu sur un serveur Windows
partagé, accessible à toute l'équipe via une URL réseau (`http://<serveur>:8501`).
**Le disque est réellement persistant** : le référentiel et l'historique de
chaque client ne sont jamais perdus au redémarrage.

## Prérequis

- Windows Server (2016+) ou Windows 10/11, avec droits administrateur
- [Python 3.10+](https://www.python.org/downloads/) installé et dans le PATH
  (`winget install Python.Python.3.12`, cocher "Add to PATH" si install manuelle)
- [Git](https://git-scm.com/download/win) installé
- Accès sortant à internet le temps de l'installation (téléchargement des
  dépendances Python et de NSSM)

## Installation (première fois)

Ouvrir **PowerShell en tant qu'administrateur**, puis :

```powershell
# 1. Cloner le dépôt à l'emplacement de votre choix
mkdir C:\Apps\Adaptools -Force  # dossier regroupant les applications Adaptools
cd C:\Apps\Adaptools
git clone https://github.com/polyskills/LS2PL-Converter.git
cd LS2PL-Converter
git checkout adaptools/lightspeed-converter

# 2. Lancer l'installation du service (Python, dépendances, NSSM, service, pare-feu)
.\deploy\windows\install-service.ps1
```

Le script :
1. vérifie Python et crée un environnement virtuel `.venv`
2. installe les dépendances (`requirements.txt`)
3. télécharge NSSM (gestionnaire de service Windows) s'il est absent
4. enregistre l'application comme service Windows (**démarrage automatique
   au boot, redémarrage automatique en cas de plantage**)
5. ouvre le port `8501` dans le pare-feu Windows

À la fin, l'application est accessible :
- en local sur le serveur : `http://localhost:8501`
- depuis le réseau : `http://<nom-ou-IP-du-serveur>:8501`

### Personnaliser le port ou le nom du service

```powershell
.\deploy\windows\install-service.ps1 -Port 8080 -ServiceName "LSPennylaneProd"
```

## Service de fetch automatique des exports LightSpeed par mail (optionnel)

En complément du service applicatif, `install-email-poller-service.ps1`
installe un second service Windows qui va chercher automatiquement les
exports LightSpeed reçus par mail (une boîte dédiée par client, hébergée
dans le tenant M365 **du client**), les convertit avec le même moteur que
l'import manuel, et renvoie le résultat par mail — voir `core/email_poller.py`
pour le détail du fonctionnement.

Prérequis avant installation (voir le pas-à-pas complet, création de
l'app comprise, dans
[`docs/configuration_m365_client.md`](../../docs/configuration_m365_client.md)) :
1. Une **app registration Azure AD** créée directement dans le tenant M365
   du client (single tenant, une par client), avec permission applicative
   `Mail.ReadWrite` + `Mail.Send` sur Microsoft Graph.
2. Le **consentement admin** accordé sur cette app, sur son propre tenant
   (bouton *Grant admin consent*, page API permissions de l'app).
3. Son **ID d'application** et son **secret client** renseignés dans LS2PL,
   page Réglages > Gestion Email (recommandé, un jeu d'identifiants par
   client) — ou, à défaut, en variables d'environnement **machine** (pas
   juste utilisateur, sans quoi le service ne les verrait pas au
   démarrage), utilisées en repli pour tout client sans identifiants
   propres :
   ```powershell
   [Environment]::SetEnvironmentVariable("LSPENNYLANE_AZURE_CLIENT_ID", "<app id>", "Machine")
   [Environment]::SetEnvironmentVariable("LSPENNYLANE_AZURE_CLIENT_SECRET", "<secret>", "Machine")

> **Préférez les saisir dans l'application** — page Réglages > Gestion Email >
> « Réglages du service de relève ». Renseignés là, ils sont emportés par la
> sauvegarde complète des données et suivent l'outil sur une nouvelle machine ;
> définis uniquement dans l'environnement du service, ils sont hors de portée de
> l'application et donc absents de toute sauvegarde. Les variables ci-dessous
> restent lues en repli.
   ```
4. `LSPENNYLANE_ALERTE_INTERNE` (optionnelle, machine) : adresse recevant
   les alertes internes.
   ```powershell
   [Environment]::SetEnvironmentVariable("LSPENNYLANE_ALERTE_INTERNE", "compta@polyskills.fr", "Machine")
   ```
5. Pour chaque client concerné : tenant ID + boîte mail renseignés page
   **Réglages**, et adresse mail dédiée sur chaque point de vente page
   **Table de correspondance**.

⚠️ Les variables d'environnement `LSPENNYLANE_AZURE_CLIENT_ID`/`_SECRET`
restent **globales au serveur**, donc communes à tous les clients qui n'ont
pas leurs propres identifiants renseignés dans Réglages — ce repli ne
fonctionne donc que tant qu'**un seul** client de ce serveur en dépend.
Pour plusieurs clients simultanément, renseigner l'ID/secret **propre à
chacun** dans Réglages > Gestion Email évite complètement cette limite.

Puis, dans le même PowerShell administrateur, après `install-service.ps1` :
```powershell
.\deploy\windows\install-email-poller-service.ps1
```

Ce service ne renvoie **jamais** de fichier au client en cas d'échec de
conversion (mapping manquant, fichier illisible...) — dans ce cas, seule
l'adresse `LSPENNYLANE_ALERTE_INTERNE` est notifiée, avec le détail de
l'erreur, pour correction manuelle du référentiel puis reprise via l'import
manuel habituel.

### Modifier l'intervalle entre deux fetch

Une fois le service installé, l'intervalle (300 secondes par défaut) se
change en modifiant la variable d'environnement **machine**
`LSPENNYLANE_POLL_INTERVAL_SECONDS` puis en redémarrant le service — la
valeur n'est lue qu'au démarrage du process, jamais relue en cours de route :

```powershell
[Environment]::SetEnvironmentVariable("LSPENNYLANE_POLL_INTERVAL_SECONDS", "120", "Machine")
.\deploy\windows\tools\nssm.exe restart LightspeedPennylaneFetchMail
```

(`"Machine"`, pas `"User"` : une variable définie seulement au niveau
utilisateur ne serait pas vue par le service.)

## Mettre à jour l'application

À chaque évolution du code (nouveau commit sur la branche) :

```powershell
cd C:\Apps\Adaptools\LS2PL-Converter
.\deploy\windows\update-service.ps1
```

Ce script arrête le service, récupère la dernière version (`git pull`),
réinstalle les dépendances si besoin, puis redémarre le service. Vérifiez
ensuite que le **hash de version** affiché dans le menu latéral de
l'application correspond bien au dernier commit sur GitHub.

**Alternative sans accès terminal/admin** : page **Réglages → Informations →
Mise à jour de l'application**, un bouton fait la même chose (git pull +
dépendances si besoin) directement depuis le navigateur, puis redémarre
l'app et le service de fetch mail — pratique pour appliquer un correctif
urgent sans passer par quelqu'un ayant un accès serveur. Repose sur le
réglage `AppExit Default Restart` déjà posé par `install-service.ps1` :
l'app s'arrête simplement, NSSM la relance seule.

## Désinstaller

### Retirer les services, garder l'outil installé

**Deux services peuvent coexister** : l'application (`LightspeedPennylane`) et
la moulinette de réception des exports par mail
(`LightspeedPennylaneFetchMail`). Le script n'en retire **qu'un à la fois** :
lancez-le une fois par service, sinon le second continue de tourner.

```powershell
cd C:\Apps\Adaptools\LS2PL-Converter
.\deploy\windows\uninstall-service.ps1
.\deploy\windows\uninstall-service.ps1 -ServiceName LightspeedPennylaneFetchMail -NoFirewall
```

`-NoFirewall` sur la seconde ligne : la moulinette n'ouvre aucun port
entrant, le commutateur évite de refermer celui de l'application si vous ne
retirez QUE la moulinette. La ligne est sans effet si elle n'a jamais été
installée.

Le code, les dépendances (`.venv`) et surtout **les données clients
(`data\clients\`) sont conservés** — seule la couche « service » est retirée.

### Supprimer complètement l'outil de la machine

**L'ordre compte, plus encore qu'ailleurs** : le script de désinstallation a
besoin de `deploy\windows\tools\nssm.exe`, qui vit *dans* le dossier et
n'est pas versionné (téléchargé à l'installation). Supprimer le dossier en
premier rend les services impossibles à retirer normalement — il faut alors
passer par `sc.exe` (voir le rattrapage plus bas).

```powershell
cd C:\Apps\Adaptools\LS2PL-Converter

# 1. Sauvegarder les données comptables — irréversible ensuite
Copy-Item -Recurse data\clients "$env:USERPROFILE\ls2pl-clients-$(Get-Date -Format yyyyMMdd)"

# 2. Retirer les deux services
.\deploy\windows\uninstall-service.ps1
.\deploy\windows\uninstall-service.ps1 -ServiceName LightspeedPennylaneFetchMail -NoFirewall

# 3. Supprimer les identifiants Azure laissés au niveau machine (voir plus bas)
[Environment]::SetEnvironmentVariable("LSPENNYLANE_AZURE_CLIENT_ID", $null, "Machine")
[Environment]::SetEnvironmentVariable("LSPENNYLANE_AZURE_CLIENT_SECRET", $null, "Machine")

# 4. Supprimer le dossier
cd C:\ ; Remove-Item -Recurse -Force C:\Apps\Adaptools\LS2PL-Converter
```

L'étape 3 n'est pas optionnelle : contrairement à Linux et macOS, où les
identifiants vivent dans l'unité systemd / le plist et disparaissent avec le
service, Windows les stocke en **variables d'environnement « Machine »**.
Elles survivent à la désinstallation et à la suppression du dossier — un
secret Azure resterait lisible sur la machine.

### Vérifier qu'il ne reste rien

```powershell
Get-Service Lightspeed*                                          # ne doit rien renvoyer
Get-NetFirewallRule -DisplayName "LightSpeed-Pennylane*"          # ne doit rien renvoyer
[Environment]::GetEnvironmentVariable("LSPENNYLANE_AZURE_CLIENT_SECRET", "Machine")  # doit être vide
```

### Rattrapage : le dossier a été supprimé avant les services

Sans `nssm.exe`, on passe par le gestionnaire de services Windows :

```powershell
sc.exe stop LightspeedPennylane
sc.exe delete LightspeedPennylane
sc.exe stop LightspeedPennylaneFetchMail
sc.exe delete LightspeedPennylaneFetchMail
Remove-NetFirewallRule -DisplayName "LightSpeed-Pennylane (8501)"
```

(Les `stop` échouent sans conséquence si les services sont déjà arrêtés.)

## Administration courante

| Action | Commande |
|---|---|
| Voir le statut du service | `Get-Service LightspeedPennylane` |
| Arrêter | `Stop-Service LightspeedPennylane` |
| Démarrer | `Start-Service LightspeedPennylane` |
| Redémarrer | `Restart-Service LightspeedPennylane` |
| Voir les logs | fichiers dans `LS2PL-Converter\logs\service.out.log` et `service.err.log` |
| Modifier la config du service (avancé) | `.\deploy\windows\tools\nssm.exe edit LightspeedPennylane` (ouvre une interface graphique) |

## Sauvegarde des données

Les données comptables des clients vivent dans `LS2PL-Converter\data\clients\`
(référentiels + historique des conversions, fichiers source et générés).
**Ce dossier n'est pas versionné dans git** (données sensibles) — mettez en
place une sauvegarde régulière de ce dossier (copie planifiée, sauvegarde
Windows Server habituelle, etc.), il n'existe nulle part ailleurs.

Depuis l'application, **Réglages > Sauvegarde > Sauvegarde complète des
données** produit un ZIP de ce dossier *et* de `data/app_config.json`
(code d'accès, URL de l'application), avec sa notice de restauration —
pratique pour une copie ponctuelle avant intervention, sans remplacer une
sauvegarde planifiée.

## Sécuriser l'accès

⚠️ Tel quel, l'application n'a **aucune authentification** : quiconque
accède à l'URL du serveur voit tous les clients. Pour un accès réseau
partagé, envisager au minimum l'un de :
- restreindre l'accès réseau au port `8501` (pare-feu / VLAN / VPN
  interne uniquement, pas d'exposition directe sur internet)
- mettre un reverse proxy (IIS, nginx, Caddy) devant l'application avec
  authentification (Basic Auth, SSO d'entreprise...) et HTTPS
- demander une évolution de l'application pour une authentification
  applicative native (comptes utilisateurs)

## Dépannage

**Le service ne démarre pas** : consulter `LS2PL-Converter\logs\service.err.log`.
Cause fréquente : port déjà utilisé par une autre application (relancer
l'installation avec `-Port` sur un autre port), ou dépendance manquante
(relancer `.\deploy\windows\update-service.ps1`).

**Page inaccessible depuis un autre poste** : vérifier que le pare-feu
Windows du serveur autorise bien le port choisi (`Get-NetFirewallRule
-DisplayName "LightSpeed-Pennylane*"`), et que le réseau/VLAN n'a pas de
restriction supplémentaire en amont (pare-feu réseau, groupe de sécurité
cloud...).

**Python introuvable** : réinstaller Python en cochant "Add python.exe to
PATH", puis ouvrir un nouveau PowerShell avant de relancer le script.
