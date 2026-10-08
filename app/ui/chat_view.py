"""The Xpat assistant as a chat panel (ai/assistant.py). Used on the public home page and, with the loaded results, on Overview."""

import os
import time
import streamlit as st
from floodcat.core.errors import ModelError
from . import state

PUBLIC_SUGGESTIONS = [
    "What does Xpat do?",
    "How do I create an account?",
    "What does 1-in-100 mean?",
    "What can the model not see?",
]
MEMBER_SUGGESTIONS = [
    "What drives the 1-in-100 loss?",
    "How is the technical premium worked out?",
    "Where does the loss concentrate?",
    "How far can I trust these results?",
]
PUBLIC_PER_HOUR = (
    20  # per browser session; the network address has its own limit on the server
)


@st.cache_resource(show_spinner=False)
def knowledge():
    from floodcat.ai.assistant import KnowledgeBase

    return KnowledgeBase.from_files()


def _public_ai_allowed():
    default = "0" if os.getenv("FLOODCAT_ENV") == "production" else "1"
    return (
        state.ai_available()
        and os.getenv("FLOODCAT_ASSISTANT_PUBLIC_AI", default) == "1"
    )


def _visitor_provider():
    """Visitors send only their question (contact details removed) about public documentation, never client data, so
    the faster cloud model is preferred when configured. FLOODCAT_ASSISTANT_PROVIDER (gemini | ollama) overrides it."""
    from floodcat.ai.llm import configured

    chosen = os.getenv("FLOODCAT_ASSISTANT_PROVIDER", "").strip().lower()
    ready = configured()
    if chosen in ready:
        return chosen
    return "gemini" if "gemini" in ready else (ready[0] if ready else None)


def _public_limit_ok(key):
    """Rate limits for signed-out visitors: per session and per network address."""
    stamps = [
        t for t in st.session_state.get(f"{key}_stamps", []) if time.time() - t < 3600
    ]
    if len(stamps) >= PUBLIC_PER_HOUR:
        st.warning(
            "You have asked a lot of questions in the last hour. Please try again later.",
            icon=":material/hourglass_top:",
        )
        return False
    try:
        from datetime import timedelta
        from floodcat.platform import identity

        ip = state.request_info().get("ip") or "unknown"
        with state.platform().tx() as conn:
            identity.rate_limit(
                conn,
                f"assistant-ip:{ip}",
                60,
                timedelta(hours=1),
                "Too many questions from your network; try again later",
            )
    except ModelError as exc:
        st.warning(str(exc), icon=":material/hourglass_top:")
        return False
    st.session_state[f"{key}_stamps"] = stamps + [time.time()]
    return True


def _client_and_facts(report):
    """(llm or None, facts, note). Members use their organisation's AI rules and quota; visitors the server default."""
    p = state.principal()
    if p is None:
        if not _public_ai_allowed():
            return (
                None,
                None,
                "AI is not switched on for visitors here, so answers quote Xpat's documentation directly.",
            )
        try:
            return state.runtime().llm(_visitor_provider()), None, None
        except ModelError:
            return (
                None,
                None,
                "AI is unavailable right now, so answers quote Xpat's documentation directly.",
            )
    facts = None
    if report is not None:
        from floodcat.ai.ask import method_facts

        facts = state.briefing_facts(report) + method_facts(state.config())
    if not state.ai_enabled("extraction"):
        return (
            None,
            facts,
            "AI is off for your organisation or this server, so answers quote Xpat's documentation directly.",
        )
    if not state.ai_quota():
        return (
            None,
            facts,
            "AI request limit reached, so this answer quotes Xpat's documentation directly.",
        )
    try:
        return (
            state.llm(
                client_data=report is not None and state.run_has_client_data(report)
            ),
            facts,
            None,
        )
    except ModelError as exc:
        return None, facts, f"{exc} Answers quote Xpat's documentation directly."


