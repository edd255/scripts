#!/usr/bin/env fish

set SSH_KEYS_TO_AUTOLOAD \
    $HOME/.ssh/... \

eval (keychain --dir "$XDG_RUNTIME_DIR" --absolute --eval --quiet)
set -x DISPLAY :0
set -x SSH_ASKPASS "$HOME/.local/bin/ssh_pass.fish"
for key in $SSH_KEYS_TO_AUTOLOAD
    set -x SSH_KEY_BEING_ADDED $key
    setsid ssh-add $key < /dev/null
end
