# Tests humains — mémoire et plans de mission

## 1. Mémoire persistante : « retiens » suffit

Fermer complètement l'ancien processus Jarvis, puis lancer depuis PowerShell :

```powershell
Set-Location 'D:\Django_Projects\jarvis-main\jarvis-main-codex'
$env:JARVIS_RUNTIME_OBSERVABILITY_ENABLED = '1'
& .\.venv\Scripts\python.exe -u .\run_jarvis.py
```

1. Activer Jarvis par le clap et dire exactement : **« Retiens cette information
   de test : mon projet fictif s'appelle Atlas Bleu. »**
2. Vérifier l'appel `remember_information` réussi. La preuve doit provenir de
   `sqlite_readback`, après écriture et relecture. Une confirmation vocale seule
   ne valide pas ce test. Le panneau peut afficher « VÉRIFIÉ · PREUVE OUTIL ».
3. Fermer Jarvis avec Échap et attendre le retour à l'invite PowerShell.
4. Relancer avec la même commande et le même compte Windows, puis demander :
   **« Comment s'appelle mon projet fictif ? »**
5. Réponse attendue : **Atlas Bleu**, avec `recall_information` dans les événements
   ou `[MEMORY] source=sqlite recalled=…` dans la console.

La lecture d'un souvenir peut afficher « TERMINÉ · NON VÉRIFIÉ » : lire une
information n'est pas une preuve de mutation de l'ordinateur. L'enregistrement,
lui, exige une relecture réussie avant confirmation.

Le fichier par défaut reste `%LOCALAPPDATA%\JarvisPersonal\memory.sqlite3`.
Si `JARVIS_MEMORY_DB_PATH` est défini, garder le même chemin entre les lancements.
Un chemin relatif est résolu depuis la racine du projet. Les souvenirs existants
ne sont pas effacés. Ce correctif est actif sans l'option de missions ci-dessous.

## 2. Plans de mission persistants — option expérimentale

Fermer Jarvis, puis ajouter avant le lancement :

```powershell
$env:JARVIS_SEMANTIC_MISSIONS_ENABLED = '1'
$env:JARVIS_RUNTIME_OBSERVABILITY_ENABLED = '1'
& .\.venv\Scripts\python.exe -u .\run_jarvis.py
```

Cette option ajoute les outils de planification à la boucle du modèle. Les
actions vocales ordinaires passent alors par cette boucle ; la latence peut
augmenter. Les commandes de cycle de vie vocal restent disponibles.

| Essai | Phrase à dire | Résultat attendu |
| --- | --- | --- |
| Plan préalable | « Prépare un plan pour ouvrir Bloc-notes et écrire Bonjour, sans encore l'exécuter. » | `create_mission_plan`, objectif original et étapes persistés ; aucune action Windows. |
| Correction | « Non, le texte à écrire est Salut. » | `correct_mission_entity`, valeur corrigée dans le plan ; aucune saisie dans la fenêtre active. |
| Consultation | « Montre-moi l'état de cette mission. » | Objectif original, texte Salut, étapes en attente ; aucune réussite globale annoncée. |
| Pause | « Mets cette mission en attente. » | `pause_mission`, état `waiting_user`, sans exécution. |
| Redémarrage | Fermer, relancer, puis « Quelles missions ai-je en attente ? » | `list_resumable_missions` retrouve le plan du même utilisateur. |
| Restauration | « Restaure seulement le plan Bloc-notes et montre ses étapes, sans les exécuter. » | `resume_mission`, texte Salut conservé ; aucune action automatique. |
| Exécution | Sur un document de test vide : « Exécute maintenant ce plan. » | Étapes exécutées dans l'ordre, nouvelles observations UI, écriture du texte Salut et preuve de résultat. |

Après la seule ouverture de Bloc-notes, le plan doit rester incomplet. Après
toutes les preuves attendues, le panneau indique « critères du plan satisfaits »
et **« objectif global non évalué »**. Les critères proposés par le modèle
peuvent être incomplets : ce statut ne certifie pas encore toute l'intention
humaine. Signaler un plan qui omet une partie de la demande.

Les contraintes textuelles sont conservées et données au modèle ; leur sens
n'est pas encore entièrement contrôlé par une politique générale. Les
confirmations déjà imposées par les outils natifs restent applicables.

Une mutation interrompue, ou une correction après une tentative de mutation,
reste `waiting_external` et demande une observation. Cette première version ne
réconcilie pas automatiquement ces situations et ne rejoue pas la mutation.
La récupération par perception fraîche et la validation complète de l'objectif
restent à développer. Le dispatcher Kernel et une équipe d'agents ne pilotent
pas encore toute l'application.

Pour revenir au fonctionnement habituel, relancer avec :

```powershell
$env:JARVIS_SEMANTIC_MISSIONS_ENABLED = '0'
```

Les souvenirs et les plans enregistrés sont conservés.

## 3. Compte rendu utile

Pour chaque essai, relever la phrase prononcée, la transcription, la réponse
vocale, le résultat visible, le nom de l'outil, son statut et sa preuve, la
latence approximative et toute erreur. Utiliser des données fictives.

Les validations automatiques isolent leurs bases et fichiers dans `.cache` :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_personal_agent_validation.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_personal_agent_validation.ps1 -Evolution
```

La première commande exécute toute la suite ; `-Evolution` sélectionne mémoire,
plans et routage vocal. `-Targeted` conserve le pack d'observabilité précédent.
Les modèles sont simulés : ces tests ne valident pas le microphone, les appels
API réels ni les manipulations Windows sur le poste de l'utilisateur.
