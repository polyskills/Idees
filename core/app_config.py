"""
Réglages globaux de l'application, communs à tous les clients (à la
différence de core.mapping_store, propre à chacun) : persistés dans
data/app_config.json. Le texte de pied de page du menu latéral, l'URL
publique de l'application (utilisée dans les mails de notification d'échec
du fetch automatique, pour renvoyer vers l'historique), et l'authentification
basique par code d'accès unique (page Réglages > Authentification).

Y vivent aussi les réglages du **service de relève mail** — adresse d'alerte
interne, identifiants Azure de repli, intervalle entre deux cycles. Ils étaient
auparavant portés uniquement par des variables d'environnement posées dans
l'unité systemd du service (ou les variables machine sous Windows), donc hors
de portée de l'application et absents de toute sauvegarde. Les stocker ici les
rend éditables depuis l'interface et les emporte dans la sauvegarde complète.
Les variables d'environnement restent lues en REPLI, pour ne rien casser sur
les installations existantes — même hiérarchie que les identifiants Azure par
client (fiche client d'abord, environnement ensuite).
"""
from __future__ import annotations

import hashlib
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_CONFIG_PATH = os.path.join(BASE_DIR, "data", "app_config.json")

DEFAULT_APP_CONFIG = {
    "footer_sidebar": "© Polyskills - 2026",
    "url_app": "",
    "auth_active": False,
    "auth_mot_de_passe_hash": "",
    # Réglages du service de relève mail (repli sur l'environnement, cf. plus bas)
    "alerte_interne": "",
    "azure_client_id": "",
    "azure_client_secret": "",
    "poll_interval_seconds": 0,      # 0 = non renseigné -> environnement, puis défaut
}

# Variable d'environnement consultée en repli pour chaque réglage de service.
ENV_REGLAGES_SERVICE = {
    "alerte_interne": "LSPENNYLANE_ALERTE_INTERNE",
    "azure_client_id": "LSPENNYLANE_AZURE_CLIENT_ID",
    "azure_client_secret": "LSPENNYLANE_AZURE_CLIENT_SECRET",
    "poll_interval_seconds": "LSPENNYLANE_POLL_INTERVAL_SECONDS",
}

POLL_INTERVAL_DEFAUT = 300


def get_app_config() -> dict:
    if not os.path.exists(APP_CONFIG_PATH):
        return dict(DEFAULT_APP_CONFIG)
    with open(APP_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(DEFAULT_APP_CONFIG)
    merged.update(data)
    return merged


def save_app_config(config: dict) -> None:
    os.makedirs(os.path.dirname(APP_CONFIG_PATH), exist_ok=True)
    with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_footer_sidebar() -> str:
    return get_app_config().get("footer_sidebar") or DEFAULT_APP_CONFIG["footer_sidebar"]


def set_footer_sidebar(texte: str) -> None:
    config = get_app_config()
    config["footer_sidebar"] = texte
    save_app_config(config)


def get_url_app() -> str:
    """URL publique de l'application (ex. https://xxx.streamlit.app), sans
    slash final. Vide si non renseignée : les mails de notification d'échec
    du fetch automatique renvoient alors vers l'app en toutes lettres, sans
    lien cliquable."""
    return (get_app_config().get("url_app") or "").rstrip("/")


def set_url_app(url: str) -> None:
    config = get_app_config()
    config["url_app"] = url.strip().rstrip("/")
    save_app_config(config)


def _hash_mot_de_passe(mot_de_passe: str) -> str:
    """Hash simple (SHA-256, sans salage) : suffisant pour une authentification
    basique par code d'accès unique et partagé (usage interne, équipe
    restreinte, même modèle de confiance que le reste de l'app - cf. secrets
    Azure stockés en clair) - évite seulement qu'une lecture accidentelle de
    data/app_config.json expose le code en clair."""
    return hashlib.sha256(mot_de_passe.encode("utf-8")).hexdigest()


def is_auth_active() -> bool:
    """L'authentification protège l'accès à TOUTE l'application (demandée au
    chargement, avant même la sélection d'un client) - réglage global, un
    seul code partagé par toute l'équipe, pas de compte individuel."""
    return bool(get_app_config().get("auth_active", False))


def has_auth_password() -> bool:
    return bool(get_app_config().get("auth_mot_de_passe_hash"))


def set_auth_active(actif: bool) -> None:
    config = get_app_config()
    config["auth_active"] = bool(actif)
    save_app_config(config)


def set_auth_password(mot_de_passe: str) -> None:
    config = get_app_config()
    config["auth_mot_de_passe_hash"] = _hash_mot_de_passe(mot_de_passe)
    save_app_config(config)


def verifier_mot_de_passe(saisi: str) -> bool:
    hash_stocke = get_app_config().get("auth_mot_de_passe_hash") or ""
    if not hash_stocke:
        return False
    return _hash_mot_de_passe(saisi) == hash_stocke


# --- Réglages du service de relève mail ------------------------------------


def _reglage_service(cle: str) -> str:
    """Valeur enregistrée dans l'application, sinon variable d'environnement.

    Cet ordre est celui des identifiants Azure par client : ce qui est saisi
    dans l'interface prime, l'environnement ne sert que de repli pour les
    installations configurées avant que ces réglages n'existent ici."""
    valeur = str(get_app_config().get(cle) or "").strip()
    if valeur:
        return valeur
    return (os.environ.get(ENV_REGLAGES_SERVICE[cle]) or "").strip()


def get_alerte_interne() -> str:
    """Adresse recevant les alertes internes du service de relève. Vide =
    aucune alerte envoyée."""
    return _reglage_service("alerte_interne")


def get_azure_credentials_globaux() -> tuple[str, str]:
    """Identifiants Azure de repli, utilisés pour les clients qui n'ont pas les
    leurs. Ne conviennent que tant qu'un seul tenant est concerné sur ce
    serveur, puisqu'ils sont partagés."""
    return _reglage_service("azure_client_id"), _reglage_service("azure_client_secret")


def get_poll_interval_seconds() -> int:
    """Secondes entre deux cycles de relève. Relu à chaque itération par
    email_poller.py : une modification depuis l'interface s'applique au cycle
    suivant, sans redémarrage du service."""
    brut = _reglage_service("poll_interval_seconds")
    try:
        valeur = int(brut)
    except (TypeError, ValueError):
        return POLL_INTERVAL_DEFAUT
    return valeur if valeur > 0 else POLL_INTERVAL_DEFAUT


def set_reglages_service(alerte_interne: str, azure_client_id: str,
                         azure_client_secret: str, poll_interval_seconds: int) -> None:
    config = get_app_config()
    config["alerte_interne"] = alerte_interne.strip()
    config["azure_client_id"] = azure_client_id.strip()
    config["azure_client_secret"] = azure_client_secret.strip()
    config["poll_interval_seconds"] = int(poll_interval_seconds or 0)
    save_app_config(config)


def reglages_service_effectifs() -> dict:
    """Ce qui s'applique réellement, et d'où ça vient — pour l'afficher sans
    laisser croire qu'un champ vide dans l'interface signifie « non
    configuré » alors qu'une variable d'environnement prend le relais."""
    config = get_app_config()
    etat = {}
    for cle, variable in ENV_REGLAGES_SERVICE.items():
        dans_app = str(config.get(cle) or "").strip()
        dans_env = (os.environ.get(variable) or "").strip()
        etat[cle] = {
            "valeur": dans_app or dans_env,
            "origine": "application" if dans_app else ("environnement" if dans_env else "aucune"),
            "variable": variable,
        }
    return etat
