# DayZ Manager

DayZ Manager est une application de bureau Windows destinée à administrer un
serveur DayZ dédié à distance. Elle centralise la connexion SSH, LinuxGSM,
Steam Workshop, les cartes, les mods, les joueurs, les fichiers de
configuration, les sauvegardes et la supervision du serveur dans une
interface claire.

Projet officiel : [github.com/prog66/dayZ-manager](https://github.com/prog66/dayZ-manager)

> **Signature du projet : Yann Escarbassière & Nova <3**

![Statut](https://img.shields.io/badge/statut-open%20source%20en%20construction-1f6feb)
![Version](https://img.shields.io/badge/version-0.9.2-2ea043)
![Plateforme](https://img.shields.io/badge/plateforme-Windows%2064--bit-0078d4)
![Interface](https://img.shields.io/badge/interface-PyQt6-41cd52)
![Licence](https://img.shields.io/badge/licence-GPL--3.0-blue)

## Sommaire

- [Objectif](#objectif)
- [Fonctionnalités](#fonctionnalités)
- [Prérequis](#prérequis)
- [Installation depuis les sources](#installation-depuis-les-sources)
- [Configuration](#configuration)
- [Préparer le serveur DayZ](#préparer-le-serveur-dayz)
- [Changer de carte](#changer-de-carte)
- [Gérer les mods](#gérer-les-mods)
- [Mises à jour GitHub](#mises-à-jour-github)
- [Build et release](#build-et-release)
- [Architecture](#architecture)
- [Tests](#tests)
- [Sécurité et données](#sécurité-et-données)
- [Dépannage](#dépannage)
- [Roadmap](#roadmap)
- [Contribuer](#contribuer)
- [Licence et crédits](#licence-et-crédits)

## Objectif

Administrer un serveur DayZ ne devrait pas nécessiter de retenir une longue
liste de commandes SSH, de chemins LinuxGSM ou de paramètres Workshop.
DayZ Manager propose un espace de travail unique pour :

- voir immédiatement l'état du serveur ;
- effectuer les opérations courantes sans ouvrir un terminal ;
- changer de carte et de mission de manière contrôlée ;
- maintenir les mods et leurs dépendances ;
- sauvegarder et restaurer la configuration ;
- suivre les logs et les signes de crash ;
- automatiser les redémarrages et la rotation des cartes.

Le logiciel pilote à distance un serveur Linux existant. Il ne remplace ni
LinuxGSM, ni SteamCMD, ni le serveur DayZ.

## Fonctionnalités

### Tableau de bord

L'accueil affiche les informations prioritaires : serveur en ligne ou hors
ligne, joueurs connectés, mémoire, CPU, espace disque, uptime, version,
mission active, mods obsolètes, dernière sauvegarde et heure d'actualisation.

### Contrôle du serveur

Les actions LinuxGSM disponibles sont :

- démarrer ;
- arrêter avec confirmation ;
- redémarrer ;
- mettre à jour ;
- valider les fichiers ;
- afficher les détails.

Les opérations longues utilisent un flux de sortie en direct et indiquent la
fin réelle de l'opération.

### Joueurs et modération

Avec BattlEye RCON activée, l'application permet de :

- lister les joueurs connectés ;
- envoyer un message général ou privé ;
- expulser un joueur ;
- bannir temporairement ou définitivement ;
- lister, supprimer, importer et exporter des bans ;
- utiliser un numéro de joueur, un GUID, un SteamID64 ou une IP selon l'action.

La RCON est exécutée côté serveur via SSH afin d'éviter d'exposer inutilement
son port sur Internet.

### Cartes, missions et profils

La page Cartes sait :

- détecter les mods de carte installés ;
- détecter les missions sous `serverfiles/mpmissions` ;
- reconnaître les cartes officielles et personnalisées ;
- importer une mission locale ;
- définir la mission active ;
- retirer les anciens mods de carte de la ligne de lancement ;
- ajouter le nouveau mod dans le bon ordre ;
- relire les fichiers après écriture ;
- vérifier le processus DayZ et les logs récents.

Les profils mémorisent le mod de carte, le template de mission, l'ordre des
mods et les paramètres de lancement. Un profil peut être appliqué, exporté
ou importé.

### Mods et Steam Workshop

La gestion des mods comprend :

- installation par ID Workshop ;
- installation d'une collection Workshop ;
- recherche Steam Workshop avec aperçu ;
- filtre “cartes uniquement” ;
- détection des mises à jour disponibles ;
- mise à jour groupée ;
- activation, désactivation et changement d'ordre ;
- analyse des `requiredAddons` ;
- blocage de la suppression d'un mod actuellement actif ;
- nouvelles tentatives SteamCMD avec purge ciblée du cache.

Les clés `.bikey` sont récupérées dans `serverfiles/keys` lorsque cela est
nécessaire.

### Configuration DayZ et économie

L'éditeur travaille sur le véritable fichier utilisé par LGSM :

```text
<chemin_lgsm>/serverfiles/cfg/dayzserver.server.cfg
```

Il propose un formulaire, un éditeur brut, une comparaison local/serveur et
une vérification après enregistrement. Les paramètres courants incluent le
nom du serveur, les mots de passe, le nombre de joueurs, l'heure et le
message du jour.

La page “Lancement & fichiers” gère `common.cfg`, les paramètres de lancement,
la mission active et les fichiers d'économie. Les fichiers XML et JSON sont
validés avant écriture lorsqu'ils sont édités depuis l'interface.

Fichiers recherchés notamment : `types.xml`, `events.xml`, `globals.xml`,
`cfgspawnabletypes.xml`, `cfgeconomycore.xml`, `cfgeventspawns.xml`,
`cfgenvironment.xml`, `cfggameplay.json` et `cfgweather.xml`.

### Logs et exploitation

L'espace Exploitation regroupe :

- console serveur ;
- suivi live des commandes longues ;
- liste des logs `.RPT`, `.ADM` et `.log` ;
- lecture et suivi continu d'un log ;
- recherche avec filtres erreurs, crashs, mods et joueurs ;
- diagnostic santé du serveur ;
- détection d'indices de crash.

### Sauvegardes

Les sauvegardes sont stockées côté serveur dans :

```text
<chemin_lgsm>/backups-manager/
```

Elles incluent les missions, le vrai fichier actif
`serverfiles/cfg/dayzserver.server.cfg` et `lgsm/config-lgsm/dayzserver/common.cfg`.
Elles peuvent recevoir un libellé, être listées, restaurées ou supprimées.
Les noms sont validés pour empêcher une sortie du dossier prévu.

### Automatisation et notifications

L'application peut installer côté serveur :

- des redémarrages planifiés ;
- un préavis RCON aux joueurs ;
- une rotation automatique de cartes ;
- un contrôle périodique et un redémarrage contrôlé après crash.

Le fuseau horaire est configurable, avec `Europe/Paris` par défaut. Les
notifications peuvent utiliser un webhook Discord ou un serveur SMTP.

### Profils et rôles

Les profils exportables transfèrent les réglages non secrets, les profils de
cartes et, si demandé, un instantané des fichiers serveur.

Les rôles locaux sont :

- **Administrateur** : accès complet ;
- **Opérateur** : opérations courantes, sans certaines actions sensibles ;
- **Lecture seule** : consultation uniquement.

Ces rôles ne remplacent pas les utilisateurs Linux ni les permissions SSH.

## Prérequis

### Ordinateur de gestion

- Windows 10 ou Windows 11 64 bits pour l'exécutable fourni ;
- accès réseau au serveur SSH ;
- Python 3.13 pour lancer les sources ;
- PowerShell Windows pour installer les mises à jour ;
- accès HTTPS à GitHub pour les releases.

### Serveur

- Linux ;
- LinuxGSM installé et fonctionnel ;
- script `./dayzserver` opérationnel ;
- compte SSH avec les droits nécessaires ;
- SteamCMD pour les téléchargements Workshop ;
- serveur DayZ dédié correctement installé ;
- BattlEye RCON en option ;
- droits de lecture et d'écriture sur les fichiers gérés.

## Installation depuis les sources

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Pour reproduire exactement l'environnement de build :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

Lancer l'application :

```powershell
.\.venv\Scripts\python.exe main.py
```

Le programme relance automatiquement le Python de `.venv` lorsqu'il est lancé
avec un autre interpréteur Python sous Windows.

## Configuration

Ouvrir `Réglages > Préférences` et renseigner :

| Champ | Description |
| --- | --- |
| IP / Hôte | Adresse IP ou nom DNS du serveur Linux |
| Port SSH | Généralement `22` |
| Utilisateur | Compte Linux utilisé par LinuxGSM |
| Mot de passe | Mot de passe SSH |
| Chemin LGSM | Dossier contenant `dayzserver` |
| Utilisateur Steam | `anonymous` ou compte autorisé |
| Mot de passe Steam | Nécessaire pour un compte privé |
| Clé API Steam | Nécessaire pour parcourir le Workshop |
| App ID Workshop | `221100` pour DayZ |
| Tentatives d'installation | Nombre d'essais SteamCMD par mod |
| Fuseau horaire | Exemple : `Europe/Paris` |
| Rôle local | Niveau d'accès dans l'application |

Tester ensuite la connexion SSH puis enregistrer.

### RCON

La configuration RCON se trouve dans `Automatisation`, ou via le bouton
“Configurer la RCON” de la page Joueurs. Le port par défaut est `2310`.

### Workshop

Créer une clé sur
[`steamcommunity.com/dev/apikey`](https://steamcommunity.com/dev/apikey),
puis la saisir dans les réglages. Sans clé API, la recherche et les aperçus
du Workshop ne sont pas disponibles.

## Préparer le serveur DayZ

Vérifier depuis le compte Linux :

```bash
cd /chemin/vers/lgsm
./dayzserver details
./dayzserver status
```

Les emplacements utilisés sont notamment :

```text
/chemin/vers/lgsm/dayzserver
/chemin/vers/lgsm/serverfiles/cfg/dayzserver.server.cfg
/chemin/vers/lgsm/serverfiles/mpmissions
/chemin/vers/lgsm/lgsm/config-lgsm/dayzserver/common.cfg
/chemin/vers/lgsm/serverfiles/keys
```

Le compte SSH doit pouvoir lire et modifier les fichiers, lancer LinuxGSM,
utiliser SteamCMD et installer les tâches cron demandées.

## Changer de carte

Le changement de carte suit ce cycle :

1. Actualiser les mods et les missions détectés.
2. Sélectionner une carte officielle ou personnalisée.
3. Vérifier que le template existe dans `mpmissions`.
4. Vérifier que le mod Workshop est installé si nécessaire.
5. Définir la carte active.
6. Écrire le template dans `dayzserver.server.cfg`.
7. Réécrire `mods=` dans `common.cfg` sans les anciens mods de carte.
8. Relire les fichiers pour confirmer l'écriture.
9. Redémarrer le serveur depuis la page Serveur.
10. Contrôler le processus et les logs pour confirmer le chargement réel.

Pour une carte personnalisée, le nom exact du dossier de mission doit être
présent sous `serverfiles/mpmissions`.

## Gérer les mods

Les mods sont enregistrés dans LGSM avec un séparateur échappé :

```text
mods="@CF;@CommunityOnlineTools;@MaCarte"
```

L'ordre affiché est l'ordre de lancement. Après une installation ou une mise
à jour, redémarrer le serveur pour charger les fichiers présents.

Ne pas supprimer manuellement un mod actif sans le retirer d'abord de la
configuration de lancement. DayZ Manager bloque cette suppression.

## Mises à jour GitHub

DayZ Manager vérifie automatiquement la dernière release stable environ
1,5 seconde après le démarrage. La vérification manuelle se trouve dans
`Réglages > À propos > Mises à jour`.

### Configurer le dépôt

Le logiciel pointe vers le dépôt officiel :

```python
GITHUB_REPOSITORY = "prog66/dayZ-manager"
GITHUB_REPOSITORY_URL = "https://github.com/prog66/dayZ-manager"
```

L'interface affiche par défaut l'URL complète
`https://github.com/prog66/dayZ-manager`. Une forme courte
`owner/repository` reste acceptée et la valeur est conservée dans
`config.json`.

### Contrôles avant installation

- release stable et version plus récente ;
- téléchargement HTTPS ;
- taille maximale et taille annoncée ;
- hash SHA-256 de l'archive ;
- protection contre les chemins dangereux dans le ZIP ;
- présence de l'exécutable et du manifeste ;
- correspondance release/manifeste ;
- correspondance hash exécutable/manifeste.

L'installation est différée jusqu'à la fermeture de l'application. Les
fichiers locaux `config.json` et `map_profiles.json` sont conservés.

## Build et release

### Build locale

```powershell
.\.venv\Scripts\python.exe tools\verify_environment.py --lock requirements-lock.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
build.bat
```

Les livrables sont générés dans `dist/staging/` :

```text
dist/staging/DayZManager/DayZManager.exe
dist/staging/DayZManager/manifest.json
dist/staging/DayZManager-windows-amd64.zip
dist/staging/DayZManager-windows-amd64.zip.sha256
dist/staging/checksums.sha256
```

Le build remplace uniquement les sorties de staging nécessaires. Il ne
supprime pas les données utilisateur ni `config.json`.

### Publication GitHub

Le workflow [`.github/workflows/release.yml`](.github/workflows/release.yml)
se déclenche lors d'un tag commençant par `v`.

Avant publication :

1. augmenter `APP_VERSION` dans `version.py` ;
2. vérifier que les tests passent ;
3. vérifier que `GITHUB_REPOSITORY` pointe vers le bon dépôt ;
4. créer un tag correspondant exactement à la version.

```text
APP_VERSION = "0.9.2"
tag GitHub   = v0.9.2
```

Le workflow installe les versions verrouillées, teste, construit le paquet et
publie l'archive ainsi que les fichiers de hash dans la release.

### Build automatique après les commits

Le workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) utilise les
runners Windows de GitHub Actions. Il s'exécute automatiquement :

- après chaque push sur `main` ;
- pour chaque pull request vers `main` ;
- à la demande depuis l'onglet **Actions**.

Il installe les dépendances verrouillées, lance les tests, vérifie la
compilation Python et construit un paquet Windows de validation. Ce paquet est
conservé comme artefact pendant 14 jours. La publication publique reste
réservée aux tags `vX.Y.Z` gérés par `release.yml`.

## Architecture

```text
dayz_manager/
├── main.py                       # Point d'entrée PyQt6
├── version.py                    # Version et dépôt de releases
├── ui/                           # Interface et thème
├── managers/                     # Logique métier
├── ssh/                          # SSH/SFTP et workers Qt
├── tools/                        # Build, manifeste et smoke test
├── tests/                        # Tests automatisés
├── requirements.txt              # Dépendances de développement
├── requirements-lock.txt         # Versions verrouillées
├── build.bat                     # Build Windows
└── .github/workflows/            # Publication des releases
```

Principaux modules métier : `commands.py`, `cfg_editor.py`, `map_manager.py`,
`workshop.py`, `rcon.py`, `scheduler.py`, `profiles.py`, `permissions.py`,
`notifications.py`, `types_editor.py` et `updater.py`.

Les commandes distantes sont centralisées et les valeurs saisies sont
échappées avant exécution. Les workers Qt maintiennent l'interface réactive.

## Tests

La suite `unittest` couvre notamment la configuration, le changement de
carte, les sauvegardes, les cartes personnalisées, les profils, les rôles, les
notifications, le manifeste, l'environnement verrouillé, l'updater, les
hashes SHA-256 et l'extraction ZIP sûre.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

La build Windows exécute également un smoke test de l'exécutable compilé.

## Sécurité et données locales

Les fichiers suivants sont ignorés par Git :

```text
config.json
map_profiles.json
```

Ils peuvent contenir des identifiants SSH, Steam, RCON, Discord ou SMTP.

Les secrets sont actuellement obfusqués en base64 pour éviter leur lecture
directe. **Base64 n'est pas un chiffrement fort.** Utiliser un compte SSH
dédié, des permissions minimales et un mot de passe différent des autres
services.

Ne jamais publier une configuration, une clé Steam, un webhook Discord, un
mot de passe RCON ou une archive de profil sensible.

DayZ Manager exécute des commandes avec les droits du compte SSH configuré.
Vérifier les chemins avant toute écriture, suppression, restauration ou
modification de carte.

## Dépannage

### Erreur DLL QtWidgets

Utiliser l'environnement du projet et non un Python global :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
build.bat
```

La build actuelle verrouille une combinaison PyQt6/Qt6 compatible avec le
paquet Windows produit par PyInstaller.

### Pas de mise à jour GitHub

Vérifier que le dépôt est public, que `GITHUB_REPOSITORY` est correct, qu'une
release stable existe, que le tag correspond à `APP_VERSION`, que l'archive
s'appelle `DayZManager-windows-amd64.zip` et qu'elle possède son fichier
`.sha256`.

### Carte absente

Vérifier que le dossier existe réellement sous :

```text
<chemin_lgsm>/serverfiles/mpmissions/<template>
```

### Workshop sans résultat

Renseigner une clé API Steam dans `Réglages` et vérifier l'accès HTTPS.

### Configuration sans effet

Le fichier actif est `serverfiles/cfg/dayzserver.server.cfg`, et non un
`serverDZ.cfg` placé directement à la racine de `serverfiles`.

## Roadmap

### Fiabilisation

- signature numérique des releases en complément du SHA-256 ;
- support UAC pour une installation dans `Program Files` ;
- vérification de démarrage après mise à jour ;
- historique des versions installées ;
- tests d'intégration sur un serveur DayZ de test ;
- rapports de couverture et de régression.

### Évolution serveur

- dépendances Workshop visualisées ;
- profils complets avec historique ;
- comparaison avancée des fichiers ;
- permissions plus fines ;
- recherches de logs enregistrables ;
- notifications de crash enrichies ;
- métriques historiques CPU, mémoire, disque et joueurs.

### Android

Une version Android est envisageable comme compagnon mobile pour consulter
l'état du serveur, gérer les joueurs, changer de profil de carte et recevoir
les alertes. L'approche recommandée est un client relié à une API sécurisée ou
à un agent côté serveur ; il ne faut pas embarquer directement les mots de
passe SSH dans une application mobile.

## Contribuer

Les contributions sont bienvenues.

Avant une pull request :

1. ne pas inclure de secrets ou de données serveur ;
2. conserver la compatibilité avec les profils existants ;
3. ajouter ou mettre à jour les tests ;
4. lancer `unittest` ;
5. vérifier l'interface et, si possible, le paquet compilé ;
6. documenter les changements visibles.

Pour les changements serveur, tester sur une instance de test et prévoir une
sauvegarde avant toute migration de configuration.

## Licence et crédits

Ce projet est distribué sous licence **GNU GPL v3.0**. Voir le fichier
[`LICENSE`](LICENSE) du dépôt officiel pour le texte complet et les droits de
redistribution, modification et partage.

**Auteur et signature : Yann Escarbassière**<br>
**Compagnon de conception et d'implémentation : Nova <3**

Merci à toutes les personnes qui testent, signalent les bugs et améliorent
DayZ Manager.
