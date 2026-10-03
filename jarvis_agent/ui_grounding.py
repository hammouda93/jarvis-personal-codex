from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


SUPPORTED_UI_ROLES = (
    "search_input",
    "message_composer",
    "result_item",
    "navigation_item",
    "send_button",
    "save_button",
    "editable_document",
    "dialog_confirm_button",
    "dialog_cancel_button",
    "tab_item",
    "generic_action",
)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s.+#]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in _normalize(value).split()
        if len(token) >= 2
    }


_ROLE_SPECS: dict[str, dict[str, Any]] = {
    "search_input": {
        "types": {"Edit", "ComboBox", "Document"},
        "writable": True,
        "keywords": (
            "search", "recherche", "rechercher", "chercher", "find",
            "lookup", "query", "بحث", "ابحث",
        ),
        "position": "top",
        "min_score": 0.68,
    },
    "message_composer": {
        "types": {"Edit", "Document", "ComboBox"},
        "writable": True,
        "keywords": (
            "message", "write a message", "type a message", "compose",
            "ecrire un message", "écrire un message", "nouveau message",
            "chat", "اكتب رسالة", "رسالة",
        ),
        "position": "bottom",
        "min_score": 0.68,
    },
    "result_item": {
        "types": {
            "ListItem", "DataItem", "Hyperlink", "Button", "Text",
            "TreeItem",
        },
        "keywords": (),
        "position": "content",
        "min_score": 0.58,
    },
    "navigation_item": {
        "types": {
            "TabItem", "TreeItem", "MenuItem", "Hyperlink", "Button",
            "ListItem",
        },
        "keywords": (
            "home", "accueil", "menu", "navigation", "nav", "section",
            "page", "tab", "onglet",
        ),
        "position": "navigation",
        "min_score": 0.60,
    },
    "send_button": {
        "types": {"Button", "Hyperlink", "MenuItem"},
        "keywords": (
            "send", "envoyer", "envoi", "submit", "ارسال", "إرسال",
        ),
        "position": "",
        "min_score": 0.72,
    },
    "save_button": {
        "types": {"Button", "MenuItem"},
        "keywords": (
            "save", "enregistrer", "sauvegarder", "حفظ",
        ),
        "position": "",
        "min_score": 0.72,
    },
    "editable_document": {
        "types": {"Document", "Edit"},
        "writable": True,
        "keywords": (
            "document", "editor", "editeur", "éditeur", "content",
            "contenu",
        ),
        "position": "content",
        "min_score": 0.50,
    },
    "dialog_confirm_button": {
        "types": {"Button", "MenuItem"},
        "keywords": (
            "ok", "yes", "oui", "confirm", "confirmer", "continue",
            "continuer", "apply", "appliquer", "done", "terminer",
            "نعم", "تأكيد",
        ),
        "position": "",
        "min_score": 0.68,
    },
    "dialog_cancel_button": {
        "types": {"Button", "MenuItem"},
        "keywords": (
            "cancel", "annuler", "close", "fermer", "no", "non",
            "إلغاء", "لا",
        ),
        "position": "",
        "min_score": 0.68,
    },
    "tab_item": {
        "types": {"TabItem"},
        "keywords": (),
        "position": "top",
        "min_score": 0.46,
    },
    "generic_action": {
        "types": {
            "Button", "Hyperlink", "MenuItem", "TabItem", "TreeItem",
            "ListItem", "CheckBox", "RadioButton",
        },
        "keywords": (),
        "position": "",
        "min_score": 0.48,
    },
}


@dataclass(frozen=True)
class GroundedControl:
    ref: str
    role: str
    score: float
    reasons: tuple[str, ...]
    control: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "role": self.role,
            "score": round(float(self.score), 4),
            "reasons": list(self.reasons),
            "control": dict(self.control),
        }


@dataclass(frozen=True)
class GroundingResult:
    role: str
    status: str
    selected: GroundedControl | None
    candidates: tuple[GroundedControl, ...]
    reason: str
    window_title: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "status": self.status,
            "selected": self.selected.as_dict() if self.selected else None,
            "candidates": [item.as_dict() for item in self.candidates],
            "reason": self.reason,
            "window_title": self.window_title,
            "refs_valid_until": "next_ui_inspection",
        }


def _control_text(control: dict[str, Any]) -> str:
    return " ".join(
        str(control.get(key) or "")
        for key in (
            "name", "id", "label", "label_hint", "value", "target",
        )
        if control.get(key)
    )


def _keyword_score(text: str, keywords: tuple[str, ...]) -> tuple[float, list[str]]:
    normalized = _normalize(text)
    if not normalized or not keywords:
        return 0.0, []

    best = 0.0
    reasons: list[str] = []
    text_tokens = _tokens(normalized)
    for keyword in keywords:
        normalized_keyword = _normalize(keyword)
        if not normalized_keyword:
            continue
        if normalized_keyword in normalized:
            score = 0.50
            reason = f"keyword:{normalized_keyword}"
        else:
            keyword_tokens = _tokens(normalized_keyword)
            if not keyword_tokens:
                continue
            overlap = keyword_tokens & text_tokens
            score = 0.34 * (len(overlap) / len(keyword_tokens))
            reason = f"token_overlap:{normalized_keyword}"
        if score > best:
            best = score
            reasons = [reason] if score > 0 else []
    return best, reasons


