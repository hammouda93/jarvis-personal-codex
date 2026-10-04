# Personal AI Agent — audit du 3 octobre 2026

## Workspace et sécurité

Workspace unique : `D:\Django_Projects\jarvis-main\jarvis-main-codex`.
Aucun `.git` initial. Le dépôt GitHub demandé ne contenait aucune référence
au contrôle préalable `git ls-remote`. Snapshot `48ff725` publié sur `main`,
puis branche `feature/codex-personal-agent-evolution` créée et publiée.

122 fichiers candidats contrôlés avant publication, par comparaison avec cinq
valeurs locales de type clé/token et recherche de signatures connues : aucune
correspondance. Cette recherche ne garantit pas la détection de tout secret
arbitraire. `.env`, caches, logs, diagnostics, bases SQLite, profils navigateur,
clés privées et archives sont exclus. Aucune valeur de secret publiée.

Python 3.9.0 et dépendances existantes de `.venv` utilisés. Les données et
fichiers temporaires des tests sont redirigés vers `.cache/codex-audit/` dans
ce workspace ; les bases personnelles ne sont pas utilisées. Le lancement du
Python du projet exige une exécution hors sandbox sur cet hôte.

## Voie active

```text
run_jarvis.py → ui.JarvisWindow → assistant_v3.AssistantWorker
  → audio (clap, enregistrement, niveaux)
  → build_stt (Groq Whisper / Faster-Whisper local) → recognition
  → lifecycle / quelques actions directes
  → build_agent_runtime (Cerebras / Groq / Ollama / OpenAI)
      → NativeToolRegistry → Windows/UIA, web visible, mémoire, MS Football
  → ElevenLabsTTS / voix Windows → Qt UI de présence

Options passives : structured tracing → EventJournal SQLite
                  kernel shadow → KernelShadowObserver → PassiveKernelStack
```

Snapshot initial : **83 modules / 23 830 lignes** dans `jarvis_agent` ; runtime
3 040 lignes, perception Windows 1 959. Pas de rewrite global justifié.
`run_voice.py` conserve le headless historique déterministe ; il n'est pas
équivalent au runtime V3. `jarvis.py` reste le lanceur historique à double clap.

## Composants inspectés et autorité réelle

| Domaine | Modules | État réel au snapshot initial |
| --- | --- | --- |
| UI / voix | `ui`, `assistant_v3`, `audio`, `states`, `stt`, `recognition`, `tts`, `language`, `config` | Actifs. Qt Widgets/QPainter/QThread ; pas de QML ni graph de mission. |
| Modèles live | `agent_runtime` | Boucles model-native. Cerebras hérite de Groq avec failover secondaire Cerebras puis Groq. |
| Outils | `native_tools`, `tools`, `windows_perception` | Actifs, route directe coexistante, refs UI temporaires et contrôles de fraîcheur. |
| Vision | `screen_vision` | Ollama local optionnel ; actions visuelles sous opt-in distinct ; OFF par défaut. |
| Données métier | `ms_football_bridge` | Bridge HTTP local schéma/query/code/routes/preview/commit ; service réel non vérifié. |
| Mémoire | `memory`, `agent_knowledge`, `knowledge_cli` | Mémoire personnelle séparée des skills/lessons/profiles/runs. Learning et strict proof OFF en baseline. |
| Scopes | `agent_knowledge_adapter`, `knowledge_broker`, `knowledge_policy`, `scoped_knowledge_store`, `write_barrier` | Fondations ; projection de l'ancien store dans la pile passive. |
| Kernel | `kernel_contracts`, `kernel_stack`, `kernel_service`, `kernel_policy`, `kernel_request_store`, `kernel_dispatcher`, `kernel_cli` | Contrats, autorisation, persistance et dispatch passifs ; aucune autorité sur la voix. |
| Shadow | `shadow_kernel_runtime`, `shadow_kernel_cli` | Miroir post-tour opt-in, routing contextuel sans dispatch. Graph des actions passées, pas plan sémantique préalable. |
| Missions | `mission_context_store`, `task_graph`, `task_graph_store`, `mission_orchestrator`, `mission_scheduler` | DAG/dépendances/persistance/approbations dans la pile passive. Pas de scheduler live vocal. |
| Agents | `agent_factory`, `agent_router`, `capability_registry` | Manifestes/builders/lifecycle/routing ; décisions shadow. Pas d'équipe spécialisée active. |
| Contexte | `context_broker`, `context_injector` | Budgets et scopes Kernel passifs ; historique live propre aux providers. |
| Événements | `event_bus`, `event_journal`, `tracing_runtime`, `incident_bundle` | Bus Kernel, journal et tracing live opt-in. Aucun flux structuré d'outils vers l'UI. |
| Routing modèle | `model_catalog`, `model_router`, `model_telemetry`, `llm_manager` | Catalogue/circuit breaker/coût/latence/manager passifs ; ne remplacent pas le failover live. |
| MCP | `connectors` | Configuration pour OpenAI, exemples désactivés ; aucun compte connecté par cet audit. |
| Gateways | `connector_registry`, `connector_gateway`, `mcp_connector_adapter`, `tool_gateway`, `execution_managers` | Frontières et backends Kernel passifs ; pas encore la frontière universelle du runtime. |
| Plugins / secrets | `plugin_manifest`, `plugin_loader`, `plugin_policy`, `secret_provider`, `local_rpc_security` | Métadonnées/politiques/secret providers ciblés ; contrat loopback sans serveur actif. |
| Supervisor | `dev_supervisor`, `supervisor_planner`, `supervisor_validation`, `correction_store`, `promotion_gate`, `component_registry` | Assessments/candidats/gates avec validation ; pas de patch autonome actif. |
| QA / replay | `regression_registry`, `regression_runner`, `replay_sandbox`, `replay_adapter`, `workspace_storage` | Packs/tests/stockage/replay ; aucune VM pilotée ou livraison autonome. |
| Legacy | `assistant`, `assistant_v2`, `agent_core`, `brain`, `planner`, `registry`, `mission`, `capabilities`, `headless` | Anciennes générations et tests conservés ; headless encore lançable. |

