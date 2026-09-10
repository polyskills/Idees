"""Tests de core.history_store : purge au-delà de MAX_HISTORIQUE_CONVERSIONS
et calcul du nombre de jours depuis la dernière conversion réussie."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.client_store import client_consolidation_index_path, client_conversions_index_path, create_client
from core.converter import ConversionResult
from core.history_store import (
    MAX_HISTORIQUE_CONVERSIONS,
    chemin_fichier,
    echecs_apres_derniere_reussite,
    jours_depuis_derniere_conversion_reussie,
    list_consolidations,
    list_history,
    record_consolidation,
    record_conversion,
)
from core.lightspeed_synthese import SyntheseResult
from core.timezone import now_local


def _res(point_de_vente="REST", statut_ok=True) -> ConversionResult:
    return ConversionResult(
        point_de_vente=point_de_vente,
        source_filename="export.xlsx",
        lignes=[{"Date": "10/08/26", "Numéro de pièce": "LS-100826-REST"}],
        ca_ht_source=100.0,
        ca_ht_genere=100.0,
        tva_source=10.0,
        ttc_source=110.0,
        total_debit=110.0,
        total_credit=110.0,
        ecart_calcule=0.0,
        ecart_report_declare=0.0,
        avertissements=[],
        erreurs=[] if statut_ok else ["compte manquant"],
    )


def _record(client_id, n, statut_ok=True):
    for i in range(n):
        record_conversion(
            client_id,
            _res(statut_ok=statut_ok),
            source_bytes=b"source",
            csv_bytes=b"csv",
            horodatage=f"2026-01-{(i % 28) + 1:02d} 10:00:00",
        )


def test_purge_ne_conserve_que_les_dernieres():
    client = create_client("Test Historique")
    _record(client["id"], MAX_HISTORIQUE_CONVERSIONS + 10)

    entries = list_history(client["id"])
    assert len(entries) == MAX_HISTORIQUE_CONVERSIONS


def test_purge_supprime_les_fichiers_des_entrees_purgees():
    client = create_client("Test Historique Fichiers")
    premiere = record_conversion(
        client["id"], _res(), source_bytes=b"source", csv_bytes=b"csv", horodatage="2026-01-01 08:00:00"
    )
    # Le journal ne porte qu'un chemin RELATIF au dossier du client : il faut le
    # résoudre pour toucher le fichier (cf. chemin_fichier).
    chemin_source = chemin_fichier(client["id"], premiere["fichier_source_chemin"])
    chemin_genere = chemin_fichier(client["id"], premiere["fichier_genere_chemin"])
    assert chemin_source and os.path.exists(chemin_source)
    assert chemin_genere and os.path.exists(chemin_genere)

    _record(client["id"], MAX_HISTORIQUE_CONVERSIONS)  # pousse la première hors fenêtre

    assert not os.path.exists(chemin_source)
    assert not os.path.exists(chemin_genere)


def test_jours_depuis_derniere_conversion_reussie_aucune_conversion():
    assert jours_depuis_derniere_conversion_reussie([]) is None


def test_jours_depuis_derniere_conversion_reussie_ignore_les_echecs():
    aujourdhui = now_local().strftime("%Y-%m-%d")
    entries = [
        {"statut": "ERREUR", "horodatage": f"{aujourdhui} 09:00:00"},
        {"statut": "OK", "horodatage": "2026-01-01 09:00:00"},
    ]
    jours = jours_depuis_derniere_conversion_reussie(entries)
    assert jours is not None and jours > 0  # ignore l'échec du jour, retombe sur le succès plus ancien


def test_jours_depuis_derniere_conversion_reussie_aujourdhui():
    aujourdhui = now_local().strftime("%Y-%m-%d")
    entries = [{"statut": "OK", "horodatage": f"{aujourdhui} 09:00:00"}]
    assert jours_depuis_derniere_conversion_reussie(entries) == 0


def test_echecs_apres_derniere_reussite_signale_un_echec_plus_recent():
    # Scénario du bug rapporté : succès à 14:15:35, échec juste après à 14:15:36
    # (même jour) — jours_depuis_derniere_conversion_reussie affiche "aujourd'hui"
    # en vert, ce qui serait trompeur seul : echecs_apres_derniere_reussite doit
    # remonter cet échec plus récent malgré le succès du jour même.
    entries = [
        {"statut": "ERREUR", "horodatage": "2026-08-18 14:15:36", "point_de_vente": "RESTAURANT"},
        {"statut": "OK", "horodatage": "2026-08-18 14:15:35", "point_de_vente": "RESTAURANT"},
    ]
    echecs = echecs_apres_derniere_reussite(entries)
    assert len(echecs) == 1
    assert echecs[0]["horodatage"] == "2026-08-18 14:15:36"


def test_echecs_apres_derniere_reussite_ignore_les_echecs_anterieurs():
    entries = [
        {"statut": "OK", "horodatage": "2026-08-18 14:15:35", "point_de_vente": "RESTAURANT"},
        {"statut": "ERREUR", "horodatage": "2026-08-17 09:00:00", "point_de_vente": "RESTAURANT"},
    ]
    assert echecs_apres_derniere_reussite(entries) == []


def test_echecs_apres_derniere_reussite_sans_aucune_reussite():
    entries = [{"statut": "ERREUR", "horodatage": "2026-08-18 14:15:36", "point_de_vente": "RESTAURANT"}]
    assert len(echecs_apres_derniere_reussite(entries)) == 1


# --- Étanchéité entre conversions et consolidations -----------------------


def _synthese(site="BAR", ecart=0.0, anomalies=None):
    import datetime as dt
    from core.lightspeed_synthese import SyntheseResult
    res = SyntheseResult(site=site, classeur=b"xlsx")
    res.jours = [dt.date(2026, 9, 7)]
    res.nb_tickets, res.nb_lignes = 23, 187
    res.ca_ttc, res.ca_ht, res.couverts = 1949.0, 1696.06, 47
    res.anomalies = [("Écart total transactions - tickets (TTC)", ecart, "0 attendu")] + (anomalies or [])
    return res


def _record_conso(client_id, n, site="BAR"):
    for i in range(n):
        record_consolidation(
            client_id,
            _synthese(site=site),
            sources=[("tickets.xls", b"t"), ("transactions.xls", b"x")],
            horodatage=f"2026-02-{(i % 28) + 1:02d} 10:00:00",
        )


def test_deux_journaux_distincts_sur_le_disque():
    client = create_client("Test Etancheite")
    _record(client["id"], 3)
    _record_conso(client["id"], 2)

    journal_conv = client_conversions_index_path(client["id"])
    journal_conso = client_consolidation_index_path(client["id"])
    assert journal_conv != journal_conso
    assert os.path.exists(journal_conv) and os.path.exists(journal_conso)
    # Aucun des deux fichiers ne contient d'entrée de l'autre nature
    assert "consolidation" not in open(journal_conv, encoding="utf-8").read()
    assert '"type": "conversion"' not in open(journal_conso, encoding="utf-8").read()


def test_chaque_liste_ne_renvoie_que_sa_propre_nature():
    client = create_client("Test Listes")
    _record(client["id"], 3)
    _record_conso(client["id"], 2)

    assert len(list_history(client["id"])) == 3
    assert len(list_consolidations(client["id"])) == 2
    assert all(e["type"] == "conversion" for e in list_history(client["id"]))
    assert all(e["type"] == "consolidation" for e in list_consolidations(client["id"]))


def test_une_serie_de_consolidations_neviction_pas_les_conversions():
    # Le plafond vaut par journal : saturer les consolidations ne doit rien
    # retirer à l'historique comptable, et réciproquement.
    client = create_client("Test Purges Independantes")
    _record(client["id"], 5)
    _record_conso(client["id"], MAX_HISTORIQUE_CONVERSIONS + 10)

    assert len(list_history(client["id"])) == 5
    assert len(list_consolidations(client["id"])) == MAX_HISTORIQUE_CONVERSIONS


def test_les_fichiers_archives_vivent_dans_des_dossiers_separes():
    client = create_client("Test Dossiers")
    conv = record_conversion(client["id"], _res(), source_bytes=b"s", csv_bytes=b"c",
                             horodatage="2026-09-08 10:00:00")
    conso = record_consolidation(client["id"], _synthese(), sources=[("tickets.xls", b"t")],
                                 horodatage="2026-09-08 11:00:00")
    assert conv["fichier_genere_chemin"].startswith("conversions/files/")
    assert conso["fichier_genere_chemin"].startswith("consolidations/files/")


def test_consolidation_archive_tous_ses_rapports_source():
    client = create_client("Test Sources Multiples")
    entree = record_consolidation(
        client["id"],
        _synthese(),
        sources=[("tickets.xls", b"t"), ("transactions.xls", b"x")],
        horodatage="2026-09-08 10:00:00",
    )
    chemins = entree["fichiers_sources_chemins"]
    assert len(chemins) == 2
    assert all(chemin_fichier(client["id"], c) for c in chemins)
    assert chemin_fichier(client["id"], entree["fichier_genere_chemin"])
    # Le champ au singulier reste renseigné : même forme d'entrée que pour une
    # conversion, ce qui garde la mécanique de purge commune aux deux journaux.
    assert entree["fichier_source_chemin"] == chemins[0]


def test_purge_supprime_aussi_les_rapports_source_au_dela_du_premier():
    client = create_client("Test Purge Sources")
    premiere = record_consolidation(
        client["id"], _synthese(), sources=[("tickets.xls", b"t"), ("transactions.xls", b"x")],
        horodatage="2026-01-01 08:00:00",
    )
    _record_conso(client["id"], MAX_HISTORIQUE_CONVERSIONS)  # pousse la première hors fenêtre

    for chemin in premiere["fichiers_sources_chemins"] + [premiere["fichier_genere_chemin"]]:
        assert chemin_fichier(client["id"], chemin) is None, chemin


def test_statut_consolidation_depend_de_lequilibre_et_des_anomalies():
    client = create_client("Test Statuts Conso")
    ok = record_consolidation(client["id"], _synthese(), sources=[("t.xls", b"t")], horodatage="2026-09-08 10:00:00")
    assert ok["statut"] == "OK"

    avert = record_consolidation(
        client["id"], _synthese(anomalies=[("Groupes non mappés (famille AUTRE)", 1, "MP CUISINE")]),
        sources=[("t.xls", b"t")], horodatage="2026-09-08 11:00:00",
    )
    assert avert["statut"] == "AVERTISSEMENT"

    erreur = record_consolidation(
        client["id"], _synthese(ecart=12.5), sources=[("t.xls", b"t")], horodatage="2026-09-08 12:00:00",
    )
    assert erreur["statut"] == "ERREUR"


# --- Portabilité des chemins et migration du dossier ----------------------


def test_les_chemins_du_journal_sont_relatifs_au_dossier_client():
    # C'est ce qui rend une sauvegarde restaurable sur une machine où
    # l'application n'est pas installée au même endroit.
    client = create_client("Test Chemins Relatifs")
    entree = record_conversion(client["id"], _res(), source_bytes=b"s", csv_bytes=b"c",
                               horodatage="2026-09-10 10:00:00")
    for cle in ("fichier_source_chemin", "fichier_genere_chemin"):
        assert not os.path.isabs(entree[cle]), entree[cle]
        assert entree[cle].startswith("conversions/files/")


def test_un_chemin_absolu_herite_est_re_ancre_sur_le_dossier_actuel():
    # Reproduit une sauvegarde restaurée ailleurs : le journal porte encore le
    # chemin absolu de la machine d'origine, le fichier est bien là mais sous
    # une autre racine.
    client = create_client("Test Re Ancrage")
    entree = record_conversion(client["id"], _res(), source_bytes=b"s", csv_bytes=b"c",
                               horodatage="2026-09-10 10:00:00")
    ancien = f"/ancien/serveur/data/clients/{client['id']}/{entree['fichier_genere_chemin']}"
    resolu = chemin_fichier(client["id"], ancien)
    assert resolu is not None and os.path.exists(resolu)


def test_un_chemin_introuvable_ne_renvoie_rien():
    client = create_client("Test Introuvable")
    assert chemin_fichier(client["id"], "conversions/files/inexistant.csv") is None
    assert chemin_fichier(client["id"], None) is None


def test_le_dossier_history_est_migre_vers_conversions():
    # Installation antérieure : les données vivaient dans history/.
    client = create_client("Test Migration")
    record_conversion(client["id"], _res(), source_bytes=b"s", csv_bytes=b"c",
                      horodatage="2026-09-10 10:00:00")
    import shutil
    base = os.path.dirname(client_conversions_index_path(client["id"]))
    ancien = os.path.join(os.path.dirname(base), "history")
    shutil.move(base, ancien)
    assert not os.path.exists(base)

    entrees = list_history(client["id"])          # déclenche la migration
    assert os.path.isdir(base) and not os.path.exists(ancien)
    assert len(entrees) == 1
    # Et le fichier archivé reste atteignable
    assert chemin_fichier(client["id"], entrees[0]["fichier_genere_chemin"])


def test_un_journal_ecrit_avant_le_renommage_reste_lisible():
    # Entrée portant « history/files/... » : le chemin doit être rattrapé.
    client = create_client("Test Ancien Libelle")
    entree = record_conversion(client["id"], _res(), source_bytes=b"s", csv_bytes=b"c",
                               horodatage="2026-09-10 10:00:00")
    ancien_libelle = entree["fichier_genere_chemin"].replace("conversions/", "history/", 1)
    assert chemin_fichier(client["id"], ancien_libelle)
