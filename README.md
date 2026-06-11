# Freezer Stock

A dependency-free web GUI for tracking food in a freezer with SQLite.

## Run

From PowerShell:

```powershell
.\run.bat
```

Or use Python 3.10 or newer directly:

```powershell
python server.py
```

Then open:

```text
http://127.0.0.1:8000
```

From another device on your LAN, open the server machine's LAN address, for example:

```text
http://10.0.20.x:8000
```

If another device cannot connect, allow inbound access to Python or port `8000` in Windows Firewall.

The app creates `freezer.db` in this folder automatically.
Server binding and authentication are controlled by `config.yml`:

```text
AUTH_OPT="NONE"
PORT="8000"
IP="0.0.0.0"
```

`AUTH_OPT` can be `NONE`, `EDIT`, or `VIEW`. `EDIT` allows public viewing but requires login for changes. `VIEW` requires login before viewing the site. If the configured port is busy on startup, the server tries the next port and updates `config.yml`.

While the server is running, type these commands in the console:

```text
stop
reload
help
ADD WEBUSER "ADMIN" "USERNAME" "PASSWORD"
ADD WEBUSER "USER" "USERNAME"
EDIT WEBUSER "OLDUSERNAME" "ADMIN" "NEWUSERNAME" "PASSWORD"
REMOVE WEBUSER "USERNAME"
```

Console output is also written to `server.log` with newest entries at the top. The log defaults to `64 MB`; change the maximum size from the Manage tab.

## Features

- Add, edit, and delete freezer items
- Add another batch of an existing food with its own quantity and expiry date
- Number and group matching food batches from oldest to newest
- Search existing foods while typing on the Add Food page
- Add or remove stock inline from Inventory and Pull Food
- Mark items as House Staples with a restock threshold
- View a Buy tab for low staples and manually requested restocks
- Assign each food to one freezer, or leave it unassigned
- Assign each food to one or more people, or no one
- Add, edit, and delete freezers, people, categories, and unit suggestions from the Manage menu
- Keep unit names lowercase and automatically merge case-insensitive duplicates
- Quickly add freezers, people, categories, and units from themed dialogs in the food form
- Change the app accent colour from the Manage tab
- Reset appearance and log settings to defaults from the Manage tab
- Change date display format from the Manage tab
- Configure authentication mode, port, and bind IP from the Manage tab
- Customize the application title and header text
- Use a hamburger navigation menu on small screens
- Adjust Inventory, Pull, Buy, and Expiring table compactness down to 35%
- Manage webuser logins from the hidden Admin tab when logged in as an admin
- Pull food lists for one person or multiple people
- Choose whether pull lists match any selected person or all selected people
- View food expiring within a set number of days or before a set date
- Use 1m, 2m, 3m, 4m, 6m, 12m, 24m, and 36m expiry shortcuts when adding food
- View an audit log showing when food was added, updated, or removed, including source IP and browser/device details when available
- Preview recent audit activity from Manage and open the full log from there
- View usage bars, a current-stock pie chart, stock totals, and recent changes from the Stats tab
- Open full food and stock-event data pages from their compact previews
- Live-filter table search and date controls without pressing a filter button
- Keep Inventory, Pull Food, Expiring, and Audit pages updated from other devices with lightweight polling
- Track food name, category, quantity, freezer, frozen date, use-by date, and notes
- Search and filter by category, freezer, or person
- Remember the last selected food category for the next new item
- Default use-by date to one year from today
- See totals plus due-soon and past-due counts
- Store all records in SQLite
