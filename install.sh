#!/bin/sh
# Installs krunner-translate for the current user. Run it from the cloned repository: ./install.sh
# It downloads the prebuilt program and the dictionary from the GitHub release.
# If the prebuilt program does not run on this system, it builds the program with cargo.
# KRUNNER_TRANSLATE_BASE_URL replaces the download address (for tests, for example file:///path/to/release).
set -eu
BASE=${KRUNNER_TRANSLATE_BASE_URL:-https://github.com/LuckJMG/krunner-translate/releases/download/v0.5-beta}
repo=$(cd "$(dirname "$0")" && pwd)
data=${XDG_DATA_HOME:-$HOME/.local/share}

for tool in curl sha256sum gzip; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool. Install it and run this script again." >&2; exit 1; }
done
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# An existing dictionary can hold languages that the user added. This script never replaces it.
dictionary=$data/krunner-translate/dictionary.sqlite3
[ -f "$dictionary" ] && keep=yes || keep=no
x86=no
[ "$(uname -m)" = x86_64 ] && x86=yes

echo "Downloading from $BASE"
curl -fsL -o "$tmp/SHA256SUMS" "$BASE/SHA256SUMS"
if [ "$keep" = no ]; then
    curl -fL --progress-bar -o "$tmp/dictionary.sqlite3.gz" "$BASE/dictionary.sqlite3.gz"
fi
if [ "$x86" = yes ]; then
    curl -fL --progress-bar -o "$tmp/krunner-translate" "$BASE/krunner-translate"
    chmod +x "$tmp/krunner-translate"
fi
if [ "$keep" = no ] || [ "$x86" = yes ]; then
    # --ignore-missing skips the files that this run does not download. A broken download still fails.
    (cd "$tmp" && sha256sum --ignore-missing -c SHA256SUMS)
fi
prebuilt=no
# ldd prints "not found" for a library or a glibc version that this system does not have.
if [ "$x86" = yes ] && ! ldd "$tmp/krunner-translate" 2>&1 | grep -q 'not found'; then
    prebuilt=yes
fi

mkdir -p "$HOME/.local/bin" "$data/krunner-translate" "$data/krunner/dbusplugins" "$data/dbus-1/services"
if [ "$prebuilt" = yes ]; then
    install -m 755 "$tmp/krunner-translate" "$HOME/.local/bin/krunner-translate"
else
    echo "The prebuilt program does not run on this system. Building it with cargo."
    command -v cargo >/dev/null || { echo "Missing tool: cargo. Install Rust from https://rustup.rs and run this script again." >&2; exit 1; }
    cargo install --path "$repo" --locked --root "$HOME/.local"
fi
if [ "$keep" = no ]; then
    # gzip writes to a new file first, so a failed decompression does not leave half a dictionary.
    gzip -dc "$tmp/dictionary.sqlite3.gz" > "$dictionary.new"
    mv "$dictionary.new" "$dictionary"
else
    echo "Keeping your dictionary ($dictionary). To get new data, run: krunner-translate update. To reset it, delete the file and run this script again."
fi
install -m 644 "$repo/install/krunner-translate.desktop" "$data/krunner/dbusplugins/krunner-translate.desktop"
sed "s|@HOME@|$HOME|" "$repo/install/net.krunnertranslate.runner.service" > "$data/dbus-1/services/net.krunnertranslate.runner.service"

# KRunner starts again when needed.
kquitapp6 krunner 2>/dev/null || true

echo
echo "Installed. Open KRunner and type: tr house"
echo
echo "WARNING: AI wrote all of this project. The AI origin does not excuse faults in it."
echo "Keep this in mind before you rely on the translations or on the program."
