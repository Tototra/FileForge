# FileForge

**Clic droit. Une roue. C'est fait.**

FileForge est une boîte à outils pour tes fichiers qui s'ouvre sous forme de roue, directement depuis ton
gestionnaire de fichiers : convertir un PDF en Word, compresser une vidéo, rogner une photo, signer un contrat,
rendre un scan cherchable… Près de soixante actions, pour macOS, Windows et Linux.

Tout se passe sur ton ordinateur : aucun fichier n'est envoyé sur Internet, et l'original n'est jamais modifié
(chaque résultat est créé à côté).

## Ce qu'elle sait faire

| Catégorie | Exemples |
| --- | --- |
| Convertir | PDF ⇄ Word / Excel / PowerPoint / images / Markdown, photos (JPG, PNG, WebP, HEIC, AVIF…), vidéo → MP4 ou GIF, audio, Excel ⇄ CSV ⇄ JSON |
| Éditer | Rogner visuellement, signer, filigrane, numérotation, redimensionner, pivoter, couper vidéo/audio, normaliser le volume |
| Pages | Fusionner, diviser, extraire, supprimer, réorganiser, pivoter des pages |
| Compresser | PDF, photos, vidéos, audio (3 niveaux), ZIP |
| Extraire | Images d'un PDF, son d'une vidéo, image fixe, contenu d'une archive |
| Sécurité | Mot de passe AES-256, déverrouillage, caviardage définitif, suppression des métadonnées et du GPS |
| Outils | OCR français/anglais, aplatir, réparer, renommer en lot, enchaîner plusieurs actions |
| Rechercher | Ouvre la roue sans fichier et tape un nom : recherche instantanée dans ton dossier personnel, tolérante aux accents et aux fautes de frappe |

## Installer

Télécharge le paquet de ton système depuis le site, ou construis-les toi-même (voir plus bas).

| Système | Installation | Ouvrir la roue |
| --- | --- | --- |
| macOS 12+ | clic droit sur `install.command` → Ouvrir | <kbd>⌃</kbd><kbd>⌥</kbd><kbd>F</kbd> dans le Finder, ou clic droit → Actions rapides |
| Windows 10/11 | double-clic sur `FileForge-Setup.exe` | <kbd>Ctrl</kbd><kbd>Alt</kbd><kbd>F</kbd> dans l'Explorateur, ou clic droit |
| Linux (Arch, Hyprland…) | `./install.sh` | <kbd>Super</kbd><kbd>Alt</kbd><kbd>F</kbd>, clic droit (Nautilus, Dolphin, Thunar, Nemo) ou `fileforge fichiers…` |

Aucun droit administrateur n'est nécessaire (sauf `sudo pacman` pour les dépendances système sous Linux).
Chaque installateur récupère un Python privé et ses bibliothèques, sans toucher à ce qui est déjà installé ;
ffmpeg et les langues OCR sont inclus.

## Organisation du dépôt

```
src/            le programme (commun aux trois systèmes)
  fileforge.py    moteur : toutes les actions
  wheel.py        la roue (pywebview) et l'intégration à chaque système
  wheel.html      interface de la roue
  search.py       recherche de fichiers par nom (index local)
  linux_setup.py  intégration Hyprland / Thunar
installers/     scripts d'installation macOS, Windows, Linux
assets/         icônes
site/           site de présentation (statique, prêt pour Cloudflare Pages)
  downloads/      paquets générés par tools/build.py
tools/          build.py (paquets), site_data.py (données de la démo), make_icon.py
tests/          selftest.py : toutes les actions ; windows_ci.py / windows_ui.py : tests sur un vrai Windows
.github/        workflow « Test Windows » : installe le .exe, teste et photographie la roue (branche windows)
```

## Développer

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install pymupdf pymupdf4llm pdf2docx pillow pillow-heif openpyxl pandas xlrd odfpy mammoth markdown python-pptx pywebview imageio-ffmpeg rapidfuzz
python tests/selftest.py              # toutes les actions, sans interface
python src/wheel.py un_fichier.pdf    # ouvre la roue
```

Après une modification :

```bash
python3 tools/build.py      # régénère site/downloads/ (archives, FileForge-Setup.exe via makensis, manifest.json)
python3 tools/site_data.py  # si les actions ou catégories ont changé (démo du site)
```

## Déployer le site sur Cloudflare Pages

Dans Cloudflare : *Workers & Pages → Créer → Pages → Connecter à Git*, choisis ce dépôt, puis :

- **Commande de build** : `python3 tools/build.py` (ou laisser vide : les paquets sont déjà dans le dépôt)
- **Répertoire de sortie** : `site`

Le site détecte le système du visiteur et met en avant le bon téléchargement ; les tailles et empreintes
SHA-256 sont lues dans `site/downloads/manifest.json`.

## Crédits

PyMuPDF, pdf2docx, Pillow, pandas, pywebview, ffmpeg, Tesseract, LibreOffice (facultatif), icônes Lucide (ISC),
polices Bricolage Grotesque et Atkinson Hyperlegible Next (SIL OFL).
