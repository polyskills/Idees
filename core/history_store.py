"""
Historisation des conversions, par client, sans base de données : fichiers
horodatés sur disque + un journal append-only au format JSON Lines (une
ligne JSON par conversion), facile à relire, filtrer et auditer.

Conservé pour chaque conversion :
- le fichier source LightSpeed reçu (tel quel)
- le fichier CSV généré pour Pennylane
- les indicateurs de contrôle (CA source/généré, équilibre, écarts)
- la liste des avertissements et erreurs rencontrés
- un statut de synthèse : OK / AVERTISSEMENT / ERREUR

Deux natures de traitement partagent ce journal, distinguées par le champ
"type" : la conversion comptable vers Pennylane (TYPE_CONVERSION) et la
consolidation du CA par période de service (TYPE_CONSOLIDATION). Un seul
mécanisme de stockage, de purge et de relecture pour les deux — mais deux
vues séparées à l'écran, pour ne pas mélanger des résultats qui n'ont ni le
même format de sortie ni la même finalité. Une entrée sans "type" vient
d'une version antérieure à la consolidation : c'est une conversion.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import uuid

from core.client_store import client_history_files_dir, client_history_index_path
from core.converter import ConversionResult

# Nombre maximum de conversions conservées par client (toutes indépendantes
# du point de vente) : au-delà, les plus anciennes sont purgées (journal +
# fichiers source/générés associés) à chaque nouvel enregistrement. Cet outil
# n'a pas vocation à être l'archive de référence sur la durée — les
# conversions plus anciennes restent consultables ailleurs (Pennylane,
# export comptable du client).
MAX_HISTORIQUE_CONVERSIONS = 45

# Nature du traitement archivé. La purge s'applique séparément à chacune :
# une période chargée en consolidations ne doit pas évincer l'historique des
# conversions comptables, et réciproquement.
TYPE_CONVERSION = "conversion"
TYPE_CONSOLIDATION = "consolidation"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "fichier"


def record_conversion(
    client_id: str,
    res: ConversionResult,
    source_bytes: bytes,
    csv_bytes: bytes,
    horodatage: str,
    destinataires_email: list[str] | None = None,
) -> dict:
    """Enregistre une conversion (un fichier source = une entrée) et retourne
    l'entrée de journal écrite. `destinataires_email` : adresse(s) mail ayant
    reçu (ou censées recevoir, en cas d'échec) le résultat — uniquement pour
    les conversions issues du fetch automatique ; vide pour un import manuel
    (page Convertisseur), qui ne notifie personne par mail."""
    files_dir = client_history_files_dir(client_id)
    os.makedirs(files_dir, exist_ok=True)

    conv_id = uuid.uuid4().hex[:12]
    ts_compact = horodatage.replace(":", "").replace("-", "").replace(" ", "_")
    base_name = f"{ts_compact}__{_slug(res.point_de_vente)}__{_slug(res.source_filename)}"

    source_path = os.path.join(files_dir, f"{base_name}__source{os.path.splitext(res.source_filename)[1] or '.dat'}")
    with open(source_path, "wb") as f:
        f.write(source_bytes)

    csv_path = os.path.join(files_dir, f"{base_name}__genere.csv")
    with open(csv_path, "wb") as f:
        f.write(csv_bytes)

    if not res.sans_erreur:
        statut = "ERREUR"
    elif res.avertissements:
        statut = "AVERTISSEMENT"
    else:
        statut = "OK"

    entree = {
        "id": conv_id,
        "type": TYPE_CONVERSION,
        "horodatage": horodatage,
        "point_de_vente": res.point_de_vente,
        "fichier_source_nom": res.source_filename,
        "fichier_source_chemin": source_path,
        "fichier_genere_chemin": csv_path,
        "statut": statut,
        "ca_ht_source": res.ca_ht_source,
        "ca_ht_genere": res.ca_ht_genere,
        "tva_source": res.tva_source,
        "ttc_source": res.ttc_source,
        "total_debit": res.total_debit,
        "total_credit": res.total_credit,
        "ecart_calcule": res.ecart_calcule,
        "ecart_report_declare": res.ecart_report_declare,
        "nb_avertissements": len(res.avertissements),
        "nb_erreurs": len(res.erreurs),
        "avertissements": res.avertissements,
        "erreurs": res.erreurs,
        "date_piece": res.lignes[0]["Date"] if res.lignes else None,
        "numero_piece": res.lignes[0]["Numéro de pièce"] if res.lignes else None,
        "destinataires_email": list(destinataires_email or []),
    }

    _ajouter_au_journal(client_id, entree)
    return entree


def _ajouter_au_journal(client_id: str, entree: dict) -> None:
    index_path = client_history_index_path(client_id)
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")
    _purger_historique(client_id)


def _purger_historique(client_id: str) -> None:
    """Ne conserve que les MAX_HISTORIQUE_CONVERSIONS entrées les plus
    récentes DE CHAQUE TYPE (indépendamment du point de vente) : réécrit le
    journal sans les plus anciennes et supprime leurs fichiers source/générés
    associés, pour ne pas accumuler indéfiniment sur un disque non dimensionné
    pour ça.

    Le plafond s'applique type par type, et non au journal entier : sinon une
    série de consolidations ferait disparaître l'historique des conversions
    comptables, alors que les deux répondent à des besoins différents."""
    entries = list_history(client_id)  # déjà trié par horodatage décroissant
    conservees, a_purger = [], []
    for type_traitement in {_type_de(e) for e in entries}:
        du_type = [e for e in entries if _type_de(e) == type_traitement]
        conservees += du_type[:MAX_HISTORIQUE_CONVERSIONS]
        a_purger += du_type[MAX_HISTORIQUE_CONVERSIONS:]
    if not a_purger:
        return

    for e in a_purger:
        # "fichiers_sources_chemins" (pluriel) n'existe que pour les
        # consolidations, qui partent de plusieurs rapports : sans lui, tous
        # les fichiers source au-delà du premier resteraient sur le disque.
        chemins = [e.get("fichier_source_chemin"), e.get("fichier_genere_chemin")]
        chemins += e.get("fichiers_sources_chemins") or []
        for chemin in chemins:
            if chemin and os.path.exists(chemin):
                os.remove(chemin)

    conservees.sort(key=lambda e: e.get("horodatage", ""), reverse=True)
    index_path = client_history_index_path(client_id)
    with open(index_path, "w", encoding="utf-8") as f:
        # Réécrit du plus ancien au plus récent (ordre naturel d'un journal
        # append-only), même si `conservees` était trié à l'envers pour l'affichage.
        for e in reversed(conservees):
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _type_de(entree: dict) -> str:
    """Une entrée écrite avant l'arrivée de la consolidation n'a pas de champ
    "type" : c'est une conversion. Évite toute migration du journal."""
    return entree.get("type") or TYPE_CONVERSION


def list_history(client_id: str, type_traitement: str | None = None) -> list[dict]:
    """Journal du client, du plus récent au plus ancien. `type_traitement`
    restreint à une nature de traitement (TYPE_CONVERSION /
    TYPE_CONSOLIDATION) — sans lui, tout est renvoyé, ce dont a besoin la
    purge."""
    index_path = client_history_index_path(client_id)
    if not os.path.exists(index_path):
        return []
    entries = []
    with open(index_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # ligne corrompue ignorée plutôt que de faire échouer tout l'historique
    if type_traitement is not None:
        entries = [e for e in entries if _type_de(e) == type_traitement]
    entries.sort(key=lambda e: e.get("horodatage", ""), reverse=True)
    return entries


def record_consolidation(
    client_id: str,
    res,  # core.lightspeed_synthese.SyntheseResult — non typé pour éviter un cycle d'import
    sources: list[tuple[str, bytes]],
    horodatage: str,
) -> dict:
    """Archive une consolidation (cf. core.lightspeed_synthese) dans le même
    journal que les conversions, sous le type TYPE_CONSOLIDATION.

    Deux différences avec une conversion, qui expliquent que ce ne soit pas la
    même fonction : la consolidation part de PLUSIEURS fichiers source (les
    rapports Tickets et Transactions, éventuellement sur plusieurs jours) et
    produit un classeur .xlsx, non un CSV. Le reste — nommage horodaté des
    fichiers, écriture append-only, purge — est strictement partagé."""
    files_dir = client_history_files_dir(client_id)
    os.makedirs(files_dir, exist_ok=True)

    conso_id = uuid.uuid4().hex[:12]
    ts_compact = horodatage.replace(":", "").replace("-", "").replace(" ", "_")
    base_name = f"{ts_compact}__{_slug(res.site)}__consolidation"

    chemins_sources = []
    for nom, contenu in sources:
        chemin = os.path.join(files_dir, f"{base_name}__source__{_slug(nom)}")
        with open(chemin, "wb") as f:
            f.write(contenu)
        chemins_sources.append(chemin)

    genere_path = os.path.join(files_dir, f"{base_name}__genere.xlsx")
    with open(genere_path, "wb") as f:
        f.write(res.classeur)

    # Un écart entre le total des transactions et celui des tickets est le seul
    # cas qui rend le classeur non fiable ; les autres anomalies sont des points
    # à vérifier, signalés sans invalider le résultat.
    if not res.sans_anomalie_bloquante:
        statut = "ERREUR"
    elif res.anomalies_a_verifier:
        statut = "AVERTISSEMENT"
    else:
        statut = "OK"

    entree = {
        "id": conso_id,
        "type": TYPE_CONSOLIDATION,
        "horodatage": horodatage,
        "point_de_vente": res.site,
        "fichier_source_nom": ", ".join(nom for nom, _ in sources),
        # "fichier_source_chemin" (singulier) est repris du format des
        # conversions pour que tout code qui lit le journal sans connaître la
        # consolidation continue de fonctionner ; la liste complète est dans
        # "fichiers_sources_chemins", et c'est elle que la purge nettoie.
        "fichier_source_chemin": chemins_sources[0] if chemins_sources else None,
        "fichiers_sources_chemins": chemins_sources,
        "fichier_genere_chemin": genere_path,
        "statut": statut,
        "periode": res.periode_libelle,
        "nb_tickets": res.nb_tickets,
        "nb_lignes": res.nb_lignes,
        "ca_ttc": res.ca_ttc,
        "ca_ht": res.ca_ht,
        "couverts": res.couverts,
        "ecart_controle": res.ecart_controle,
        "nb_anomalies": len(res.anomalies),
        "anomalies": [[libelle, str(valeur), detail] for libelle, valeur, detail in res.anomalies],
        "destinataires_email": [],
    }

    _ajouter_au_journal(client_id, entree)
    return entree


def jours_depuis_derniere_conversion_reussie(entries: list[dict]) -> int | None:
    """Nombre de jours écoulés depuis la dernière conversion au statut OK
    (succès sans avertissement ni erreur), toutes conversions confondues pour
    ce client. None si aucune conversion réussie n'est présente dans
    l'historique conservé (MAX_HISTORIQUE_CONVERSIONS) — ne veut pas
    forcément dire qu'il n'y en a jamais eu, seulement qu'elle est sortie de
    la fenêtre conservée ici ; les conversions plus anciennes restent
    consultables ailleurs (Pennylane, export comptable du client).

    `entries` est attendu trié par horodatage décroissant (cf. list_history)."""
    from core.timezone import now_local

    for e in entries:
        if e.get("statut") != "OK":
            continue
        try:
            derniere = dt.datetime.strptime(e["horodatage"], "%Y-%m-%d %H:%M:%S").date()
        except (KeyError, ValueError):
            continue
        return (now_local().date() - derniere).days
    return None


def echecs_apres_derniere_reussite(entries: list[dict]) -> list[dict]:
    """Tentatives en échec (statut ERREUR) survenues depuis la dernière
    conversion réussie (ou toutes les tentatives en échec présentes si
    aucune réussite dans l'historique conservé). Complète
    jours_depuis_derniere_conversion_reussie : une conversion réussie
    aujourd'hui ne veut pas dire que TOUT va bien si une tentative plus
    récente encore a échoué entre-temps (plusieurs cycles par jour) — sans ce
    signal séparé, l'alerte "dernière conversion réussie : aujourd'hui"
    donnerait à tort une impression de succès complet.

    `entries` est attendu trié par horodatage décroissant (cf. list_history)."""
    horodatage_derniere_reussite = next(
        (e.get("horodatage", "") for e in entries if e.get("statut") == "OK"), None
    )
    if horodatage_derniere_reussite is None:
        return [e for e in entries if e.get("statut") == "ERREUR"]
    return [
        e for e in entries
        if e.get("statut") == "ERREUR" and e.get("horodatage", "") > horodatage_derniere_reussite
    ]
