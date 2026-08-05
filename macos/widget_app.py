# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyobjc-framework-Cocoa",
#   "pyobjc-framework-WebKit",
#   "pyobjc-framework-Quartz",
# ]
# ///
"""
Animal Kill Clock -- a macOS desktop widget.

Hosts widget.html in a borderless, shadowless WKWebView window that sits at the
desktop window level: above the wallpaper, below the desktop icons and every
normal window. That is what makes it a widget you *pin* rather than another
window you have to manage -- it never covers anything, never appears in Cmd-Tab,
never follows you between Spaces, and does not need a Dock tile.

Run directly:   uv run --script widget_app.py
Or double-click "Animal Kill Clock.app" (see make-app.sh).

Everything is driven from a menu bar item; settings persist to
~/Library/Application Support/AnimalKillClock/config.json.
"""

import json
import os
import signal
import sys

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSObject,
    NSScreen,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWorkspace,
)
from Foundation import NSURL, NSTimer
from Quartz import (
    CGWindowLevelForKey,
    kCGDesktopWindowLevelKey,
    kCGMaximumWindowLevelKey,
)
from WebKit import (
    WKUserScript,
    WKUserScriptInjectionTimeAtDocumentStart,
    WKWebView,
    WKWebViewConfiguration,
)

HERE = os.path.dirname(os.path.abspath(__file__))
WIDGET = os.path.normpath(os.path.join(HERE, "..", "widget.html"))

SUPPORT = os.path.expanduser("~/Library/Application Support/AnimalKillClock")
CONFIG = os.path.join(SUPPORT, "config.json")

AGENT_LABEL = "org.animalclock.widget"
AGENT_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{AGENT_LABEL}.plist")

# Anchors are (horizontal, vertical) in screen terms. The widget's own CSS also
# takes an align value, but at these window sizes the card fills the window, so
# the anchor that matters is where the *window* goes on screen.
ANCHORS = [
    ("Top Left", "top-left"),
    ("Top", "top"),
    ("Top Right", "top-right"),
    ("Left", "left"),
    ("Center", "center"),
    ("Right", "right"),
    ("Bottom Left", "bottom-left"),
    ("Bottom", "bottom"),
    ("Bottom Right", "bottom-right"),
]

REGIONS = [("United States", "us"), ("United Kingdom", "uk"),
           ("Canada", "ca"), ("Australia", "au")]

SIZES = [("Small", 380), ("Medium", 480), ("Large", 620), ("Extra Large", 820)]

MODES = [
    ("Pinned to Desktop", "desktop"),
    ("Float Above Windows", "float"),
    ("Normal Window", "normal"),
]

DEFAULTS = {
    "mode": "desktop",
    "region": "us",
    "theme": "light",
    "anchor": "top-right",
    "width": 480,
    "margin": 28,
    "compact": False,
    "frame": True,
    "screen": 0,
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG) as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(SUPPORT, exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, CONFIG)


def compact_number(n):
    """1_234_567_890 -> '1.23B'. Keeps the menu bar title a stable width."""
    for cut, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= cut:
            return f"{n / cut:.2f}{suffix}"
    return str(int(n))


