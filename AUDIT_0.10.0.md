# Audit DayZ Manager — 19 septembre 2026

## Conclusion et périmètre

La base 0.9.3 couvre LinuxGSM, mods, cartes, joueurs, fichiers, sauvegardes et
notifications. Les principales lacunes concernent la fiabilité des opérations,
la protection des données et la lisibilité des parcours. La version locale
0.10.0 corrige les défauts ci-dessous et ajoute un import et un diagnostic intégrés.

Audit du code, des commandes générées, des tests et du rendu local. Aucun
redémarrage distant, remplacement de mission réelle, modification de cron ou
envoi de mail réel n'a été effectué. Ce rapport ne certifie pas une installation
distante et ne remplace pas un test de restauration sur serveur isolé.

## Défauts corrigés

| Domaine | Constat | Correction 0.10.0 |
| --- | --- | --- |
| Missions | Écriture directe dans la mission finale, sans progression ni ZIP | ZIP/dossier, validation des chemins et volumes, progression par fichier, préparation distante temporaire |
| Remplacement | Mission potentiellement partielle après coupure | Copie `.backup-…` de l'ancienne mission, publication après transfert, remise en place si publication refusée |
| SFTP | Permissions traitées comme dossiers absents | Création seulement sur ENOENT, chemin absolu préservé, erreurs contextualisées |
| Fichiers distants | Écriture directe susceptible de tronquer le fichier | Temporaire, conservation du mode et remplacement atomique POSIX SFTP ; échec sans remplacement si extension absente |
| SSH | Attente de fin avant lecture pouvant bloquer une grosse sortie | Lecture des deux flux pendant l'exécution et délai total borné |
| Identité SSH | Acceptation renouvelée des clés inconnues | Mémorisation dans `known_hosts`, rejet des changements ultérieurs (première connexion TOFU) |
| Test SSH | Redirigeait la connexion globale avant enregistrement | Connexion de test indépendante et fermée après contrôle |
| Threads Qt | Résultat confondu avec fin effective du thread | Signal `completed` distinct, worker conservé jusqu'à la fin, fermeture différée |
| Rafraîchissement | Demandes qui s'empilent | Un cycle de statistiques à la fois |
| Rôles | Lecture seule autorisant restauration/sécurité, gardes manquantes | Consultation seule, rôles inconnus restrictifs, protection de l'import/modération/mods |
| Sauvegardes | `echo` masquant l'échec de tar | Code d'erreur propagé |
| Restauration | Extraction sans validation des membres | Refus des chemins sortants, liens et fichiers spéciaux avant extraction |
| Processus | Recherche pouvant trouver sa propre commande ; double zéro | Motif sans auto-correspondance et une seule ligne de décompte |
| RCON | CRC ignoré, réponses absentes/tronquées acceptées | CRC, séquence et intégralité vérifiés, accusés de réception des messages serveur |
| Cron | Redémarrages effaçant rotations et CRON_TZ étrangers | Blocs distincts, marqueurs exacts, préservation des autres tâches/fuseaux, lecture vérifiée |
| Réglages | Écriture interrompue et types invalides | Sauvegarde atomique, garde-fous structure/ports/intervalles |
| Export | Snapshots contenant des mots de passe malgré « secrets exclus » | Nouveaux exports limités aux réglages non secrets et profils ; anciens snapshots encore importables explicitement |
| Import profil | Secrets/rôle locaux écrasables | Champs secrets et rôle ignorés à l'import |
| Notifications | Échec Discord empêchant le mail | Canaux indépendants, erreurs explicites, SSL sur 465 / STARTTLS sur les autres ports |
| Mise à jour | Retour arrière pouvant supprimer l'installation initiale si déplacement refusé | États de déplacement contrôlés, précédent dossier conservé, réglages récupérés au moment du remplacement |
| Distribution | Données locales empaquetables | Exclusion de config.json, map_profiles.json, known_hosts |

## Interface et nouvelles fonctions

- Palette sombre verte, dialogues et tableaux contrastés, tailles compactes.
- Accueil avec RAM, CPU, OS et hôte visibles, étapes de préparation, accès rapides.
- Recherche de 16 destinations avec autocomplétion et Ctrl+K.
- `Exploitation → Diagnostic & activité` : LinuxGSM, fichiers serveur, droits
  d'import, Python, cron, tar et conseils ; historique des messages de la session.
