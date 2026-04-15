#!/usr/bin/env fish

if not set -q ZELLIJ_SESSION_NAME
    echo "error: run this from inside an attached zellij session (ZELLIJ_SESSION_NAME is not set)" >&2
    exit 1
end

set -l tab_list (zellij action query-tab-names 2>/dev/null | string collect)
or begin
    echo "error: failed to query tab names (is zellij running, and does it support query-tab-names?)" >&2
    exit 1
end

# Count tabs robustly (counts lines even if some are empty).
set -l n (printf '%s' "$tab_list" | awk 'END{print NR}')

if test "$n" -lt 1
    echo "error: no tabs found" >&2
    exit 1
end

for i in (seq 1 "$n")
    zellij action go-to-tab "$i" >/dev/null 2>&1
    zellij action rename-tab "#$i" >/dev/null 2>&1
end
