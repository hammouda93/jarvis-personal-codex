# Lancement direct de Jarvis sur Windows

Double-cliquer sur **Jarvis.exe**, à la racine du projet, pour ouvrir l'interface.
Le clap et les commandes vocales fonctionnent ensuite comme avec `run_jarvis.py`.
Échap ferme Jarvis. Un second lancement du même projet est bloqué tant que le
premier lanceur est actif.

Ce fichier est un lanceur Windows compilé. Il utilise `.venv\Scripts\python.exe`
et `run_jarvis.py` dans le même projet ; il ne contient pas une copie autonome
de Python et de ses dépendances. Garder l'exécutable dans ce dossier. Un raccourci
Windows peut pointer vers lui depuis le Bureau. Le fichier `.env` reste chargé
par le code existant et les souvenirs restent dans leur emplacement habituel.
Les changements de code Python sont utilisés au prochain lancement sans
recompiler le lanceur.

Le processus enfant reçoit aussi le `PATH` et `VIRTUAL_ENV` du `.venv`, comme
après activation dans PowerShell, sans modifier l'environnement global Windows.

Les sorties et erreurs sont enregistrées en UTF-8 dans
`%LOCALAPPDATA%\JarvisPersonal\logs\desktop_*.log`. Ces journaux peuvent
contenir les phrases prononcées ; ils restent locaux. Une erreur fatale affiche
le chemin du journal. Le panneau d'observabilité garde son réglage `.env`
`JARVIS_RUNTIME_OBSERVABILITY_ENABLED`, comme les autres options du projet.

## Recompiler

Fermer Jarvis, puis exécuter depuis le projet :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_jarvis_exe.ps1
```

Le script utilise le compilateur .NET Framework de Windows. Aucune clé API ni
base personnelle n'est incorporée. `Jarvis.exe` est un fichier généré localement,
exclu de Git ; les sources et le script de construction sont versionnés.

## Vérification sans microphone ni API

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_desktop_launcher.ps1
```

Cette commande contrôle le type Windows GUI du binaire, démarre son interpréteur
réel depuis un autre dossier et crée/ferme la fenêtre Qt hors écran avec un
worker de diagnostic. Les bases et journaux de ce test sont isolés dans `.cache`.
Une fixture vérifie les chemins avec espaces et caractères Unicode, les deux
flux simultanés, le choix de l'entrée normale et l'erreur d'environnement absent.
Le démarrage vocal réel reste à valider par double-clic puis clap.

Validation exécutée le 4 octobre 2026 : compilation réussie, `Jarvis.exe`
de 10 240 octets et **cinq contrôles d'intégration réussis**. Le diagnostic
utilise bien le Python du projet et PySide6 6.8.2.1 ; la fenêtre existante
s'ouvre et se ferme sans lancer le worker vocal. Les sorties simultanées et
les chemins accentués ont été vérifiés avec une fixture d'interpréteur.

Le lanceur utilise [CreateNoWindow](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.createnowindow)
pour le processus enfant et lit les deux flux de façon asynchrone, puis attend
leur vidage avec [WaitForExit et la redirection des sorties](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.redirectstandardoutput).
Le type `winexe` est compilé par [Csc](https://learn.microsoft.com/en-us/visualstudio/msbuild/csc-task).
