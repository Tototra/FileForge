#!/bin/bash
# Publie le dossier site/ sur GitHub Pages (branche gh-pages) → https://tototra.github.io/FileForge/
set -euo pipefail
cd "$(dirname "$0")/.."
# GitHub Pages publie la version commitée de site/ : si elle diffère des fichiers locaux, les deux miroirs divergeraient
git diff --quiet HEAD -- site || { echo "site/ a des modifications non commitées : commite-les d'abord." >&2; exit 1; }
[[ -z "$(git ls-files --others --exclude-standard site)" ]] || { echo "site/ contient des fichiers non suivis : ajoute-les d'abord." >&2; exit 1; }
git subtree split --prefix site -b gh-pages-tmp >/dev/null
git push -f origin gh-pages-tmp:gh-pages
git branch -D gh-pages-tmp >/dev/null
echo "Publié : https://tototra.github.io/FileForge/ (1 à 2 minutes)"
