# FreezerDB

FreezerDB is a dependency-free web app for tracking freezer food, stock levels, expiry dates, and household staples using SQLite.

It is designed for simple home use on one PC or across a local network.

## Features

### Food Inventory

* Add, edit, and delete freezer items.
* Track food name, category, quantity, freezer, frozen date, use-by date, notes, and assigned people.
* Add multiple batches of the same food, each with its own quantity and expiry date.
* Automatically number and group matching food batches from oldest to newest.
* Assign each food item to one freezer, or leave it unassigned.
* Assign each food item to one or more people, or leave it unassigned.
* Search existing foods while typing on the Add Food page.
* Search and filter inventory by category, freezer, or person.
* Remember the last selected food category when adding a new item.
* Default new use-by dates to one year from today.
* Use quick expiry shortcuts when adding food: `1m`, `2m`, `3m`, `4m`, `6m`, `12m`, `24m`, and `36m`.

### Stock Management

* Add or remove stock inline from the Inventory page.
* Add or remove stock inline from the Pull Food page.
* View stock totals, due-soon counts, and past-due counts.
* Mark foods as House Staples.
* Set restock thresholds for staple items.
* Use the Buy tab to view low staples and manually requested restocks.

### Pull Food

* Create pull lists for one person or multiple people.
* Choose whether pull lists match any selected person or all selected people.
* Quickly remove stock while pulling food.

### Expiry Tracking

* View food expiring within a chosen number of days.
* View food expiring before a selected date.
* Live-filter date controls without pressing a filter button.
* See due-soon and past-due items at a glance.

### Buy List

* View low House Staples that need restocking.
* View manually requested restock items.
* Use the Buy tab as a simple shopping/restock list.

### Manage Menu

* Add, edit, and delete freezers.
* Add, edit, and delete people.
* Add, edit, and delete categories.
* Add, edit, and delete unit suggestions.
* Quickly add freezers, people, categories, and units from themed dialogs in the food form.
* Keep unit names lowercase automatically.
* Automatically merge duplicate unit names case-insensitively.
* Change the app accent colour.
* Change the date display format.
* Reset appearance and log settings to defaults.
* Configure authentication mode, port, and bind IP.
* Customize the application title and header text.
* Preview recent audit activity and open the full audit log.

### Admin Tools

* Manage webuser logins from the hidden Admin tab when logged in as an admin.
* Add, edit, and remove web users.
* Use authentication modes for open access, edit-only login, or full view login protection.

### Audit Log

* View when food was added, updated, or removed.
* Record source IP address when available.
* Record browser and device details when available.
* Preview recent audit activity from the Manage tab.
* Open the full audit log for more detailed history.

### Stats

* View freezer usage bars.
* View a current-stock pie chart.
* View stock totals.
* View recent stock changes.
* Open full food and stock-event data pages from compact previews.

### Interface

* Use a hamburger navigation menu on small screens.
* Adjust Inventory, Pull Food, Buy, and Expiring table compactness down to 35%.
* Live-filter table search and date controls without pressing a filter button.
* Keep Inventory, Pull Food, Expiring, and Audit pages updated from other devices with lightweight polling.

### Data Storage

* Store all records in SQLite.
* Automatically create `freezer.db` in the project folder on first run.

## Requirements

* Python 3.10 or newer
* No external Python packages required

FreezerDB is designed to run with the Python standard library only.

## Run

From PowerShell:

```powershell
.\run.bat
```

Or run the server directly with Python:

```powershell
python server.py
```

Then open:

```text
http://127.0.0.1:8000
```

## Access From Another Device

To access FreezerDB from another device on your LAN, open the server machine's LAN address.

Example:

```text
http://10.0.20.x:8000
```

Replace `10.0.20.x` with the actual LAN IP address of the computer running FreezerDB.

If another device cannot connect, allow inbound access to Python or port `8000` in Windows Firewall.

## Configuration

Server binding and authentication are controlled by `config.yml`.

Example:

```text
AUTH_OPT="NONE"
PORT="8000"
IP="0.0.0.0"
```

### Authentication Modes

`AUTH_OPT` controls how login protection works.

```text
NONE
```

No login required.

```text
EDIT
```

Anyone can view the site, but login is required to make changes.

```text
VIEW
```

Login is required before viewing the site.

### Port

`PORT` controls the web server port.

Example:

```text
PORT="8000"
```

If the configured port is busy on startup, FreezerDB tries the next available port and updates `config.yml`.

### Bind IP

`IP` controls which network address the server binds to.

For local-only access:

```text
IP="127.0.0.1"
```

For LAN access:

```text
IP="0.0.0.0"
```

## Console Commands

While the server is running, type commands directly into the console.

```text
stop
reload
help
```

### Webuser Commands

```text
ADD WEBUSER "ADMIN" "USERNAME" "PASSWORD"
ADD WEBUSER "USER" "USERNAME"
EDIT WEBUSER "OLDUSERNAME" "ADMIN" "NEWUSERNAME" "PASSWORD"
REMOVE WEBUSER "USERNAME"
```

Examples:

```text
ADD WEBUSER "ADMIN" "jacob" "mypassword"
ADD WEBUSER "USER" "viewer"
EDIT WEBUSER "viewer" "USER" "viewer2" "newpassword"
REMOVE WEBUSER "viewer2"
```

## Logs

Console output is also written to:

```text
server.log
```

Newest entries are written at the top.

The log size defaults to:

```text
64 MB
```

The maximum log size can be changed from the Manage tab.

## Database

FreezerDB stores app data in:

```text
freezer.db
```

The database is created automatically in the project folder.

## Suggested `.gitignore`

The repository should ignore local database, log, cache, and archive files while keeping the app source and static files.

```gitignore
# Local data
freezer.db
webuser_auth.db
server.log

# Python cache
*.pyc
__pycache__/

# Archives
*.7z
```

## Project Files

Main files:

```text
server.py
config.yml
version.yml
changelog.md
readme.md
run.bat
run.ps2
static/
```

## Notes

FreezerDB v1.0.0 is intended for trusted home or LAN use. If exposing it outside your local network, use proper network security, strong passwords, and a reverse proxy with HTTPS.
