#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Final, Literal

FlavorName = Literal["latte", "mocha"]
Appearance = Literal["light", "dark"]


@dataclass(frozen=True)
class Rule:
    line_type: str
    pattern: re.Pattern[str]
    replacement: str


def esc(code: str) -> str:
    return f"\033[{code}m"


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.removeprefix("#")
    if len(value) != 6:
        raise ValueError(f"expected #rrggbb color, got {hex_color!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def fg(hex_color: str) -> str:
    r, g, b = hex_to_rgb(hex_color)
    return esc(f"38;2;{r};{g};{b}")


def bg(hex_color: str) -> str:
    r, g, b = hex_to_rgb(hex_color)
    return esc(f"48;2;{r};{g};{b}")


RESET: Final = esc("0")
BOLD: Final = esc("1")

CATPPUCCIN: Final[dict[FlavorName, dict[str, str]]] = {
    "latte": {
        "rosewater": "#dc8a78",
        "flamingo": "#dd7878",
        "pink": "#ea76cb",
        "mauve": "#8839ef",
        "red": "#d20f39",
        "maroon": "#e64553",
        "peach": "#fe640b",
        "yellow": "#df8e1d",
        "green": "#40a02b",
        "teal": "#179299",
        "sky": "#04a5e5",
        "sapphire": "#209fb5",
        "blue": "#1e66f5",
        "lavender": "#7287fd",
        "text": "#4c4f69",
        "subtext1": "#5c5f77",
        "subtext0": "#6c6f85",
        "overlay2": "#7c7f93",
        "overlay1": "#8c8fa1",
        "overlay0": "#9ca0b0",
        "surface2": "#acb0be",
        "surface1": "#bcc0cc",
        "surface0": "#ccd0da",
        "base": "#eff1f5",
        "mantle": "#e6e9ef",
        "crust": "#dce0e8",
    },
    "mocha": {
        "rosewater": "#f5e0dc",
        "flamingo": "#f2cdcd",
        "pink": "#f5c2e7",
        "mauve": "#cba6f7",
        "red": "#f38ba8",
        "maroon": "#eba0ac",
        "peach": "#fab387",
        "yellow": "#f9e2af",
        "green": "#a6e3a1",
        "teal": "#94e2d5",
        "sky": "#89dceb",
        "sapphire": "#74c7ec",
        "blue": "#89b4fa",
        "lavender": "#b4befe",
        "text": "#cdd6f4",
        "subtext1": "#bac2de",
        "subtext0": "#a6adc8",
        "overlay2": "#9399b2",
        "overlay1": "#7f849c",
        "overlay0": "#6c7086",
        "surface2": "#585b70",
        "surface1": "#45475a",
        "surface0": "#313244",
        "base": "#1e1e2e",
        "mantle": "#181825",
        "crust": "#11111b",
    },
}


def normalize_flavor(value: str) -> FlavorName | None:
    normalized = value.strip().lower().replace("catppuccin-", "")
    if normalized in ("latte", "light"):
        return "latte"
    if normalized in ("mocha", "dark"):
        return "mocha"
    return None


def command_result(
    command: tuple[str, ...], timeout: float = 0.5
) -> tuple[int, str] | None:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    return completed.returncode, completed.stdout.strip().strip("'\"")


def appearance_from_text(value: str) -> Appearance | None:
    normalized = value.strip().lower()
    if not normalized:
        return None
    if "prefer-dark" in normalized or "dark" in normalized or "night" in normalized:
        return "dark"
    if "prefer-light" in normalized or "light" in normalized:
        return "light"
    return None


def detect_gnome_appearance() -> Appearance | None:
    gtk_theme = command_result(
        ("gsettings", "get", "org.gnome.desktop.interface", "gtk-theme")
    )
    if gtk_theme is not None:
        appearance = appearance_from_text(gtk_theme[1])
        if appearance is not None:
            return appearance

    color_scheme = command_result(
        ("gsettings", "get", "org.gnome.desktop.interface", "color-scheme")
    )
    if color_scheme is not None:
        appearance = appearance_from_text(color_scheme[1])
        if appearance is not None:
            return appearance
        if color_scheme[1].strip().lower() == "default":
            return "light"

    return None


def detect_system_appearance() -> Appearance | None:
    return detect_gnome_appearance()


def select_flavor() -> FlavorName:
    for env_var in ("COLOR_OBJDUMP_THEME", "CATPPUCCIN_FLAVOR"):
        value = os.environ.get(env_var)
        if value is None:
            continue
        flavor = normalize_flavor(value)
        if flavor is not None:
            return flavor

    appearance = detect_system_appearance()
    if appearance == "light":
        return "latte"
    if appearance == "dark":
        return "mocha"
    return "mocha"


PALETTE: Final = CATPPUCCIN[select_flavor()]

ADDR_FG: Final = fg(PALETTE["overlay1"])
BRACKET_FG: Final = fg(PALETTE["overlay2"])
SYMBOL_FG: Final = fg(PALETTE["green"])
COMMENT_FG: Final = fg(PALETTE["mauve"])
IMMEDIATE_FG: Final = fg(PALETTE["peach"])
FILENAME_FG: Final = fg(PALETTE["blue"])
FILE_LINE_FG: Final = fg(PALETTE["sapphire"])
FALLBACK_FG: Final = fg(PALETTE["subtext0"])
FALLBACK_BG: Final = bg(PALETTE["surface0"])
MNEMONIC_FG: Final = fg(PALETTE["yellow"])
SECTION_STYLE: Final = f"{bg(PALETTE['mauve'])}{fg(PALETTE['base'])}"
HEADER_FG: Final = fg(PALETTE["rosewater"])

LT: Final = f"{BRACKET_FG}{BOLD}<{RESET}"
GT: Final = f"{BRACKET_FG}{BOLD}>{RESET}"

HEX_ADDRESS: Final = r"[0-9a-f]+"
SYMBOL_NAME: Final = r"[a-zA-Z_@.][a-zA-Z0-9_@.]*"
ANSI_GAP: Final = r"[\s\\/|,\-+>'\[m0-9;\033]+"
MNEMONIC: Final = r"[a-z][a-z0-9.]*"
CODE_CONTEXT_LINE_TYPES: Final = frozenset(("file spec", "code"))

RULES: Final[tuple[Rule, ...]] = (
    Rule(
        "id",
        re.compile(rf"^({HEX_ADDRESS}) <({SYMBOL_NAME})>:$"),
        rf"{ADDR_FG}\1{RESET} {LT}{SYMBOL_FG}\2{RESET}{GT}:",
    ),
    Rule(
        "id",
        re.compile(rf"^({HEX_ADDRESS}) <({SYMBOL_NAME})(\+|-)0x([0-9a-f]+)>:$"),
        rf"{ADDR_FG}\1{RESET} {LT}{SYMBOL_FG}\2{RESET}\3{IMMEDIATE_FG}0x\4{RESET}{GT}:",
    ),
    Rule(
        "func spec",
        re.compile(rf"^({SYMBOL_NAME})\("),
        rf"{SYMBOL_FG}\1{RESET}(",
    ),
    Rule(
        "instruction",
        re.compile(
            rf"^(\s*)({HEX_ADDRESS}):"
            rf"({ANSI_GAP})"
            rf"(([0-9a-f]{{2}}\s)+\s*)"
            rf"(({MNEMONIC})\b)"
        ),
        rf"\1\2:\3\4{MNEMONIC_FG}\6{RESET}",
    ),
    Rule(
        "instruction",
        re.compile(rf"^(\s*)({HEX_ADDRESS}):"),
        rf"\1{ADDR_FG}\2{RESET}:",
    ),
    Rule(
        "instruction",
        re.compile(rf"#\s({HEX_ADDRESS}) <({SYMBOL_NAME})>"),
        rf"{COMMENT_FG}#{RESET} {ADDR_FG}\1{RESET} {LT}{SYMBOL_FG}\2{RESET}{GT}",
    ),
    Rule(
        "instruction",
        re.compile(rf"#\s({HEX_ADDRESS}) <({SYMBOL_NAME})\+0x([0-9a-f]+)>"),
        rf"{COMMENT_FG}#{RESET} {ADDR_FG}\1{RESET} {LT}{SYMBOL_FG}\2{RESET}+{IMMEDIATE_FG}0x\3{RESET}{GT}",
    ),
    Rule(
        "file spec",
        re.compile(r"^([^:\n]+):(\d+)( \(.*\))?$"),
        rf"{FILENAME_FG}\1{RESET}:{FILE_LINE_FG}\2{RESET}\3",
    ),
    Rule(
        "section spec",
        re.compile(r"^(Disassembly of section \..*:)$"),
        rf"{SECTION_STYLE}\1{RESET}",
    ),
    Rule(
        "header",
        re.compile(r"^(.*):(\s*)file format (.*)$"),
        rf"{BOLD}{HEADER_FG}\1{RESET}{BOLD}:\2file format {HEADER_FG}\3{RESET}",
    ),
)


def handle_broken_pipe() -> int:
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, sys.stdout.fileno())
    finally:
        os.close(devnull)
    return 1


def style_line(line: str, last_line_type: str | None) -> tuple[str, str | None]:
    matched_regular_rule = False
    for rule in RULES:
        line, replacements = rule.pattern.subn(rule.replacement, line)
        if replacements:
            matched_regular_rule = True
            last_line_type = rule.line_type
    if not matched_regular_rule and (
        line.strip() or last_line_type in CODE_CONTEXT_LINE_TYPES
    ):
        line = f"{FALLBACK_BG} {RESET} {FALLBACK_FG}{line}{RESET}"
        last_line_type = "code"
    return line, last_line_type


def main() -> int:
    last_line_type: str | None = None
    try:
        for line in sys.stdin:
            styled_line, last_line_type = style_line(line, last_line_type)
            sys.stdout.write(styled_line)
        sys.stdout.flush()
        return 0
    except BrokenPipeError:
        return handle_broken_pipe()


if __name__ == "__main__":
    raise SystemExit(main())
