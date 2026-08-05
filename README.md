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
| `macos/make-app.sh`        | Builds `~/Desktop/Apps/Animal Kill Clock.app`.                     |
| `windows/AnimalKillClock.hta` | Windows, zero install. Double-click it.                        |
| `windows/README.md`        | Both Windows routes, including Lively Wallpaper.                   |

## macOS

```sh
./macos/make-app.sh
open ~/Desktop/Apps/"Animal Kill Clock.app"
```

Requires [uv](https://docs.astral.sh/uv/); the first launch resolves PyObjC and
caches it.

The window sits at the **desktop window level**: above your wallpaper, below
your icons and every normal window. So it is pinned rather than floating: it
never covers anything, never shows up in Cmd-Tab or Mission Control, and follows
you across every Space. There is no Dock tile; everything is under the
**Kill Clock** menu bar item, which also carries the running total so the number
is still readable when something full-screen is covering the desktop.

From that menu:

- **Display**: pinned to desktop, floating above windows, or a normal window
- **Region**: United States, United Kingdom, Canada, Australia
- **Position**: nine anchors, since a desktop-level window can't be dragged
  (clicks there belong to the Finder). Switch to *Float Above Windows* if you'd
  rather drag it into place.
- **Size**, **Theme**, **Screen**, **Just the Number**, **Show Border**
- **Open at Login**: writes a LaunchAgent

Settings persist to `~/Library/Application Support/AnimalKillClock/config.json`.

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

## How the number is calculated

Same method as the source site: a per-second rate multiplied by the seconds
elapsed since January 1 in your local time zone. Nothing is fetched at runtime.

The rates are derived from published annual totals divided by the real length of
the current year, so the per-species lines always sum to the headline and a leap
year doesn't inflate the count. The U.S. figures are USDA slaughter data
adjusted for imports, exports and pre-slaughter mortality, plus the Counting
Animals estimates for fish and shellfish, which comes to roughly 55.4 billion a
year, about 1,758 a second. The other three countries are published only as a
per-second rate, so those clocks run a total with no breakdown.

To refresh the numbers, read the FAQ table at animalclock.org and edit the
`REGIONS` block at the top of the script in `widget.html` (and the matching one
in the `.hta`). Nothing else needs to change.

## Credit

The clock, the research behind it, and the design this follows are the work of
[animalclock.org](https://animalclock.org). This repository is an independent
widget build: the code is written from scratch and none of the site's assets are
redistributed. If the widget is useful to you, the site is where the actual
argument and the sourcing live.
