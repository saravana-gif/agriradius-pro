"""Sign-in gate.

Identity is the user's @oneroot.farm Google account; authorisation is the
email -> role allowlist in core.permissions. No password is stored here -
Google holds the only password.

Two identity mechanisms, chosen automatically:

  * NATIVE Google sign-in (Streamlit OIDC) - used when an [auth] section
    is present in secrets. This is what works on the .streamlit.app URL:
    the user clicks "Sign in", authenticates with their @oneroot.farm
    Google password, and Streamlit hands us the verified email.

  * LEGACY header / DEV fallback - used when [auth] is NOT configured, so
    nothing breaks before Google sign-in is set up. Reads a Cloudflare
    Access header if the app is fronted by it, else DEV_EMAIL for local
    work.

Secrets (.streamlit/secrets.toml):
    [auth]                     enables native Google sign-in (redirect_uri,
                               cookie_secret, client_id, client_secret,
                               server_metadata_url)
    SSO_ALLOWED_DOMAIN         default "oneroot.farm"; blank = any domain
    OWNER_EMAIL                seeded as owner at startup; default
                               saravana@oneroot.farm
    DEV_EMAIL                  local only; pretend this address signed in
"""

import streamlit as st

from core import permissions

_DEFAULT_DOMAIN = "oneroot.farm"
_DEFAULT_OWNER = "saravana@oneroot.farm"


def _secret(key, default=""):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def _domain():
    return str(_secret("SSO_ALLOWED_DOMAIN", _DEFAULT_DOMAIN)).strip().lower()


def _clean(email):
    return str(email or "").strip().lower()


def _native_configured():
    """True when native Google sign-in is set up (an [auth] section)."""
    try:
        return "auth" in st.secrets
    except Exception:
        return False


# ----------------------------------------------------------------------
# Screens
# ----------------------------------------------------------------------
def _shell(inner):
    st.markdown(
        "<div style='max-width:560px;margin:12vh auto 0;text-align:center'>"
        "<div style='font-size:1.7rem;font-weight:800;color:#0E3D20'>"
        "\U0001F6F0 OneRoot AgriRadius Pro</div>" + inner + "</div>",
        unsafe_allow_html=True,
    )


def _login_screen():
    _shell(
        "<div style='color:#5B6770;margin:12px 0 4px'>Sign in with your "
        "<b>@oneroot.farm</b> Google account to continue.</div>"
        "<div style='color:#8A949B;font-size:.9rem'>This app is for OneRoot "
        "(ENP Farms) members only.</div>")
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        if st.button("\U0001F511 Sign in with Google",
                     use_container_width=True, type="primary"):
            st.login()


def _denied(message, detail="", logout=False):
    _shell(f"<div style='color:#5B6770;margin:12px 0 6px'>{message}</div>"
           f"<div style='color:#8A949B;font-size:.9rem'>{detail}</div>")
    if logout:
        c1, c2, c3 = st.columns([1, 1, 1])
        with c2:
            if st.button("Sign out", use_container_width=True):
                try:
                    st.logout()
                except Exception:
                    st.rerun()


# ----------------------------------------------------------------------
# Identity resolution
# ----------------------------------------------------------------------
def _native_email():
    try:
        if bool(getattr(st.user, "is_logged_in", False)):
            return _clean(getattr(st.user, "email", "") or "")
    except Exception:
        pass
    return ""


def _legacy_email():
    """Cloudflare Access header, else DEV_EMAIL (local only)."""
    email = ""
    try:
        headers = st.context.headers or {}
        email = headers.get("Cf-Access-Authenticated-User-Email", "") or ""
    except Exception:
        email = ""
    if not email:
        email = _secret("DEV_EMAIL", "")
    email = _clean(email)
    dom = _domain()
    if not email or "@" not in email:
        return ""
    if dom and not email.endswith("@" + dom):
        return ""
    return email


# ----------------------------------------------------------------------
# Entry points
# ----------------------------------------------------------------------
def require_login():
    """Return the signed-in user dict, or None (caller should st.stop())."""
    # Seed the owner once per session, not on every rerun (a Sheets hit).
    if not st.session_state.get("_owner_ensured"):
        try:
            permissions.ensure_owner(str(_secret("OWNER_EMAIL", _DEFAULT_OWNER)))
        except Exception:
            pass
        st.session_state["_owner_ensured"] = True

    if _native_configured():
        return _require_native()
    return _require_legacy()


def _authorise(email):
    """Shared: domain check + allowlist lookup. Returns user dict or None."""
    dom = _domain()
    if dom and not email.endswith("@" + dom):
        _denied(
            f"<b>{email}</b> is not an @{dom} account.",
            "This app is only for OneRoot members. Sign in with your "
            "@oneroot.farm Google account.",
            logout=True)
        return None
    user = permissions.get(email)
    if not user:
        _denied(
            f"<b>{email}</b> signed in, but hasn't been given access yet.",
            "Ask an admin to add you in the People &amp; Access panel, "
            "then reload this page.",
            logout=True)
        return None
    st.session_state["user"] = user
    return user


def _require_native():
    email = _native_email()
    if not email:
        _login_screen()
        return None
    return _authorise(email)


def _require_legacy():
    email = _legacy_email()
    if not email:
        _denied(
            "Google sign-in isn't set up yet.",
            "Add an [auth] section to the app secrets to turn on "
            "@oneroot.farm sign-in (see DEPLOY.md).")
        return None
    return _authorise(email)


def is_owner(user=None):
    user = user or st.session_state.get("user") or {}
    return user.get("role") == "owner"


def current_role():
    return (st.session_state.get("user") or {}).get("role", "viewer")


# ----------------------------------------------------------------------
# Admin panel - owners only. Add / remove / change role, live.
# ----------------------------------------------------------------------
def admin_panel():
    if not is_owner():
        return

    me = _clean((st.session_state.get("user") or {}).get("email"))

    with st.sidebar.expander("\U0001F465 People & Access", expanded=False):
        st.caption("Members sign in with their @oneroot.farm Google "
                   "password — nothing is stored here. Add someone by "
                   "email and role; changes apply live.")

        with st.form("add_user", clear_on_submit=True):
            email = st.text_input("Email", placeholder="name@oneroot.farm")
            role = st.selectbox("Role", permissions.ROLES, index=1)
            if st.form_submit_button("Add / update", type="primary",
                                     use_container_width=True):
                try:
                    permissions.upsert(email, role, True)
                    st.success(f"Saved {_clean(email)}")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        st.divider()

        rows = permissions.list_all()
        st.caption(f"{len(rows)} member(s)")
        for r in rows:
            em = r["email"]
            tag = "" if r["active"] else " · disabled"
            st.markdown(f"**{em}**{tag}")
            c1, c2 = st.columns([2, 1])
            with c1:
                idx = (permissions.ROLES.index(r["role"])
                       if r["role"] in permissions.ROLES else 2)
                new_role = st.selectbox(
                    "Role", permissions.ROLES, index=idx,
                    key=f"role_{em}", label_visibility="collapsed")
                if new_role != r["role"]:
                    permissions.upsert(em, new_role, r["active"])
                    st.rerun()
            with c2:
                if em == me:
                    st.caption("you")
                elif st.button("Remove", key=f"rm_{em}",
                               use_container_width=True):
                    permissions.remove(em)
                    st.rerun()


# Backwards-compatible alias (the shared password gate is gone).
def require_password():
    return require_login() is not None
