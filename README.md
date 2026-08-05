# Animal Kill Clock: a desktop widget

A live desktop widget version of the [U.S. Animal Kill Clock](https://animalclock.org):
a running count of the animals killed for food so far this year, in the same
spare style as the site.

Pinned to the desktop on macOS, and usable on Windows either as a
zero-install window or as a real desktop-level wallpaper widget.

![the widget](docs/preview.png)

## What's here

| Path                       | What it is                                                        |
| -------------------------- | ----------------------------------------------------------------- |
| `widget.html`              | The widget. Self-contained, no dependencies, works offline.        |
| `macos/widget_app.py`      | macOS host: a borderless WKWebView pinned at the desktop layer.    |
| `macos/sync.py`            | Pulls the live figures from animalclock.org.                       |
| `macos/make-app.sh`        | Builds `Animal Kill Clock.app` into `/Applications`.               |
| `windows/AnimalKillClock.hta` | Windows, zero install. Double-click it.                        |
| `windows/README.md`        | Both Windows routes, including Lively Wallpaper.                   |

## macOS

```sh
./macos/make-app.sh
open -a "Animal Kill Clock"
```

Installs to `/Applications`; set `AKC_APP_DIR` to put it somewhere else.

Requires [uv](https://docs.astral.sh/uv/); the first launch resolves PyObjC and
caches it.

**Drag it anywhere.** Grab the card and move it; where you drop it is
remembered. It collides with the screen edges rather than sliding off, and
sticks when it gets within a few pixels of one, so it lands flush without you
having to be precise. Pick an anchor from the menu to snap it back to an edge.

**The footer link works**, and opens in your real browser rather than inside
the widget. That needs handling natively for two reasons: the transparent
surface that makes the card draggable also swallows clicks meant for the page,
and a WKWebView ignores `target="_blank"` unless you implement a `WKUIDelegate`,
so the link was a dead click either way. A press that does not turn into a drag
is hit-tested against the page and any link handed to the shell.

**Resize it** by dragging either side. Only the width is yours to set: the
height is whatever the card needs at that width, so the window shrink-wraps to
its content afterwards. Everything scales together, so making it wider makes the
whole widget bigger rather than just stretching it.

The window sits just above your desktop icons and about two billion levels below
every normal window. So it is pinned rather than floating: it never covers
anything you're working in, never shows up in Cmd-Tab or Mission Control, and
follows you across every Space. There is no Dock tile; everything is under the
**Kill Clock** menu bar item, which also carries the running total so the number
is still readable when something full-screen covers the desktop.

From that menu:

- **Display**: *Pinned to Desktop* (the default, draggable), *Behind Desktop
  Icons* (true wallpaper level, so it can't be clicked or dragged), *Float Above
  Windows*, or *Normal Window*
- **Region**: United States, United Kingdom, Canada, Australia
- **Position**: nine anchors, plus **Reset Position** once you've dragged it
- **Size**, **Theme**, **Screen**, **Just the Number**, **Show Border**
- **Sync Now**, under a line showing how long ago the figures were fetched
- **Open at Login**: writes a LaunchAgent

Settings persist to `~/Library/Application Support/AnimalKillClock/config.json`.

### Why not a real macOS widget?

Because a native one can't tick. Apple's widget guidance covers WidgetKit
widgets, the kind that live in Notification Center and on the desktop, and it is
explicit that they "don't support continuous, real-time updates" and that update
frequency is limited. A clock counting 1,758 a second is exactly what that
budget rules out. Hence a small hosted window instead, placed to behave like a
widget: pinned, glanceable, and covering nothing.

## Windows

See [`windows/README.md`](windows/README.md). Short version: double-click
`windows/AnimalKillClock.hta` for a movable window with nothing to install, or
point [Lively Wallpaper](https://github.com/rocksdanister/lively) at
`widget.html` for one genuinely pinned behind your icons.

## Anywhere else

`widget.html` is just a web page. Open it in any browser, or point any widget
host at it. It sizes itself to whatever box it's given, from a 380px window up to
a 4K wallpaper, and needs no network (the webfont loads asynchronously and it
falls back to the system sans if you're offline).

Options go on the URL: `widget.html?region=uk&theme=dark&align=bottom-right`.
The full table is in `windows/README.md`.

## Where the numbers come from

The widget syncs with animalclock.org over the network, on launch and every few
hours after. What it fetches is worth being precise about, because it is not a
count.

**The site has no counter API, and no server-side total to read.** Its headline
is computed in your browser as `rate x seconds since January 1`, in *your* local
time zone, which means two people in different time zones legitimately see
different numbers on the same page. There is no single authoritative figure
sitting on a server anywhere.

So what syncs is the **inputs**, scraped from the pages themselves:

- the per-second rate, from the `data-counter` attribute the site drives its own
  headline from (1,758 for the U.S.)
- the annual per-species figures from each region's death-stats section
- the server's clock, from the HTTP `Date` header, so a machine whose own clock
  has drifted still counts against real time

That is a real network dependency on the source rather than a reimplementation
of it: when the site updates its figures, the widget follows without a code
change. The figures are cached to disk, so it draws instantly and keeps working
offline, and the footer says which it is (`synced 2h ago` or `built-in
figures`). If a fetch fails or the markup changes, it falls back to the values
built into `widget.html` rather than blanking.

The per-species lines split the headline in proportion to each species' share of
the annual total, so the rows sum to the number above them. The U.S. figures are
USDA slaughter data adjusted for imports, exports and pre-slaughter mortality,
plus the Counting Animals estimates for fish and shellfish, roughly 55.4 billion
a year.

### Reading alike side by side

The widget repaints every two seconds by default, matching the website's own
refresh, so the digits agree when both are on screen. Measured over 12 samples
against the live site, that holds the gap at a steady one second; ticking at
250ms instead put it between one and three seconds and visibly jittering.

The residual offset is the site's own load phase and cannot be removed. Its
counter is seeded once when the page loads and then stepped by a timer of its
own, so its idea of "now" is fixed by the moment you opened that tab. Two
browser tabs of animalclock.org opened a second apart disagree with each other
by the same amount. Matching the cadence removes the jitter, not the phase.

If you would rather have the most accurate live count than one that matches the
website, turn off **Match Website Cadence** in the menu (or pass
`?cadence=250`). That counts the actual second more closely and runs slightly
ahead of the site.

## Credit

The clock, the research behind it, and the design this follows are the work of
[animalclock.org](https://animalclock.org). This repository is an independent
widget build: the code is written from scratch and none of the site's assets are
redistributed. If the widget is useful to you, the site is where the actual
argument and the sourcing live.
