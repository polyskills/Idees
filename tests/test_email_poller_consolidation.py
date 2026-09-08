"""
Tests du fetch mail pour la CONSOLIDATION : les deux rapports Lightspeed
(Tickets et Transactions) arrivent dans deux messages distincts, le premier
patiente dans le sas d'appariement (core.consolidation_sas) et la
consolidation se déclenche à l'arrivée du second.

Comme pour la conversion, toute l'orchestration est jouée avec un faux client
Graph : aucun réseau, aucun tenant Azure.
"""
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import pytest

from core import consolidation_sas
from core.client_store import create_client
from core.email_poller import signaler_orphelins, traiter_client
from core.history_store import list_consolidations, list_history
from core.mapping_store import DEFAULT_MAPPINGS, load_mappings, save_mappings
from tests.test_email_poller import FakeGraph
from tests.test_synthese import COLS_TICKETS, COLS_TRANSACTIONS, TICKETS, TRANSACTIONS, _classeur

ADRESSE_CONSO = "conso-bar@client.example.com"


def _client_avec_consolidation(site="BAR", code_pdv="REST") -> dict:
    """Client dont le point de vente porte une adresse dédiée à la
    consolidation et un site — les deux nouvelles colonnes de la Table de
    correspondance."""
    client = create_client("Test Conso Mail")
    mappings = {**DEFAULT_MAPPINGS}
    mappings["points_de_vente"] = [
        {**p,
         "adresse_email_consolidation": ADRESSE_CONSO if p["code"] == code_pdv else "",
         "site_consolidation": site if p["code"] == code_pdv else ""}
        for p in DEFAULT_MAPPINGS["points_de_vente"]
    ]
    save_mappings(client["id"], mappings)
    client["email_tenant_id"] = "tenant-test"
    client["email_mailbox"] = "boite@client.example.com"
    return client


def _fichiers(periode="20260907_20260908"):
    lt = [[i, d, a, an, tot, pre, cv, ty, ann, pr, od]
          for i, d, a, an, tot, pre, cv, ty, ann, pr, od in TICKETS]
    lx = [[i, a, ty, q, fp / q if q else fp, fp, "SKU", it, gr, "TVA", 0.1, pre, tax]
          for i, a, ty, q, fp, it, gr, pre, tax in TRANSACTIONS]
    return (
        (f"cli_bar_tickets_{periode}.xlsx", _classeur(COLS_TICKETS, lt)),
        (f"cli_bar_transactions_{periode}.xlsx", _classeur(COLS_TRANSACTIONS, lx)),
    )


def _message(id_, piece):
    return {"id": id_, "toRecipients": [{"emailAddress": {"address": ADRESSE_CONSO}}], "attachments": [piece]}


def test_premier_rapport_seul_patiente_sans_rien_produire():
    client = _client_avec_consolidation()
    tickets, _ = _fichiers()
    graph = FakeGraph()
    graph.messages.append(_message("m1", tickets))

    assert traiter_client(graph, client) == 1
    assert graph.marked_read == ["m1"]          # le message est traité, pas relu en boucle
    assert graph.sent == []                     # rien à annoncer : ce n'est pas une anomalie
    assert list_consolidations(client["id"]) == []

    attente = consolidation_sas.lister(client["id"])
    assert len(attente) == 1
    assert consolidation_sas.rapport_manquant(attente[0]) == "transactions"


def test_le_second_rapport_declenche_la_consolidation():
    client = _client_avec_consolidation()
    tickets, transactions = _fichiers()
    graph = FakeGraph()

    graph.messages = [_message("m1", tickets)]
    traiter_client(graph, client)
    graph.messages = [_message("m2", transactions)]
    traiter_client(graph, client)

    entrees = list_consolidations(client["id"])
    assert len(entrees) == 1
    assert entrees[0]["statut"] == "AVERTISSEMENT"   # groupe MP CUISINE non mappé
    assert entrees[0]["ca_ttc"] == 180.0

    envoyes = [m for m in graph.sent if m["subject"].startswith("[LS2PL] Consolidation")]
    assert len(envoyes) == 1
    noms_joints = [n for n, _ in envoyes[0]["attachments"]]
    assert any(n.endswith(".xlsx") and n.startswith("synthese_bar_") for n in noms_joints)
    assert len(noms_joints) == 3                      # les deux rapports source + le classeur

    # Le sas est vidé une fois la paire traitée
    assert consolidation_sas.lister(client["id"]) == []
    # Et rien n'est allé polluer l'historique des conversions comptables
    assert list_history(client["id"]) == []


