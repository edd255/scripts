import urllib.request
import urllib.error
from pwn import log
import os

LISTS = {
    "StevenBlack": "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/fakenews-gambling-porn-social/hosts",
    "1Hosts": "https://badmojr.github.io/1Hosts/Lite/hosts.txt",
}

LLMS = {
    "ChatGPT": "chatgpt.com",
    "Claude": "claude.ai",
    "Gemini": "gemini.google.com",
}

TLDS = {
    ".ru",
    ".su",
    ".xn--p1ai",
    ".xn--p1acf",
    ".cn",
    ".xn--fiqs8s",
    ".xn--55qx5d",
    ".xn--io0a7i",
    ".zip",
    ".mov",
    ".biz",
    ".click",
}


def remove_duplicates(in_file: str, out_file: str) -> None:
    seen = set()
    with open(out_file, "w") as out_fd, open(in_file, "r") as in_fd:
        for line in in_fd:
            if line not in seen:
                out_fd.write(line)
                seen.add(line)


def dl_cat(urls: dict[str, str], file: str) -> None:
    with open(file, "a") as outfile:
        for name, url in urls.items():
            try:
                with urllib.request.urlopen(url) as response:
                    content = response.read().decode("utf-8")
                    outfile.write(content)
                    log.success(f"Processed '{name}'.")
            except urllib.error.URLError as e:
                log.failure(f"Error downloading {url}: {e}")
            except UnicodeDecodeError as e:
                log.failure(f"Error decoding content from {url}: {e}")
    log.success(f"Content concatenated into {file}")


def cleanup_names(file: str) -> None:
    with open(file, "r") as fd:
        lines = fd.readlines()
    processed_lines = []
    for line in lines:
        line = line.split("#", 1)[0]
        if line.startswith(
            (
                "127.0.0.1 ",
                "255.255.255.255 ",
                "::1 ",
                "fe80::",
                "ff80::",
                "ff00::",
                "ff02::",
            )
        ):
            continue
        line = line.replace("0.0.0.0 ", "")
        line = line.replace("  ", "").replace("\n", "")
        if line.strip() and line != "0.0.0.0":
            processed_lines.append(f"{line}\n")
    with open(file, "w") as fd:
        fd.writelines(processed_lines)
    log.success(f"Processed 'names' file: {file}")


def add_llms(urls: dict[str, str], file: str) -> None:
    with open(file, "a") as fd:
        for name, url in urls.items():
            log.success(f"Processed '{name}'.")
            fd.write(f"{url}\n")


def add_tlds(tlds: set[str], file: str) -> None:
    with open(file, "a") as fd:
        for tld in tlds:
            log.success(f"Processed '{tld}'.")
            fd.write(f"*{tld}\n")


def main() -> None:
    add_llms(LLMS, "blocked-names.txt")
    add_tlds(TLDS, "tmp")
    dl_cat(LISTS, "tmp")
    cleanup_names("tmp")
    remove_duplicates("tmp", "blocked-names.txt")
    os.remove("tmp")


if __name__ == "__main__":
    main()
