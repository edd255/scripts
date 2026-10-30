#!/usr/bin/env fish

function log_info
    echo (set_color --bold green)"[*]"(set_color --reset) (string join ' ' -- $argv)
end

function log_warn
    echo (set_color --bold red)"[!]"(set_color --reset) (string join ' ' -- $argv) >&2
end

function link_theme -a target link
    if not test -e "$target"
        log_warn "Missing theme target: $target"
        return 1
    end

    mkdir -p (dirname "$link")
    command ln -sfnT -- "$target" "$link"
end

function replace_if_file -a from to file
    if not test -f "$file"
        log_warn "Missing config: $file"
        return 1
    end

    sd "$from" "$to" "$file"
end

function touch_if_file -a file
    if test -f "$file"
        touch "$file"
    else
        log_warn "Missing config for reload touch: $file"
        return 1
    end
end

function switch_theme
    set -l config_home "$HOME/.config"
    set -l current_scheme (gsettings get org.gnome.desktop.interface color-scheme)

    set -l theme
    set -l catppuccin
    set -l other_catppuccin
    set -l gnome_scheme
    set -l cosmic_value
    set -l other_cosmic_value
    set -l wallpaper_from
    set -l wallpaper_to

    switch "$current_scheme"
        case "'prefer-dark'"
            set theme light
            log_info "Switching to light..."
        case "'prefer-light'"
            set theme dark
            log_info "Switching to dark..."
        case '*'
            log_warn "Unknown GNOME color-scheme: $current_scheme"
            return 1
    end

    switch "$theme"
        case light
            set catppuccin catppuccin-latte
            set other_catppuccin catppuccin-mocha
            set gnome_scheme "'prefer-light'"
            set fish_theme catppuccin_latte
            set cosmic_value false
            set other_cosmic_value true
            set wallpaper_from 'cosmos\.jpg'
            set wallpaper_to 'rocket.jxl'

        case dark
            set catppuccin catppuccin-mocha
            set other_catppuccin catppuccin-latte
            set fish_theme catppuccin_mocha
            set gnome_scheme "'prefer-dark'"
            set cosmic_value true
            set other_cosmic_value false
            set wallpaper_from 'rocket\.jxl'
            set wallpaper_to 'cosmos.jpg'
    end

    set -l alacritty_cfg "$config_home/alacritty/alacritty.toml"
    set -l alacritty_theme "$config_home/alacritty/themes/theme.toml"

    set -l gitui_theme "$config_home/gitui/theme.ron"

    set -l foot_cfg "$config_home/foot/foot.ini"
    set -l foot_theme "$config_home/foot/themes/theme.ini"

    set -l kitty_cfg "$config_home/kitty/kitty.conf"
    set -l kitty_theme "$config_home/kitty/themes/current-theme.conf"

    set -l fzf_theme "$config_home/fzf/current-theme"

    set -l cosmic_cfg "$config_home/cosmic/com.system76.CosmicTheme.Mode/v1/is_dark"

    set -l nvim_cfg "$config_home/nvim/lua/plugins/plugins.lua"

    set -l zathura_cfg "$config_home/zathura/zathurarc"
    set -l zathura_theme "$config_home/zathura/current-theme"

    set -l git_cfg "$config_home/git/delta.gitconfig"

    set -l zellij_cfg "$config_home/zellij/config.kdl"

    set -l television_theme "$config_home/television/themes/current-theme.toml"

    set -l wallpaper_cfgs \
        "$config_home/cosmic/com.system76.CosmicBackground/v1/output.eDP-1" \
        "$config_home/cosmic/com.system76.CosmicBackground/v1/output.DP-5" \
        "$config_home/cosmic/com.system76.CosmicBackground/v1/output.HDMI-A-1" \
        "$config_home/cosmic/com.system76.CosmicBackground/v1/all"

    log_info "Change alacritty..."
    link_theme "$config_home/alacritty/themes/$catppuccin.toml" "$alacritty_theme"
    touch_if_file "$alacritty_cfg"

    log_info "Change foot..."
    link_theme "$config_home/foot/themes/$catppuccin.ini" "$foot_theme"
    touch_if_file "$foot_cfg"

    set foot_mode dark
    test "$catppuccin" = catppuccin-latte; and set foot_mode light
    sd 'initial-color-theme=(light|dark)' "initial-color-theme=$foot_mode" "$foot_cfg"

    log_info "Change gitui..."
    link_theme "$config_home/gitui/$catppuccin.ron" "$gitui_theme"
    touch_if_file "$gitui_theme"

    log_info "Change fish..."
    fish_config theme choose $fish_theme

    log_info "Change fzf..."
    link_theme "$config_home/fzf/$catppuccin" "$fzf_theme"

    log_info "Change zathura..."
    link_theme "$config_home/zathura/$catppuccin" "$zathura_theme"
    touch_if_file "$zathura_cfg"

    log_info "Change kitty..."
    link_theme "$config_home/kitty/themes/$catppuccin.conf" "$kitty_theme"
    touch_if_file "$kitty_cfg"

    log_info "Change git..."
    replace_if_file "$other_catppuccin" "$catppuccin" "$git_cfg"

    log_info "Change cosmic..."
    replace_if_file "$other_cosmic_value" "$cosmic_value" "$cosmic_cfg"

    log_info "Change neovim..."
    replace_if_file "$other_catppuccin" "$catppuccin" "$nvim_cfg"

    log_info "Change zellij..."
    replace_if_file "$other_catppuccin" "$catppuccin" "$zellij_cfg"

    log_info "Change television..."
    link_theme "$config_home/television/themes/$catppuccin.toml" "$television_theme"

    log_info "Change wallpaper..."
    for cfg in $wallpaper_cfgs
        replace_if_file "$wallpaper_from" "$wallpaper_to" "$cfg"
    end

    log_info "Rebuilding bat cache..."
    command bat cache --build > /dev/null

    log_info "Changing GNOME settings..."
    gsettings set org.gnome.desktop.interface color-scheme "$gnome_scheme"

    log_info "Changing darkman..."
    if command -sq darkman
        darkman set "$theme" > /dev/null
    else
        log_warn "Missing command: darkman"
    end
end

switch_theme
