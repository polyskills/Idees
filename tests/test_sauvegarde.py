"""
Tests de core.sauvegarde : archive ZIP de tout l'état non versionné de
l'application, destinée à une reprise sur une autre machine.
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import app_config, client_store
from core.client_store import create_client
from core.converter import ConversionResult
from core.history_store import chemin_fichier, list_history, record_conversion
from core.app_config import set_reglages_service
from core.sauvegarde import construire_archive_donnees, nom_archive, taille_lisible


def _res(pdv="REST") -> ConversionResult:
    return ConversionResult(point_de_vente=pdv, source_filename="export.xlsx", lignes=[])


def _archive() -> tuple[zipfile.ZipFile, dict]:
    contenu, resume = construire_archive_donnees()
    return zipfile.ZipFile(io.BytesIO(contenu)), resume


def test_archive_contient_les_donnees_clients_et_la_config_globale():
    client = create_client("Client Sauvegardé")
    record_conversion(client["id"], _res(), source_bytes=b"source", csv_bytes=b"csv",
                      horodatage="2026-09-10 10:00:00")
    app_config.set_url_app("https://ls2pl.example.com")

    zf, resume = _archive()
    noms = zf.namelist()

    assert "data/app_config.json" in noms
    assert "data/clients/index.json" in noms
    assert f"data/clients/{client['id']}/conversions/index.jsonl" in noms
    assert any(n.startswith(f"data/clients/{client['id']}/conversions/files/") for n in noms)
    assert resume["nb_clients"] == 1
    assert resume["taille_octets"] > 0


def test_archive_porte_une_notice_de_restauration():
    create_client("Client Notice")
    zf, _ = _archive()
    notice = zf.read("SAUVEGARDE.txt").decode("utf-8")
    # Ce que quelqu'un doit retrouver des mois plus tard, sans contexte
    assert "Dézipper cette archive" in notice
    assert "LSPENNYLANE_AZURE_CLIENT_SECRET" in notice   # ce qui n'est PAS dans l'archive
    assert "secrets Azure" in notice                      # l'avertissement de confidentialité


def test_archive_se_dezippe_a_la_racine_du_depot():
    # Les chemins de l'archive reproduisent l'arborescence réelle : restaurer,
    # c'est dézipper à la racine, sans rien déplacer à la main.
    create_client("Client Arborescence")
    zf, _ = _archive()
    for nom in zf.namelist():
        assert nom == "SAUVEGARDE.txt" or nom.startswith("data/"), nom


def test_archive_restauree_ailleurs_retrouve_ses_fichiers(tmp_path, monkeypatch):
    # Cœur de l'objectif : une reprise sur une machine où l'application n'est
    # pas installée au même endroit doit garder l'accès aux fichiers archivés.
    client = create_client("Client Déménagé")
    entree = record_conversion(client["id"], _res(), source_bytes=b"source", csv_bytes=b"csv",
                               horodatage="2026-09-10 10:00:00")
    contenu, _ = construire_archive_donnees()

    # Nouvelle machine : autre racine, application réinstallée ailleurs
    nouvelle_racine = tmp_path / "autre_serveur"
    zipfile.ZipFile(io.BytesIO(contenu)).extractall(nouvelle_racine)
    monkeypatch.setattr(client_store, "CLIENTS_DIR", str(nouvelle_racine / "data" / "clients"))
    monkeypatch.setattr(client_store, "CLIENTS_INDEX",
                        str(nouvelle_racine / "data" / "clients" / "index.json"))

    entrees = list_history(client["id"])
    assert len(entrees) == 1
    resolu = chemin_fichier(client["id"], entrees[0]["fichier_genere_chemin"])
    assert resolu is not None and os.path.exists(resolu)
    assert str(nouvelle_racine) in resolu   # bien lu depuis la nouvelle racine
    assert open(resolu, "rb").read() == b"csv"


def test_archive_sans_aucun_client_reste_valide():
    zf, resume = _archive()
    assert "SAUVEGARDE.txt" in zf.namelist()
    assert resume["nb_clients"] == 0


def test_nom_archive_et_taille_lisible():
    assert nom_archive().startswith("donnees_ls2pl_") and nom_archive().endswith(".zip")
    assert taille_lisible(512) == "512 o"
    assert taille_lisible(2048) == "2.0 Ko"
    assert taille_lisible(5 * 1024 * 1024) == "5.0 Mo"


def test_les_reglages_du_service_sont_dans_larchive():
    # C'était le dernier angle mort d'une reprise sur nouvelle machine : ces
    # réglages vivaient dans l'unité systemd, hors de portée de l'application.
    import json
    create_client("Client Réglages Service")
    set_reglages_service("alerte@polyskills.fr", "app-id", "secret-azure", 600)

    zf, _ = _archive()
    config = json.loads(zf.read("data/app_config.json").decode("utf-8"))
    assert config["alerte_interne"] == "alerte@polyskills.fr"
    assert config["azure_client_id"] == "app-id"
    assert config["azure_client_secret"] == "secret-azure"
    assert config["poll_interval_seconds"] == 600


def test_la_notice_explique_le_cas_des_reglages_restes_dans_lenvironnement():
    create_client("Client Notice Service")
    zf, _ = _archive()
    notice = zf.read("SAUVEGARDE.txt").decode("utf-8")
    assert "Réglages > Gestion Email" in notice
    assert "à redéfinir à la main" in notice
