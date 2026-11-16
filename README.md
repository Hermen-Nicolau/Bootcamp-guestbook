# Tanzu Bootcamp Guestbook

A small guestbook app for the Tanzu Platform for Cloud Foundry Bootcamp. Each student pushes their own copy into their own space, and every copy connects to the **same Postgres database**. Anyone who signs the guestbook with their name and hometown shows up on everyone else's page within 3 seconds.

## What this lab teaches

| Concept | Where you see it in the lab |
| --- | --- |
| Orgs, spaces and roles | Each student creates and targets their own space in the bootcamp org |
| `cf push` and manifests | One-instance push with the Python buildpack, a random route and an HTTP health check |
| Marketplace and user-provided services | The instructor creates one Postgres instance from the marketplace. Each space gets a user-provided `bootcamp-db` with its credentials, and each app binds to that |
| `VCAP_SERVICES` | The app reads its database credentials from the environment, and none live in the code |
| Logs and status | `cf app`, `cf events`, `cf logs` and Apps Manager show the same app from two angles |
| Quotas | Scaling to 3 instances hits the org quota until an admin raises it |
| Load balancing and HA | With 3 instances, the page shows the GoRouter rotating requests across instances |
| Cleanup | Unbinding, deleting your service entry without touching the shared database, and deleting the app and its route |

## How the app works

```
Browser ──► GoRouter ──► bootcamp-app-<you> (1–3 instances, your space)
                                   │  bound to bootcamp-db (user-provided, in your space)
                                   ▼  credentials from VCAP_SERVICES
              bootcamp-postgres (marketplace Postgres, in the instructor's bootcamp-shared space)
                                   ▲
Other students' apps ──► their own bootcamp-db (same credentials) ──┘
```

The Postgres broker on OMA Eng doesn't support service sharing. Instead, the instructor creates a service key on `bootcamp-postgres` and creates a user-provided service called `bootcamp-db` with those credentials in every student space.

- **Frontend:** a single HTML page with a form. It polls `/api/entries` every 3 seconds, so new entries appear without a refresh.
- **Backend:** Python's built-in HTTP server with no web framework. It stores entries in the `bootcamp_guestbook` table and creates the table on first use.
- **Database driver:** `pg8000`, a pure-Python Postgres driver. The driver and its dependencies are bundled in `vendor/`, so staging works without internet access.

### Endpoints

| Path | Method | What it does |
| --- | --- | --- |
| `/` | GET | Guestbook page |
| `/api/entries` | GET | The latest 200 entries as JSON, plus `served_by` (which instance answered) |
| `/api/entries` | POST | Adds an entry: `{"name": "...", "hometown": "..."}`, each up to 60 characters |
| `/db` | GET | Database check: bound service, host, PostgreSQL version and entry count. Returns 503 if not connected |
| `/health` | GET | Liveness check: always 200 while the process is up. It doesn't check the database on purpose, so a database blip doesn't get every instance restarted |

The app finds Postgres credentials in `VCAP_SERVICES` whether the broker provides a `uri`, a `jdbcUrl`, or separate `host`, `port`, `name`, `username` and `password` fields.

### Files

```
app.py             the whole app
manifest.yml       1 instance, 256M, python_buildpack, random route, HTTP health check on /health
Procfile           web: python app.py
requirements.txt   pg8000
vendor/            pg8000 and its dependencies as wheels, for offline staging
```

Requires `python_buildpack` with Python 3.9 or later.

---

## Lab steps (about 45 minutes)

Set these once per terminal session. Use your first name in lowercase, and the org name your instructor gives you:

```bash
export ME=<your-first-name>
export ORG=<bootcamp-org-name>
```

### Step 1 – Log in and create your space

```bash
cf api <cf-api-endpoint>
cf login --sso                     # or: cf login
cf target -o $ORG
cf create-space $ME
cf target -o $ORG -s $ME
cf space $ME
cf space-users $ORG $ME            # you're Space Manager and Space Developer in your new space
```

