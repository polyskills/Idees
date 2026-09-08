"""
Isolation des tests vis-à-vis des données réelles.

Les chemins de stockage sont dérivés de l'emplacement du code
(core/client_store.py, core/app_config.py) : `<racine du dépôt>/data/...`.
Or, dans une installation déployée, le service tourne DEPUIS le dépôt cloné
(`WorkingDirectory` = racine du dépôt, cf. deploy/*/install-service.sh) —
`data/` n'y est donc pas un dossier de travail, c'est la production.

La fixture ci-dessous est appliquée automatiquement à TOUS les tests et
redirige ces chemins vers un dossier temporaire propre à chaque test. Un
`pytest` lancé par inadvertance depuis une installation en service ne peut
donc plus toucher aux référentiels clients, aux historiques ni au code
d'accès : ce n'est plus une question d'endroit d'où l'on lance la commande.

Ne jamais revenir à un nettoyage du VRAI dossier (`shutil.rmtree` sur
`CLIENTS_DIR`), qui était le fonctionnement précédent : il effaçait les
données de production sans un message, `ignore_errors=True` masquant jusqu'à
l'échec de la suppression, et la suite passait au vert.

tests/test_isolation_donnees.py vérifie que cette isolation est bien active.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core import app_config, client_store


@pytest.fixture(autouse=True)
def donnees_isolees(tmp_path, monkeypatch):
    """Redirige tout le stockage vers un dossier temporaire, recréé pour
    chaque test — d'où l'état vierge dont chaque test dispose, sans avoir à
    nettoyer quoi que ce soit lui-même.

    monkeypatch fonctionne parce que le code lit ces variables au moment de
    l'appel et non à l'import : `client_dir()` recalcule
    `os.path.join(CLIENTS_DIR, ...)` à chaque fois. Un test qui aurait besoin
    du chemin doit donc le lire de la même façon (`client_store.CLIENTS_DIR`,
    `app_config.APP_CONFIG_PATH`) et jamais via un `from ... import` qui
    figerait la valeur d'origine."""
    racine = tmp_path / "data"
    clients_dir = racine / "clients"
    monkeypatch.setattr(client_store, "CLIENTS_DIR", str(clients_dir))
    monkeypatch.setattr(client_store, "CLIENTS_INDEX", str(clients_dir / "index.json"))
    monkeypatch.setattr(app_config, "APP_CONFIG_PATH", str(racine / "app_config.json"))
    return racine
