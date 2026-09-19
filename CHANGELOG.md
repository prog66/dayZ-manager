# Journal des versions

## 0.10.0 — 2026-09-19

- Nouvel accueil, recherche Ctrl+K, diagnostic guidé et historique de session.
- Missions ZIP/dossiers, détection Alteria, progression, publication après
  transfert complet et sauvegarde au remplacement.
- Droits lecture seule, modération et actions non protégées corrigés.
- SSH : gros flux, empreintes persistantes, test isolé, écritures atomiques,
  durée de vie des threads et fermeture différée.
- Sauvegardes : erreurs propagées et archives validées avant restauration.
- Cron : isolation redémarrages/rotations/fuseaux ; lecture vérifiée.
- RCON : CRC, réponses complètes et accusés de réception.
- Réglages atomiques, exports sans snapshots secrets, packages sans données locales.
- SMTP SSL/STARTTLS, canaux de notification indépendants.
- Mise à jour Windows conservant l'installation précédente.
- Détails, limites et roadmap : [rapport d'audit](AUDIT_0.10.0.md).
