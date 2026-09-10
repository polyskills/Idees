"""
Sauvegarde complète des données de l'application, en vue d'une reprise sur une
autre machine.

Tout ce qui fait l'état de l'outil vit sous `data/` et n'est PAS versionné :
le dépôt Git seul ne permet donc pas de remettre l'application en service avec
ses clients. Ce module produit une archive ZIP de cet état, à conserver hors
du serveur.

Contenu :
- `data/clients/`        : liste des clients, référentiels, les deux journaux,
                           fichiers archivés, sas d'appariement — et les
                           identifiants Azure, qui vivent sur la fiche client ;
- `data/app_config.json` : code d'accès, URL de l'application, pied de menu.
                           Sans lui, une restauration rendrait les clients mais
                           une application sans code d'accès ni URL (celle qui
                           construit les liens dans les mails de résultat).

Restent en dehors, volontairement : l'environnement virtuel et le binaire NSSM
(réinstallés), les logs (sans valeur), et les variables d'environnement du
service (`LSPENNYLANE_AZURE_CLIENT_ID/_SECRET`, `LSPENNYLANE_ALERTE_INTERNE`)
qui vivent dans l'unité systemd ou les variables machine Windows, pas dans
l'application — elles sont redéfinies à l'installation.

⚠️ L'archive contient les secrets Azure de TOUS les clients et l'intégralité de
leurs données comptables : à traiter comme une donnée sensible.
"""
from __future__ import annotations

import io
import os
import zipfile

from core import app_config, client_store
from core.timezone import now_local

# Racines dans l'archive : reproduire l'arborescence réelle permet de restaurer
# en dézippant à la racine du dépôt, sans rien déplacer à la main.
PREFIXE_CLIENTS = "data/clients"
PREFIXE_CONFIG = "data/app_config.json"

NOTICE = """SAUVEGARDE DES DONNÉES — Convertisseur LightSpeed / Pennylane
============================================================

Archive créée le {horodatage}.

CONTENU
  data/clients/           tous les clients : référentiels, historiques des
                          conversions et des consolidations, fichiers
                          archivés, identifiants Azure
  data/app_config.json    code d'accès, URL de l'application, pied de menu

RESTAURATION SUR UNE AUTRE MACHINE
  1. Installer l'application normalement (voir deploy/<os>/README.md) :
     clonage du dépôt, service, dépendances.
  2. ARRÊTER le service.
  3. Dézipper cette archive À LA RACINE du dépôt cloné. Le dossier data/ y est
     recréé tel quel.
  4. Redémarrer le service.

  Les chemins enregistrés dans les journaux sont relatifs au dossier de chaque
  client : l'application retrouve les fichiers archivés même si elle n'est pas
  installée au même endroit qu'à l'origine.

  À REDÉFINIR À LA MAIN, car hors de l'application : les variables
  d'environnement du service de relève mail
  (LSPENNYLANE_AZURE_CLIENT_ID, LSPENNYLANE_AZURE_CLIENT_SECRET,
  LSPENNYLANE_ALERTE_INTERNE).

CONFIDENTIALITÉ
  Cette archive contient les secrets Azure de tous les clients et l'intégralité
  de leurs données comptables. À stocker en lieu sûr, hors du serveur.
"""


def construire_archive_donnees() -> tuple[bytes, dict]:
    """Archive ZIP de tout l'état non versionné, et son résumé
    (nombre de clients, de fichiers, taille) pour l'afficher avant
    téléchargement.

    Les chemins sont lus sur les modules (`client_store.CLIENTS_DIR`,
    `app_config.APP_CONFIG_PATH`) et non importés au chargement : c'est ce qui
    permet aux tests de les rediriger vers un dossier temporaire."""
    racine_clients = client_store.CLIENTS_DIR
    chemin_config = app_config.APP_CONFIG_PATH

    horodatage = now_local().strftime("%Y-%m-%d %H:%M:%S")
    buf = io.BytesIO()
    nb_fichiers = 0

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SAUVEGARDE.txt", NOTICE.format(horodatage=horodatage))

        if os.path.isdir(racine_clients):
            for dossier, _, fichiers in os.walk(racine_clients):
                for nom in sorted(fichiers):
                    chemin = os.path.join(dossier, nom)
                    relatif = os.path.relpath(chemin, racine_clients).replace(os.sep, "/")
                    zf.write(chemin, f"{PREFIXE_CLIENTS}/{relatif}")
                    nb_fichiers += 1

        if os.path.exists(chemin_config):
            zf.write(chemin_config, PREFIXE_CONFIG)
            nb_fichiers += 1

    contenu = buf.getvalue()
    return contenu, {
        "horodatage": horodatage,
        "nb_clients": len(client_store.list_clients()),
        "nb_fichiers": nb_fichiers,
        "taille_octets": len(contenu),
    }


def nom_archive() -> str:
    return f"donnees_ls2pl_{now_local().strftime('%Y%m%d_%H%M%S')}.zip"


def taille_lisible(octets: int) -> str:
    valeur = float(octets)
    for unite in ("o", "Ko", "Mo", "Go"):
        if valeur < 1024 or unite == "Go":
            return f"{valeur:.0f} {unite}" if unite == "o" else f"{valeur:.1f} {unite}"
        valeur /= 1024
    return f"{valeur:.1f} Go"
