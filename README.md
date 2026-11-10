# VintedFind

**Get a push notification on your phone the moment something you want is listed on Vinted.**

Vinted has no saved-search alerts fast enough to catch good deals, and no public API. VintedFind watches your searches (brand, size, category, condition, colour, price) about once a minute and pings your phone for every new listing. Tap the notification and the item opens straight in the Vinted app.

- 🔎 **Search form with real Vinted filters.** Type-ahead brand search, category tree, sizes per category, condition, colour, price range, keyword
- 📱 **Phone alerts via [ntfy](https://ntfy.sh)**, with photo, price, size and a link to the item. Free, no account needed
- 🖥️ **Responsive dashboard** with a live feed of everything found, usable on desktop and phone
- 🪶 **No dependencies.** One Python file using only the standard library, so it runs on anything with Python 3.9+
- 🐳 **Docker-ready** for a NAS (Synology, etc.), Raspberry Pi or home server, so it can run 24/7

> ⚠️ Unofficial, personal-use tool. Not affiliated with Vinted. See [Disclaimer](#disclaimer).

---

## Contents

1. [Try it on your computer](#1-try-it-on-your-computer)
2. [Set up phone alerts](#2-set-up-phone-alerts)
3. [Create a search](#3-create-a-search)
4. [Run it 24/7](#4-run-it-247)
5. [Use the dashboard away from home](#5-use-the-dashboard-away-from-home)
6. [Updating](#6-updating)
7. [Configuration](#configuration)
8. [Tips and limitations](#tips-and-limitations)
9. [Troubleshooting](#troubleshooting)
10. [How it works](#how-it-works)

---

## 1. Try it on your computer

You need **Python 3.9 or newer**. macOS and most Linux systems already have it; check with `python3 --version`. On Windows, install it from [python.org](https://www.python.org/downloads/).

```bash
git clone https://github.com/blikbrein74/VintedFind.git
cd VintedFind
python3 server.py
```

Open **http://localhost:8765** in your browser. That's it: there's nothing to install.

On a Mac you can also double-click **`Start VintedFind.command`**. It opens the dashboard and keeps the Mac awake while it runs.

> Alerts only arrive while VintedFind is running. For 24/7 alerts, see [Run it 24/7](#4-run-it-247).

## 2. Set up phone alerts

VintedFind sends notifications through **ntfy**, a free, open-source push service.

1. Install the **ntfy** app: [iPhone](https://apps.apple.com/app/ntfy/id1625396347) · [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy).
2. In VintedFind, open the **Alerts** tab. You'll see a randomly generated topic, like `vintedfind-3f9a…`.
3. In the ntfy app, tap **+** and subscribe to that exact topic.
4. Back in VintedFind, switch on **Send a push for every new listing** and press **Send test**.

> 🔒 Treat the topic like a password: anyone who knows it can read your alerts. Keep the random one, or choose another hard-to-guess name.

## 3. Create a search

Open the **Searches** tab and fill in what you're looking for:

| Field | How it works |
|---|---|
| **Brand** | Start typing and pick from Vinted's brand list. You can pick several. |
| **Category** | Drill down, e.g. *Men → Shoes → Sneakers*. Category names appear in your Vinted site's language. |
| **Size** | Appears once you pick a category, showing that category's sizes. Tap all that fit. |
| **Condition** | New with tags, Very good, and so on. Optional. |
| **Colour** | One or more colours. Optional. |
| **Price** | Min and/or max in €. Optional. |
| **Keyword** | Free text, e.g. `gore-tex`. Optional. |

Click **Watch**. The search gets an automatic name, like *New Balance · Shoes · 43, 44 · ≤ €80*.

- **The first check only learns** what's already listed. From then on, every new listing triggers an alert.
- **Edit** changes a search; it re-learns quietly, so you don't get a flood of old items.
- **Pause** and **Check now** do what they say.
- Already built a search on the Vinted website? Use **Paste a link instead** and paste its address.

## 4. Run it 24/7

VintedFind has to run somewhere that's always on. Pick one:

| Option | Cost | Notes |
|---|---|---|
| **NAS or home server with Docker** (Synology, QNAP, Unraid…) | Free if you have one | ⭐ Recommended. Always on, and uses your home connection, which Vinted rarely blocks. |
| **Raspberry Pi** | About €70 once | Silent, uses little power, also on your home connection. |
| **Always-on Mac** | Free | Fine if it never sleeps. A laptop that gets closed won't work. |
| ~~Cloud server / GitHub Actions~~ | — | Not recommended. Vinted blocks datacenter addresses much more often, and GitHub Actions can't run more often than every 5 minutes (often much later). |

### Option A: Docker Compose (Raspberry Pi, Linux server, any Docker host)

```bash
git clone https://github.com/blikbrein74/VintedFind.git
cd VintedFind
docker compose up -d
```

The dashboard runs at `http://<that-machine's-ip>:8765`. Your searches are stored in `./data/state.json`.

It uses the official `python:3.12-alpine` image with your folder mounted into it, so nothing gets built. It restarts automatically after a reboot.

### Option B: Synology NAS (step by step)

You need DSM 7.2 or newer and a model that supports Container Manager (most "+" models and many others).

1. **Install Container Manager.** In DSM, open **Package Center**, search for *Container Manager* and click **Install**. This creates a shared folder called `docker`.
2. **Download VintedFind.** On this GitHub page, click **Code → Download ZIP** and unzip it on your computer.
3. **Copy it to the NAS.**
   - **Mac:** in Finder press **⌘K**, connect to `smb://<your-nas-name>.local` (or its IP), and open the `docker` share.
   - **Windows:** open `\\<your-nas-name>\docker` in Explorer.

   Create a folder `vintedfind` in it and copy in `server.py`, `docker-compose.yml` and the `static` folder.
   *Alternatively, use DSM's **File Station** to upload the files.*
4. **Create the project.** Open **Container Manager → Project → Create**:
   - **Project name:** `vintedfind`
   - **Path:** `/docker/vintedfind`
   - **Source:** *Use existing docker-compose.yml*

   Click **Next** through the remaining screens (skip *Web Station*), then **Done**. The first start downloads Python, which takes about a minute.
5. **Open the dashboard** at `http://<your-nas-ip>:8765`. You'll find the IP in DSM under **Control Panel → Network → Network Interface**.
   If the page doesn't load and the DSM firewall is on, allow TCP port **8765** under **Control Panel → Security → Firewall**.
6. **Set up [phone alerts](#2-set-up-phone-alerts)** and [your searches](#3-create-a-search).

> 💡 Already tried VintedFind on your computer? Copy its `data` folder into `docker/vintedfind` too, before step 4, to keep your searches and ntfy topic.

### Option C: Background service on a Mac

```bash
./install-mac-service.sh            # install, or update after changing code
./install-mac-service.sh uninstall  # remove (your searches are kept)
```

This installs a LaunchAgent that starts at login, restarts if it crashes, and keeps the Mac awake while it's on the charger. It runs from a copy in `~/.vintedfind`, because macOS doesn't allow background services to read cloud-synced folders like Google Drive or iCloud. Logs are in `~/.vintedfind/vintedfind.log`.

> ⚠️ Run VintedFind in **one place only**. Two copies send every alert twice.

## 5. Use the dashboard away from home

Phone alerts work everywhere. The **dashboard** is only reachable on your home network.

To use it on the go, install **[Tailscale](https://tailscale.com)**. It's free, and it's in Synology's Package Center too. Put it on both the server and your phone, then open `http://<server-tailscale-name>:8765` from anywhere.

> 🚫 Don't forward port 8765 on your router. The dashboard has no login, so anyone on the internet could see and change your searches.

## 6. Updating

**Git / Docker Compose:**

```bash
git pull
docker compose restart   # or restart `python3 server.py`
```

**Synology:**
1. Download the new version.
2. Copy `server.py` and the `static` folder over the old ones in `docker/vintedfind`, choosing **Replace**.
3. In **Container Manager → Project → vintedfind**, click **Stop** and then **Start**.

> ⚠️ Never replace the whole folder: the `data` folder inside it holds your searches and settings.

---

## Configuration

Most settings live in the dashboard's **Alerts** tab:
- how often to check (30 s to 5 min)
- whether to ignore promoted ("bumped") listings
- the ntfy topic and server (you can use a [self-hosted ntfy](https://docs.ntfy.sh/install/))

Command-line options and environment variables:

| Setting | Default | Purpose |
|---|---|---|
| `--port 8765` | `8765` | Dashboard port. |
| `--lan` | off | Listen on all network interfaces, so other devices can reach the dashboard. The Docker setup enables this. |
| `VINTEDFIND_DATA` | `./data` | Folder for `state.json`, which holds your searches, settings and seen items. |
| `VINTEDFIND_SITE` | `vinted.nl` | Vinted country site. Other euro sites like `vinted.fr`, `vinted.de` or `vinted.be` should work; only `vinted.nl` is tested. Price filters assume EUR. |
| `TZ` (Docker) | `Europe/Amsterdam` | Time zone for log timestamps. Change it in `docker-compose.yml`. |

## Tips and limitations

- **Keep searches specific** (brand + size, or category + size). Each check reads the ~96 newest matching listings. A very broad search, like "Nike, any size", can get more than 96 new listings within a minute, and some will be missed.
- **Don't check too often.** 30–60 seconds is a good balance. If Vinted starts refusing requests, VintedFind backs off automatically and shows the error on the search.
- **When Vinted changes its website**, VintedFind may stop finding items until the code is updated. Your searches show *"No item list found"* when that happens.
- **Push bursts are capped:** at most 5 individual pushes per check, plus one summary for the rest.

## Troubleshooting

| Problem | What to do |
|---|---|
| Dashboard doesn't load from another device | Start with `--lan` (Docker does this already) and check the firewall allows port 8765. |
| No phone notifications | Check the topic in the ntfy app matches exactly, that pushes are switched on, and that **Send test** arrives. |
| A search shows *HTTPError 403/429* | Vinted is rate-limiting you. Raise the check interval; VintedFind backs off automatically meanwhile. |
| *No item list found on the page* | Vinted changed its website. Check for an update, or open an issue. |
| Every alert arrives twice | VintedFind is running in two places, e.g. on your Mac and your NAS. Stop one. |
| *Couldn't load categories* / brand search fails | The server can't reach Vinted. Check its internet connection. |

## How it works

Vinted has no public API, and the internal `/api/v2/catalog/items` endpoint that older projects relied on no longer exists.

- **Finding items.** Vinted's catalog page is server-rendered (Next.js) and embeds the search results as JSON. VintedFind fetches the same public page a browser would, sorted newest first, and reads the items from it.
- **Building the search form.** The brand, size and category pickers use the same lookups as the Vinted website's own filter menus.
- **Remembering what's been seen.** Seen item IDs are stored per search in `data/state.json`, so only genuinely new listings trigger an alert.

```
server.py            HTTP server, dashboard API, poller thread, ntfy pushes
static/index.html    the dashboard (single file, no build step)
docker-compose.yml   run it with Docker / Synology Container Manager
install-mac-service.sh  optional macOS background service
data/state.json      your searches & settings (created on first run, not in git)
```

## Disclaimer

VintedFind is an unofficial project for personal use and is not affiliated with, endorsed by, or connected to Vinted. It reads publicly available pages at a modest rate, but automated access may still be against Vinted's terms of use. You use it at your own risk and are responsible for how you use it. Please be considerate: keep check intervals reasonable and don't use it to resell or redistribute Vinted's data.

## License

[MIT](LICENSE)
