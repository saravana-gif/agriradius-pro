"""Ask a question about the selected area.

Answers come only from figures already computed for this circle, and
each one names where it came from. It is a shortcut through thirteen
tabs, not an advisor.
"""

import streamlit as st


def ask_body():
    from core import answers

    st.markdown("#### 💬 Ask about this area")
    st.caption(
        "Answers come from the numbers this app has already measured "
        "for the selected circle, and each says which tab it came "
        "from so you can check it. It will not give agronomic advice "
        "and will not invent a figure it has not measured.")

    state = dict(st.session_state)
    tips = answers.suggestions(state)
    if tips:
        st.caption("Measured for this area: "
                   + " · ".join(t.rstrip("?").replace(
                       "What is the ", "") for t in tips))

    q = st.text_input(
        "Your question", key="ask_q",
        placeholder="How much irrigated land is here?")
    if not q:
        return

    res = answers.answer(q, state)
    kind = res.get("kind")
    if kind == "answer":
        st.success(res["text"])
    elif kind == "not_measured":
        st.warning(res["text"])
    else:
        st.info(res["text"])