If you get "not authorized", ask the instructor for access.

### Step 2 – Push the app with one instance

```bash
git clone <this-repo-url> && cd bootcamp-app
cat manifest.yml
cf push bootcamp-app-$ME
cf app bootcamp-app-$ME
ROUTE=$(cf app bootcamp-app-$ME | awk '/^routes:/ {print $2}')
curl -sk https://$ROUTE/db         # "bound": false – no database yet
```

Open `https://$ROUTE` in your browser. The page loads, but the status bar is red.

### Step 3 – Bind to the shared database and sign the guestbook

```bash
cf services                        # bootcamp-db, a user-provided service the instructor created in your space
cf bind-service bootcamp-app-$ME bootcamp-db
cf restart bootcamp-app-$ME        # a running app only sees new credentials after a restart
cf env bootcamp-app-$ME            # find bootcamp-db under VCAP_SERVICES
curl -sk https://$ROUTE/db         # "ok": true
```

Sign the guestbook in your browser, then watch your classmates' entries appear. You can also sign from the CLI:

```bash
curl -sk -X POST https://$ROUTE/api/entries -H 'Content-Type: application/json' \
     -d '{"name":"<your name>","hometown":"<your hometown>"}'
```

### Step 4 – Check logs and status (CLI and Apps Manager)

```bash
cf app bootcamp-app-$ME
cf events bootcamp-app-$ME
cf logs bootcamp-app-$ME --recent  # look for API, STG, CELL, APP/PROC/WEB and RTR lines
cf logs bootcamp-app-$ME           # live stream; leave it running in a second terminal
```

In Apps Manager, open your org, then your space, then `bootcamp-app-<you>`. Compare the Overview, Logs, Services, Environment Variables and Events with what the CLI showed.

### Step 5 – Scale to 3 instances and hit the quota

```bash
cf scale bootcamp-app-$ME -i 3     # should FAIL: the org's app instance limit is reached
cf org $ORG
cf org-quota <org-quota-name>
```

One volunteer with admin access raises the org quota:

```bash
cf update-org-quota <org-quota-name> -a 100
```

Then everyone scales again:

```bash
cf scale bootcamp-app-$ME -i 3
cf app bootcamp-app-$ME            # 3/3
```

Keep the page open. The status bar shows which instance answered each poll (0, 1, 2), and the Instance column shows which instance saved each entry.

### Step 6 – Clean up

```bash
cf unbind-service bootcamp-app-$ME bootcamp-db
cf restart bootcamp-app-$ME
curl -sk https://$ROUTE/db         # "bound": false again
cf delete-service bootcamp-db -f   # removes only your space's credentials entry; the database is untouched
cf delete bootcamp-app-$ME -r -f   # -r also deletes the route
cf apps && cf routes && cf services   # all empty
```

The instructor deletes the service key and the `bootcamp-postgres` instance at the end.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Status bar says *No Postgres service bound* | Bind it, then `cf restart` |
| Bound, but the connection times out | No App Security Group allows port 5432 to the database. Ask the instructor, then `cf restart` |
| `bootcamp-db` isn't in `cf services` | The instructor hasn't created it in your space yet. Ask them |
| A classmate's entries don't show | Their `bootcamp-db` must have the same credentials as yours. Compare the host in `cf env` |
| `password authentication failed` | The instructor's service key changed. They need to update `bootcamp-db` in every space, then you run `cf restart` |
| Staging fails | `cf buildpacks` must list `python_buildpack`, and `vendor/` must contain all 5 wheels |
| `cf scale -i 3` works with no error | Some students haven't pushed yet, or the quota was already raised |

## Run it locally (optional)

```bash
python3 -m venv .venv && .venv/bin/pip install --no-index --find-links=vendor -r requirements.txt
VCAP_SERVICES='{"user-provided":[{"name":"bootcamp-db","credentials":{"uri":"postgres://user:pass@localhost:5432/bootcamp"}}]}' \
  PORT=8080 .venv/bin/python app.py
```

Then open http://localhost:8080.