`__init__` est le marqueur du package. L'inventaire AST
`PERSONAL_AI_AGENT_ARCHITECTURE.json` détaille chaque module, ses imports,
classes/fonctions et les méthodes de test. Reproduction :
`python scripts/build_architecture_inventory.py` (sans import runtime ni `.env`).

## Écarts établis par inspection

- **Tour ≠ mission :** tracing/shadow marquent completed à partir d'un retour ou
  de l'absence d'échecs. Critères sémantiques persistants manquants ; ces statuts
  ne doivent pas devenir une preuve de mission dans la nouvelle UI.
- **Preuve trop permissive :** `_actions_have_verified_proof` peut accepter une
  inspection générique postérieure ou une preuve d'action antérieure. Il manque
  l'attribution mutation/objectif/observation.
- **Windows :** Start Menu/Desktop et scan d'exécutables borné existent. Pas de
  pipeline Get-StartApps/AUMID/App Paths. Chemins de quelques apps encore explicites.
- **Research :** `search_web` ouvre Google. OpenAI a une recherche provider-side
  optionnelle. Aucun `research_web` générique, broker, annonce autonome ni recovery
  complet. `background_web_research.py` n'existe pas.
- **Mission / grounding :** pas de `mission_semantics.py`, de rôles sémantiques
  search/composer/send ou de correction persistante d'entités de mission.
- **Flags :** telemetry/agent registry/dev supervisor sont déclarés, sans
  activation complète dans la boucle live. Un flag n'est pas une intégration.
- **Config :** anciens noms Cerebras `SECONDARY_FAILOVER` / `FALLBACK_GROQ` dans
  `.env` sans lecteur correspondant ; le code lit `FALLBACK_TO_GROQ`. Valeurs
  privées préservées.
- **Secret redaction :** initialement, le journal filtre les champs sensibles,
  mais peut conserver une clé ou un bearer token dans un texte libre.
- **Performance :** les logs/perf ponctuels existent, mais aucune mesure globale
  CPU/GPU/latence STT/UI validée. Le coût d'une nouvelle UI reste à mesurer.

22 logs de lancement examinés par agrégats sans contenu personnel : 111 STATE,
33 STT, 19 TTS, 30 AGENT, 9 AGENT_TOOL ; aucun KERNEL_SHADOW ou `verified` dans
cet ensemble. Cela ne prouve ni réussite live actuelle ni défaut universel.
Les exports de diagnostics n'ont pas été publiés.

## Tests initiaux et baseline

22 fichiers, 266 méthodes AST. **266 tests effectivement exécutés en 246,882 s :
3 erreurs** au snapshot initial.

| Test | Cause reproduite | Correction |
| --- | --- | --- |
| `test_compact_inspection_preserves_capability_refs` | Import `json` manquant dans le test. | Import ajouté, assertions conservées. |
| `test_weak_fixed_french_retries_auto_and_prefers_grounded_action` | Mock d'un champ de dataclass frozen. | Remplacer l'objet settings par `dataclasses.replace`. |
| `test_groq_leaves_msf_domain_after_clear_general_topic_switch` | Routing MSF correct ; `ajouter des paiements` pris pour une obligation write_ui, appel modèle supplémentaire. | Verbes d'édition ambigus soumis à une destination UI générique. |

