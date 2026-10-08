# Photos → Vidéo

Petite app web : tu envoies plusieurs photos, tu choisis un nombre
d'images par seconde, elle génère une vidéo (ffmpeg) et te la fait
télécharger.

## Fonctionnement

- Les photos sont normalisées (rotation EXIF corrigée, redimensionnées si
  besoin, mises à la taille de la première photo avec des bandes noires si
  le ratio ne correspond pas) puis assemblées en vidéo H.264 au frame rate
  choisi.
- Le fichier vidéo généré est supprimé du serveur juste après l'envoi au
  navigateur — rien ne s'accumule sur le disque.
- Nécessite `ffmpeg` installé sur le système (pas une lib Python).

## Installation

```bash
cd photo-to-video
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Lancement

```bash
python app.py
```

Ouvre l'URL affichée, choisis tes photos (dans l'ordre où tu veux
qu'elles apparaissent), règle les images/seconde, et télécharge la vidéo.

## Réglages

Variables d'environnement (dans `.env` ou en ligne de commande) :

- `HOST` (défaut `0.0.0.0`), `PORT` (défaut `5001`)
- `DISABLE_SSL` — `1` pour servir en HTTP simple (usage local uniquement)
- `APP_PASSWORD` — mot de passe d'accès si l'app est exposée publiquement
- `CERT_DOMAIN` — domaine dont le certificat certbot sera utilisé pour le HTTPS
- `MAX_UPLOAD_MB` — taille max d'upload en Mo (défaut : 500)
- `MAX_DIMENSION` — plus grande dimension autorisée par photo en pixels,
  au-delà l'image est réduite (défaut : 1920)
