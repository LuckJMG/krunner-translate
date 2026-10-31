# krunner-translate

A KRunner plugin that translates words and phrases. It works offline. Type `tr house` in KRunner and press Enter on a row to copy the translation.

> **Warning: AI wrote all of this project.**
> The AI origin does not excuse faults in the code, the data, or this text.
> Faults can exist. Keep this in mind before you rely on the translations or on the program.

## What it does

- Translates between English and Spanish. These are the only languages in version 0.1 beta.
- Uses a local dictionary file. No query leaves your machine.
- Shows base forms. For `casas`, it also shows the result for `casa`.
- Groups the rows in sections, for example `house (en → es)`. The best match is first.
- Copies the translation to the clipboard when you press Enter.

## Requirements

- KDE Plasma 6. The plugin was tested on Plasma 6.7.5 only. Other versions can fail.
- Linux on x86-64 for the prebuilt program. On other machines, the install script builds the program with `cargo`.
- The tools `curl`, `sha256sum`, and `gzip`.
- About 90 MB of disk space for the dictionary.

## Install

Clone the repository and run the install script:

```sh
git clone https://github.com/LuckJMG/krunner-translate.git
cd krunner-translate
./install.sh
```

The script downloads the program and the dictionary from the release, and it compares their SHA-256 checksums. If the prebuilt program does not run on your system, the script builds it with `cargo`. For that, install Rust from <https://rustup.rs>.

The script installs these files in your home folder. It does not use `sudo`.

| File | Place |
|---|---|
| Program | `~/.local/bin/krunner-translate` |
| Dictionary | `~/.local/share/krunner-translate/dictionary.sqlite3` |
| KRunner descriptor | `~/.local/share/krunner/dbusplugins/krunner-translate.desktop` |
| D-Bus service | `~/.local/share/dbus-1/services/net.krunnertranslate.runner.service` |

If a dictionary file exists, the script keeps it, so the languages that you added stay. To reset the dictionary, delete the file and run the script again.

The script restarts KRunner. KRunner starts the program when you type `tr`. The program stops a few seconds after the last query.

## Use

Open KRunner and type `tr`, a space, and a word or phrase.

| Query | Result |
|---|---|
| `tr house` | Searches English to Spanish and Spanish to English. The best match is first. |
| `tr es: casa` | `es:` sets the source language. |
| `tr :es house` | `:es` sets the target language. |
| `tr en:es house` | Sets both languages. |
| `tr casa\: la` | `\:` writes a colon that is not a language marker. |

Only known language codes count as language markers. In any other case, the first word is part of the text.

Each section has a heading with the word, the direction, and the base form. Each row shows one translation. The gray text under the row is the meaning of the word. Press Enter on a row to copy the translation.

## Settings and commands

The main language and the second language decide the target of a query without language markers. The defaults are `en` and `es`. Use the commands in a terminal. The program is `~/.local/bin/krunner-translate`.

| Command | Result |
|---|---|
| `krunner-translate list` | Prints the settings file, the main language, the second language, and the installed languages. |
| `krunner-translate set main fr` | Sets the main language. The language must be installed. |
| `krunner-translate set second es` | Sets the second language. |
| `krunner-translate add` | Lists the available languages. |
| `krunner-translate add fr` | Downloads the language packs, and adds the language. The program shows the download size and asks first. |
| `krunner-translate update fr` | Downloads the packs of an installed language again, and replaces its data. It works for the main and the second language too. Use it after a fix in the packs. The program asks first. |
| `krunner-translate update --all` | Does the same for every installed language. You can also write `-a`. |
| `krunner-translate remove fr` | Removes a language, after a question. You cannot remove the main or the second language. |
| `krunner-translate help` | Prints the commands. |

If you set a language that is already the other one, the two languages swap. A change works at once. The settings are in `~/.config/krunner-translate/config.ini`.

## Languages

The dictionary has English and Spanish at the start. Other languages come in packs. Each pack is a file in the release `data-v1` of this repository. The packs are English, Spanish, and French. All three languages have base forms for verbs.

To add a language, run `krunner-translate add fr`. The program downloads the packs, checks their SHA-256, and adds them in one step. If a pack is wrong, nothing changes. A new language comes with the pairs to every installed language.

If you type a code that is not installed, such as `tr de: haus`, KRunner shows "Language de is not installed". A query without language markers searches only between the main and the second language. To search from another language, type its code, for example `tr fr: maison`.

## Uninstall

```sh
rm ~/.local/bin/krunner-translate
rm -r ~/.local/share/krunner-translate
rm ~/.local/share/krunner/dbusplugins/krunner-translate.desktop
rm ~/.local/share/dbus-1/services/net.krunnertranslate.runner.service
kquitapp6 krunner
```

## Build from source

Install Rust and a C compiler. Then run:

```sh
cargo build --release
cargo test
```

The tests use no dictionary file. To make the language packs and the dictionary file, read the header of `tools/build_packs.py`. It lists the files to download and the commands to run.

## Make a release (maintainers)

```sh
tools/build-release.sh <output folder> <dictionary.sqlite3>
```

The script builds the program in a Debian 11 container with `podman`, so the program runs on every system with glibc 2.30 or newer. It also compresses the dictionary and writes `SHA256SUMS` and `THIRD-PARTY-NOTICES`. The language packs come from `tools/build_packs.py packs`. Upload them to the release `data-v1`.

## Data and attribution

The dictionary file `dictionary.sqlite3` is made from these sources:

- Translations: [WikDict](https://www.wikdict.com) (English-Spanish and Spanish-English). WikDict data comes from Wiktionary and is under Creative Commons BY-SA.
- Spanish base forms: the Spanish Wiktionary data from [kaikki.org](https://kaikki.org). It comes from [Wiktionary](https://www.wiktionary.org) contributors and is under Creative Commons BY-SA.
- English base forms: WikDict.

`tools/build_packs.py` changes the data. It merges and filters the translations, keeps the best score for each word, and builds the tables of base forms. It writes one pack for each pair and each language. The `merge` command joins packs into the dictionary file.

The dictionary file is licensed under [Creative Commons Attribution-ShareAlike 4.0](https://creativecommons.org/licenses/by-sa/4.0/). WikDict does not state a license version on its site. The file is a changed copy of that data.

## License

Copyright (C) 2026 LuckJMG.

The program is free software under the GNU General Public License, version 3 or later. See `LICENSE`. The licenses of the Rust crates that the program links are in the file `THIRD-PARTY-NOTICES` of each release.

The dictionary file is not part of the program. Its license is in the section "Data and attribution".
