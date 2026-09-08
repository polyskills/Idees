"""
Historique des consolidations du client sélectionné : rapports source
conservés, classeur de synthèse généré, indicateurs et anomalies relevées.

Séparé de l'historique des conversions comptables — même mécanisme de
stockage et de purge (core.history_store, plafond appliqué type par type),
mais deux vues distinctes : les deux traitements n'ont ni le même format de
sortie ni la même finalité.
"""
from __future__ import annotations

import os

import streamlit as st

from core.history_store import MAX_HISTORIQUE_CONVERSIONS, TYPE_CONSOLIDATION, list_history
from core.ui_common import select_client

client_id = select_client()

st.title("🕓 Historique des consolidations")
st.caption(
    f"Les {MAX_HISTORIQUE_CONVERSIONS} consolidations les plus récentes sont conservées ici avec leurs "
    "rapports source et le classeur de synthèse produit."
)

if client_id is None:
    st.stop()

entries = list_history(client_id, TYPE_CONSOLIDATION)

if not entries:
    st.info(
        "Aucune consolidation enregistrée pour ce client pour l'instant — "
        "elles apparaissent ici dès la première lancée depuis la page **Consolidation**."
    )
    st.stop()

sites = sorted({e.get("point_de_vente", "") for e in entries})
c1, c2 = st.columns([2, 2])
filtre_site = c1.multiselect("Filtrer par site", options=sites, default=sites)
filtre_statut = c2.multiselect(
    "Filtrer par statut", options=["OK", "AVERTISSEMENT", "ERREUR"], default=["OK", "AVERTISSEMENT", "ERREUR"]
)
filtered = [e for e in entries if e.get("point_de_vente") in filtre_site and e.get("statut") in filtre_statut]

st.divider()
st.subheader(f"Consolidations ({len(filtered)}/{len(entries)})")

# Même resserrement de la liste que sur l'historique des conversions (cf.
# pages/historique.py) : sur plusieurs dizaines d'entrées repliées, les 16px
# d'espacement par défaut de Streamlit deviennent vite beaucoup.
st.markdown(
    """
    <style>
    .st-key-liste_consolidations {
        gap: 0.35rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

statut_icone = {"OK": "✅", "AVERTISSEMENT": "⚠️", "ERREUR": "❌"}

with st.container(key="liste_consolidations"):
    for e in filtered:
        titre = (
            f"{statut_icone.get(e.get('statut'), '•')} {e['horodatage']} — {e.get('point_de_vente', '—')} — "
            f"{e.get('periode') or '—'} ({e.get('nb_tickets', 0)} tickets)"
        )
        with st.expander(titre):
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("CA TTC", f"{e.get('ca_ttc', 0):,.2f} €".replace(",", " "))
            m2.metric("CA HT", f"{e.get('ca_ht', 0):,.2f} €".replace(",", " "))
            m3.metric("Couverts", f"{e.get('couverts', 0):,}".replace(",", " "))
            ecart = e.get("ecart_controle", 0)
            m4.metric(
                "Contrôle transactions / tickets",
                "Équilibré ✅" if abs(ecart) <= 0.01 else f"Écart {ecart:+.2f} €",
                delta_color="off",
            )

            # La ligne de contrôle d'équilibre est toujours présente dans les
            # anomalies : elle est déjà affichée en indicateur ci-dessus, on ne
            # la répète pas ici.
            a_verifier = [a for a in e.get("anomalies", []) if not str(a[0]).startswith("Écart total transactions")]
            for anomalie in a_verifier:
                libelle, valeur, detail = (list(anomalie) + ["", ""])[:3]
                st.warning(f"**{libelle}** — {valeur}\n\n{detail}")
            if not a_verifier:
                st.success("Aucun point à vérifier relevé sur cette consolidation.")

            gen_path = e.get("fichier_genere_chemin")
            if gen_path and os.path.exists(gen_path):
                with open(gen_path, "rb") as f:
                    st.download_button(
                        "⬇️ Classeur de synthèse (.xlsx)",
                        data=f.read(),
                        file_name=os.path.basename(gen_path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"conso_gen_{e['id']}",
                        type="primary",
                    )

            st.caption("Rapports source conservés :")
            chemins = e.get("fichiers_sources_chemins") or [e.get("fichier_source_chemin")]
            colonnes = st.columns(max(len(chemins), 1))
            for i, chemin in enumerate(chemins):
                if chemin and os.path.exists(chemin):
                    with open(chemin, "rb") as f:
                        colonnes[i].download_button(
                            f"⬇️ {os.path.basename(chemin).split('__source__')[-1]}",
                            data=f.read(),
                            file_name=os.path.basename(chemin).split("__source__")[-1],
                            key=f"conso_src_{e['id']}_{i}",
                        )
