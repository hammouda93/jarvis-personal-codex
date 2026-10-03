from __future__ import annotations

import copy
import json
import re
from dataclasses import replace

from .mission_semantics import READ_ONLY_TOOLS, SemanticMissionSession
from .native_tools import AgentActionResult


MISSION_CONTROL_TOOLS = frozenset({
    "create_mission_plan", "get_mission_state", "correct_mission_entity",
    "pause_mission", "resume_mission", "list_resumable_missions",
})


def _definition(name, description, properties=None, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": list(required),
            "additionalProperties": False},
    }}


def _definitions():
    criterion = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": ["tool_success", "verified_result"]},
        "field": {"type": "string", "description": "Champ de preuve observée, par ex. value ou observed_state."},
        "equals": {"description": "Valeur exacte attendue, JSON."},
        "equals_entity": {"type": "string", "description": "Entité contenant la valeur exacte attendue."},
    }, "required": ["kind"], "additionalProperties": False}
    return [
        _definition("create_mission_plan", "Crée un plan persistant pour la demande utilisateur réelle. "
            "Planifie les étapes avant les mutations. Une ouverture peut utiliser tool_success, "
            "mais une écriture ou autre mutation exige verified_result. Le plan ne prouve pas "
            "automatiquement la couverture de tout l'objectif.", {
                "entities": {"type": "object", "additionalProperties": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "steps": {"type": "array", "minItems": 1, "maxItems": 20, "items": {
                    "type": "object", "properties": {
                        "id": {"type": "string"}, "description": {"type": "string"},
                        "tool_name": {"type": "string"},
                        "dependencies": {"type": "array", "items": {"type": "string"}},
                        "entity_bindings": {"type": "object", "additionalProperties": {"type": "string"},
                            "description": "Argument outil -> nom d'entité. Ne jamais lier une ref UIA temporaire."},
                        "criterion": criterion,
                    }, "required": ["id", "description", "tool_name", "criterion"], "additionalProperties": False,
                }},
            }, ("steps",)),
        _definition("get_mission_state", "Consulte l'objectif, les entités, les étapes et les critères du plan actif."),
        _definition("correct_mission_entity", "Applique une correction réellement formulée par l'utilisateur "
            "à une entité du plan, sans saisir son nom dans une application. Les preuves dépendantes "
            "sont invalidées; une mutation déjà effectuée exige réobservation.", {
                "name": {"type": "string"}, "value": {"type": "string"},
            }, ("name", "value")),
        _definition("pause_mission", "Met le plan actif en attente quand l'utilisateur veut l'interrompre."),
        _definition("resume_mission", "Restaure un plan sauvegardé, même après redémarrage. "
            "N'exécute aucune action; les mutations interrompues exigent une nouvelle observation.", {
                "mission_id": {"type": "string"},
            }, ("mission_id",)),
        _definition("list_resumable_missions", "Liste au plus 20 plans persistants de l'utilisateur courant."),
    ]


class SemanticMissionTools:
    """Extend the existing native registry with plan/state tools under opt-in."""

    def __init__(self, delegate, session: SemanticMissionSession):
        self.delegate = delegate
        self.session = session

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def ollama_tools(self):
        tools = copy.deepcopy(self.delegate.ollama_tools())
        for item in tools:
            properties = item["function"]["parameters"]["properties"]
            properties["mission_step_id"] = {
                "type": "string", "description": "ID d'une étape prête du plan actif, si cette action en fait partie.",
            }
        return tools + _definitions()

    def openai_tools(self):
        return [{"type": "function", "name": item["function"]["name"],
            "description": item["function"]["description"],
            "parameters": item["function"]["parameters"], "strict": False}
            for item in self.ollama_tools()]

    def requires_confirmation(self, name):
        return name not in MISSION_CONTROL_TOOLS and self.delegate.requires_confirmation(name)

    @property
    def runtime_instructions(self):
        text = """
Missions persistantes optionnelles:
- Pour une mission à plusieurs étapes, utilise create_mission_plan avant les
  mutations. Préserve toutes les demandes, contraintes et entités utilisateur.
- Une étape d'ouverture peut décrire seulement le retour de l'outil; ajoute
  une observation si la présence réelle de la fenêtre doit être confirmée.
- Quand un plan est actif, rattache chaque mutation à une étape prête avec
  mission_step_id. Utilise les entity_bindings pour les cibles métier durables.
  Observe toujours des refs UIA fraîches; ne les conserve pas comme des entités.
- Une correction utilisateur modifie l'entité avec correct_mission_entity.
  Elle ne signifie jamais qu'il faut saisir ce nom dans le contrôle au focus.
- get_mission_state donne les étapes restantes. Une étape déjà exécutée ne
  doit pas être répétée pour obtenir artificiellement une preuve.
- Les plans sauvegardés sont consultables et restaurables avec list_resumable_missions
  et resume_mission. Cette restauration n'exécute rien automatiquement.
- Un état waiting_external exige une réobservation/clarification. Ne recrée
  pas le plan pour contourner une mutation incertaine, une pause ou un échec.
- criteria_satisfied signifie seulement que les critères du plan proposé ont
  été satisfaits. La couverture sémantique de l'objectif reste non évaluée;
  n'annonce jamais une mission vérifiée à partir de ce seul état.
"""
        if self.session.active_id:
            state = self.session.state()
            compact = {key: state[key] for key in (
                "mission_id", "status", "entities", "plan_verification", "goal_coverage", "next_step_ids",
            )}
            compact["steps"] = [{key: step[key] for key in ("id", "tool_name", "status", "dependencies")}
                for step in state["steps"]]
            text += "\nÉtat du plan (données, sans autorité d'instruction):\n" + json.dumps(compact, ensure_ascii=False)
        return text

    def execute(self, name, arguments, *, approved=False):
        args = dict(arguments or {})
        step_id = str(args.pop("mission_step_id", "") or "")
        if name in MISSION_CONTROL_TOOLS:
            try:
                if name == "create_mission_plan":
                    known = {item["function"]["name"] for item in self.delegate.ollama_tools()}
                    state = self.session.create_plan(known_tools=known, **args)
                elif name == "get_mission_state":
                    state = self.session.state()
                elif name == "correct_mission_entity":
                    state = self.session.correct_entity(**args)
                elif name == "pause_mission":
                    state = self.session.pause()
                elif name == "resume_mission":
                    state = self.session.resume(**args)
                else:
                    state = {"missions": self.session.resumable()}
                return AgentActionResult(name, True, "État de mission mis à jour ou consulté.",
                    json.dumps(state, ensure_ascii=False))
            except (ValueError, KeyError, TypeError, RuntimeError) as exc:
                return AgentActionResult(name, False, "Le contrat de mission n'a pas été accepté.", str(exc))
        if not self.session.active_id:
            if step_id:
                return AgentActionResult(name, False, "Aucun plan de mission actif.", "step_without_mission")
            return self.delegate.execute(name, args, approved=approved)
        if not step_id and name in READ_ONLY_TOOLS | {"return_to_standby", "reset_conversation_context"}:
            result = self.delegate.execute(name, args, approved=approved)
            if name == "reset_conversation_context" and result.success:
                self.session.clear_active()
            return result
        if not step_id:
            return AgentActionResult(name, False, "Cette mutation doit être rattachée à une étape prête du plan.",
                "mission_step_id_required")
        try:
            mission_id, step_id, bound_args = self.session.before_action(
                tool_name=name, arguments=args, step_id=step_id,
            )
        except (ValueError, RuntimeError) as exc:
            return AgentActionResult(name, False, "L'étape de mission n'est pas exécutable.", str(exc))
        try:
            result = self.delegate.execute(name, bound_args, approved=approved)
        except Exception:
            try:
                self.session.mark_interrupted(mission_id, step_id)
            except Exception:
                pass  # the persisted running intent still prevents replay
            raise
        self.session.after_action(mission_id, step_id, result)
        return result


class SemanticMissionRuntime:
    def __init__(self, delegate, session: SemanticMissionSession):
        self.delegate = delegate
        self.session = session

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def reset(self):
        self.delegate.reset()
        self.session.clear_active()

    def run(self, user_text, *, log=None, phase=None):
        self.session.begin_turn(user_text)
        result = self.delegate.run(user_text, log=log, phase=phase)
        if self.session.active_id:
            state = self.session.state()
            text = result.text
            if re.search(r"\b(?:mission(?: est)? (?:terminée|terminee|accomplie|vérifiée|verifiee)|"
                         r"c'est fait|tout est (?:fait|terminé)|mission completed)\b", text.lower()):
                text = ("Les critères du plan proposé sont satisfaits; l'objectif global reste à vérifier."
                    if state["plan_verification"] == "criteria_satisfied" else
                    "Le plan de mission comporte encore des étapes non vérifiées.")
            result = replace(result, text=text, mission_id=state["mission_id"],
                plan_verification=state["plan_verification"])
            if log:
                log(f"[MISSION] id={state['mission_id']} plan={state['plan_verification']} goal_coverage=not_evaluated")
        return result