class Widget(NSObject):
    # ------------------------------------------------------------------ setup
    def initWithConfig_(self, cfg):
        self = objc.super(Widget, self).init()
        if self is None:
            return None
        self.cfg = cfg
        self.buildWindow()
        self.buildStatusItem()
        self.apply()
        return self

    @objc.python_method
    def buildWindow(self):
        rect = NSMakeRect(0, 0, self.cfg["width"], 340)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setHasShadow_(False)
        self.window.setMovableByWindowBackground_(True)
        self.window.setReleasedWhenClosed_(False)

        conf = WKWebViewConfiguration.alloc().init()
        self.userContent = conf.userContentController()

        self.web = WKWebView.alloc().initWithFrame_configuration_(
            self.window.contentView().bounds(), conf
        )
        self.web.setAutoresizingMask_(1 << 1 | 1 << 4)  # width | height
        # Let the wallpaper show through the window's transparent margins.
        self.web.setValue_forKey_(False, "drawsBackground")
        self.window.contentView().addSubview_(self.web)
        self.window.orderFront_(None)

    @objc.python_method
    def buildStatusItem(self):
        bar = NSStatusBar.systemStatusBar()
        self.status = bar.statusItemWithLength_(NSVariableStatusItemLength)
        self.status.button().setTitle_("Kill Clock")
        self.status.setMenu_(self.buildMenu())

        # The menu bar carries the live total too, so the count is readable even
        # when a full-screen window is covering the desktop the widget lives on.
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0, self, b"tick:", None, True
        )

    # ------------------------------------------------------------------- menu
    @objc.python_method
    def _item(self, title, action, rep, state=False):
        # `action` is a selector NAME (b"setMode:"). Wrapping a bound method in
        # objc.selector() here makes a fresh, unbound selector that the menu
        # cannot dispatch -- the item renders but clicking it does nothing.
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, action, ""
        )
        it.setTarget_(self)
        it.setRepresentedObject_(rep)
        it.setState_(1 if state else 0)
        return it

    @objc.python_method
    def _submenu(self, parent, title, options, action, current):
        head = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        sub = NSMenu.alloc().init()
        for label, value in options:
            sub.addItem_(self._item(label, action, value, value == current))
        head.setSubmenu_(sub)
        parent.addItem_(head)

    @objc.python_method
    def buildMenu(self):
        m = NSMenu.alloc().init()
        m.setAutoenablesItems_(False)

        self.countItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "--", None, ""
        )
        self.countItem.setEnabled_(False)
        m.addItem_(self.countItem)
        m.addItem_(NSMenuItem.separatorItem())

        self._submenu(m, "Display", MODES, b"setMode:", self.cfg["mode"])
        self._submenu(m, "Region", REGIONS, b"setRegion:", self.cfg["region"])
        self._submenu(m, "Position", ANCHORS, b"setAnchor:", self.cfg["anchor"])
        self._submenu(m, "Size", [(n, str(w)) for n, w in SIZES],
                      b"setWidth:", str(self.cfg["width"]))
        self._submenu(m, "Theme", [("Light", "light"), ("Dark", "dark")],
                      b"setTheme:", self.cfg["theme"])

        if len(NSScreen.screens()) > 1:
            screens = [(f"Display {i + 1}", str(i))
                       for i in range(len(NSScreen.screens()))]
            self._submenu(m, "Screen", screens, b"setScreen:",
                          str(self.cfg["screen"]))

        m.addItem_(NSMenuItem.separatorItem())
        m.addItem_(self._item("Just the Number", b"toggleCompact:", "",
                              self.cfg["compact"]))
        m.addItem_(self._item("Show Border", b"toggleFrame:", "",
                              self.cfg["frame"]))
        m.addItem_(self._item("Open at Login", b"toggleLogin:", "",
                              os.path.exists(AGENT_PLIST)))

        m.addItem_(NSMenuItem.separatorItem())
        m.addItem_(self._item("Open animalclock.org", b"openSite:", ""))
        quit_ = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", b"quit:", "q"
        )
        quit_.setTarget_(self)
        m.addItem_(quit_)
        return m

    @objc.python_method
    def refreshMenu(self):
        self.status.setMenu_(self.buildMenu())

    # ----------------------------------------------------------------- apply
    @objc.python_method
    def apply(self):
        """Push the whole config to the window and reload the page."""
        cfg = self.cfg

        opts = {
            "region": cfg["region"],
            "theme": cfg["theme"],
            "align": "center",
            "compact": "1" if cfg["compact"] else "0",
            "frame": "1" if cfg["frame"] else "0",
        }
        # loadFileURL: drops a query string, so hand the options to the page as a
        # global written before any of its own script runs.
        src = "window.__AKC_OPTS__ = %s;" % json.dumps(opts)
        self.userContent.removeAllUserScripts()
        self.userContent.addUserScript_(
            WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
                src, WKUserScriptInjectionTimeAtDocumentStart, True
            )
        )

        mode = cfg["mode"]
        if mode == "desktop":
            level = CGWindowLevelForKey(kCGDesktopWindowLevelKey)
            # Behind everything, so clicks belong to whatever is actually there.
            self.window.setIgnoresMouseEvents_(True)
        elif mode == "float":
            level = CGWindowLevelForKey(kCGMaximumWindowLevelKey) - 1
            self.window.setIgnoresMouseEvents_(False)
        else:
            level = 0
            self.window.setIgnoresMouseEvents_(False)
        self.window.setLevel_(level)

        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle
        )

        url = NSURL.fileURLWithPath_(WIDGET)
        self.web.loadFileURL_allowingReadAccessToURL_(
            url, NSURL.fileURLWithPath_(os.path.dirname(WIDGET))
        )
        self.place()
        # First pass for responsiveness; the repeating tick keeps correcting it.
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.45, self, b"sizeToContent:", None, False
        )

    def sizeToContent_(self, _):
        """Shrink-wrap the window to the card.

        The card's height is not knowable up front: it depends on the region
        (only the U.S. clock has a species table), on compact mode, and on
        whether the webfont has swapped in yet. So this is idempotent and runs on
        the repeating tick as well -- it no-ops until the measured height
        actually differs, and self-corrects after a late font load.
        """
        def done(value, error):
            if error is not None or value is None:
                return
            try:
                height = float(value)
            except (TypeError, ValueError):
                return
            frame = self.window.frame()
            if abs(frame.size.height - height) < 1:
                return
            frame.size.height = max(60.0, height)
            self.window.setFrame_display_(frame, True)
            self.place()

        self.web.evaluateJavaScript_completionHandler_(
            "document.getElementById('card').offsetHeight", done
        )

    @objc.python_method
    def place(self):
        screens = NSScreen.screens()
        idx = min(self.cfg["screen"], len(screens) - 1)
        vis = screens[idx].visibleFrame()
        frame = self.window.frame()
        w, h = self.cfg["width"], frame.size.height
        m = self.cfg["margin"]
        anchor = self.cfg["anchor"]

        if "left" in anchor:
            x = vis.origin.x + m
        elif "right" in anchor:
            x = vis.origin.x + vis.size.width - w - m
        else:
            x = vis.origin.x + (vis.size.width - w) / 2

        if anchor.startswith("top"):
            y = vis.origin.y + vis.size.height - h - m
        elif anchor.startswith("bottom"):
            y = vis.origin.y + m
        else:
            y = vis.origin.y + (vis.size.height - h) / 2

        self.window.setFrame_display_(NSMakeRect(x, y, w, h), True)

    @objc.python_method
    def update(self, **changes):
        self.cfg.update(changes)
        save_config(self.cfg)
        self.apply()
        self.refreshMenu()

    # --------------------------------------------------------------- actions
    def setMode_(self, sender):
        self.update(mode=sender.representedObject())

    def setRegion_(self, sender):
        self.update(region=sender.representedObject())

    def setAnchor_(self, sender):
        self.update(anchor=sender.representedObject())

    def setTheme_(self, sender):
        self.update(theme=sender.representedObject())

    def setWidth_(self, sender):
        self.update(width=int(sender.representedObject()))

    def setScreen_(self, sender):
        self.update(screen=int(sender.representedObject()))

    def toggleCompact_(self, sender):
        self.update(compact=not self.cfg["compact"])

    def toggleFrame_(self, sender):
        self.update(frame=not self.cfg["frame"])

    def openSite_(self, sender):
        NSWorkspace.sharedWorkspace().openURL_(
            NSURL.URLWithString_("https://animalclock.org")
        )

    def toggleLogin_(self, sender):
        if os.path.exists(AGENT_PLIST):
            os.system(f"launchctl bootout gui/$(id -u)/{AGENT_LABEL} 2>/dev/null")
            os.remove(AGENT_PLIST)
        else:
            app = os.path.expanduser("~/Desktop/Apps/Animal Kill Clock.app")
            target = (f"{app}/Contents/MacOS/launch" if os.path.exists(app)
                      else os.path.abspath(__file__))
            os.makedirs(os.path.dirname(AGENT_PLIST), exist_ok=True)
            with open(AGENT_PLIST, "w") as fh:
                fh.write(LOGIN_PLIST.format(label=AGENT_LABEL, target=target))
            os.system(f"launchctl bootstrap gui/$(id -u) '{AGENT_PLIST}' 2>/dev/null")
        self.refreshMenu()

    def tick_(self, _):
        self.sizeToContent_(None)

        def done(value, error):
            if error is None and value is not None:
                try:
                    n = float(value)
                except (TypeError, ValueError):
                    return
                self.countItem.setTitle_(f"{int(n):,} this year")
                self.status.button().setTitle_(compact_number(n))

        self.web.evaluateJavaScript_completionHandler_(
            "parseInt((document.getElementById('count').textContent||'0')"
            ".replace(/,/g,''),10)||0",
            done,
        )

    def quit_(self, sender):
        NSApp().terminate_(self)


LOGIN_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{target}</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict>
</plist>
"""


def main():
    if not os.path.exists(WIDGET):
        sys.exit(f"widget.html not found next to the app: {WIDGET}")

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = NSApplication.sharedApplication()
    # Accessory: a menu bar item and a desktop window, no Dock tile, no Cmd-Tab
    # entry. A widget should not behave like an application you switch to.
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    widget = Widget.alloc().initWithConfig_(load_config())
    app.setDelegate_(widget)
    app.run()


if __name__ == "__main__":
    main()
