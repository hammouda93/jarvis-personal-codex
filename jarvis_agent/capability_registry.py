from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .kernel_contracts import (
    AgentManifest,
    CapabilitySpec,
    KnowledgeScope,
    RiskLevel,
)


@dataclass(frozen=True)
class RegisteredCapability:
    spec: CapabilitySpec
    provider_agent_id: str


class CapabilityRegistry:
    """Declarative agent/capability registry.

    This is deliberately not wired into routing yet. It gives Jarvis one stable
    contract for future specialized agents without changing today's runtime.
    """

    def __init__(self):
        self._agents: dict[str, AgentManifest] = {}
        self._capabilities: dict[str, RegisteredCapability] = {}

    def register_agent(
        self,
        manifest: AgentManifest,
        capabilities: Iterable[CapabilitySpec],
    ) -> None:
        self._agents[manifest.agent_id] = manifest
        for spec in capabilities:
            self._capabilities[spec.name] = RegisteredCapability(
                spec=spec,
                provider_agent_id=manifest.agent_id,
            )

    def get_agent(self, agent_id: str) -> AgentManifest | None:
        return self._agents.get(str(agent_id))

    def get_capability(
        self,
        name: str,
    ) -> RegisteredCapability | None:
        return self._capabilities.get(str(name))

    def agents(self) -> list[AgentManifest]:
        return sorted(
            self._agents.values(),
            key=lambda item: item.agent_id,
        )

    def capabilities(self) -> list[RegisteredCapability]:
        return sorted(
            self._capabilities.values(),
            key=lambda item: item.spec.name,
        )

    def providers_for(self, capability_names: Iterable[str]) -> set[str]:
        providers: set[str] = set()
        for name in capability_names:
            item = self.get_capability(name)
            if item is not None:
                providers.add(item.provider_agent_id)
        return providers

    def tool_allowed(self, agent_id: str, tool_name: str) -> bool:
        manifest = self.get_agent(agent_id)
        if manifest is None:
            return False
        return str(tool_name) in set(manifest.allowed_tools)


