from __future__ import annotations

from enum import Enum


class AssistantState(str, Enum):
    STARTING = "starting"
    CALIBRATING = "calibrating"
    IDLE = "idle"
    ARMED = "armed"
    WAKE = "wake"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    UNDERSTANDING = "understanding"
    THINKING = "thinking"
    PLANNING = "planning"
    ROUTING = "routing"
    ACTING = "acting"
    OBSERVING = "observing"
    VERIFYING = "verifying"
    RESEARCHING = "researching"
    RECOVERING = "recovering"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    SPEAKING = "speaking"
    SUCCESS = "success"
    COMPLETED = "completed"
    FAILED = "failed"
    ERROR = "error"


STATE_LABELS: dict[AssistantState, str] = {
    AssistantState.STARTING: "INITIALISATION",
    AssistantState.CALIBRATING: "CALIBRATION AUDIO",
    AssistantState.IDLE: "EN VEILLE",
    AssistantState.ARMED: "PRÊT",
    AssistantState.WAKE: "RÉVEIL",
    AssistantState.LISTENING: "JE VOUS ÉCOUTE",
    AssistantState.TRANSCRIBING: "TRANSCRIPTION",
    AssistantState.UNDERSTANDING: "COMPRÉHENSION",
    AssistantState.THINKING: "RÉFLEXION",
    AssistantState.PLANNING: "PLANIFICATION",
    AssistantState.ROUTING: "ROUTAGE",
    AssistantState.ACTING: "ACTION EN COURS",
    AssistantState.OBSERVING: "OBSERVATION",
    AssistantState.VERIFYING: "VÉRIFICATION",
    AssistantState.RESEARCHING: "RECHERCHE EN ARRIÈRE-PLAN",
    AssistantState.RECOVERING: "RÉCUPÉRATION",
    AssistantState.WAITING_APPROVAL: "EN ATTENTE DE VALIDATION",
    AssistantState.BLOCKED: "BLOQUÉ",
    AssistantState.SPEAKING: "RÉPONSE",
    AssistantState.SUCCESS: "TERMINÉ",
    AssistantState.COMPLETED: "TERMINÉ",
    AssistantState.FAILED: "ÉCHEC",
    AssistantState.ERROR: "ATTENTION",
}
