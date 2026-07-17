"""Project panel - save and reopen analyses."""

import streamlit as st

from core.project import (
    save_project,
    list_projects,
    load_project,
    apply_project,
)


def project_panel():

    with st.expander("💾 Project", expanded=False):

        # --- Save ---
        name = st.text_input(
            "Project Name",
            placeholder="e.g. Chamarajanagar Survey"
        )

        if st.button("Save Project", use_container_width=True):

            if not name.strip():
                st.error("Enter a project name first.")
            else:
                try:
                    save_project(name, st.session_state)
                    st.success(f"Saved: {name}")
                except Exception as e:
                    st.error(f"Could not save: {e}")

        st.divider()

        # --- Open ---
        projects = list_projects()

        if not projects:
            st.caption("No saved projects yet.")
            return

        selected = st.selectbox("Saved Projects", projects)

        if st.button("Open Project", use_container_width=True):

            try:
                data = load_project(selected)
                apply_project(data, st.session_state)
                st.rerun()
            except Exception as e:
                st.error(f"Could not open: {e}")