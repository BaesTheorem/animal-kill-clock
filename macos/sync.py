"""Fetch the live figures from animalclock.org.

The site has no counter API, and there is nothing server-side to read: its clock
is computed in the browser as `rate x seconds since Jan 1`, in the *viewer's*
time zone. So what is actually worth pulling over the network is the inputs, not
an answer:

  * the per-second rate, from the `data-counter` attribute the site drives its
    own headline from
  * the annual per-species figures from the death-stats section
  * the server's clock, from the HTTP Date header, so a Mac whose own clock has
    drifted still counts against real time rather than its own

Results are cached to disk and reused when offline, so the widget never depends
on the network to draw. Anything that cannot be parsed falls back to the values
built into widget.html rather than blanking the card.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

BASE = "https://animalclock.org"
REGION_PATHS = {"us": "/", "uk": "/uk", "ca": "/ca", "au": "/au"}

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# "<h3 class="heading-stats">Chickens</h3> <p>8,127,632,113</p>" -- the label and
# its annual figure, which sit next to each other in the death-stats list.
STAT_RE = re.compile(
    r'heading-stats"[^>]*>\s*([A-Za-z ]+?)\s*(?:<sup>.*?</sup>)?\s*</h3>\s*<p>\s*([\d,]+)\s*</p>',
    re.S,
)
RATE_RE = re.compile(r'class="counter"[^>]*data-counter="(\d+)"')


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        served = resp.headers.get("Date")
    skew = None
    if served:
        try:
            # Positive means the server is ahead of us.
            skew = parsedate_to_datetime(served).timestamp() - time.time()
        except (TypeError, ValueError):
            skew = None
    return body, skew


def fetch_region(region):
    """Return {rate, species, skew} for one region, or None if it can't parse."""
    path = REGION_PATHS.get(region)
    if path is None:
        return None
    html, skew = _get(BASE + path)

    m = RATE_RE.search(html)
    if not m:
        return None
    rate = int(m.group(1))
    if not 1 <= rate <= 1_000_000:      # refuse a nonsense parse
        return None

    species = [[name, int(val.replace(",", ""))]
               for name, val in STAT_RE.findall(html)]

    out = {"rate": rate, "skew": skew}
    # Only the U.S. page publishes a per-species table worth showing.
    if len(species) >= 4:
        out["species"] = species
    return out


def fetch_all(regions=("us", "uk", "ca", "au")):
    data, errors = {}, {}
    for r in regions:
        try:
            got = fetch_region(r)
            if got:
                data[r] = got
            else:
                errors[r] = "could not parse"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors[r] = str(exc)
    if not data:
        return None
    # One clock offset for the whole payload; they all come from the same host.
    skews = [v.pop("skew") for v in data.values() if v.get("skew") is not None]
    return {
        "fetchedAt": time.time(),
        "source": BASE,
        "skew": round(sum(skews) / len(skews), 3) if skews else 0,
        "regions": data,
        "errors": errors,
    }


def load_cache(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_cache(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


if __name__ == "__main__":
    print(json.dumps(fetch_all(), indent=2))
