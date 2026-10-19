# FileForge pour Linux (Arch + Hyprland)

Boîte à outils pour tes fichiers : PDF (fusionner, diviser, compresser, rogner, signer, caviarder, OCR,
convertir en Word/Excel/PowerPoint…), images, vidéos, audio, documents. Tout se fait dans une roue
qui s'ouvre sous ta souris.

## Installation

```bash
tar xzf FileForge-Linux.tar.gz
cd fileforge-linux
./install.sh
```

Le script :

1. propose d'installer les dépendances avec `sudo pacman -S --needed` (Python GTK/WebKit, Tk, ffmpeg,
   Tesseract + français) — c'est la seule étape qui utilise sudo ;
2. installe FileForge dans `~/.local/share/fileforge` (environnement Python privé) ;
3. crée la commande `~/.local/bin/fileforge` et l'entrée « Ouvrir avec → FileForge » ;
4. ajoute FileForge au clic droit de Nautilus (Scripts), Dolphin, Nemo, PCManFM-Qt et Thunar ;
5. **Hyprland** : détecte ta version et ton format de config (Lua 0.55+, `hyprland.conf` 0.53+ ou plus
   ancien), écrit `~/.config/hypr/fileforge.lua` (ou `.conf`) et ajoute **une seule ligne** à ta config
   après sauvegarde (`hyprland.lua.avant-fileforge`). Il te demande avant.

## Utilisation

- **Super + Alt + F** : la roue s'ouvre sous la souris ; glisse-y des fichiers depuis ton gestionnaire.
- **Clic droit → FileForge…** (Nautilus : clic droit → Scripts → FileForge), ou **Ouvrir avec → FileForge**.
- **Terminal / yazi / lf** : `fileforge fichier1.pdf image.heic …`
  (yazi : ajoute un opener `{ run = 'fileforge "$@"', orphan = true, desc = "FileForge" }`).

Dans la roue : survole une catégorie, tape pour chercher une action, Entrée pour lancer, Échap pour revenir.
À la fin : Ouvrir, Afficher dans le gestionnaire de fichiers, ou Enchaîner une autre action.
Les originaux ne sont jamais modifiés.

## Règles Hyprland (si tu préfères les écrire toi-même)

Config Lua (0.55+) :

```lua
hl.window_rule({
    name  = "fileforge-roue",
    match = { title = "^(FileForge-Roue)$" },
    float = true,
    size  = { 760, 760 },
    move  = { "cursor_x - (window_w * 0.5)", "cursor_y - (window_h * 0.5)" },
    border_size = 0, rounding = 0, no_shadow = true, no_blur = true, no_anim = true,
})
hl.window_rule({ name = "fileforge-outils", match = { title = "^(FileForge — .*)$" }, float = true, center = true })
hl.bind("SUPER + ALT + F", hl.dsp.exec_cmd("~/.local/bin/fileforge"))
```

`hyprland.conf` (0.53+) :

```ini
windowrule {
    name = fileforge-roue
    match:title = ^(FileForge-Roue)$
    float = on
    size = 760 760
    move = (cursor_x-(window_w*0.5)) (cursor_y-(window_h*0.5))
    border_size = 0
    rounding = 0
    no_shadow = on
    no_blur = on
    no_anim = on
}
bind = SUPER ALT, F, exec, ~/.local/bin/fileforge
```

Sway / i3 : `for_window [title="^FileForge-Roue$"] floating enable, border none`.

## Dépannage

- **Roue blanche ou noire** : le lanceur désactive déjà le rendu DMA-BUF de WebKit (souci fréquent avec
  NVIDIA). Sans compositeur, le fond est noir au lieu de transparent.
- **La roue se ferme quand la souris sort de la roue** : c'est voulu (comme un clic à côté) ; si ton
  `follow_mouse` gêne, Échap / « Fermer » restent disponibles.
- **Journal** : `~/.local/state/fileforge/FileForge.log`
- **PowerPoint / Excel → PDF** : `sudo pacman -S libreoffice-fresh` (proposé à l'installation).

## Désinstaller

```bash
~/.local/share/fileforge/uninstall.sh
```

Retire FileForge, ses menus, la ligne ajoutée à ta config Hyprland et l'action Thunar
(les sauvegardes `*.avant-fileforge` sont conservées).