61 tests runtime/reconnaissance après correction : **OK**, dont deux nouvelles
régressions. Voir `DECISION_UI_COMPLETION_GUARD.md`, commit `4d83772`.
Script architecture existant : préflight syntaxe OK, 70 tests de fondations OK,
88 tests de baseline historique OK. Résultats finaux ajoutés plus bas.

## Roadmap fondée sur cet état

Le produit est un **runtime V3 à vérifier en live, avec fondations passives et
shadow contextuel optionnel**. Des fichiers de phase 7/9 ne signifient pas que
ces phases sont actives. Prochaines étapes :

1. Baseline verte et validation reproductible, sécurité et diagnostics.
2. Événements réels vers états UI bornés et preuves attribuées ; couvrir ensuite
   les fast paths et les appels modèle/failovers effectivement utilisés.
3. Mission sémantique shadow : entités/corrections/critères/plan vs exécution.
4. Découverte Windows générique et grounding, validations Win32/MSIX réelles.
5. Research Broker read-only, sources non fiables et recovery local borné.
6. Autorité Kernel progressive, puis agents/Supervisor/missions longues.

La référence visuelle utilisateur reste à venir. Le flux d'événements précède
le graph, les animations et l'identité visuelle. Aucun scénario réel voix,
WhatsApp, envoi, Cerebras/Groq ou MS Football n'est déclaré validé par les mocks.

## Première évolution livrée : observabilité passive

Le bus et les proxies de tracing existants sont étendus. Nouveaux événements
de tour/phase, IDs corrélés request/result/proof, durée réelle des appels,
exceptions observables et journal facultatif. Le masquage du journal et du flux
live couvre également les secrets courants dans des textes libres.

`runtime_activity.py` projette un tour et au plus 100 appels ;
`runtime_activity_panel.py` affiche les événements dans l'UI actuelle via un
slot Qt queued. Succès sans preuve reste **TERMINÉ · NON VÉRIFIÉ**. Une preuve
explicite, structurée et attribuée au résultat permet **VÉRIFIÉ · PREUVE OUTIL**.
Les erreurs restent visibles après recovery. Un tour terminé n'est jamais
affiché comme une mission vérifiée.

Activation opt-in : `JARVIS_RUNTIME_OBSERVABILITY_ENABLED=1`. Valeur par défaut
0, `.env` préservé. Cette option n'active ni journal SQLite, ni nouvelle route,
ni agents spécialisés. Voir `DECISION_RUNTIME_OBSERVABILITY.md` pour les
sources officielles, projets/issues/PR/tests étudiés, limites et lancement.

## Résultats effectivement obtenus

| Validation | Résultat |
| --- | --- |
| Suite initiale avant correction | 266 tests, 3 erreurs, 246,882 s |
| Runtime/reconnaissance après correction | 61 tests OK |
| Suite complète de baseline corrigée | 268 tests OK, 257,031 s |
| Script architecture existant | Préflight OK ; 70 fondations OK ; 88 baseline OK |
| Script vision existant | Préflight OK ; 88 baseline OK ; 15 ciblés OK |
| Script post-fix / learning diagnostics existant | 3 ciblés OK ; 150 tests OK ; export de base de test isolée |
| Première intégration observabilité + runtime/V3 + tracing historique | 86 tests OK |
| Script ciblé après ajout intégration fenêtre/concurrence | 22 tests OK |
| **Script complet final** | **292 tests OK, 222,299 s**, dont 24 nouveaux tests observabilité et 2 régressions baseline |
| Inventaire final AST | 85 modules ; 292 méthodes de test dans 23 fichiers |
| Rendu Qt offscreen | Fenêtre existante, fixtures étiquetées, lisibilité inspectée ; police Segoe UI chargée pour le test |
| Benchmark synthétique | 3 000 appels, médiane observée 0,237 ms ; historique borné à 100 ; détails/limites dans la décision |

Le message de test `Journal unavailable: OSError` est attendu dans la fixture
qui vérifie la continuité du runtime lors d'une panne du journal.
Les tests réseau/Windows emploient des mocks ; ils ne valident pas une mission
réelle. GPU, RSS, coût API, latence STT/TTS et comportement UI sur le desktop
réel ne sont pas mesurés par ce benchmark.