- `Configuration → Carte → Importer une mission` : ZIP/dossier, détection
  Alteria, nom modifiable, remplacement explicite avec sauvegarde, progression.
- L'import seul ne redémarre pas le serveur. L'activation reste une action séparée.

## Couverture et fonctions manquantes

| Fonction | Présent | Suite à développer |
| --- | --- | --- |
| LinuxGSM | Commandes, détails, état | Précontrôles disque/ports, chemins LGSM personnalisés |
| Multi-serveurs | Une connexion, profils de cartes | Connexions multiples isolées et changement de contexte |
| Missions | Import protégé ZIP/dossier | Annulation/reprise, comparaison, restauration des copies dans l'UI |
| Sauvegardes | Création/restauration/suppression distantes | Téléchargement local, horaires dédiés, rétention, restauration testée |
| Secrets | Base64 historique | Coffre Windows/DPAPI, migration et export maîtrisés |
| SSH | Mot de passe, clés d'hôtes mémorisées | Clé/agent, gestion visuelle des empreintes |
| Rôles | Restrictions locales corrigées | Comptes et permissions réelles côté serveur |
| Notifications | Discord/SMTP, test depuis réglages | Choix des événements, reprise, limitation des répétitions |
| Supervision | App ouverte + monitor LGSM distant | Agent et notifications indépendants du poste Windows |
| Workshop | Recherche, collections simples, dépendances | Collections imbriquées, reprise et résolution fiable des dépendances |
| CFG/XML/JSON | Édition et validation syntaxique | Validation sémantique, conflits entre administrateurs, parseur CFG complet |
| Windows | Package et mise à jour GitHub | Signature Authenticode, installeur, qualification de l'auto-update sur VM |
| Architecture | Modules métier séparés | Découpage du dashboard et injection des connexions |

## Limites connues

- Transferts sérialisés ; progression par fichier et non par octet. Un dossier
  `.import-…` peut rester après échec, indiqué dans l'erreur pour diagnostic.
- Copies `.backup-…` des missions et `.__previous-…` de l'app conservées sans
  suppression ou rétention automatiques.
- Détection DayZ globale à l'hôte : plusieurs instances sur la même machine ne
  sont pas encore distinguées.
- Première clé SSH en confiance initiale (TOFU). Secrets Base64 non chiffrés.
  Les rôles locaux ne sont pas une frontière de sécurité face à un accès SSH.
- CRON_TZ dépend du démon cron installé ; sa prise en charge et les changements
  heure été/hiver ne sont pas validés par le seul diagnostic de présence.
- Restauration nécessitant Python 3, refusant les liens ; pas de transaction
  globale sur tous les fichiers du serveur.
- SMTP, Steam, RCON, tâches cron et import réel restent à vérifier sur serveur.
  Aucun mail envoyé ; le serveur SMTP prérempli n'est pas certifié par ce test.
- Préparation de mise à jour testée ; cycle complet de remplacement/retour arrière
  Windows à qualifier sur une VM.
- Accueil inspecté hors connexion : contrôle manuel avec longues valeurs réelles
  et résolutions/DPI supplémentaires encore utile.

## Vérification et livrables

- 64 tests réussis dans l'environnement verrouillé du projet.
- Cas couverts : import imbriqué, remplacement explicite, transfert interrompu,
  échec de publication et restauration du nom, ZIP dangereux/volumineux, erreurs
  d'écriture, export sans secrets, notifications indépendantes, gros flux SSH,
  RCON/CRC, isolation cron, archive de restauration malveillante.
- Tests Qt : navigation, refus lecture seule, durée de vie des workers, reprise
  après erreur d'import, isolation du test SSH.
- Rendu hors connexion inspecté à 1280×860 et 1040×680 ; import et diagnostic inclus.
- Livrables locaux prévus sous `dist/audit-0.10.0` ; build et lancement vérifiés
  séparément avant remise. Aucun déploiement distant inclus.

## Roadmap priorisée

1. Qualification sur serveur de test : import, restauration, RCON, cron, mails ;
   validation de l'auto-update dans une VM Windows.
2. Coffre Windows pour les secrets et authentification SSH par clé.
3. Sauvegardes planifiées, téléchargement local, rétention contrôlée.
4. Multi-serveurs et supervision indépendante de l'application.
5. Découpage des pages Qt, signature et installeur Windows.
