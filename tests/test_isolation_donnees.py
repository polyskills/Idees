"""
Garde-fou : vérifie que la suite de tests ne peut pas atteindre les données
réelles de l'application (cf. tests/conftest.py).

Ces tests ne portent pas sur une fonctionnalité mais sur la sécurité du
dispositif de test lui-même. S'ils échouent, ne PAS les contourner : c'est le
signe qu'un lancement de pytest depuis une installation en service détruirait
des référentiels et des historiques clients.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import app_config, client_store
from core.client_store import client_history_files_dir, create_client
from core.history_store import record_conversion
from core.converter import ConversionResult

RACINE_DEPOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DONNEES_REELLES = os.path.join(RACINE_DEPOT, "data")


def test_aucun_chemin_de_stockage_ne_pointe_sur_les_donnees_reelles():
    for chemin in (client_store.CLIENTS_DIR, client_store.CLIENTS_INDEX, app_config.APP_CONFIG_PATH):
        assert not os.path.abspath(chemin).startswith(DONNEES_REELLES + os.sep), chemin


def test_ecrire_pendant_un_test_ne_touche_pas_au_dossier_reel():
    # Contrôle de bout en bout : on crée réellement un client et on archive une
    # conversion, puis on vérifie que rien n'est apparu dans data/ du dépôt.
    avant = sorted(os.listdir(DONNEES_REELLES)) if os.path.isdir(DONNEES_REELLES) else []

    client = create_client("Client de test isolé")
    record_conversion(
        client["id"],
        ConversionResult(point_de_vente="REST", source_filename="export.xlsx", lignes=[]),
        source_bytes=b"source",
        csv_bytes=b"csv",
        horodatage="2026-09-08 10:00:00",
    )

    assert client_history_files_dir(client["id"]).startswith(client_store.CLIENTS_DIR)
    apres = sorted(os.listdir(DONNEES_REELLES)) if os.path.isdir(DONNEES_REELLES) else []
    assert avant == apres, "des fichiers sont apparus dans le dossier de données réel"
    assert not os.path.isdir(os.path.join(DONNEES_REELLES, "clients", client["id"]))
