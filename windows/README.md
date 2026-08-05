# Animal Kill Clock on Windows

Two ways to run it, depending on whether you want a movable window or something
pinned behind your desktop icons.

## 1. Zero install: `AnimalKillClock.hta`

Double-click it. That's the whole setup. Windows opens it with `mshta.exe`, which
ships with every Windows install, so there is nothing to download and nothing to
trust beyond the file itself (it is plain HTML and JavaScript, readable in any
text editor).

- **Move it** by dragging anywhere on the card.
- **Close it** with `Esc`, or the `x` that appears when you hover.
- **Configure it** by opening the file in Notepad and editing the `CONFIG` block
  near the top: region, theme, width, where on screen it opens, compact mode.
- **Start it with Windows**: press `Win+R`, run `shell:startup`, and drop a
  shortcut to the `.hta` in the folder that opens.

Caveats, so nothing is a surprise:

- It is an ordinary window. `mshta` gives no way to mark a window topmost or to
  sink it to the desktop layer, so other windows can cover it. Use option 2 if
  you want a real pinned widget.
- It renders in the legacy Trident engine, so this file is a standalone
  reimplementation of `../widget.html` rather than a wrapper around it. If you
  change the figures in one, change them in both.

## 2. Pinned to the desktop: Lively Wallpaper

[Lively Wallpaper](https://github.com/rocksdanister/lively) is free and open
source (also on the Microsoft Store). It renders HTML as your actual wallpaper,
which is the closest Windows equivalent to the macOS build here: the clock sits
behind your icons, covers nothing, and costs no window.

1. Install Lively and open it.
2. Drag `widget.html` (in the parent folder, not the `.hta`) onto the Lively
   library, or use **Add Wallpaper → Browse** and pick it.
3. Set it as your wallpaper.

Because Lively renders the file full-screen, use the query options to place the
card where you want it on the wallpaper. In Lively's wallpaper settings, set the
file path with options appended:

```
widget.html?align=top-right&bg=%23c9c4bd&scale=1.2
```

| Option    | Values                                                              |
| --------- | ------------------------------------------------------------------- |
| `region`  | `us` `uk` `ca` `au`                                                 |
| `theme`   | `light` `dark`                                                      |
| `align`   | `center` `top` `bottom` `left` `right` and the four corners         |
| `scale`   | a multiplier, e.g. `1.4`                                            |
| `bg`      | page colour behind the card, URL-encoded (`%23` for `#`)            |
| `compact` | `1` for the headline only                                           |
| `frame`   | `0` to drop the hairline border                                     |

If Lively will not take a query string on a local file, copy `widget.html` next
to a small `index.html` that redirects to it with the options you want.

---

Data and concept: [animalclock.org](https://animalclock.org).
