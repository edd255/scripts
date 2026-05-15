#!/usr/bin/env fish

function switch_theme
    set current_scheme (gsettings get org.gnome.desktop.interface color-scheme)
    if string match -q "'prefer-dark'" $current_scheme
        echo "[*] Switching to light..."
        set theme light
    else
        echo "[*] Switching to dark..."
        set theme dark
    end

    set alacritty_cfg ~/.config/alacritty/alacritty.toml
    set alacritty_dark "dark_mode"
    set alacritty_light "light_mode"

    set cosmic_cfg ~/.config/cosmic/com.system76.CosmicTheme.Mode/v1/is_dark
    set cosmic_dark "true"
    set cosmic_light "false"

    set kitty_cfg ~/.config/kitty/kitty.conf
    set kitty_dark "mocha"
    set kitty_light "latte"

    set nvim_cfg ~/.config/nvim/lua/plugins/plugins.lua
    set nvim_dark "mocha"
    set nvim_light "latte"

    set zathura_cfg ~/.config/zathura/zathurarc
    set zathura_dark "mocha"
    set zathura_light "latte"

    set git_cfg ~/.config/git/delta.gitconfig
    set git_dark "features = catppuccin-mocha"
    set git_light "features = catppuccin-latte"

    set lazygit_cfg ~/.config/fish/functions/lg.fish
    set lazygit_dark "mocha"
    set lazygit_light "latte"

    set yazi_cfg ~/.config/yazi/init.lua
    set yazi_flavor_cfg ~/.config/yazi/theme.toml
    set yazi_dark "mocha"
    set yazi_light "latte"

    set zellij_cfg ~/.config/zellij/config.kdl
    set zellij_dark "catppuccin-mocha"
    set zellij_light "catppuccin-latte"

    set television_cfg ~/.config/zellij/config.kdl
    set television_dark "catppuccin-mocha"
    set television_light "catppuccin-latte"

    set batman_cfg ~/.config/fish/functions/batman.fish
    set batman_dark "dark"
    set batman_light "light"

    set bat_cfg ~/.config/fish/functions/bat.fish
    set bat_dark "mocha"
    set bat_light "latte"

    set cat_cfg ~/.config/fish/functions/cat.fish
    set cat_dark "mocha"
    set cat_light "latte"

    set fzf_cfg ~/.config/fish/conf.d/env.fish
    set fzf_dark "darkrc"
    set fzf_light "lightrc"

    if test "$theme" = "light"
        sd $alacritty_dark $alacritty_light $alacritty_cfg
        sd $kitty_dark $kitty_light $kitty_cfg
        sd $zathura_dark $zathura_light $zathura_cfg
        sd $git_dark $git_light $git_cfg
        sd $cosmic_dark $cosmic_light $cosmic_cfg
        sd $lazygit_dark $lazygit_light $lazygit_cfg
        sd $yazi_dark $yazi_light $yazi_cfg
        sd $yazi_dark $yazi_light $yazi_flavor_cfg
        sd $nvim_dark $nvim_light $nvim_cfg
        sd $zellij_dark $zellij_light $zellij_cfg
        sd $television_dark $television_light $television_cfg
        sd $batman_dark $batman_light $batman_cfg
        sd $bat_dark $bat_light $bat_cfg
        sd $cat_dark $cat_light $cat_cfg
        sd $fzf_dark $fzf_light $fzf_cfg
        set fish_theme "catppuccin_latte"
        set gnome_scheme "'prefer-light'"
    else if test "$theme" = "dark"
        sd $alacritty_light $alacritty_dark $alacritty_cfg
        sd $kitty_light $kitty_dark $kitty_cfg
        sd $zathura_light $zathura_dark $zathura_cfg
        sd $git_light $git_dark $git_cfg
        sd $cosmic_light $cosmic_dark $cosmic_cfg
        sd $lazygit_light $lazygit_dark $lazygit_cfg
        sd $yazi_light $yazi_dark $yazi_cfg
        sd $yazi_light $yazi_dark $yazi_flavor_cfg
        sd $nvim_light $nvim_dark $nvim_cfg
        sd $zellij_light $zellij_dark $zellij_cfg
        sd $television_light $television_dark $television_cfg
        sd $batman_light $batman_dark $batman_cfg
        sd $bat_light $bat_dark $bat_cfg
        sd $cat_light $cat_dark $cat_cfg
        sd $fzf_light $fzf_dark $fzf_cfg
        set fish_theme "catppuccin_mocha"
        set gnome_scheme "'prefer-dark'"
    else
        echo "[-] Invalid theme: $theme. Use 'light' or 'dark'."
        return 1
    end

    echo "[*] Changing GNOME settings..."
    gsettings set org.gnome.desktop.interface color-scheme $gnome_scheme

    echo "[*] Changing fish theme..."
    printf 'y\n' | fish_config theme save "$fish_theme"
end

switch_theme
