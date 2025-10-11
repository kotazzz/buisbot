from pathlib import Path

PATH = "."
OUTPUT = "output.txt"

# Черный список файлов и папок, которые нужно исключить
blacklist = [
    "packer.py",
    "output.txt",
    ".git",
    "*.pyc",
    "uv.lock",
    ".gitignore",
]

# Список дополнительных файлов, которые нужно добавить в конце
extra_files = [
    "Makefile"
]

with open(OUTPUT, "w", encoding="utf-8") as out:
    # Рекурсивно все файлы из PATH
    for file in Path(PATH).rglob("*"):
        if file.is_file() and not any(file.match(pattern) for pattern in blacklist) and ".git" not in file.parts:
            rel_path = "/" + str(file.as_posix())
            out.write(f"{rel_path}\n")
            out.write("```\n")
            print("Reading", file)
            out.write(file.read_text(encoding="utf-8"))
            out.write("```\n\n")
    
    # Дополнительные файлы
    for file in extra_files:
        if not any(Path(file).match(pattern) for pattern in blacklist):
            p = Path(file)
            if p.is_file():
                rel_path = "/" + str(p.as_posix())
                out.write(f"{rel_path}\n")
                out.write("```\n")
                out.write(p.read_text(encoding="utf-8"))
                out.write("```\n\n")
