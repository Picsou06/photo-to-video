# Photos → Vidéo

Petite app web : tu envoies plusieurs photos, tu règles le diaporama, elle génère une vidéo H.264 (ffmpeg) à regarder et télécharger.

## Fonctionnalités

- Ajout de photos en plusieurs fois, par bouton ou glisser-déposer.
- Ordre modifiable : glisser une vignette (appui long sur téléphone), flèches, tri par nom ou par date, inversion.
- Suppression d'une photo ou de toutes.
- Réglages :
  - durée de chaque photo (0,1 à 10 s) ;
  - transition : aucune, fondu ou glissement, et sa durée ;
  - format : celui de la première photo, 16:9, 9:16, 1:1 ou 4:3 ;
  - photos d'un autre format : bandes (couleur au choix) ou recadrage ;
  - résolution 480p, 720p ou 1080p, et qualité.
- Aperçu du diaporama dans le navigateur avant la génération.
- Vidéo lisible directement dans la page, puis téléchargeable.
- Affichage adapté à l'ordinateur et au téléphone.
- Les fichiers sont supprimés du serveur dès que la vidéo a été téléchargée.

## Lancement avec Docker

```bash
cp .env.example .env   # remplir FLASK_SECRET, et APP_PASSWORD si l'app n'est pas protégée autrement
docker compose up -d --build
```

L'app écoute sur `127.0.0.1:5011`, à placer derrière un reverse proxy en HTTPS.

## Lancement sans Docker

Nécessite Python 3 et `ffmpeg` installé sur le système.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Réglages du serveur

Variables d'environnement (dans `.env`) :

- `HOST` (défaut `0.0.0.0`), `PORT` (défaut `5001`)
- `DISABLE_SSL` : `1` pour servir en HTTP simple (derrière un reverse proxy, ou en local)
- `APP_PASSWORD` : mot de passe demandé par l'app avant d'y accéder
- `FLASK_SECRET` : clé de signature des sessions
- `CERT_DOMAIN` : domaine dont le certificat certbot sera utilisé pour le HTTPS intégré
- `MAX_UPLOAD_MB` : taille maximale d'un envoi en Mo (défaut : illimité)
- `MAX_DIMENSION` : plus grand côté de la vidéo en pixels (défaut : 1920)
