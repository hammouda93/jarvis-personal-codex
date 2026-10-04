# Mémoire durable et missions sémantiques — 3 octobre 2026

## Défaut reproduit

L'utilisateur demande : « Retiens cette information de test : mon projet fictif
s'appelle Atlas Bleu. » Après relance : « Comment s'appelle mon projet fictif ? »

Sur une base fictive isolée, une nouvelle instance SQLite retrouve `Atlas Bleu`
par mots-clés mais aucun résultat pour la question complète. La conjonction
des mots inclut `comment`. Un modèle simulé peut aussi confirmer la mémorisation
sans appeler `remember_information` : zéro écriture, confirmation retournée.
Ces deux défauts sont reproduits ; ils ne prouvent pas lequel s'est produit
sur le poste de l'utilisateur sans le journal de son essai.

## Réparation mémoire

Réutiliser SQLite et le fichier existant, sans recopier l'historique vocal dans
la mémoire. L'intention explicite `retiens` autorise déjà l'écriture.
Les trois boucles de providers exigent
maintenant un appel réussi avant une confirmation et autorisent un seul
checkpoint de correction dans le budget de tours. Si l'appel manque encore,
la réponse dit que l'enregistrement n'est pas confirmé. Cerebras hérite de
cette boucle Groq.

L'outil relit la ligne par une nouvelle connexion après commit. La preuve est
attribuée à ce résultat d'enregistrement. Normalisation Unicode/casse/accents,
mots interrogatifs filtrés et conjonction des termes significatifs conservée :
`Atlas Nova` ne doit pas retrouver un souvenir sur `Atlas Bleu`.

Une question peut récupérer au plus trois souvenirs pertinents avant le modèle.
La lecture utilise le véritable outil et le flux d'observabilité existant.
Les données sont bornées et présentées comme données, sans autorité de contrôle.
Le contexte récent de l'utilisateur prime en cas de conflit. Cette recherche
reste lexicale ; elle ne promet pas une compréhension sémantique de toute
paraphrase. Une phrase ordinaire ne déclenche aucune écriture persistante.

Le chemin par défaut reste `%LOCALAPPDATA%/JarvisPersonal/memory.sqlite3`.
`JARVIS_MEMORY_DB_PATH` permet un chemin explicite stable ou une base de tests.
Ni `.env` ni la base personnelle existante ne sont modifiés par ce développement.

## Recherche technique préalable

