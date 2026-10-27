#!/bin/bash
# Publie le dossier site/ sur GitHub Pages (branche gh-pages) → https://tototra.github.io/FileForge/
set -euo pipefail
cd "$(dirname "$0")/.."
git subtree split --prefix site -b gh-pages-tmp >/dev/null
git push -f origin gh-pages-tmp:gh-pages
git branch -D gh-pages-tmp >/dev/null
echo "Publié : https://tototra.github.io/FileForge/ (1 à 2 minutes)"
