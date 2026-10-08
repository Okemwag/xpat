import streamlit as st
from floodcat.platform import data
from ui import state
from ui.components import page_header, when

p = state.principal()
page_header('Notifications')
with state.platform().tx() as conn: items = data.list_notifications(conn, p)
if not items: st.info('Nothing yet. You will be told about assignments, referrals, evidence to review and decisions on your proposals.')
if any(not n['read_at'] for n in items) and st.button('Mark all as read'):
    with state.platform().tx() as conn: data.mark_read(conn, p)
    st.rerun()
for n in items:
    with st.container(border=True):
        st.markdown(('🔵 ' if not n['read_at'] else '') + f"**{n['message']}**  \n{when(n['created_at'])} · {n['kind'].replace('_', ' ')}")
