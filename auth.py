"""auth.py.

Module d'authentification par mot de passe pour la plateforme inter-SERM.

Principe :
  - Le mot de passe est stocke sous forme de hash SHA-256 dans ``st.secrets``
    (cle ``MOT_DE_PASSE_HASH``).
  - Si la cle est absente ou vide, l'acces est libre (mode developpement).
  - L'etat d'authentification est conserve en ``st.session_state`` pour
    toute la session navigateur.

Configuration (dans .streamlit/secrets.toml) :
    MOT_DE_PASSE_HASH = "e3b0c44..."   # sha256 du mot de passe choisi

Pour generer le hash :
    python -c "import hashlib; print(hashlib.sha256(b'monmotdepasse').hexdigest())"
"""

from __future__ import annotations

import hashlib
import logging

import streamlit as st

LOG = logging.getLogger(__name__)

_CLE_SESSION = "serm_authentifie"
_CLE_ESSAIS = "serm_nb_essais"
_MAX_ESSAIS = 5


def _hash(texte: str) -> str:
    """Hash SHA-256 d'une chaine."""
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _hash_attendu() -> str:
    """Retourne le hash configure dans st.secrets, ou '' si absent."""
    try:
        valeur = st.secrets.get("MOT_DE_PASSE_HASH", "")
        return (valeur or "").strip()
    except Exception:
        return ""


def verifier_authentification() -> bool:
    """Affiche le formulaire de connexion si necessaire.

    Retourne ``True`` si l'utilisateur est authentifie (ou si aucun mot
    de passe n'est configure), ``False`` sinon.

    Appeler cette fonction en tete de ``app.py`` avant tout rendu :

        from auth import verifier_authentification
        if not verifier_authentification():
            st.stop()
    """
    hash_attendu = _hash_attendu()

    # Pas de protection configuree : acces libre.
    if not hash_attendu:
        return True

    # Deja authentifie dans cette session.
    if st.session_state.get(_CLE_SESSION, False):
        return True

    # Trop d'essais infructueux.
    nb_essais = st.session_state.get(_CLE_ESSAIS, 0)
    if nb_essais >= _MAX_ESSAIS:
        st.error(
            f"Trop de tentatives ({_MAX_ESSAIS}). "
            "Veuillez recharger la page pour reessayer."
        )
        return False

    # --- Formulaire de connexion ---
    try:
        from config.territoire_loader import cfg as _cfg
        _cfg_p = _cfg().plateforme
        _nom = _cfg_p.nom
        _institution = _cfg_p.institution
    except Exception:
        _nom = "Plateforme d'analyse"
        _institution = "DREAL"

    col_g, col_c, col_d = st.columns([1, 2, 1])
    with col_c:
        st.markdown(
            f"<div class='login-shell'>"
            f"<p class='login-kicker'>{_institution}</p>"
            f"<h2 class='login-title'>{_nom}</h2>"
            f"<p class='login-lead'>"
            f"Accès réservé aux partenaires autorisés. "
            f"Saisissez le mot de passe pour continuer."
            f"</p>"
            f"</div>",
            unsafe_allow_html=True,
        )
        with st.form("form_connexion", clear_on_submit=True):
            mdp = st.text_input(
                "Mot de passe",
                type="password",
                placeholder="••••••••",
            )
            soumis = st.form_submit_button(
                "Se connecter", use_container_width=True, type="primary"
            )

        if soumis:
            if _hash(mdp) == hash_attendu:
                st.session_state[_CLE_SESSION] = True
                st.session_state[_CLE_ESSAIS] = 0
                LOG.info("Connexion reussie.")
                st.rerun()
            else:
                nb_essais += 1
                st.session_state[_CLE_ESSAIS] = nb_essais
                restants = _MAX_ESSAIS - nb_essais
                if restants > 0:
                    st.error(
                        f"Mot de passe incorrect. "
                        f"({restants} essai(s) restant(s))"
                    )
                else:
                    st.error(
                        "Trop de tentatives. Rechargez la page pour reessayer."
                    )
                LOG.warning("Tentative de connexion echouee (%d/%d).", nb_essais, _MAX_ESSAIS)

    return False


def deconnecter() -> None:
    """Deconnecte l'utilisateur (reinitialise la session)."""
    st.session_state[_CLE_SESSION] = False
    st.session_state[_CLE_ESSAIS] = 0
    st.rerun()