- [SQLite, expressions et LIKE](https://www.sqlite.org/lang_expr.html) : le
  traitement de casse natif de LIKE ne couvre pas tout Unicode. Une fonction
  de normalisation Python enregistrée sur chaque connexion conserve le schéma.
- [Python 3.9, sqlite3](https://docs.python.org/3.9/library/sqlite3.html) :
  paramètres SQL et fonctions définies par l'application.
- [SQLite FTS5](https://www.sqlite.org/fts5.html) : alternative indexée avec
  tokenizer Unicode. Une migration d'index n'est pas nécessaire pour réparer
  cette petite base ; le scan normalisé reste une limite à mesurer à grande échelle.
- [LangGraph, persistence](https://docs.langchain.com/oss/python/langgraph/persistence) :
  distinction entre état de conversation et données persistantes intersessions.
- [LangGraph, interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) :
  la reprise peut réexécuter du code situé avant une interruption. Une reprise
  ne doit donc pas répéter aveuglément une mutation dont l'issue est inconnue.
- [Tests de persistance des sous-graphes](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/tests/test_subgraph_persistence.py) :
  vérifier la séparation d'état et une invocation nouvelle, pas seulement un
  objet de conversation encore en mémoire.

Aucune dépendance LangGraph n'est ajoutée ; les contrats existants du projet
sont conservés.

## Intégration vers le Personal AI Agent

L'intégration ajoute un plan sémantique persistant opt-in à la boucle
model-native. Elle réutilise `MissionContextStore`, `MissionTaskGraph`,
`TaskGraphStore` et `MissionEventBus`. Le modèle formule entités, étapes et
critères ; le runtime valide le contrat, les dépendances et les preuves.
Un graphe des actions déjà exécutées n'est pas présenté comme un plan préalable.

Les outils de mission permettent de consulter, corriger une entité, mettre en
attente et restaurer un plan. Une correction invalide les étapes dépendantes.
Les mutations sont rattachées à une étape prête ; une réussite sans preuve
appropriée reste non vérifiée. Une reprise après crash demande une observation
pour une action interrompue, sans exécution automatique.

Le statut porte sur les critères du plan proposé. La couverture sémantique de
l'objectif utilisateur reste distincte et non validée automatiquement. Cette
étape n'attribue aucune autorité globale au dispatcher Kernel, n'ajoute pas une
équipe d'agents et n'active pas les envois ou l'apprentissage autonomes.

## Contrat livré et limites

`JARVIS_SEMANTIC_MISSIONS_ENABLED=1` active cette intégration dans le builder
réel. L'option reste désactivée par défaut en attendant les essais humains.
La réparation de mémoire ne dépend pas de cette option.

Le contexte versionné et le graphe canonique sont enregistrés ensemble dans
une transaction SQLite. `TaskGraphStore` reste une projection récupérable ;
son indisponibilité ne doit pas perdre une étape déjà accomplie. Les contrôles
de version prennent un verrou de transaction avant lecture. `mark_status`
met maintenant à jour le JSON et la version, ainsi que la colonne de statut.
Les connexions sont explicitement fermées après chaque opération, y compris
sous Windows. La sérialisation du graphe est partagée, conserve la priorité
zéro et annule l'ajout d'un nœud qui créerait un cycle.

Le contrat borne le plan à 20 étapes, 20 entités et 15 contraintes. Il contrôle
le propriétaire, les outils connus, les dépendances, les entités et les critères.
L'intention d'action est persistée avant l'appel natif. Les valeurs d'entités
liées remplacent les arguments devenus périmés. Une preuve doit venir du même
outil et respecter les valeurs et types attendus ; une valeur vide observée
reste une preuve valide d'effacement.

`tool_success` est réservé aux lectures et aux résultats de lancement/navigation.
Une ouverture réussie ne constitue pas une preuve d'état visible de l'interface.
Les mutations de contenu exigent `verified_result` et une observation structurée.
Les corrections invalident les étapes liées et leurs descendants. Après une
tentative de mutation, elles demandent une observation ; une restauration
n'exécute aucun outil et ne rejoue pas une action interrompue.

La réconciliation automatique d'une mutation incertaine reste à développer.
Les contraintes textuelles ne sont pas encore une politique sémantique générale.
Même si tous les critères du plan sont satisfaits, `goal_coverage` reste
`not_evaluated` et aucune mission globale n'est certifiée. Les événements réels
`mission.updated` alimentent le panneau Qt. Les confirmations natives restent
en place ; aucun contrôle global du Kernel n'est revendiqué.

Les essais humains sont détaillés dans
[PERSONAL_AI_AGENT_MANUAL_VALIDATION.md](PERSONAL_AI_AGENT_MANUAL_VALIDATION.md).
## Résultats exécutés

| Validation | Résultat |
| --- | --- |
| Reproduction avant correction | Question naturelle : zéro résultat malgré une ligne persistée ; faux modèle : confirmation sans aucune écriture |
| Mémoire et boucles de runtime après correction | 80 tests OK, 20,173 s |
| Missions, mémoire et observabilité après correction du garde de texte final | 70 tests OK, 134,702 s |
| Suite complète finale, connexions et routage vocal inclus | **342 tests OK, 353,448 s** |
| Nouveaux tests | 17 mémoire, 32 plans, 1 routage vocal ; total +50 par rapport à la baseline précédente |
| Persistance mémoire interprocessus | Écriture commitée dans une base fictive, puis lecture de la question exacte par un second processus Python |
| Reprise de mission | Nouvelle session, entité corrigée conservée ; mutation interrompue non rejouée ; panne de projection sans perte du graphe canonique |
| Concurrence SQLite | Deux instances tentant la même version : une sauvegarde acceptée, un conflit rejeté |
| Rendu Qt | Fenêtre réelle rendue hors écran avec fixtures étiquetées ; preuve outil et critères du plan distincts, lisibilité inspectée |
| Inventaire AST | 87 modules, 342 méthodes de test |

Les tests couvrent les boucles réelles Ollama, Groq et OpenAI avec réponses de
modèle simulées, ainsi que le builder Cerebras sans appel API. Le message
`Journal unavailable: OSError` est une panne injectée attendue. Les essais
automatiques utilisent des bases, fichiers et répertoires temporaires isolés.
Les durées incluent les entrées/sorties de cette machine et ne constituent pas
une mesure de latence vocale ou de performance en production. Aucun scénario
microphone/API/Windows réel n'est annoncé comme validé.
