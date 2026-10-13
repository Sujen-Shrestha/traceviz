from traceviz.core.sessions.state import TraceState
from traceviz.core.sessions.summary import summarize


def session_message(session_id: int, state: TraceState) -> dict:
    return {"type": "state", "id": session_id, **state.to_dict(), "summary": summarize(state).to_dict()}
