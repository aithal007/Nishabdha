"""Read-only AG-UI event stream for the CopilotKit reviewed-policy assistant.

No account context, tools, client instructions, or shared agent state are trusted.
The endpoint reuses the reviewed extractive answer path; it cannot mutate banking data.
"""

import json
import uuid
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.knowledge.rag import answer_rag

router = APIRouter(prefix="/api/copilot", tags=["policy assistant"])


class PolicyMessage(BaseModel):
    role: Literal["user", "assistant", "system", "developer", "tool"]
    content: str | None = Field(default=None, max_length=4000)


class PolicyRun(BaseModel):
    threadId: str = Field(min_length=1, max_length=128)
    runId: str = Field(min_length=1, max_length=128)
    messages: list[PolicyMessage] = Field(default_factory=list, max_length=40)


def event(kind: str, **payload) -> str:
    return "data: " + json.dumps({"type": kind, **payload}, ensure_ascii=False) + "\n\n"


@router.post("/policy")
async def policy_assistant(run: PolicyRun):
    """Public demo-policy explanations only, matching the public knowledge lookup."""

    async def stream():
        yield event("RUN_STARTED", threadId=run.threadId, runId=run.runId)
        question = next(
            (
                m.content.strip()
                for m in reversed(run.messages)
                if m.role == "user" and m.content and m.content.strip()
            ),
            None,
        )
        if not question:
            text = "Ask about transfer approval, bank-session verification, or support-assistant permissions. I can explain reviewed demo policies; I cannot access accounts or perform banking actions."
        else:
            try:
                result = await answer_rag(question[:1000], auto_research=False)
                text = result["spoken_summary"]
                if result.get("answer"):
                    titles = list(
                        dict.fromkeys(
                            a.get("source_info", "Reviewed demo policy")
                            for a in result["answer"]
                        )
                    )
                    text += "\n\nReviewed source: " + "; ".join(titles)
                text += "\n\nThis assistant provides policy explanations only."
            except Exception:
                yield event(
                    "RUN_ERROR",
                    message="Reviewed policy lookup is temporarily unavailable.",
                    code="POLICY_UNAVAILABLE",
                )
                return
        message_id = str(uuid.uuid4())
        yield event("TEXT_MESSAGE_START", messageId=message_id, role="assistant")
        yield event("TEXT_MESSAGE_CONTENT", messageId=message_id, delta=text)
        yield event("TEXT_MESSAGE_END", messageId=message_id)
        yield event("RUN_FINISHED", threadId=run.threadId, runId=run.runId)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
