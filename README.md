# FileForge

**Clic droit. Une roue. C'est fait.**

[![Site](https://img.shields.io/badge/site-tototra.github.io%2FFileForge-7c5cff)](https://tototra.github.io/FileForge/) [![Licence GPL v3](https://img.shields.io/badge/licence-GPL%20v3-blue)](LICENSE) ![Windows · macOS · Linux](https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-lightgrey)

FileForge est une boîte à outils pour tes fichiers qui s'ouvre sous forme de roue, directement depuis ton
gestionnaire de fichiers : convertir un PDF en Word, compresser une vidéo, rogner une photo, signer un contrat,
rendre un scan cherchable… Près de soixante actions, pour macOS, Windows et Linux.

Tout se passe sur ton ordinateur : aucun fichier n'est envoyé sur Internet, et l'original n'est jamais modifié
(chaque résultat est créé à côté).

## Ce qu'elle sait faire

| Catégorie | Exemples |
| --- | --- |
| Convertir | PDF ⇄ Word / Excel / PowerPoint / images / Markdown, photos (JPG, PNG, WebP, HEIC, AVIF…), vidéo → MP4 ou GIF, audio, Excel ⇄ CSV ⇄ JSON |
| Éditer | **Éditeur PDF** (modifier le texte, ajouter du texte, surligner, dessiner, images, pages), rogner visuellement, signer, filigrane, numérotation, redimensionner, pivoter, couper vidéo/audio, normaliser le volume |
| Pages | Fusionner, diviser, extraire, supprimer, réorganiser, pivoter des pages |
| Compresser | PDF, photos, vidéos, audio (3 niveaux), ZIP |
| Extraire | Images d'un PDF, son d'une vidéo, image fixe, contenu d'une archive |
| Sécurité | Mot de passe AES-256, déverrouillage, caviardage définitif, suppression des métadonnées et du GPS |
| Outils | OCR français/anglais, aplatir, réparer, renommer en lot, enchaîner plusieurs actions |
| Rechercher | <kbd>⌃</kbd><kbd>⌥</kbd><kbd>G</kbd> partout sur Mac (ou la roue ouverte sans fichier), puis tape un nom : recherche instantanée dans ton dossier personnel, tolérante aux accents et aux fautes de frappe |

## Installer

Télécharge le paquet de ton système depuis [le site](https://tototra.github.io/FileForge/), ou construis-les toi-même (voir plus bas).

Une fois installé, FileForge propose lui-même les nouvelles versions (vérification une fois par jour, installation en un clic). Chaque manifeste de version est signé (Ed25519) et chaque paquet vérifié par son empreinte SHA-256 : une version qui ne vient pas de l'auteur est refusée.

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
  updater.py      mises à jour (manifeste signé, empreinte vérifiée)
  ed25519.py      vérification des signatures (Python pur)
  hotkey_mac.py   agent macOS du raccourci global ⌃⌥G
  linux_setup.py  intégration Hyprland / Thunar
installers/     scripts d'installation macOS, Windows, Linux
assets/         icônes
site/           site de présentation (statique, prêt pour Cloudflare Pages)
  downloads/      paquets générés par tools/build.py
tools/          build.py (paquets), site_data.py (données de la démo), make_icon.py
tests/          suite pytest (toutes les actions, éditeur, mises à jour, recherche, roue, paquets) ;
                windows_ci.py / mac_ci.py / update_ci.py : tests sur une vraie installation (CI)
.github/        workflow « Test Windows » : installe le .exe, teste et photographie la roue (branche windows)
```

## Développer

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install pymupdf pymupdf4llm pdf2docx pillow pillow-heif openpyxl pandas xlrd odfpy mammoth markdown markdown-it-py pygments python-pptx python-docx pywebview imageio-ffmpeg rapidfuzz pytest pyflakes
python -m pytest tests -m "not slow"  # tests rapides (une vingtaine de secondes)
python -m pytest tests                # tout : vidéo, audio, OCR, LibreOffice, LaTeX, paquets (~10 min)
python src/wheel.py un_fichier.pdf    # ouvre la roue
```

Après une modification :

```bash
python3 tools/build.py      # régénère site/downloads/ (archives, FileForge-Setup.exe via makensis, manifest.json)
python3 tools/site_data.py  # si les actions ou catégories ont changé (démo du site)
```

## Publier une nouvelle version

1. Changer `__version__` dans `src/fileforge.py`.
2. Écrire les nouveautés dans `tools/release.json` (`"required": true` pour une mise à jour importante, installée sans demander).
3. `python3 tools/build.py` : construit les paquets et **signe** le manifeste avec la clé privée
   `~/.config/fileforge/update_signing.key` (jamais dans le dépôt ; à sauvegarder hors de l'ordinateur).
   Sans elle, aucun ordinateur n'accepterait la mise à jour. `makensis` est obligatoire (`brew install makensis`).
4. Commiter `site/`, puis `tools/publish_pages.sh` (GitHub Pages) et `npx wrangler deploy` (miroir) :
   chaque ordinateur se voit proposer la mise à jour dans la journée.

## Publier le site

Le site est un Worker Cloudflare de fichiers statiques (`wrangler.jsonc`, dossier `site/`) :

```bash
python3 tools/build.py     # si le code a changé : régénère site/downloads/
tools/publish_pages.sh     # publie sur https://tototra.github.io/FileForge/ (branche gh-pages)
npx wrangler deploy        # miroir : https://filiforme.to-trahant.workers.dev
```

Le site détecte le système du visiteur et met en avant le bon téléchargement ; les tailles et empreintes
SHA-256 sont lues dans `site/downloads/manifest.json`.

## Licence

Copyright © 2026 Thomas Trahant ([Tototra](https://github.com/Tototra)).

FileForge est un logiciel libre distribué sous licence **GNU GPL v3** (voir [LICENSE](LICENSE)) : tu peux
l'utiliser, l'étudier, le modifier et le partager, à condition que toute copie ou version modifiée reste sous
la même licence, avec son code source et la mention de l'auteur d'origine. Il est interdit d'en faire un
logiciel fermé.

## Crédits

PyMuPDF, pdf2docx, Pillow, pandas, pywebview, ffmpeg, Tesseract, LibreOffice (facultatif), icônes Lucide (ISC),
polices Bricolage Grotesque et Atkinson Hyperlegible Next (SIL OFL).
