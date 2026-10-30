#!/bin/sh
# Builds the release files in one folder.
# Usage: tools/build-release.sh <output folder> <dictionary.sqlite3>
# The program is built in a Debian 11 container, so it runs on every system with glibc 2.30 or newer.
set -eu
out=$(mkdir -p "$1/target" && cd "$1" && pwd)
dictionary=$2
repo=$(cd "$(dirname "$0")/.." && pwd)

# --security-opt label=disable: SELinux hosts (Fedora) otherwise block the mounted source folder.
podman run --rm --security-opt label=disable \
    -v "$repo":/src:ro -v "$out/target":/target -e CARGO_TARGET_DIR=/target -w /src \
    docker.io/library/rust:1-bullseye cargo build --release --locked

cp "$out/target/release/krunner-translate" "$out/krunner-translate"
gzip -9 -c "$dictionary" > "$out/dictionary.sqlite3.gz"
(cd "$repo" && python3 -I tools/notices.py) > "$out/THIRD-PARTY-NOTICES"
# install.sh checks these two files. The notices file is only for readers.
(cd "$out" && sha256sum krunner-translate dictionary.sqlite3.gz > SHA256SUMS)
ls -l "$out/krunner-translate" "$out/dictionary.sqlite3.gz" "$out/THIRD-PARTY-NOTICES" "$out/SHA256SUMS"
