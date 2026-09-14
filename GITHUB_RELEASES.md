# Publier les mises à jour GitHub

DayZ Manager vérifie automatiquement la dernière release stable au démarrage
(environ 1,5 seconde après l'ouverture). L'utilisateur peut aussi lancer la
vérification depuis `À propos > Mises à jour`.

## Préparer le dépôt

1. Le dépôt officiel est [`prog66/dayZ-manager`](https://github.com/prog66/dayZ-manager).
2. `version.py` pointe déjà vers ce dépôt avec `GITHUB_REPOSITORY_URL`.
   Cette URL est affichée par défaut dans l'application, dans
   `À propos > Mises à jour`. La forme courte `owner/repository` reste
   également acceptée.
3. Augmenter `APP_VERSION` avant chaque publication.

## Publier une version

Le workflow `.github/workflows/ci.yml` teste et construit automatiquement chaque
push sur `main` et chaque pull request. Le workflow
`.github/workflows/release.yml` publie une release avec un tag `vX.Y.Z`.
Le tag doit correspondre exactement à `APP_VERSION` sans le `v`.

```text
v0.9.2  ->  APP_VERSION = "0.9.2"
```

Le workflow lance les tests, construit l'exécutable Windows et publie :

- `DayZManager-windows-amd64.zip`
- `DayZManager-windows-amd64.zip.sha256`
- `checksums.sha256`

En local, `build.bat` produit les mêmes fichiers dans
`dist/staging/`. La release doit rester stable : les releases brouillon ou
pré-release sont ignorées par le logiciel.

## Sécurité de l'installation

Avant installation, le logiciel vérifie :

- téléchargement en HTTPS depuis GitHub ;
- taille maximale et taille annoncée ;
- SHA-256 de l'archive ;
- absence de chemin dangereux dans le ZIP ;
- présence de `DayZManager.exe` et `manifest.json` ;
- correspondance entre version, manifeste et hash de l'exécutable.

L'installation se fait après fermeture de l'application avec un installateur
PowerShell différé. `config.json` et `map_profiles.json` sont conservés.