def _show(msg):
    with st.chat_message(
        msg["role"],
        avatar=":material/person:"
        if msg["role"] == "user"
        else ":material/support_agent:",
    ):
        st.markdown(msg["content"])
        meta = msg.get("meta")
        if not meta:
            return
        if meta.get("unsupported"):
            st.caption(
                f":orange[Check these figures; they are not in Xpat's documentation or your results: {', '.join(meta['unsupported'])}]"
            )
        if meta.get("sources"):
            st.caption(
                "Sources: "
                + " · ".join(
                    dict.fromkeys(
                        f"{s['title']}, {s['heading']}" for s in meta["sources"]
                    )
                )
            )
        if meta.get("note"):
            st.caption(meta["note"])


def chat_panel(key="assistant", report=None, height=420):
    """The chat. `report` (signed-in Overview) lets it answer about the loaded results too."""
    messages = st.session_state.setdefault(f"{key}_messages", [])
    signed_in = state.principal() is not None
    box = st.container(height=height, border=True)
    with box:
        if not messages:
            with st.chat_message("assistant", avatar=":material/support_agent:"):
                st.markdown(
                    "Hello. I can explain what Xpat does, how to use it and how the flood model works"
                    + (
                        ", and answer questions about the results you have loaded."
                        if report is not None
                        else "."
                    )
                    + " I answer from Xpat's own documentation and say when I don't know."
                )
        for msg in messages:
            _show(msg)
    picked = None
    if not messages:
        picked = st.pills(
            "Try asking",
            MEMBER_SUGGESTIONS if report is not None else PUBLIC_SUGGESTIONS,
            key=f"{key}_pick",
            label_visibility="collapsed",
        )
    typed = st.chat_input(
        "Ask about Xpat, the model or your results"
        if report is not None
        else "Ask about Xpat",
        key=f"{key}_input",
        submit_mode="disable",
        max_chars=800,
    )
    question = typed or picked
    row = st.container(horizontal=True)
    if messages and row.button(
        "Clear conversation",
        key=f"{key}_clear",
        icon=":material/delete_sweep:",
        type="tertiary",
    ):
        st.session_state[f"{key}_messages"] = []
        st.session_state.pop(f"{key}_pick", None)
        st.rerun()
    if not question:
        return
    if not signed_in and not _public_limit_ok(key):
        return
    from floodcat.ai.assistant import answer

    with box:
        _show({"role": "user", "content": question})
        with st.chat_message("assistant", avatar=":material/support_agent:"):
            with st.status(":shimmer[Looking it up]", type="compact") as status:
                llm, facts, note = _client_and_facts(report)
                try:
                    result = answer(question, knowledge(), llm, messages, facts)
                except ModelError as exc:
                    if llm is None:
                        status.update(label="Could not answer", state="error")
                        st.error(str(exc))
                        return
                    result = answer(
                        question, knowledge(), None, messages, facts
                    )  # model failed: fall back to search
                    note = f"The AI model did not answer ({exc}), so this quotes Xpat's documentation directly."
                status.update(
                    label="Answered" if result["answerable"] else "Not covered",
                    state="complete",
                )
    by = (
        f"Answered by {result['model']} from Xpat's documentation"
        + (" and your results." if facts else ".")
        if result["mode"] == "ai"
        else None
    )
    messages.append({"role": "user", "content": question})
    messages.append(
        {
            "role": "assistant",
            "content": result["answer"],
            "meta": {
                "sources": result["sources"],
                "unsupported": result["unsupported_figures"],
                "note": note or by,
            },
        }
    )
    if signed_in:
        state.audit_ai(
            "ai.assistant_answered",
            "assistant",
            key,
            {
                "mode": result["mode"],
                "model": result["model"],
                "answerable": result["answerable"],
                "sources": len(result["sources"]),
                "unsupported_figures": result["unsupported_figures"],
                "with_results": bool(facts),
            },
        )
    st.rerun()
