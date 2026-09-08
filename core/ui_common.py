"""Éléments d'interface partagés entre les pages : sélecteur de client,
pied de menu, bandeau d'informations techniques, et présentation commune de
la zone de dépôt de fichiers — tout ce qui doit rester identique d'une page à
l'autre pour que l'outil garde une cohérence visuelle."""
from __future__ import annotations

import html

import streamlit as st

from core.app_config import get_footer_sidebar
from core.client_store import create_client, list_clients
from core.timezone import to_local
from core.version_info import get_version_info


def render_infos_techniques(client_id: str | None) -> None:
    """Affiche l'ID technique du client actif, le commit Git réellement en
    cours d'exécution (pour vérifier après un déploiement que c'est bien la
    dernière version poussée qui tourne, plutôt que de le supposer) et le
    bouton de purge du cache. Anciennement dans la barre latérale de chaque
    page ; rassemblé dans un espace dédié de la page Réglages pour désencombrer
    le menu latéral."""
    if client_id is not None:
        st.caption(f"ID technique du client actif : `{client_id}`")

    info = get_version_info()
    if info["hash"]:
        date_str = info["date"]
        local_dt = to_local(info["date"]) if info["date"] else None
        if local_dt is not None:
            date_str = local_dt.strftime("%d/%m/%Y %H:%M") + " (heure de Paris)"
        st.caption(
            f"🔖 Version déployée : `{info['hash']}`"
            + (" *(modifs. non commitées)*" if info["dirty"] else "")
            + f"\n\nBranche `{info['branch']}` · {date_str}\n\n> {info['message']}"
        )
    else:
        st.caption("🔖 Version : information Git indisponible sur cet hébergement.")

    if st.button("🔄 Vider le cache et recharger"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()


def render_client_selector() -> str | None:
    """Rendu unique du sélecteur de client (liste déroulante seule, sans
    intitulé visible), à appeler depuis app.py. Streamlit place le menu de
    navigation à une position fixe de la barre latérale, quel que soit
    l'ordre des appels st.sidebar dans le script (même avant st.navigation()) :
    le faire apparaître au-dessus nécessite donc en plus un réordonnancement
    CSS flex (order) sur les conteneurs de la barre latérale, posé dans
    app.py. Mémorise le choix dans st.session_state['client_id'], relu
    ensuite par select_client(). Ne rend rien si aucun client n'existe encore
    (select_client() affiche alors le formulaire de création rapide)."""
    clients = list_clients()
    if not clients:
        return None

    ids = [c["id"] for c in clients]
    noms = {c["id"]: c["nom"] for c in clients}
    current = st.session_state.get("client_id")
    index = ids.index(current) if current in ids else 0
    with st.sidebar:
        selected = st.selectbox(
            "Client actif",
            options=ids,
            index=index,
            format_func=lambda cid: noms.get(cid, cid),
            key="client_id_selector",
            label_visibility="collapsed",
        )
    st.session_state["client_id"] = selected
    return selected


def select_client() -> str | None:
    """Retourne le client actif choisi via le sélecteur en haut du menu
    latéral (render_client_selector, appelé une fois depuis app.py). Si aucun
    client n'existe encore, affiche ici le formulaire de création rapide.

    ⚠️ Aucune authentification n'est appliquée à ce stade (usage interne,
    équipe restreinte) : tout utilisateur de l'app voit tous les clients.
    """
    clients = list_clients()
    if clients:
        return st.session_state.get("client_id")

    with st.sidebar:
        st.warning("Aucun client paramétré.")
        with st.form("creation_client_rapide"):
            nom = st.text_input("Nom du client")
            if st.form_submit_button("Créer ce client") and nom.strip():
                c = create_client(nom.strip())
                st.session_state["client_id"] = c["id"]
                st.rerun()
        st.caption("Ou rendez-vous sur la page **Clients** pour plus d'options.")
    return None


def render_footer_sidebar() -> None:
    """Pied de page du menu latéral (texte personnalisable page Réglages,
    onglet Informations). Positionné en CSS (position: fixed, cf. app.py)
    plutôt que par simple ordre d'appel : le sélecteur de client remonté
    au-dessus du menu de navigation déplace, avec lui, tout le reste du
    contenu ajouté à la barre latérale (même conteneur Streamlit) — sans
    ce correctif, le pied de page serait entraîné vers le haut lui aussi."""
    texte = get_footer_sidebar()
    if texte:
        with st.sidebar:
            st.markdown(
                f'<div class="ls-pennylane-sidebar-footer">{html.escape(texte)}</div>',
                unsafe_allow_html=True,
            )


def styliser_zone_de_depot() -> None:
    """Agrandit la zone de dépôt de fichiers et traduit ses libellés intégrés.

    Appelée par TOUTES les pages proposant un dépôt de fichiers (Convertisseur,
    Consolidation) : la présentation doit être la même partout, et dupliquer ce
    correctif page par page reviendrait à les laisser diverger au premier
    ajustement.

    Zone de dépôt agrandie de 50% (plus facile à viser) et libellés traduits :
    st.file_uploader ne propose ni paramètre de taille ni de traduction de ses
    textes intégrés ("Upload", "200MB per file..."), ce qui impose un correctif
    CSS (taille) + JS (traduction, rejouée à chaque rendu puisque Streamlit
    reconstruit le DOM à chaque interaction)."""
    st.markdown(
        """
        <style>
        div[data-testid="stFileUploaderDropzone"] {
            min-height: 102px !important; /* 68px d'origine, +50% */
            padding: 24px !important;
        }
        div[data-testid="stFileUploaderDropzone"] span[data-testid="stIconMaterial"] {
            font-size: 1.5em !important;
        }
        div[data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] p {
            font-size: 1.1rem !important;
        }
        div[data-testid="stFileUploaderDropzoneInstructions"] span {
            font-size: 1.05rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.iframe(
        r"""
        <script>
        const traductions = [
            [/^Upload$/, "Parcourir les fichiers"],
            [/^Browse files$/, "Parcourir les fichiers"],
            [/^Drag and drop file(s)? here$/, "Glissez-déposez votre fichier ici"],
            [/^(\d+)MB per file(.*)$/, "$1 Mo par fichier$2"],
        ];

        function traduireNoeud(node) {
            if (node.nodeType === Node.TEXT_NODE) {
                const original = node.textContent;
                const cible = original.trim();
                for (const [motif, remplacement] of traductions) {
                    if (motif.test(cible)) {
                        const nouveau = original.replace(motif, remplacement);
                        if (nouveau !== original) node.textContent = nouveau;
                        return;
                    }
                }
            } else {
                node.childNodes.forEach(traduireNoeud);
            }
        }

        function traduireTout() {
            traduireNoeud(window.parent.document.body);
        }

        new MutationObserver(traduireTout).observe(window.parent.document.body, {
            childList: true, subtree: true, characterData: true,
        });
        traduireTout();
        </script>
        """,
        height=1,
    )
