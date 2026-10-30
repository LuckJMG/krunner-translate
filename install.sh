#!/bin/sh
# Installs krunner-translate for the current user. Run it from the cloned repository: ./install.sh
# It downloads the prebuilt program and the dictionary from the GitHub release.
# If the prebuilt program does not run on this system, it builds the program with cargo.
# KRUNNER_TRANSLATE_BASE_URL replaces the download address (for tests, for example file:///path/to/release).
set -eu
BASE=${KRUNNER_TRANSLATE_BASE_URL:-https://github.com/LuckJMG/krunner-translate/releases/download/v0.1-beta}
repo=$(cd "$(dirname "$0")" && pwd)
data=${XDG_DATA_HOME:-$HOME/.local/share}

for tool in curl sha256sum gzip; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool. Install it and run this script again." >&2; exit 1; }
done
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Downloading from $BASE"
curl -fL --progress-bar -o "$tmp/dictionary.sqlite3.gz" "$BASE/dictionary.sqlite3.gz"
curl -fsL -o "$tmp/SHA256SUMS" "$BASE/SHA256SUMS"
prebuilt=no
if [ "$(uname -m)" = x86_64 ]; then
    curl -fL --progress-bar -o "$tmp/krunner-translate" "$BASE/krunner-translate"
    chmod +x "$tmp/krunner-translate"
    # Without krunner-translate in the folder, --ignore-missing skips its line. A broken download still fails.
    (cd "$tmp" && sha256sum --ignore-missing -c SHA256SUMS)
    # ldd prints "not found" for a library or a glibc version that this system does not have.
    if ! ldd "$tmp/krunner-translate" 2>&1 | grep -q 'not found'; then
        prebuilt=yes
    fi
else
    (cd "$tmp" && sha256sum --ignore-missing -c SHA256SUMS)
fi

mkdir -p "$HOME/.local/bin" "$data/krunner-translate" "$data/krunner/dbusplugins" "$data/dbus-1/services"
if [ "$prebuilt" = yes ]; then
    install -m 755 "$tmp/krunner-translate" "$HOME/.local/bin/krunner-translate"
else
    echo "The prebuilt program does not run on this system. Building it with cargo."
    command -v cargo >/dev/null || { echo "Missing tool: cargo. Install Rust from https://rustup.rs and run this script again." >&2; exit 1; }
    cargo install --path "$repo" --locked --root "$HOME/.local"
fi
# gzip writes to a new file first, so a failed decompression does not damage an installed dictionary.
gzip -dc "$tmp/dictionary.sqlite3.gz" > "$data/krunner-translate/dictionary.sqlite3.new"
mv "$data/krunner-translate/dictionary.sqlite3.new" "$data/krunner-translate/dictionary.sqlite3"
install -m 644 "$repo/install/krunner-translate.desktop" "$data/krunner/dbusplugins/krunner-translate.desktop"
sed "s|@HOME@|$HOME|" "$repo/install/net.krunnertranslate.runner.service" > "$data/dbus-1/services/net.krunnertranslate.runner.service"

# KRunner starts again when needed.
kquitapp6 krunner 2>/dev/null || true

echo
echo "Installed. Open KRunner and type: tr house"
echo
echo "WARNING: AI wrote all of this project. The AI origin does not excuse faults in it."
echo "Keep this in mind before you rely on the translations or on the program."
