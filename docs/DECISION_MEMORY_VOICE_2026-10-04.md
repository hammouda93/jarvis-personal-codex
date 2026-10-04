# Correction mémoire à partir d'un essai vocal — 4 octobre 2026

## Ce que le journal établit

L'appel `remember_information` du projet Atlas a réussi avec une preuve
`sqlite_readback`. Cette écriture n'est donc pas restée dans la conversation.
Le journal contient la transcription **Atlas**, sans « Bleu ».

Deux formulations mettent ensuite en défaut la version précédente :

- « S'il te plaît, garde dans mémoire que je veux regarder des films. Le premier
  film, c'est “Inception”. » Le détecteur n'acceptait que « en mémoire » pour
  ce verbe. Sur Cerebras, l'outil d'écriture était donc retiré du catalogue.
  Le modèle a tenté une lecture vide, puis déclaré la capacité indisponible.
- « C'est quoi mon projet fictif test ? » Après redémarrage, cette amorce ne
  déclenchait pas le chargement des souvenirs. Une recherche stricte de la
  phrase complète exigeait aussi le terme « test », absent de l'enregistrement.
  Le modèle a répondu sans consulter SQLite et a interprété « test » comme un nom.

Les deux défauts ont été reproduits avant correction dans une base fictive :
les variantes d'écriture sont refusées et les quatre runtimes n'effectuent
aucun rappel pour cette question. Les tests précédents couvraient une autre
formulation ; ils ne suffisaient pas à certifier toutes les demandes vocales.

## Changement

La normalisation existante du projet est réutilisée pour l'intention mémoire.
Les demandes explicites « garde dans mémoire », « garde dans ta mémoire »,
« enregistre dans la mémoire » et « mets en mémoire » exposent l'outil réel.
Les négations, y compris « garde pas », et une simple envie de regarder un film
ne donnent pas cette autorisation. La confirmation exige toujours une écriture
et une relecture SQLite réussies.

Les questions avec un point d'interrogation et les amorces familières comme
« c'est quoi » peuvent charger des souvenirs pertinents. La recherche native
reste conjonctive et tente d'abord tous les termes significatifs. Si aucun
résultat n'existe, le préchargement peut proposer une recherche partielle
en omettant un seul terme, avec au moins deux termes conservés. Les termes
capitalisés ou entre guillemets sont préservés. Au plus huit variantes sont
essayées, puis le véritable outil `recall_information` lit les résultats.

La question originale et le terme omis accompagnent au plus trois souvenirs
bornés dans le contexte temporaire. Le journal distingue `match=exact` et
`match=partial`. Une correspondance partielle est un candidat, pas une preuve
du terme manquant ; plusieurs candidats doivent conduire à une précision.
Ce mécanisme reste lexical. Il ne garantit pas la compréhension de toute
paraphrase ni l'identification de tous les noms écrits en minuscules.

Le schéma SQLite, le chemin personnel et les outils de mission ne changent pas.
La base personnelle et `.env` n'ont pas été modifiés lors du développement.

## Validation

- Avant correction : deux tests de reproduction échouent, avec neuf sous-cas
  en échec. Aucun appel API ni accès Windows dans cette reproduction.
- Après correction : 91 tests mémoire/runtime passent en 32,139 s avant le
  dernier complément de négation et le test interprocessus étendu.
- Dix nouveaux tests couvrent les phrases du journal, les quatre providers,
  les négations, une session neuve, les entités protégées et l'ambiguïté.
  Le test interprocessus existant vérifie aussi la question familière.
- **Cerebras réel**, avec seulement les outils SQLite et des données fictives :
  enregistrement d'Atlas, rappel dans une nouvelle session, enregistrement
  d'Inception, puis rappel dans une autre session réussis. Les deux écritures
  ont été relues dans la base isolée. Le mécanisme de secours Cerebras existant
  a été utilisé ; ces résultats ne certifient pas la disponibilité constante
  de l'API principale. Aucun microphone ni action Windows n'a été utilisé.
- **Suite complète finale : 352 tests OK, 328,387 s**, dont le complément de
  négation et le rappel familier dans un second processus Python.
- Inventaire AST : 87 modules et 352 méthodes de test. Le message
  `Journal unavailable: OSError` est une panne injectée attendue dans les tests.

Les bases et journaux de validation restent dans `.cache` et sont exclus de Git.
Le [guide humain](PERSONAL_AI_AGENT_MANUAL_VALIDATION.md) ajoute les deux phrases
réellement prononcées ; un essai sur le microphone reste nécessaire.
