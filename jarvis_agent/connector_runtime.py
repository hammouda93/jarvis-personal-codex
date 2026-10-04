from __future__ import annotations

import json
from typing import Any

from .connector_gateway import ConnectorGateway, ConnectorResult
from .connector_registry import (
    ConnectorCapability,
    ConnectorRegistry,
    DEFAULT_CONNECTOR_REGISTRY,
)
from .kernel_contracts import RiskLevel
from .native_tools import AgentActionResult


_READ_RISKS = frozenset({RiskLevel.READ})
_REVERSIBLE_RISKS = frozenset({RiskLevel.REVERSIBLE})
_EXTERNAL_RISKS = frozenset(
    {RiskLevel.EXTERNAL_SIDE_EFFECT, RiskLevel.DESTRUCTIVE}
)


def _function_definition(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


class ConnectorToolRegistry:
    """Provider-neutral model tools over the existing ConnectorGateway.

    Reasoning chooses a logical connector capability. The gateway owns backend
    selection and the adapter performs the external primitive. Risk classes are
    separated into distinct tools so approval requirements never depend on a
    model-supplied string.
    """

    def __init__(
        self,
        delegate,
        *,
        gateway: ConnectorGateway | None = None,
        registry: ConnectorRegistry | None = None,
    ):
        self.delegate = delegate
        self.registry = registry or DEFAULT_CONNECTOR_REGISTRY
        self.gateway = gateway or ConnectorGateway(self.registry)

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    @staticmethod
    def _definitions() -> list[dict[str, Any]]:
        common = {
            "connector_id": {
                "type": "string",
                "description": (
                    "Identifiant exact d'un connecteur déclaré, par ex. "
                    "gmail, google_calendar, google_drive ou github."
                ),
            },
            "capability": {
                "type": "string",
                "description": "Capacité exacte déclarée par list_connectors.",
            },
            "arguments": {
                "type": "object",
                "description": (
                    "Arguments structurés de la capacité. N'invente jamais "
                    "des champs non documentés par le connecteur."
                ),
            },
        }
        return [
            _function_definition(
                "list_connectors",
                (
                    "Liste les connecteurs logiques, leurs capacités, leurs "
                    "risques et les backends réellement connectés. Lecture seule."
                ),
                {},
                [],
            ),
            _function_definition(
                "connector_read",
                (
                    "Exécute uniquement une capacité de connecteur classée READ. "
                    "Utilise list_connectors si la capacité ou la connexion est "
                    "incertaine."
                ),
                common,
                ["connector_id", "capability"],
            ),
            _function_definition(
                "connector_write",
                (
                    "Exécute uniquement une mutation classée REVERSIBLE, par "
                    "exemple créer un brouillon ou téléverser un fichier. Les "
                    "effets externes irréversibles ne sont pas autorisés ici."
                ),
                common,
                ["connector_id", "capability"],
            ),
            _function_definition(
                "connector_external",
                (
                    "Exécute une capacité à effet externe ou destructif, par "
                    "exemple envoyer, publier, partager ou créer/modifier un "
                    "événement. Confirmation utilisateur explicite obligatoire."
                ),
                common,
                ["connector_id", "capability"],
            ),
        ]

    def ollama_tools(self) -> list[dict[str, Any]]:
        return [*self.delegate.ollama_tools(), *self._definitions()]

    def openai_tools(self) -> list[dict[str, Any]]:
        tools = list(self.delegate.openai_tools())
        for item in self._definitions():
            fn = item["function"]
            tools.append(
                {
                    "type": "function",
                    "name": fn["name"],
                    "description": fn["description"],
                    "parameters": fn["parameters"],
                    "strict": False,
                }
            )
        return tools

    def requires_confirmation(self, name: str) -> bool:
        if str(name) == "connector_external":
            return True
        return bool(self.delegate.requires_confirmation(name))

    def _capability(
        self,
        connector_id: str,
        capability_name: str,
    ) -> tuple[Any, ConnectorCapability | None]:
        spec = self.registry.get(connector_id)
        if spec is None:
            return None, None
        capability = next(
            (
                item
                for item in spec.capabilities
                if item.name == capability_name
            ),
            None,
        )
        return spec, capability

    @staticmethod
    def _bounded_arguments(raw: Any) -> dict[str, Any]:
        arguments = dict(raw or {})
        encoded = json.dumps(
            arguments,
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        )
        if len(encoded) > 24000:
            raise ValueError("connector_arguments_too_large")
        return arguments

    @staticmethod
    def _result(
        tool_name: str,
        result: ConnectorResult,
        *,
        backend: str = "",
    ) -> AgentActionResult:
        data = dict(result.data or {})
        verified = bool(result.success and data)
        detail = {
            "connector_id": result.connector_id,
            "capability": result.capability,
            "backend": backend,
            "verified": verified,
            "evidence": data if verified else {},
            "error": result.error,
        }
        return AgentActionResult(
            name=tool_name,
            success=result.success,
            message=result.message,
            detail=json.dumps(detail, ensure_ascii=False, default=str)[:16000],
        )

    def _execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        expected_risks: frozenset[RiskLevel],
        approved: bool,
    ) -> AgentActionResult:
        connector_id = str(arguments.get("connector_id") or "").strip()
        capability_name = str(arguments.get("capability") or "").strip()
        if not connector_id or not capability_name:
            return AgentActionResult(
                name=tool_name,
                success=False,
                message="Connecteur et capacité sont requis.",
                detail="connector_identity_required",
            )

        spec, capability = self._capability(connector_id, capability_name)
        if spec is None:
            return AgentActionResult(
                name=tool_name,
                success=False,
                message="Connecteur inconnu.",
                detail="connector_not_registered",
            )
        if capability is None:
            return AgentActionResult(
                name=tool_name,
                success=False,
                message="Capacité non déclarée pour ce connecteur.",
                detail="connector_capability_not_registered",
            )
        if capability.risk not in expected_risks:
            return AgentActionResult(
                name=tool_name,
                success=False,
                message=(
                    "Cette capacité appartient à une autre classe de risque "
                    "et ne peut pas être exécutée avec cet outil."
                ),
                detail=json.dumps(
                    {
                        "reason": "connector_risk_boundary_mismatch",
                        "risk": capability.risk.value,
                    },
                    ensure_ascii=False,
                ),
            )

        try:
            payload = self._bounded_arguments(arguments.get("arguments"))
        except (TypeError, ValueError) as exc:
            return AgentActionResult(
                name=tool_name,
                success=False,
                message="Arguments du connecteur invalides.",
                detail=str(exc),
            )

        available = self.gateway.available_backends(connector_id)
        selected = self.registry.choose_backend(connector_id, available)
        result = self.gateway.execute(
            connector_id=connector_id,
            capability=capability_name,
            arguments=payload,
            approved=bool(approved),
        )
        return self._result(
            tool_name,
            result,
            backend=selected.value if selected is not None else "",
        )

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        *,
        approved: bool = False,
    ) -> AgentActionResult:
        tool_name = str(name or "").strip()
        args = dict(arguments or {})

        if tool_name == "list_connectors":
            connectors = []
            for spec in self.registry.all():
                backends = self.gateway.available_backends(spec.connector_id)
                connectors.append(
                    {
                        "id": spec.connector_id,
                        "display_name": spec.display_name,
                        "connected": bool(backends),
                        "backends": [item.value for item in backends],
                        "capabilities": [
                            {
                                "name": cap.name,
                                "risk": cap.risk.value,
                                "requires_confirmation": bool(
                                    cap.requires_confirmation
                                    or cap.risk
                                    in {
                                        RiskLevel.EXTERNAL_SIDE_EFFECT,
                                        RiskLevel.DESTRUCTIVE,
                                    }
                                ),
                            }
                            for cap in spec.capabilities
                        ],
                    }
                )
            return AgentActionResult(
                name=tool_name,
                success=True,
                message="État des connecteurs disponible.",
                detail=json.dumps(
                    {
                        "connectors": connectors,
                        "verified": True,
                        "evidence": {"source": "local_connector_registry"},
                    },
                    ensure_ascii=False,
                )[:20000],
            )

        if tool_name == "connector_read":
            return self._execute(
                tool_name,
                args,
                expected_risks=_READ_RISKS,
                approved=approved,
            )
        if tool_name == "connector_write":
            return self._execute(
                tool_name,
                args,
                expected_risks=_REVERSIBLE_RISKS,
                approved=approved,
            )
        if tool_name == "connector_external":
            return self._execute(
                tool_name,
                args,
                expected_risks=_EXTERNAL_RISKS,
                approved=approved,
            )

        return self.delegate.execute(
            tool_name,
            args,
            approved=approved,
        )
