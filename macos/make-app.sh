#!/bin/zsh
# Build (or rebuild) "Animal Kill Clock.app" -- a double-clickable launcher for
# widget_app.py. Idempotent: run it again any time to pick up code changes.
#
# The bundle is deliberately thin. It is an LSUIElement (accessory) app: no Dock
# tile, no Cmd-Tab entry, no menu bar of its own -- just the desktop window and a
# status item. That sidesteps the Dock-tile identity problem that forces heavier
# bundles elsewhere, because there is no tile to bind in the first place. The
# launcher shells out to `uv run --script`, which resolves the pinned deps from
# the header of widget_app.py and caches them after the first run.
set -e

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
APP="${AKC_APP_DIR:-/Applications}/Animal Kill Clock.app"
UV="${UV:-$HOME/.local/bin/uv}"

[ -x "$UV" ] || UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  echo "uv not found. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

echo "Building $APP ..."
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# ---------------------------------------------------------------- launcher ---
cat > "$APP/Contents/MacOS/launch" <<LAUNCH
#!/bin/zsh
# Only ever one widget: a second copy would stack an identical card on the first.
pkill -f 'widget_app\.py' 2>/dev/null || true
exec "$UV" run --script "$PROJ/macos/widget_app.py"
LAUNCH
chmod +x "$APP/Contents/MacOS/launch"

# ------------------------------------------------------------------ plist ----
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Animal Kill Clock</string>
  <key>CFBundleDisplayName</key><string>Animal Kill Clock</string>
  <key>CFBundleIdentifier</key><string>org.animalclock.widget</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# ------------------------------------------------------------------- icon ----
# Best effort: the app works fine without one, so never fail the build over it.
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
if python3 -c "import playwright" 2>/dev/null; then
  echo "  rendering icon ..."
  python3 - "$PROJ/macos/icon.html" "$ICONSET/icon_512x512@2x.png" <<'PY' || true
import sys
from playwright.sync_api import sync_playwright
src, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1024, "height": 1024})
    pg.goto("file://" + src)
    pg.wait_for_timeout(1500)
    pg.screenshot(path=out)
    b.close()
PY
fi

if [ -f "$ICONSET/icon_512x512@2x.png" ]; then
  for s in 16 32 128 256 512; do
    sips -z $s $s "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1
    sips -z $((s*2)) $((s*2)) "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || \
    echo "  (icon skipped)"
else
  echo "  (no icon: pip install playwright && playwright install chromium)"
fi
rm -rf "$(dirname "$ICONSET")"

# Nudge Finder/LaunchServices so the new bundle and icon are picked up at once.
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$APP" 2>/dev/null || true

echo "Done. Open it from Applications, then use the 'Kill Clock' menu bar item."
