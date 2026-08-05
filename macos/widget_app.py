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

Hosts widget.html in a borderless, shadowless WKWebView window pinned just above
the desktop icons and roughly two billion levels below every normal window. That
is what makes it a widget you *pin* rather than another window you have to
manage: it never covers anything you are working in, never appears in Cmd-Tab,
never follows you between Spaces, and does not need a Dock tile. It is still
high enough to receive clicks, so the card can be dragged where you want it.

Run directly:   uv run --script widget_app.py
Or double-click "Animal Kill Clock.app" (see make-app.sh).

Everything is driven from a menu bar item; settings persist to
~/Library/Application Support/AnimalKillClock/config.json.
"""

import json
import os
import signal
import sys
import threading
import time

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSCursor,
    NSEvent,
    NSMakePoint,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSObject,
    NSScreen,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSView,
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
    kCGDesktopIconWindowLevelKey,
    kCGDesktopWindowLevelKey,
    kCGMaximumWindowLevelKey,
)
from WebKit import (
    WKUserScript,
    WKUserScriptInjectionTimeAtDocumentStart,
    WKWebView,
    WKWebViewConfiguration,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync as syncmod  # noqa: E402  (needs the path above)

HERE = os.path.dirname(os.path.abspath(__file__))
WIDGET = os.path.normpath(os.path.join(HERE, "..", "widget.html"))

SUPPORT = os.path.expanduser("~/Library/Application Support/AnimalKillClock")
CONFIG = os.path.join(SUPPORT, "config.json")
SYNC_CACHE = os.path.join(SUPPORT, "sync.json")
SYNC_EVERY = 6 * 3600     # seconds between refreshes of the published figures

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
    ("Behind Desktop Icons", "wallpaper"),
    ("Float Above Windows", "float"),
    ("Normal Window", "normal"),
]

DEFAULTS = {
    "mode": "desktop",
    "region": "us",
    "theme": "light",
    "anchor": "top-right",
    # Set by dragging: [x, top] in screen coordinates, with `top` measured the
    # Cocoa way (from the bottom of the display). Storing the TOP edge rather
    # than the origin keeps the card from jumping when its height changes, since
    # a Cocoa frame grows upward from its origin.
    "pos": None,
    "width": 480,
    "margin": 28,
    "compact": False,
    "frame": True,
    # Repaint interval, ms. 2000 matches animalclock.org's own refresh so the
    # two read alike side by side; 250 counts the actual second more closely.
    "cadence": 2000,
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


DEBUG = os.environ.get("AKC_DEBUG")


def debug(msg):
    if not DEBUG:
        return
    with open("/tmp/akc-debug.log", "a") as fh:
        fh.write(msg + "\n")


class WidgetWindow(NSWindow):
    """A borderless window that can still take the keyboard and mouse.

    NSWindow returns False from canBecomeKeyWindow for borderless windows, and a
    window that can never become key does not get mouse events delivered to its
    views. Overriding it is what makes the card grabbable at all.
    """

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True


EDGE = 10.0     # width of the resize strip along each side, in points
SNAP = 14.0     # how close to a screen edge before the card sticks to it
MIN_W = 300.0
MAX_W = 1600.0


class DragView(NSView):
    """A transparent surface over the web view that moves and resizes the window.

    WKWebView consumes mouse events, so setMovableByWindowBackground: never
    fires and CSS -webkit-app-region (an Electron feature) does nothing here.
    Laying an ordinary NSView over the whole web view is the reliable way to get
    a grabbable card. The page underneath is display-only, so nothing is lost;
    its one link is duplicated in the menu.

    Grabbing within EDGE points of the left or right side resizes instead of
    moving. Only the width is draggable: the card's height is whatever its
    content needs at that width, so the window shrink-wraps to it afterwards.
    """

    def initWithFrame_(self, frame):
        self = objc.super(DragView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.owner = None
        self._grab = None
        self._frame0 = None
        self._edge = None       # None | "left" | "right"
        return self

    def acceptsFirstMouse_(self, event):
        # The widget is an accessory app that is usually not frontmost. Without
        # this, the first click would only bring it forward and the drag would
        # need a second click.
        return True

    # -- cursor feedback ----------------------------------------------------
    def resetCursorRects(self):
        b = self.bounds()
        grip = NSCursor.resizeLeftRightCursor()
        self.addCursorRect_cursor_(NSMakeRect(0, 0, EDGE, b.size.height), grip)
        self.addCursorRect_cursor_(
            NSMakeRect(b.size.width - EDGE, 0, EDGE, b.size.height), grip)

    # -- interaction --------------------------------------------------------
    def mouseDown_(self, event):
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        w = self.bounds().size.width
        self._edge = "left" if p.x <= EDGE else ("right" if p.x >= w - EDGE else None)
        self._grab = NSEvent.mouseLocation()
        self._frame0 = self.window().frame()
        debug("mouseDown edge=%s grab=%s" % (self._edge, self._grab))

    def mouseDragged_(self, event):
        if self._grab is None:
            return
        now = NSEvent.mouseLocation()
        dx = now.x - self._grab.x
        dy = now.y - self._grab.y
        f = self._frame0

        if self._edge:
            # Keep the edge you did NOT grab pinned, and the top edge pinned,
            # since the height is about to be recomputed from the content.
            if self._edge == "right":
                width = f.size.width + dx
            else:
                width = f.size.width - dx
            width = max(MIN_W, min(MAX_W, width))
            x = f.origin.x if self._edge == "right" else f.origin.x + f.size.width - width
            top = f.origin.y + f.size.height
            self.window().setFrame_display_(
                NSMakeRect(x, top - f.size.height, width, f.size.height), True)
            if self.owner is not None:
                self.owner.widthChanged(width)
            return

        self.window().setFrameOrigin_(
            self.owner.collide(f.origin.x + dx, f.origin.y + dy,
                               f.size.width, f.size.height)
            if self.owner is not None
            else NSMakePoint(f.origin.x + dx, f.origin.y + dy)
        )

    def mouseUp_(self, event):
        acted = self._grab is not None
        edge = self._edge
        self._grab = None
        self._edge = None
        debug("mouseUp acted=%s edge=%s" % (acted, edge))
        if acted and self.owner is not None:
            if edge:
                self.owner.widthSettled()
            self.owner.rememberPosition()


class Widget(NSObject):
    # ------------------------------------------------------------------ setup
    def initWithConfig_(self, cfg):
        self = objc.super(Widget, self).init()
        if self is None:
            return None
        self.cfg = cfg
        self.sync = syncmod.load_cache(SYNC_CACHE)
        self.syncing = False
        self.buildWindow()
        self.buildStatusItem()
        self.apply()
        self.maybeSync()
        return self

    # ------------------------------------------------------------------- sync
    @objc.python_method
    def maybeSync(self, force=False):
        """Refresh the published figures from animalclock.org, off the main thread.

        The cache on disk is what the widget actually draws from, so a failed or
        slow fetch costs nothing: the card is already on screen with the last
        good figures, or with the built-ins on a first run with no network.
        """
        if self.syncing:
            return
        age = time.time() - (self.sync or {}).get("fetchedAt", 0)
        if not force and age < SYNC_EVERY:
            return
        self.syncing = True

        def work():
            payload = None
            try:
                payload = syncmod.fetch_all()
            except Exception as exc:            # never let a fetch kill the app
                debug("sync failed: %r" % (exc,))
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                b"syncFinished:", payload, False
            )

        threading.Thread(target=work, daemon=True).start()

    def syncFinished_(self, payload):
        self.syncing = False
        if payload:
            self.sync = payload
            syncmod.save_cache(SYNC_CACHE, payload)
            debug("sync ok: %s" % list(payload.get("regions", {})))
            self.apply()
        self.refreshMenu()

    def syncNow_(self, sender):
        self.maybeSync(force=True)
        self.refreshMenu()

    def syncTick_(self, _):
        self.maybeSync()

    @objc.python_method
    def syncStatus(self):
        if self.syncing:
            return "Syncing..."
        if not self.sync:
            return "Not synced (using built-in figures)"
        age = time.time() - self.sync.get("fetchedAt", 0)
        if age < 90:
            return "Synced just now"
        if age < 3600:
            return "Synced %dm ago" % round(age / 60)
        if age < 172800:
            return "Synced %dh ago" % round(age / 3600)
        return "Synced %dd ago" % round(age / 86400)

    @objc.python_method
    def buildWindow(self):
        rect = NSMakeRect(0, 0, self.cfg["width"], 340)
        self.window = WidgetWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setHasShadow_(False)
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

        self.drag = DragView.alloc().initWithFrame_(
            self.window.contentView().bounds()
        )
        self.drag.owner = self
        self.drag.setAutoresizingMask_(1 << 1 | 1 << 4)  # width | height
        self.window.contentView().addSubview_(self.drag)

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
        # Long-running widget: re-check the published figures periodically so a
        # machine left on for weeks does not keep showing last month's rate.
        self.syncTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            900.0, self, b"syncTick:", None, True
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
        self._submenu(m, "Position", ANCHORS,
                      b"setAnchor:", None if self.cfg.get("pos") else self.cfg["anchor"])
        if self.cfg.get("pos"):
            m.addItem_(self._item("Reset Position", b"resetPosition:", ""))
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
        m.addItem_(self._item("Match Website Cadence", b"toggleCadence:", "",
                              self.cfg.get("cadence", 2000) >= 2000))
        m.addItem_(self._item("Open at Login", b"toggleLogin:", "",
                              os.path.exists(AGENT_PLIST)))

        m.addItem_(NSMenuItem.separatorItem())
        status = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            self.syncStatus(), None, "")
        status.setEnabled_(False)
        m.addItem_(status)
        m.addItem_(self._item("Sync Now", b"syncNow:", ""))
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
            "cadence": str(cfg.get("cadence", 2000)),
            # The window IS the card here, so it should track a resized window
            # rather than stopping at the 560px reading measure.
            "fill": "1",
        }

        # Hand the page whatever the last successful fetch produced for this
        # region. Absent, it falls back to the figures built into widget.html.
        live = (self.sync or {}).get("regions", {}).get(cfg["region"])
        payload = {}
        if live:
            payload = {
                "rate": live.get("rate"),
                "species": live.get("species"),
                "fetchedAt": self.sync.get("fetchedAt"),
                "skew": self.sync.get("skew", 0),
            }
        # loadFileURL: drops a query string, so hand the options to the page as a
        # global written before any of its own script runs.
        src = ("window.__AKC_OPTS__ = %s; window.__AKC_SYNC__ = %s;"
               % (json.dumps(opts), json.dumps(payload) if payload else "null"))
        self.userContent.removeAllUserScripts()
        self.userContent.addUserScript_(
            WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
                src, WKUserScriptInjectionTimeAtDocumentStart, True
            )
        )

        mode = cfg["mode"]
        if mode == "desktop":
            # Just above the desktop icons, which is the lowest level that can
            # still be clicked: the wallpaper level below it is covered by the
            # Dock's own full-screen backdrop window, so a window down there
            # never receives a mouse event no matter what it is set to. This is
            # still ~2.1 billion levels below normal windows, so the widget
            # cannot cover anything you are actually working in.
            level = CGWindowLevelForKey(kCGDesktopIconWindowLevelKey) + 1
            self.window.setIgnoresMouseEvents_(False)
        elif mode == "wallpaper":
            # True wallpaper level: behind the desktop icons too, and therefore
            # not draggable. Drag it in another mode, then switch back.
            level = CGWindowLevelForKey(kCGDesktopWindowLevelKey)
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
    def collide(self, x, y, w, h):
        """Stop the card at the screen edges, and stick when it gets close.

        Returns the origin the window should actually take for a requested one.
        Clamping is what makes the edges solid; the SNAP band on top of it means
        you do not have to land the drag pixel-perfectly to sit flush.
        """
        vis = self.visibleFrameFor(x + w / 2, y + h / 2)
        left, bottom = vis.origin.x, vis.origin.y
        right, top = left + vis.size.width, bottom + vis.size.height

        x = max(left, min(x, right - w))
        y = max(bottom, min(y, top - h))

        if abs(x - left) < SNAP:
            x = left
        elif abs((x + w) - right) < SNAP:
            x = right - w
        if abs(y - bottom) < SNAP:
            y = bottom
        elif abs((y + h) - top) < SNAP:
            y = top - h
        return NSMakePoint(x, y)

    @objc.python_method
    def widthChanged(self, width):
        """Live feedback while a side is being dragged."""
        self.cfg["width"] = float(width)
        # Record the position first. Re-fitting the height runs place(), which
        # would otherwise yank the card back to the stored x and fight a drag on
        # the left edge, where x is supposed to be moving.
        self.rememberPosition(persist=False)
        self.sizeToContent_(None)

    @objc.python_method
    def widthSettled(self):
        """Persist the new width and re-run the menu's Size checkmarks."""
        save_config(self.cfg)
        self.refreshMenu()

    @objc.python_method
    def rememberPosition(self, persist=True):
        """Record where a drag left the card, so nothing snaps it back."""
        f = self.window.frame()
        self.cfg["pos"] = [float(f.origin.x), float(f.origin.y + f.size.height)]
        if persist:
            save_config(self.cfg)

    @objc.python_method
    def visibleFrameFor(self, x, y):
        """The usable area of whichever display holds the given point."""
        for s in NSScreen.screens():
            fr = s.frame()
            if (fr.origin.x <= x <= fr.origin.x + fr.size.width
                    and fr.origin.y <= y <= fr.origin.y + fr.size.height):
                return s.visibleFrame()
        return NSScreen.screens()[0].visibleFrame()

    @objc.python_method
    def place(self):
        frame = self.window.frame()
        w, h = self.cfg["width"], frame.size.height

        pos = self.cfg.get("pos")
        if pos:
            # A dragged position wins over the anchor. Clamp it so the card can
            # never end up stranded off-screen after a display is unplugged or
            # the resolution changes -- keep a grabbable strip of it reachable.
            x, top = float(pos[0]), float(pos[1])
            vis = self.visibleFrameFor(x + w / 2, top - h / 2)
            edge = 80.0
            x = max(vis.origin.x - w + edge,
                    min(x, vis.origin.x + vis.size.width - edge))
            top = max(vis.origin.y + edge,
                      min(top, vis.origin.y + vis.size.height))
            self.window.setFrame_display_(NSMakeRect(x, top - h, w, h), True)
            return

        screens = NSScreen.screens()
        idx = min(self.cfg["screen"], len(screens) - 1)
        vis = screens[idx].visibleFrame()
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
        # Choosing an anchor is an explicit request to re-place the card, so it
        # discards whatever position a drag had pinned.
        self.update(anchor=sender.representedObject(), pos=None)

    def resetPosition_(self, sender):
        self.update(pos=None)

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

    def toggleCadence_(self, sender):
        # On: repaint every 2s like the website, so the digits agree when both
        # are on screen. Off: repaint 8x faster, which is a truer live count but
        # visibly runs ahead of the site.
        slow = self.cfg.get("cadence", 2000) >= 2000
        self.update(cadence=250 if slow else 2000)

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
