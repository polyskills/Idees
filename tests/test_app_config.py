"""Tests de core.app_config : authentification basique par code d'accès unique."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core import app_config
from core.app_config import (
    POLL_INTERVAL_DEFAUT,
    get_alerte_interne,
    get_azure_credentials_globaux,
    get_poll_interval_seconds,
    has_auth_password,
    reglages_service_effectifs,
    set_reglages_service,
    is_auth_active,
    set_auth_active,
    set_auth_password,
    verifier_mot_de_passe,
)


def test_auth_desactivee_et_sans_mot_de_passe_par_defaut():
    assert is_auth_active() is False
    assert has_auth_password() is False


def test_set_auth_password_puis_verification():
    set_auth_password("secret123")
    assert has_auth_password() is True
    assert verifier_mot_de_passe("secret123") is True
    assert verifier_mot_de_passe("mauvais") is False


def test_mot_de_passe_jamais_stocke_en_clair():
    set_auth_password("secret123")
    # Lu via le module, jamais via un `from ... import` : c'est l'attribut
    # du module que la fixture d'isolation redirige (cf. tests/conftest.py).
    with open(app_config.APP_CONFIG_PATH, "r", encoding="utf-8") as f:
        contenu = f.read()
    assert "secret123" not in contenu


def test_verifier_mot_de_passe_sans_mot_de_passe_defini_refuse_tout():
    # Aucun code défini : même une chaîne vide ne doit jamais être acceptée.
    assert verifier_mot_de_passe("") is False
    assert verifier_mot_de_passe("nimporte quoi") is False


def test_activer_puis_desactiver_authentification():
    set_auth_active(True)
    assert is_auth_active() is True
    set_auth_active(False)
    assert is_auth_active() is False


def test_changer_le_mot_de_passe_invalide_l_ancien():
    set_auth_password("ancien")
    set_auth_password("nouveau")
    assert verifier_mot_de_passe("ancien") is False
    assert verifier_mot_de_passe("nouveau") is True


# --- Réglages du service de relève ----------------------------------------
#
# Ils vivaient uniquement dans des variables d'environnement posées à
# l'installation du service : invisibles depuis l'application sur Linux (son
# unité systemd n'en porte aucune) et absents de toute sauvegarde. Ils sont
# désormais portés par l'application, l'environnement servant de repli.


def test_reglages_service_absents_par_defaut():
    assert get_alerte_interne() == ""
    assert get_azure_credentials_globaux() == ("", "")
    assert get_poll_interval_seconds() == POLL_INTERVAL_DEFAUT


def test_reglages_saisis_dans_lapplication():
    set_reglages_service("alerte@polyskills.fr", "app-id", "secret", 600)
    assert get_alerte_interne() == "alerte@polyskills.fr"
    assert get_azure_credentials_globaux() == ("app-id", "secret")
    assert get_poll_interval_seconds() == 600


def test_repli_sur_lenvironnement_quand_le_reglage_est_vide(monkeypatch):
    # Installation configurée avant que ces réglages n'existent dans l'app :
    # rien ne doit changer pour elle.
    monkeypatch.setenv("LSPENNYLANE_ALERTE_INTERNE", "depuis-env@polyskills.fr")
    monkeypatch.setenv("LSPENNYLANE_POLL_INTERVAL_SECONDS", "120")
    assert get_alerte_interne() == "depuis-env@polyskills.fr"
    assert get_poll_interval_seconds() == 120


def test_lapplication_prime_sur_lenvironnement(monkeypatch):
    monkeypatch.setenv("LSPENNYLANE_ALERTE_INTERNE", "depuis-env@polyskills.fr")
    set_reglages_service("saisi@polyskills.fr", "", "", 0)
    assert get_alerte_interne() == "saisi@polyskills.fr"
    # L'intervalle, lui, reste vide côté app : il retombe sur l'environnement
    monkeypatch.setenv("LSPENNYLANE_POLL_INTERVAL_SECONDS", "90")
    assert get_poll_interval_seconds() == 90


def test_intervalle_invalide_retombe_sur_le_defaut(monkeypatch):
    monkeypatch.setenv("LSPENNYLANE_POLL_INTERVAL_SECONDS", "pas un nombre")
    assert get_poll_interval_seconds() == POLL_INTERVAL_DEFAUT


def test_origine_de_chaque_reglage_est_restituee(monkeypatch):
    # L'interface doit pouvoir dire « ce champ est vide ici mais l'environnement
    # prend le relais », sinon un champ vide laisse croire à une absence de
    # configuration — et à une sauvegarde complète alors qu'elle ne l'est pas.
    monkeypatch.setenv("LSPENNYLANE_AZURE_CLIENT_ID", "id-env")
    set_reglages_service("alerte@polyskills.fr", "", "", 0)
    etat = reglages_service_effectifs()
    assert etat["alerte_interne"]["origine"] == "application"
    assert etat["azure_client_id"]["origine"] == "environnement"
    assert etat["azure_client_secret"]["origine"] == "aucune"
    assert etat["azure_client_id"]["variable"] == "LSPENNYLANE_AZURE_CLIENT_ID"
