# FreezerDB

FreezerDB is a simple web app for keeping track of food stored in your freezer.

It helps you see what you have, where it is, who it belongs to, when it was frozen, and when it should be used by. It also keeps track of stock levels, low staples, expiry dates, and recent changes.

FreezerDB stores everything locally in SQLite and does not require any external Python packages.

## Run

From PowerShell:

```powershell
.\run.bat
```

Or run it directly with Python 3.10 or newer:

```powershell
python server.py
```

Then open:

```text
http://127.0.0.1:8000
```

From another device on your LAN, open the server machine’s LAN address, for example:

```text
http://10.0.20.x:8000
```

If another device cannot connect, allow inbound access to Python or port `8000` in Windows Firewall.

The app creates `freezer.db` in this folder automatically.

## Configuration

Server binding and authentication are controlled by `config.yml`:

```text
AUTH_OPT="NONE"
PORT="8000"
IP="0.0.0.0"
```

`AUTH_OPT` can be:

```text
NONE
EDIT
VIEW
```

`NONE` disables login.

`EDIT` allows anyone to view the site, but requires login before making changes.

`VIEW` requires login before viewing the site.

If the configured port is busy on startup, FreezerDB tries the next available port and updates `config.yml`.

Most appearance, log, authentication, port, and app title settings can also be changed from the Manage tab.

## Features

FreezerDB lets you add, edit, and delete freezer items, including multiple batches of the same food with different quantities and expiry dates. Matching batches are grouped together from oldest to newest, making it easier to use older food first.

Each item can have a name, category, quantity, freezer, frozen date, use-by date, notes, and assigned people. Foods can be linked to a freezer or left unassigned, and they can be assigned to one person, multiple people, or no one.

You can search and filter your inventory by food name, category, freezer, or person. The Add Food page can search existing foods while you type, remembers the last category you used, and defaults new use-by dates to one year from today. Quick expiry shortcuts are available for common time ranges like 1 month, 6 months, 12 months, and 24 months.

Stock can be added or removed directly from the Inventory and Pull Food pages. The Pull Food page can make lists for one person or multiple people, with options to match any selected person or all selected people.

House Staples can be given restock thresholds, and the Buy tab shows staples that are running low along with manually requested restocks.

The Expiring page shows food due soon or past due, either within a set number of days or before a chosen date. Inventory, Pull Food, Buy, Expiring, and Audit views update automatically while the app is open.

The Manage tab lets you maintain freezers, people, categories, and unit suggestions. Unit names are kept lowercase, and duplicate units are merged case-insensitively.

FreezerDB also includes an audit log showing when food was added, updated, or removed. When available, the log includes the source IP address and browser or device details.

The Stats tab shows freezer usage, current stock, stock totals, and recent changes.

## Authentication and Admin Panel

When authentication is enabled, FreezerDB includes a full Admin panel for managing users, server settings, backups, logs, and server maintenance from inside the app.

The Admin tab is only available when logged in as an admin.

The Admin panel includes:

### Statistics

The Statistics card shows a quick server overview, including connected users, CPU usage, RAM usage, and app storage usage.

### Logged-in Users

The Users card shows currently active web users, including their role, IP address, and last active time.

Admins can force-log out a single user or force-log out all active users.

### Webuser Admin

The Webuser Admin card lets admins manage login accounts without using console commands.

Admins can:

* Add new users
* Set user roles
* Change usernames
* Reset passwords
* Remove users
* View account creation dates

User roles are used to separate normal users from admins.

### Server Config

The Server Config card lets admins change important server settings from the browser.

This includes:

* Authentication mode
* Bind IP
* Port
* Maximum log size
* Application title
* Header start text
* Favicon image

Config changes can be saved from the Admin panel, and defaults can be restored when needed.

### Backup and Restore

The Backup and Restore card lets admins download backups and restore from backup files.

Admins can download the app settings, the full dataset, or restore supported backup files through the browser.

### Server Log

The Server Log card shows recent server output inside the Admin panel.

Admins can preview the log, open the full log, and check recent server activity without going back to the console.

### Reset History

The Admin panel includes reset history cards for statistics and stock events.

These show recent reset activity so admins can see when data was cleared and what was affected.

### Server Controls

The Server Controls card provides maintenance actions from the browser.

Admins can reload server data or shut down the server.

## Console Commands

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

When adding a webuser the `"PASSWORD"` field is optional, if you do not provide one the server will generate a password for you.

Console output is also written to `server.log`, with newest entries at the top.

The log defaults to `64 MB`. You can change the maximum size from the Manage tab or Admin panel.


## Data

FreezerDB stores its records in SQLite.

The main database is:

```text
freezer.db
```

Webuser login data is stored separately in:

```text
webuser_auth.db
```

## Suggested `.gitignore`

```gitignore
freezer.db
webuser_auth.db
server.log
*.pyc
__pycache__/
*.7z
```