def test_ordre_darrivee_indifferent():
    client = _client_avec_consolidation()
    tickets, transactions = _fichiers()
    graph = FakeGraph()

    graph.messages = [_message("m1", transactions)]   # Transactions en premier
    traiter_client(graph, client)
    assert list_consolidations(client["id"]) == []

    graph.messages = [_message("m2", tickets)]
    traiter_client(graph, client)
    assert len(list_consolidations(client["id"])) == 1


def test_deux_periodes_en_parallele_ne_se_melangent_pas():
    client = _client_avec_consolidation()
    t7, x7 = _fichiers("20260907_20260908")
    t8, x8 = _fichiers("20260908_20260909")
    graph = FakeGraph()

    graph.messages = [_message("m1", t7), _message("m2", t8)]
    traiter_client(graph, client)
    assert len(consolidation_sas.lister(client["id"])) == 2   # deux clés distinctes
    assert list_consolidations(client["id"]) == []

    graph.messages = [_message("m3", x8)]                     # complète la seconde seulement
    traiter_client(graph, client)
    assert len(list_consolidations(client["id"])) == 1
    restant = consolidation_sas.lister(client["id"])
    assert len(restant) == 1 and restant[0]["date_debut"] == "07/09/26"


def test_renvoi_du_meme_rapport_remplace_sans_doublon():
    client = _client_avec_consolidation()
    tickets, _ = _fichiers()
    graph = FakeGraph()
    graph.messages = [_message("m1", tickets), _message("m2", tickets)]
    traiter_client(graph, client)

    attente = consolidation_sas.lister(client["id"])
    assert len(attente) == 1
    assert attente[0]["rapports"]["tickets"]["remplace"] is True


def test_site_non_renseigne_bloque_et_conserve_la_paire():
    # Le site détermine les périodes de service : sans lui, aucun calcul
    # possible. La paire doit rester dans le sas plutôt que d'être perdue.
    client = _client_avec_consolidation(site="")
    tickets, transactions = _fichiers()
    graph = FakeGraph()
    graph.messages = [_message("m1", tickets), _message("m2", transactions)]
    traiter_client(graph, client)

    assert list_consolidations(client["id"]) == []
    assert len(consolidation_sas.lister(client["id"])) == 1
    echecs = [m for m in graph.sent if "Échec de consolidation" in m["subject"]]
    # Sous-chaîne sans apostrophe : le corps du mail est échappé en HTML
    # (html.escape transforme « n'est » en « n&#x27;est »).
    assert echecs and "site de consolidation" in echecs[0]["body_html"]


def test_rapport_non_identifiable_signale_au_lieu_detre_range():
    client = _client_avec_consolidation()
    tickets, _ = _fichiers()
    graph = FakeGraph()
    graph.messages = [_message("m1", ("export_renomme_20260907_20260908.xlsx", tickets[1]))]
    traiter_client(graph, client)

    assert consolidation_sas.lister(client["id"]) == []
    assert any("_tickets_" in m["body_html"] for m in graph.sent)


def test_orphelin_signale_une_seule_fois_apres_le_delai():
    client = _client_avec_consolidation()
    tickets, _ = _fichiers()
    graph = FakeGraph()
    graph.messages = [_message("m1", tickets)]
    traiter_client(graph, client)
    graph.sent.clear()

    # Le dépôt vient d'avoir lieu : rien à signaler avant l'échéance.
    assert signaler_orphelins(graph, "boite@client.example.com", client["id"]) == 0

    # On recule artificiellement l'horodatage de dépôt au-delà du délai.
    etat = consolidation_sas.lister(client["id"])[0]
    ancien = (dt.datetime.now() - dt.timedelta(hours=consolidation_sas.DELAI_ALERTE_HEURES + 1))
    etat["rapports"]["tickets"]["horodatage"] = ancien.strftime("%Y-%m-%d %H:%M:%S")
    consolidation_sas._ecrire_etat(client["id"], etat["cle"], etat)

    assert signaler_orphelins(graph, "boite@client.example.com", client["id"]) == 1
    # Un incident se signale une fois, pas à chaque cycle du service.
    assert signaler_orphelins(graph, "boite@client.example.com", client["id"]) == 0
    # Et le rapport reçu est conservé : un envoi tardif complétera la paire.
    assert len(consolidation_sas.lister(client["id"])) == 1