Reproduction de la suite finale :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_personal_agent_validation.ps1
```

Prochain critère avant extension d'autorité : valider le flux sur un tour vocal
réel, couvrir les actions directes et les appels provider-side, puis concevoir
le contrat sémantique shadow. Le Research Broker et la découverte AUMID restent
des travaux ultérieurs, et non des fonctionnalités annoncées comme présentes.

## Deuxième évolution : mémoire durable et plans proposés

Le mot « retiens » autorise l'enregistrement explicite. La confirmation exige
maintenant un appel natif réussi et une relecture SQLite après commit. Une
question naturelle pertinente peut charger des souvenirs dans un nouveau
runtime, indépendamment de l'historique de conversation. La recherche Unicode
filtre les mots interrogatifs tout en conservant la conjonction des termes
significatifs. Elle reste lexicale, sans promesse de compréhension de toutes
les paraphrases. Le chemin personnel existant est conservé ; un chemin explicite
stable est configurable par `JARVIS_MEMORY_DB_PATH`.

`mission_semantics.py` et `semantic_mission_runtime.py` intègrent les contrats
de contexte, DAG et bus existants à la boucle model-native, sous l'option
`JARVIS_SEMANTIC_MISSIONS_ENABLED=1`, désactivée par défaut. Le modèle peut
proposer un plan, consulter son état, corriger des entités, le mettre en attente
et le restaurer après redémarrage. Les mutations d'un plan actif sont rattachées
à une étape prête. L'intention est persistée avant exécution, les dépendances
sont contrôlées et les preuves correspondent à l'outil et aux valeurs attendues.
Une correction n'effectue aucune saisie Windows ; une reprise n'exécute rien
automatiquement. Le routage vocal ordinaire rejoint cette boucle lorsque
l'option est active.

Le graphe complet est canonique dans la transaction du contexte versionné ;
`TaskGraphStore` reste une projection récupérable. Les opérations de version
sont atomiques, les connexions se ferment explicitement et `mark_status`
conserve le statut dans le JSON chargé. La sérialisation du DAG conserve la
priorité zéro et un ajout cyclique est annulé.

Les événements `mission.updated` affichent les étapes et les critères dans le
panneau Qt. **Critères du plan satisfaits ne signifie pas objectif global
vérifié.** La couverture sémantique reste `not_evaluated`, les contraintes
textuelles ne constituent pas encore une politique générale et la récupération
automatique d'une mutation incertaine reste à développer. Kernel/Supervisor,
équipe d'agents, Research Broker et découverte AUMID restent à intégrer.

Validation finale de cette évolution : **342 tests OK, 353,448 s** ; 87 modules
et 342 méthodes dans l'inventaire AST. Les 50 nouveaux tests couvrent mémoire,
plans et routage vocal. La mémoire a été relue dans un second processus Python ;
les boucles des modèles et les actions Windows sont simulées. Le panneau réel
a été inspecté par rendu Qt hors écran. Aucun essai vocal/API/Windows réel
n'est déclaré réussi.

Voir la [décision et les limites](DECISION_PERSISTENT_MEMORY_AND_MISSIONS.md)
et les [tests humains à effectuer](PERSONAL_AI_AGENT_MANUAL_VALIDATION.md).

## Correctif vocal du 4 octobre 2026

Un journal humain confirme une écriture SQLite vérifiée d'Atlas, puis révèle
deux formulations non couvertes : « garde dans mémoire » masquait l'outil
d'enregistrement, et « C'est quoi mon projet fictif test ? » ne chargeait
aucun souvenir après relance. Ces cas ont été reproduits avant correction.

Le détecteur accepte désormais les variantes explicites avec « dans mémoire »
et conserve les négations. Le rappel couvre les questions familières et peut
fournir des candidats partiels bornés, avec le terme omis explicitement indiqué.
La recherche native stricte reste conjonctive ; les termes capitalisés ou
entre guillemets sont conservés dans les variantes. La compréhension de toutes
les paraphrases et de tous les noms en minuscules n'est pas revendiquée.

**352 tests OK, 328,387 s**, dont 10 nouveaux tests et un rappel étendu au
second processus. **Quatre scénarios avec Cerebras réel** sur une base fictive
et une surface d'outils limitée à SQLite ont enregistré puis retrouvé Atlas et
Inception dans des sessions neuves. La configuration de secours Cerebras a
été utilisée. Aucun microphone ni action Windows réelle dans ces vérifications.

Voir le [diagnostic, le correctif et ses limites](DECISION_MEMORY_VOICE_2026-10-04.md).