def build_default_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()

    registry.register_agent(
        AgentManifest(
            agent_id="windows",
            display_name="Windows Agent",
            version="0.1",
            capabilities=(
                "computer.observe",
                "computer.interact",
                "computer.files",
            ),
            allowed_tools=(
                "list_windows",
                "inspect_active_window",
                "open_application",
                "open_file",
                "open_folder",
                "ground_ui_role",
                "activate_window",
                "click_ui_element",
                "write_ui_element",
                "type_text_active_window",
                "press_key",
                "close_tab",
                "close_window",
                "observe_screen",
                "click_visual_target",
                "write_visual_target",
            ),
            memory_scopes=(
                KnowledgeScope.APP,
                KnowledgeScope.AGENT,
                KnowledgeScope.SKILL,
                KnowledgeScope.TEST,
            ),
            description=(
                "Controls the real Windows desktop through structured UIA/Win32 "
                "perception with local vision fallback."
            ),
        ),
        (
            CapabilitySpec(
                name="computer.observe",
                description="Observe windows and structured controls.",
                risk=RiskLevel.READ,
                tags=("windows", "uia"),
            ),
            CapabilitySpec(
                name="computer.interact",
                description="Interact with visible Windows applications.",
                risk=RiskLevel.REVERSIBLE,
                tags=("windows", "uia", "vision"),
            ),
            CapabilitySpec(
                name="computer.files",
                description="Open user-selected files and installers.",
                risk=RiskLevel.REVERSIBLE,
                tags=("windows", "files"),
            ),
        ),
    )

    registry.register_agent(
        AgentManifest(
            agent_id="browser",
            display_name="Browser Agent",
            version="0.1",
            capabilities=(
                "browser.navigate",
                "browser.search",
                "browser.interact",
            ),
            allowed_tools=(
                "open_url",
                "search_web",
                "inspect_active_window",
                "ground_ui_role",
                "click_ui_element",
                "write_ui_element",
                "press_key",
                "close_tab",
                "observe_screen",
                "click_visual_target",
                "write_visual_target",
            ),
            memory_scopes=(
                KnowledgeScope.APP,
                KnowledgeScope.AGENT,
                KnowledgeScope.SKILL,
                KnowledgeScope.TEST,
            ),
            description=(
                "Operates browser tasks while preserving real interface state."
            ),
        ),
        (
            CapabilitySpec(
                name="browser.navigate",
                description="Navigate to a URL or browser page.",
                risk=RiskLevel.REVERSIBLE,
                tags=("browser",),
            ),
            CapabilitySpec(
                name="browser.search",
                description="Prepare and submit browser searches.",
                risk=RiskLevel.REVERSIBLE,
                tags=("browser", "search"),
            ),
            CapabilitySpec(
                name="browser.interact",
                description="Interact with the current browser interface.",
                risk=RiskLevel.REVERSIBLE,
                tags=("browser", "uia", "vision"),
            ),
        ),
    )

    registry.register_agent(
        AgentManifest(
            agent_id="ms_football",
            display_name="MS Football Agent",
            version="0.1",
            capabilities=(
                "msf.read",
                "msf.prepare_mutation",
                "msf.commit_mutation",
            ),
            allowed_tools=(
                "msf_capabilities",
                "msf_describe_schema",
                "msf_count_records",
                "msf_query_records",
                "msf_readonly_sql",
                "msf_search_code",
                "msf_list_routes",
                "msf_resolve_route",
                "msf_prepare_mutation",
                "msf_commit_mutation",
            ),
            memory_scopes=(
                KnowledgeScope.DOMAIN,
                KnowledgeScope.AGENT,
                KnowledgeScope.SKILL,
                KnowledgeScope.TEST,
                KnowledgeScope.USER,
            ),
            description="Domain agent for MS Football workflows.",
        ),
        (
            CapabilitySpec(
                name="msf.read",
                description="Read MS Football application data.",
                risk=RiskLevel.READ,
                tags=("ms_football",),
            ),
            CapabilitySpec(
                name="msf.prepare_mutation",
                description="Prepare a proposed MS Football mutation.",
                risk=RiskLevel.REVERSIBLE,
                tags=("ms_football", "approval"),
            ),
            CapabilitySpec(
                name="msf.commit_mutation",
                description="Commit an approved MS Football mutation.",
                risk=RiskLevel.EXTERNAL_SIDE_EFFECT,
                requires_confirmation=True,
                tags=("ms_football", "approval"),
            ),
        ),
    )

    registry.register_agent(
        AgentManifest(
            agent_id="communications",
            display_name="Communication Agent",
            version="0.1",
            capabilities=(
                "communications.read",
                "communications.compose",
                "communications.send",
            ),
            allowed_tools=("connector_read", "connector_write", "connector_external"),
            allowed_connectors=("gmail", "whatsapp", "instagram"),
            memory_scopes=(
                KnowledgeScope.AGENT,
                KnowledgeScope.APP,
                KnowledgeScope.USER,
                KnowledgeScope.SKILL,
                KnowledgeScope.TEST,
            ),
            description=(
                "Future connector-oriented agent for Gmail, WhatsApp, Instagram "
                "and similar communication services."
            ),
        ),
        (
            CapabilitySpec(
                name="communications.read",
                description="Read messages through an authorized connector.",
                risk=RiskLevel.READ,
                tags=("connector", "communications"),
            ),
            CapabilitySpec(
                name="communications.compose",
                description="Prepare a message without sending it.",
                risk=RiskLevel.REVERSIBLE,
                tags=("connector", "communications"),
            ),
            CapabilitySpec(
                name="communications.send",
                description="Send an external message.",
                risk=RiskLevel.EXTERNAL_SIDE_EFFECT,
                requires_confirmation=True,
                tags=("connector", "communications"),
            ),
        ),
    )

    registry.register_agent(
        AgentManifest(
            agent_id="developer",
            display_name="Developer Agent",
            version="0.1",
            capabilities=(
                "developer.inspect",
                "developer.patch",
                "developer.test",
                "developer.replay",
                "developer.publish",
            ),
            allowed_tools=("connector_read", "connector_external"),
            allowed_connectors=("github",),
            memory_scopes=(
                KnowledgeScope.CORE,
                KnowledgeScope.APP,
                KnowledgeScope.AGENT,
                KnowledgeScope.SKILL,
                KnowledgeScope.TEST,
            ),
            description=(
                "Future Dev Supervisor execution agent. Patch/replay capabilities "
                "must be sandboxed before touching the live user environment."
            ),
        ),
        (
            CapabilitySpec(
                name="developer.inspect",
                description="Inspect code, traces and regression evidence.",
                risk=RiskLevel.READ,
                tags=("developer", "supervisor"),
            ),
            CapabilitySpec(
                name="developer.patch",
                description="Prepare a code patch in a controlled workspace.",
                risk=RiskLevel.REVERSIBLE,
                tags=("developer", "supervisor", "sandbox"),
            ),
            CapabilitySpec(
                name="developer.test",
                description="Run selected regression tests.",
                risk=RiskLevel.REVERSIBLE,
                tags=("developer", "tests"),
            ),
            CapabilitySpec(
                name="developer.replay",
                description="Replay a scenario in an isolated environment.",
                risk=RiskLevel.REVERSIBLE,
                tags=("developer", "replay", "sandbox"),
            ),
            CapabilitySpec(
                name="developer.publish",
                description="Publish an approved external repository change.",
                risk=RiskLevel.EXTERNAL_SIDE_EFFECT,
                requires_confirmation=True,
                tags=("developer", "connector", "external"),
            ),
        ),
    )

    registry.register_agent(
        AgentManifest(
            agent_id="personal_admin",
            display_name="Personal Admin Agent",
            version="0.1",
            capabilities=("personal_admin.read", "personal_admin.write"),
            allowed_tools=("connector_read", "connector_external"),
            allowed_connectors=("google_calendar",),
            memory_scopes=(KnowledgeScope.AGENT, KnowledgeScope.USER, KnowledgeScope.TEST),
            description="Calendar and personal-administration workflows through controlled connectors.",
        ),
        (
            CapabilitySpec(
                name="personal_admin.read",
                description="Read authorized personal-administration data.",
                risk=RiskLevel.READ,
                tags=("connector", "personal_admin"),
            ),
            CapabilitySpec(
                name="personal_admin.write",
                description="Perform an approved external admin mutation.",
                risk=RiskLevel.EXTERNAL_SIDE_EFFECT,
                requires_confirmation=True,
                tags=("connector", "personal_admin", "external"),
            ),
        ),
    )

    registry.register_agent(
        AgentManifest(
            agent_id="data",
            display_name="Data Agent",
            version="0.1",
            capabilities=("data.read", "data.write", "data.share"),
            allowed_tools=("connector_read", "connector_write", "connector_external"),
            allowed_connectors=("google_drive",),
            memory_scopes=(KnowledgeScope.AGENT, KnowledgeScope.USER, KnowledgeScope.TEST),
            description="Authorized file/data access separated from external sharing side effects.",
        ),
        (
            CapabilitySpec(
                name="data.read",
                description="Read authorized external data.",
                risk=RiskLevel.READ,
                tags=("connector", "data"),
            ),
            CapabilitySpec(
                name="data.write",
                description="Perform a reversible authorized data mutation.",
                risk=RiskLevel.REVERSIBLE,
                tags=("connector", "data", "write"),
            ),
            CapabilitySpec(
                name="data.share",
                description="Share data with an external principal.",
                risk=RiskLevel.EXTERNAL_SIDE_EFFECT,
                requires_confirmation=True,
                tags=("connector", "data", "external"),
            ),
        ),
    )

    registry.register_agent(
        AgentManifest(
            agent_id="research",
            display_name="Research Agent",
            version="0.1",
            capabilities=("research.web",),
            allowed_tools=("research_web",),
            memory_scopes=(KnowledgeScope.SESSION, KnowledgeScope.TEST),
            max_concurrency=2,
            description=(
                "Read-only background web research. Retrieved content is "
                "untrusted data and cannot directly authorize actions."
            ),
        ),
        (
            CapabilitySpec(
                name="research.web",
                description="Read-only browser-invisible external research.",
                risk=RiskLevel.READ,
                tags=("research", "web", "untrusted_input"),
            ),
        ),
    )

    registry.register_agent(
        AgentManifest(
            agent_id="memory",
            display_name="Memory Agent",
            version="0.1",
            capabilities=("memory.read", "memory.write"),
            allowed_tools=(
                "recall_information",
                "search_agent_knowledge",
                "agent_knowledge_stats",
                "remember_information",
                "save_verified_skill",
                "save_feedback_lesson",
            ),
            memory_scopes=(
                KnowledgeScope.USER,
                KnowledgeScope.AGENT,
                KnowledgeScope.SKILL,
                KnowledgeScope.TEST,
            ),
            description=(
                "Persistent personal memory and validated operational knowledge."
            ),
        ),
        (
            CapabilitySpec(
                name="memory.read",
                description="Read persistent memory or operational knowledge.",
                risk=RiskLevel.READ,
                tags=("memory", "knowledge"),
            ),
            CapabilitySpec(
                name="memory.write",
                description="Persist explicit user memory or verified knowledge.",
                risk=RiskLevel.REVERSIBLE,
                tags=("memory", "knowledge", "write"),
            ),
        ),
    )

    registry.register_agent(
        AgentManifest(
            agent_id="interaction",
            display_name="Interaction Agent",
            version="0.1",
            capabilities=("interaction.session",),
            allowed_tools=(
                "get_current_time",
                "list_connectors",
                "reset_conversation_context",
                "return_to_standby",
            ),
            memory_scopes=(KnowledgeScope.SESSION,),
            description="Session-local lifecycle and utility capabilities.",
        ),
        (
            CapabilitySpec(
                name="interaction.session",
                description="Session lifecycle and local utility operations.",
                risk=RiskLevel.READ,
                tags=("session", "utility"),
            ),
        ),
    )

    return registry


DEFAULT_CAPABILITY_REGISTRY = build_default_registry()
