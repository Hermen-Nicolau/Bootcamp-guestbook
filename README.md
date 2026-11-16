# Tanzu Bootcamp Guestbook

A small guestbook app for the Tanzu Platform for Cloud Foundry Bootcamp. Each student pushes their own copy into their own space, and every copy connects to the **same Postgres database**. Anyone who signs the guestbook with their name and hometown shows up on everyone else's page within 3 seconds.

## What this lab teaches

| Concept | Where you see it in the lab |
| --- | --- |
| Orgs, spaces and roles | You create and work in your own space in the bootcamp org |
| `cf push` and manifests | You deploy the app using the manifest in this repo |
| Services and binding | You connect your app to a database service the instructor prepared |
| `VCAP_SERVICES` | The app reads its database credentials from the environment, and none live in the code |
| Logs and status | You inspect the same app from the cf CLI and from Apps Manager |
| Quotas | Scaling up runs into a limit you have to find and get raised |
| Load balancing and HA | With several instances, the page shows the GoRouter rotating requests |
| Cleanup | You remove everything you created without affecting anyone else |

## How the app works

```
Browser ──► GoRouter ──► bootcamp-app-<you> (your space)
                                   │  bound to bootcamp-db (user-provided, in your space)
                                   ▼  credentials from VCAP_SERVICES
              bootcamp-postgres (marketplace Postgres, in the instructor's space)
                                   ▲
Other students' apps ──► their own bootcamp-db (same credentials) ──┘
```

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

### Files

```
app.py             the whole app
manifest.yml       instances, memory, buildpack, route and health check settings
Procfile           how the platform starts the app
requirements.txt   pg8000
vendor/            pg8000 and its dependencies as wheels, for offline staging
```

---

## The lab (about 45 minutes)

This lab doesn't give you the commands. You get a goal for each task and a way to check you've reached it, and you work out how to get there. `cf help -a`, `cf <command> --help`, Apps Manager and the Day 1 slides have everything you need. Work with your neighbours, and ask the instructor when you're stuck for more than a few minutes.

The instructor will give you:

- the cf API endpoint and the Apps Manager URL
- the name of the bootcamp org

Use your first name in lowercase wherever this guide says `<you>`.

### Task 1 – Your own space

**Goal:** you're logged in to the foundation with the cf CLI, and you're targeting a space named `<you>` inside the bootcamp org.

**You're done when:**
- `cf target` shows the bootcamp org and your space
- you can name the roles you hold in your space, and explain how you got them

**Think about:** Can a classmate see what you deploy in your space? Why or why not?

### Task 2 – Deploy the app

**Goal:** the app from this repo is running in your space as `bootcamp-app-<you>`, with one instance.

**You're done when:**
- the app shows as running, with 1 of 1 instances
- you can open its route in a browser and see the guestbook page
- you can explain what the red status bar is telling you

**Hints:**
- Read `manifest.yml` before you deploy. What does it decide for you?
- The app name in the manifest isn't `bootcamp-app-<you>`. How do you deploy it under your own name?
- `/db` tells you, in JSON, whether the app can reach a database.

**Think about:** Which parts of the app's status are the desired state, and which are the actual state?

### Task 3 – Connect to the shared database

**Goal:** your app is connected to the database through the `bootcamp-db` service in your space, and you've signed the guestbook.

**You're done when:**
- the status bar on your page is green
- `/db` returns `"ok": true`
- your entry appears on the page, and your classmates' entries appear on your page as they sign

**Hints:**
- The service already exists in your space. Find it before you try to create anything.
- Connecting a service to an app takes more than one step. A running app doesn't see new environment variables on its own.
- Find where the app gets its database credentials. What is the name of that environment variable, and what's in it?

**Think about:**
- Your app and your classmate's app run in different spaces, yet they show the same data. How?
- Every space's `bootcamp-db` holds the same credentials. What are the downsides of that?

### Task 4 – Observe your app

**Goal:** you can answer questions about your app from both the cf CLI and Apps Manager.

**Find and compare, in both tools:**
- the app's state, instance count, and memory use per instance
- the history of what has happened to the app (push, bind, restart)
- the services bound to it, and its environment variables
- its logs, both recent and live

**In the logs, find:**
- a line from staging
- a line from the Cloud Controller about something you did
- a line from your app when someone signs the guestbook
- a GoRouter line for a request. What's the status code, and how does `response_time` compare to `gorouter_time`?

**Think about:** If you had to open a ticket about a slow request, which value from the router log would you include?

### Task 5 – Scale out

**Goal:** your app runs 3 instances.

**Expect a failure on the way.** When it happens:
- read the error and work out what limit you've hit, and where it's set
- find the numbers behind it: what's the limit, and what's using it up?
- work out who has permission to raise that limit, and ask the instructor

**You're done when:**
- the app shows 3 of 3 instances
- the status bar on your page shows different instances answering as it refreshes
- new log lines from your app come from more than one instance

**Think about:**
- You only asked for 2 more instances. Why wasn't there room?
- Which high availability level from Day 1 do 3 instances give you?

### Task 6 – Clean up

**Goal:** you've removed everything you created, in the right order, without affecting anyone else.

**You're done when:**
- your app is no longer bound to `bootcamp-db`, and you've confirmed the app noticed
- `bootcamp-db` is gone from your space
- your app and its route are gone, and listing apps, routes and services in your space shows nothing

**Think about:**
- After you unbind, does the running app lose its database connection right away? Why or why not?
- Deleting `bootcamp-db` from your space doesn't delete the database or your classmates' entries. Why?
- If you delete an app without removing its route, what's left behind?

---

## When you're stuck

| What you see | Where to look |
| --- | --- |
| "Not authorized" | Which role does that command need? Check your roles in the org and in your space |
| The status bar says no database is bound | Is the service bound? Did the app pick up the change? |
| Bound, but the connection times out | Something between the app container and the database is blocking traffic. Which Day 2 topic controls outgoing traffic from apps? |
| `bootcamp-db` isn't in your space | Ask the instructor. It's created for each space after everyone has one |
| Staging fails | Does the buildpack in the manifest exist on this foundation? Is the `vendor/` folder complete? |
| A classmate's entries don't show | Compare the database host your app and theirs are using |
| Scaling worked without an error | Maybe someone already raised the limit. Check what it is now |

## Run it locally (optional)

```bash
python3 -m venv .venv && .venv/bin/pip install --no-index --find-links=vendor -r requirements.txt
VCAP_SERVICES='{"user-provided":[{"name":"bootcamp-db","credentials":{"uri":"postgres://user:pass@localhost:5432/bootcamp"}}]}' \
  PORT=8080 .venv/bin/python app.py
```

Then open http://localhost:8080.

---

*Instructors: the full step-by-step commands, setup and answer key are in the instructor lab guide, not in this repo.*
