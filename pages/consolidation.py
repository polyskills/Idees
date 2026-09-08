"""
Consolidation LightSpeed
========================
Croise les deux rapports Lightspeed Back Office — « Tickets » et
« Transactions » — pour produire un classeur de synthèse du CA par période de
service (SYNTHESE, JOUR x PERIODE, ROTATIONS, DUREE PRESENCE, DONNEES,
TICKETS, ANOMALIES).

Indépendante de la conversion comptable : elle ne consulte pas le référentiel
du client et ne produit aucune écriture Pennylane. Les deux traitements
partagent en revanche le même applicatif, le même mécanisme d'archivage et le
même client sélectionné.

L'historique de ces consolidations se consulte depuis « Historique
consolidations », séparé de celui des conversions.
"""
from __future__ import annotations

import streamlit as st

from core.history_store import record_consolidation
from core.lightspeed_synthese import (
    SITES,
    SyntheseError,
    classer_fichiers,
    construire_synthese,
)
from core.timezone import now_local
from core.ui_common import select_client

client_id = select_client()

st.title("📊 Consolidation LightSpeed")
st.caption(
    "Déposez les deux rapports Lightspeed Back Office d'une même période — « Tickets » et "
    "« Transactions » — pour obtenir la synthèse du CA par période de service. Plusieurs jours "
    "peuvent être traités d'un coup en déposant tous les exports : les doublons sont éliminés."
)

if client_id is None:
    st.info("Créez un client (page **Clients**) avant de pouvoir lancer une consolidation.")
    st.stop()

st.subheader("1. Déposer les exports")
uploaded_files = st.file_uploader(
    "Rapports Tickets et Transactions (.xls / .xlsx)",
    type=["xls", "xlsx"],
    accept_multiple_files=True,
    key="conso_uploader",
)

# Même précaution que la page Convertisseur : le résultat conservé en session
# pour survivre aux reruns des widgets devient trompeur dès que le jeu de
# fichiers change. On le purge sur changement de signature plutôt que
# d'attendre un nouveau clic.
signature = tuple(sorted((uf.name, uf.size) for uf in uploaded_files)) if uploaded_files else ()
if st.session_state.get("conso_signature") != signature:
    st.session_state.pop("conso_resultat", None)
    st.session_state["conso_signature"] = signature

if not uploaded_files:
    st.stop()

par_nom = {uf.name: uf for uf in uploaded_files}
noms = list(par_nom)
sugg_tickets, sugg_transactions, inconnus = classer_fichiers(noms)

st.subheader("2. Vérifier la répartition des fichiers")
st.caption(
    "Pré-remplie d'après le nom des fichiers (`..._tickets_...` / `..._transactions_...`). "
    "Corrigez si un export a été renommé."
)
if inconnus:
    st.warning(
        "Fichier(s) non reconnus d'après leur nom, à répartir manuellement : "
        + ", ".join(f"**{n}**" for n in inconnus)
    )

c1, c2 = st.columns(2)
choix_tickets = c1.multiselect("Rapport(s) « Tickets »", options=noms, default=sugg_tickets)
choix_transactions = c2.multiselect("Rapport(s) « Transactions »", options=noms, default=sugg_transactions)

en_double = sorted(set(choix_tickets) & set(choix_transactions))
if en_double:
    st.error(
        "Un même fichier ne peut pas être à la fois Tickets et Transactions : "
        + ", ".join(f"**{n}**" for n in en_double)
    )

site = st.selectbox(
    "Site (détermine les périodes de service)",
    options=list(SITES),
    help="Les plages horaires de chaque période dépendent du site : "
    + " · ".join(f"{s} : {', '.join(p for p, *_ in SITES[s]['periodes'])}" for s in SITES),
)

pret = bool(choix_tickets) and bool(choix_transactions) and not en_double
if not pret and not en_double:
    st.info("Sélectionnez au moins un rapport de chaque type pour lancer la consolidation.")

st.divider()
st.subheader("3. Consolider")

if st.button("🔄 Lancer la consolidation", type="primary", disabled=not pret):
    tickets = [(n, par_nom[n].getvalue()) for n in choix_tickets]
    transactions = [(n, par_nom[n].getvalue()) for n in choix_transactions]
    try:
        res = construire_synthese(tickets, transactions, site)
    except SyntheseError as e:
        st.error(f"❌ {e}")
        st.stop()
    # Archivée immédiatement, avant même d'être téléchargée : l'historique doit
    # garder la trace de ce qui a été produit, pas seulement de ce qui a été
    # récupéré — même logique que pour les conversions.
    record_consolidation(client_id, res, tickets + transactions, now_local().strftime("%Y-%m-%d %H:%M:%S"))
    st.session_state["conso_resultat"] = res

res = st.session_state.get("conso_resultat")
if res is None:
    st.stop()

st.divider()
st.subheader("4. Résultat")
st.caption(f"{res.site} — {res.periode_libelle} · {res.nb_tickets} tickets · {res.nb_lignes} lignes de transaction")

m1, m2, m3, m4 = st.columns(4)
m1.metric("CA TTC", f"{res.ca_ttc:,.2f} €".replace(",", " "))
m2.metric("CA HT", f"{res.ca_ht:,.2f} €".replace(",", " "))
m3.metric("Couverts", f"{res.couverts:,}".replace(",", " "))
m4.metric(
    "Contrôle transactions / tickets",
    "Équilibré ✅" if res.sans_anomalie_bloquante else f"Écart {res.ecart_controle:+.2f} €",
    delta_color="off",
)

if res.sans_anomalie_bloquante:
    st.success(
        "✅ Le total des lignes de transaction correspond exactement au total des tickets : "
        "aucune vente perdue ni comptée deux fois."
    )
else:
    st.error(
        f"❌ Écart de {res.ecart_controle:+.2f} € entre le total des transactions et celui des tickets. "
        "Les deux rapports ne couvrent probablement pas exactement la même période — le classeur est "
        "généré quand même, mais ses totaux ne sont pas fiables en l'état."
    )

a_verifier = res.anomalies_a_verifier
if a_verifier:
    with st.expander(f"⚠️ {len(a_verifier)} point(s) à vérifier", expanded=not res.sans_anomalie_bloquante):
        for libelle, valeur, detail in a_verifier:
            st.warning(f"**{libelle}** — {valeur}\n\n{detail}")
else:
    st.info("Aucun point à vérifier signalé : groupes tous mappés, aucun ticket annulé, périodes cohérentes.")

jour_fname = f"{res.jours[0]:%Y%m%d}" if res.jours else "sansdate"
if len(res.jours) > 1:
    jour_fname += f"_{res.jours[-1]:%Y%m%d}"
st.download_button(
    "⬇️ Télécharger le classeur de synthèse (.xlsx)",
    data=res.classeur,
    file_name=f"synthese_{res.site.lower()}_{jour_fname}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
st.caption(
    "Les onglets de synthèse sont construits en formules `SUMIFS` sur les onglets DONNEES et "
    "TICKETS : le classeur reste recalculable, filtrable et vérifiable dans Excel."
)
