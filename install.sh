#!/bin/bash
# Animal Kill Clock -- macOS one-line installer.
#
#   curl -fsSL https://raw.githubusercontent.com/BaesTheorem/animal-kill-clock/main/install.sh | bash
#
# Why this never trips Gatekeeper: Gatekeeper only inspects files carrying the
# com.apple.quarantine attribute, which browsers and mail clients stamp onto
# downloads. Nothing here is a downloaded executable -- this script fetches the
# SOURCE (readable text) and assembles the .app on your machine, so the bundle
# is a locally created file with no quarantine attribute and nothing to warn
# about. That is the same trust model as Homebrew: you are trusting source you
# can read, not a binary somebody else built.
#
# What it does, in order:
#   1. installs uv (the Python runner) into ~/.local if you don't have it
#   2. fetches this repo's source into ~/.local/share/animal-kill-clock
#   3. builds "Animal Kill Clock.app" into /Applications (AKC_APP_DIR overrides)
#   4. pre-installs the Python dependencies so first launch is instant
#   5. launches the widget
#
# Re-running updates in place. Uninstall:
#   rm -rf /Applications/"Animal Kill Clock.app" ~/.local/share/animal-kill-clock \
#          ~/Library/Application\ Support/AnimalKillClock \
#          ~/Library/LaunchAgents/org.animalclock.widget.plist
set -euo pipefail

REPO="BaesTheorem/animal-kill-clock"
HOME_DIR="${AKC_HOME:-$HOME/.local/share/animal-kill-clock}"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }

case "$(uname -s)" in
  Darwin) ;;
  *) echo "This installer is for macOS. On Windows, see windows/README.md." >&2
     exit 1 ;;
esac

# --- 1. uv ------------------------------------------------------------------
UV="$(command -v uv || true)"
[ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
if [ -z "$UV" ]; then
  say "Installing uv (Python runner, goes in ~/.local/bin)"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  UV="$HOME/.local/bin/uv"
fi
export UV

# --- 2. source --------------------------------------------------------------
say "Fetching the source into $HOME_DIR"
rm -rf "$HOME_DIR"
mkdir -p "$HOME_DIR"
curl -fsSL "https://github.com/$REPO/tarball/main" \
  | tar xz -C "$HOME_DIR" --strip-components=1

# --- 3. build the app locally ----------------------------------------------
say "Building Animal Kill Clock.app (no download, no quarantine, no warning)"
bash "$HOME_DIR/macos/make-app.sh"

# --- 4. pre-warm dependencies ----------------------------------------------
say "Preparing Python dependencies (one-time, ~30s)"
"$UV" run --script "$HOME_DIR/macos/widget_app.py" --prewarm

# --- 5. launch --------------------------------------------------------------
if [ -z "${AKC_NO_LAUNCH:-}" ]; then
  say "Launching. Look for the card on your desktop and 'Kill Clock' in the menu bar."
  open -a "Animal Kill Clock" || open "${AKC_APP_DIR:-/Applications}/Animal Kill Clock.app"
fi
say "Done."