def _hint_score(text: str, hint: str) -> tuple[float, list[str]]:
    hint_tokens = _tokens(hint)
    if not hint_tokens:
        return 0.0, []
    text_tokens = _tokens(text)
    overlap = hint_tokens & text_tokens
    if not overlap:
        return 0.0, []
    ratio = len(overlap) / max(1, len(hint_tokens))
    return min(0.30, 0.30 * ratio), [
        "mission_hint:" + ",".join(sorted(overlap))[:120]
    ]


def _position_score(
    control: dict[str, Any],
    window: dict[str, Any],
    position: str,
) -> tuple[float, list[str]]:
    if not position:
        return 0.0, []
    bounds = control.get("bounds") or []
    window_bounds = window.get("bounds") or []
    if len(bounds) != 4 or len(window_bounds) != 4:
        return 0.0, []
    wl, wt, wr, wb = [float(value) for value in window_bounds]
    cl, ct, cr, cb = [float(value) for value in bounds]
    width = max(1.0, wr - wl)
    height = max(1.0, wb - wt)
    cx = ((cl + cr) / 2.0 - wl) / width
    cy = ((ct + cb) / 2.0 - wt) / height
    cw = max(0.0, cr - cl) / width

    if position == "top" and cy <= 0.45:
        return 0.10, ["position:top"]
    if position == "bottom" and cy >= 0.58:
        bonus = 0.12 + (0.05 if cw >= 0.25 else 0.0)
        return bonus, ["position:bottom"]
    if position == "navigation" and (cx <= 0.36 or cy <= 0.22):
        return 0.09, ["position:navigation"]
    if position == "content" and 0.10 <= cx <= 0.90 and 0.10 <= cy <= 0.92:
        return 0.06, ["position:content"]
    return 0.0, []


def _score_control(
    control: dict[str, Any],
    role: str,
    spec: dict[str, Any],
    window: dict[str, Any],
    hint: str,
) -> GroundedControl | None:
    ref = str(control.get("ref") or "").strip()
    control_type = str(control.get("type") or "").strip()
    if not ref or control_type not in spec["types"]:
        return None
    if control.get("enabled") is False:
        return None
    if spec.get("writable") is True and control.get("writable") is not True:
        return None

    score = 0.25
    reasons = [f"type:{control_type}"]
    if control.get("writable") is True:
        score += 0.08
        reasons.append("writable")

    text = _control_text(control)
    semantic_score, semantic_reasons = _keyword_score(
        text,
        tuple(spec.get("keywords") or ()),
    )
    score += semantic_score
    reasons.extend(semantic_reasons)

    hint_value, hint_reasons = _hint_score(text, hint)
    score += hint_value
    reasons.extend(hint_reasons)

    position_value, position_reasons = _position_score(
        control,
        window,
        str(spec.get("position") or ""),
    )
    score += position_value
    reasons.extend(position_reasons)

    if role == "editable_document" and control_type == "Document":
        score += 0.18
        reasons.append("document_type")
    elif role == "result_item" and control_type in {
        "ListItem", "DataItem", "Hyperlink", "TreeItem"
    }:
        score += 0.12
        reasons.append("result_like_type")
    elif role == "generic_action":
        score += 0.20
        reasons.append("actionable_type")
    elif role == "tab_item":
        score += 0.20
        reasons.append("tab_type")

    return GroundedControl(
        ref=ref,
        role=role,
        score=min(1.0, score),
        reasons=tuple(reasons),
        control=dict(control),
    )


def ground_role(
    snapshot: dict[str, Any],
    role: str,
    *,
    mission_hint: str = "",
    max_candidates: int = 5,
) -> GroundingResult:
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in _ROLE_SPECS:
        return GroundingResult(
            role=normalized_role,
            status="invalid_role",
            selected=None,
            candidates=(),
            reason="unsupported_semantic_role",
            window_title=str(
                (snapshot.get("window") or {}).get("title") or ""
            ),
        )

    spec = _ROLE_SPECS[normalized_role]
    window = dict(snapshot.get("window") or {})
    controls = list(snapshot.get("controls") or [])
    ranked: list[GroundedControl] = []
    for raw in controls:
        if not isinstance(raw, dict):
            continue
        item = _score_control(
            raw,
            normalized_role,
            spec,
            window,
            mission_hint,
        )
        if item is not None:
            ranked.append(item)
    ranked.sort(
        key=lambda item: (
            -item.score,
            str(item.control.get("name") or "").casefold(),
            item.ref,
        )
    )
    ranked = ranked[: max(1, min(int(max_candidates), 10))]
    window_title = str(window.get("title") or "")
    if not ranked:
        return GroundingResult(
            role=normalized_role,
            status="not_found",
            selected=None,
            candidates=(),
            reason="no_compatible_control",
            window_title=window_title,
        )

    minimum = float(spec.get("min_score") or 0.65)
    top = ranked[0]
    if top.score < minimum:
        return GroundingResult(
            role=normalized_role,
            status="not_found",
            selected=None,
            candidates=tuple(ranked),
            reason="semantic_evidence_below_threshold",
            window_title=window_title,
        )

    if len(ranked) > 1:
        second = ranked[1]
        if second.score >= minimum and top.score - second.score < 0.075:
            return GroundingResult(
                role=normalized_role,
                status="ambiguous",
                selected=None,
                candidates=tuple(ranked),
                reason="multiple_semantically_plausible_controls",
                window_title=window_title,
            )

    return GroundingResult(
        role=normalized_role,
        status="resolved",
        selected=top,
        candidates=tuple(ranked),
        reason="role_grounded_from_current_snapshot",
        window_title=window_title,
    )
