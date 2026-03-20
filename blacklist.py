import urllib.request as request
from urllib.error import URLError
from pwn import log
from pathlib import Path
import tempfile

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

LOCALS = (
    "127.0.0.1 ",
    "255.255.255.255 ",
    "::1 ",
    "fe80::",
    "ff80::",
    "ff00::",
    "ff02::",
)


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
                with request.urlopen(url) as response:
                    content = response.read().decode("utf-8")
                    outfile.write(content)
                    log.success(f"Processed '{name}'.")
            except URLError as e:
                log.failure(f"Error downloading {url}: {e}")
            except UnicodeDecodeError as e:
                log.failure(f"Error decoding content from {url}: {e}")
    log.success(f"Content concatenated into {file}")


def cleanup_names(file: str) -> None:
    path = Path(file)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp_dir:
        tmp_path = Path(tmp_dir) / path.name
        with path.open("r") as in_fd, tmp_path.open("w") as out_fd:
            for line in in_fd:
                line = line.split("#", 1)[0]
                if line.startswith(LOCALS):
                    continue
                line = line.replace("0.0.0.0 ", "")
                line = line.replace("  ", "").replace("\n", "")
                if line.strip() and line != "0.0.0.0":
                    out_fd.write(f"{line}\n")
        tmp_path.replace(path)
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
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "tmp"
        add_tlds(TLDS, str(tmp_path))
        dl_cat(LISTS, str(tmp_path))
        cleanup_names(str(tmp_path))
        remove_duplicates(str(tmp_path), "blocked-names.txt")
        add_llms(LLMS, "blocked-names.txt")


if __name__ == "__main__":
    main()
