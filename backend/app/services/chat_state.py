"""
Safe chat lifecycle state machine.
"""

from __future__ import annotations

from enum import Enum


class ChatState(str, Enum):
    RECEIVED = "RECEIVED"
    AUTHENTICATED = "AUTHENTICATED"
    SCOPED = "SCOPED"
    RETRIEVED = "RETRIEVED"
    DRAFT_GENERATED = "DRAFT_GENERATED"
    GROUNDING_VALIDATED = "GROUNDING_VALIDATED"
    POLICY_VALIDATED = "POLICY_VALIDATED"
    READY_TO_STREAM = "READY_TO_STREAM"
    STREAMING = "STREAMING"
    COMPLETED = "COMPLETED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"


ALLOWED_TRANSITIONS: dict[ChatState, set[ChatState]] = {
    ChatState.RECEIVED: {ChatState.AUTHENTICATED, ChatState.FAILED},
    ChatState.AUTHENTICATED: {ChatState.SCOPED, ChatState.FAILED},
    ChatState.SCOPED: {ChatState.RETRIEVED, ChatState.FAILED},
    ChatState.RETRIEVED: {ChatState.DRAFT_GENERATED, ChatState.FAILED},
    ChatState.DRAFT_GENERATED: {ChatState.GROUNDING_VALIDATED, ChatState.FAILED},
    ChatState.GROUNDING_VALIDATED: {ChatState.POLICY_VALIDATED, ChatState.FAILED},
    ChatState.POLICY_VALIDATED: {ChatState.READY_TO_STREAM, ChatState.ABSTAINED, ChatState.FAILED},
    ChatState.ABSTAINED: {ChatState.READY_TO_STREAM, ChatState.FAILED},
    ChatState.READY_TO_STREAM: {ChatState.STREAMING, ChatState.COMPLETED, ChatState.FAILED},
    ChatState.STREAMING: {ChatState.COMPLETED, ChatState.FAILED},
    ChatState.COMPLETED: set(),
    ChatState.FAILED: set(),
}


class ChatStateMachine:
    """Tracks safe chat lifecycle transitions without storing prompt or PHI text."""

    def __init__(self) -> None:
        self.current = ChatState.RECEIVED
        self._trace: list[dict[str, str | int]] = [{"index": 0, "state": self.current.value}]

    def transition(self, next_state: ChatState) -> None:
        if next_state not in ALLOWED_TRANSITIONS[self.current]:
            raise RuntimeError(f"Invalid chat state transition: {self.current.value} -> {next_state.value}")
        self.current = next_state
        self._trace.append({"index": len(self._trace), "state": next_state.value})

    def fail(self) -> None:
        if self.current is not ChatState.FAILED and ChatState.FAILED in ALLOWED_TRANSITIONS[self.current]:
            self.transition(ChatState.FAILED)

    @property
    def trace(self) -> list[dict[str, str | int]]:
        return list(self._trace)
