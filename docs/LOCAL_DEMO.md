# Try the product on your own computer (local demo)

This runs the whole product on your computer, so you can click through a milestone yourself.
Everything in it is made up: a made-up business, made-up sample files, a throwaway database. It never
touches AWS, never sends email, and never holds real tax data.

You need **only Docker**. You do not need Node, Python, Git bash, `make` or WSL on Windows.

Quick start on Windows: install Docker Desktop (section 1), open PowerShell in this folder, run
`.\demo.ps1`, open `http://localhost:5173`. (`demo.ps1` has not yet been run on a real Windows computer; if it fails,
use the WSL way in section 2, which is verified only up to the database steps.)

## 1. One-time setup on Windows

1. **Install Docker Desktop for Windows** from <https://www.docker.com/products/docker-desktop/>.
   Use the default options. If it asks to turn on WSL 2, say yes. Restart the computer if it asks.
   It needs Windows 10 or 11 and about 8 GB of memory and 5 GB of free disk.
2. **Start Docker Desktop** from the Start menu and wait until the bottom-left says **Engine running**.
   Leave it open while you use the demo.
3. **Get this project's folder** on your computer (a `git clone`, or "Download ZIP" from GitHub and unzip it).
4. **Open PowerShell in that folder.** In File Explorer, open the folder, click the address bar, type
   `powershell` and press Enter.

## 2. Start it

In that PowerShell window:

```powershell
.\demo.ps1
```

If Windows says "running scripts is disabled on this system", use this instead (it changes nothing
on your computer; it applies only to this one run):

```powershell
powershell -ExecutionPolicy Bypass -File .\demo.ps1
```

The first start downloads and builds things and takes **5 to 10 minutes**; later starts are faster.
When it is ready you will see a green box that prints the exact address:

```
  The demo is ready.  Open this in your browser:

      http://localhost:5173

  Ready-made account (a made-up business, Demo Traders):
      email:     demo@example.com
      password:  Seven-Lamps-42!
```

That address opens the Kartaa landing page (the static site in `landing/`). Its **Sign in** button goes to `http://localhost:5173/signin` and **Sign up** to `/signup`. Someone who is already signed in who opens the address goes straight to their home instead (the app leaves a plain `kartaa_in` cookie while you are signed in, so the web server knows which to show). Real hosting of the landing page is separate and not set up.

Open that address in your browser. Leave the PowerShell window open: **sign-up and password-reset codes
appear in it** (the demo prints them instead of emailing them). **Team invitations are printed there too**: the demo sends no real email, so when you invite someone on the Team page the terminal shows `INVITATION for <email>` and the accept link. Open that link in a browser where you are signed out, sign in (or create an account) with the invited email, and press **Accept the invitation**. A person with no account creates it first, then opens the link again. The link is shown nowhere else: never on the Team page, never in the API log. Press Ctrl+C to stop watching for codes;
the demo keeps running. `.\demo.ps1 codes` watches again.

Stop it, and throw away everything it held, with `.\demo.ps1 stop`. **Every start begins empty**: the demo's
sign-in accounts live in a file inside the demo's own storage, which `stop` removes, so anything you did is forgotten
when it stops. That is expected. Restarting only the API (`docker compose -p gstdemo restart api`) keeps accounts and
signed-in browsers.

### Mac and Linux

Install Docker Desktop (Mac) or Docker Engine with the Compose plugin (Linux), start it, then in this folder:

```bash
./demo.sh          # or: make demo
./demo.sh stop     # or: make demo-stop
```

It does the same things and prints the same box.

### Trying finalize (practice numbers only)

Finalizing an invoice (giving it a number) is **off in the product** until the CA confirms the numbering scope, so by default
the Finalize button does nothing here either. To try it, start the demo with the switch:

```bash
./demo.sh --finalize       # Windows: .\demo.ps1 -Finalize
```

> **Practice only.** Finalize is switched on in this demo's own throwaway database and nowhere else. The numbers it gives
> are practice numbers, not real invoice numbers, and are forgotten when the demo stops. The switch is not available in
> staging or production configuration, and it stays off there until the CA answers (D-010, D-044, CA-1). Without the
> flag the demo behaves as the product ships.

### Windows with WSL (an alternative that is partly verified)

**Status, so you know what to trust:** `.\demo.ps1` is the simplest way and needs none of the steps below, but it has
**not yet been run on a real Windows computer** (it was read line by line and checked on Linux only). The WSL way below uses
the project's normal development setup instead of `demo.ps1`. It has been run on a real Windows computer **only through
`make db-up` and `make db-migrate`** (steps 1 to 5). **Steps 6 to 8 (starting the API and the web app and opening the page)
have not yet been confirmed by anyone**, so treat them as the expected steps, not as proven ones, and tell us what happens.
It shows the product's real pages with your own database; it does not include the demo's made-up business and sample files,
so you create a business through the sign-up page.

**First time (about 30 minutes)**

1. Install **Docker Desktop**, and in Settings > Resources > WSL integration turn on your Ubuntu distro. Install Ubuntu from
   the Microsoft Store if you do not have it, then in PowerShell run `wsl --shutdown` and reopen Ubuntu so the setting takes effect.
   A `docker-desktop` entry in `wsl --status` or `wsl -l -v` is Docker's own and cannot be used for these steps: you need Ubuntu.
2. In Ubuntu, check three things (they are all part of step 2, so the later step numbers stay the same):
   - **Docker:** `docker ps` must print a table. If it says "permission denied ... docker.sock", turn the WSL integration
     on as in step 1; if it still fails, run `sudo usermod -aG docker $USER`, then close and reopen Ubuntu.
   - **Python 3.12:** the project needs it. Ubuntu's own Python may be newer (3.14 at the time of writing) and is too new,
     so install 3.12 from the deadsnakes archive:
     `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update && sudo apt install python3.12 python3.12-venv`.
   - **Node.js 22 or newer** for the web app (`node -v`).
3. Get the code **inside the Linux home folder** (`cd ~`, not under `/mnt/c`, which is slow). The repository is private, so
   sign in with GitHub's own tool: install `gh` (`sudo apt install gh`), run `gh auth login`, follow its browser steps, then
   `gh repo clone pankajkumar-codes/distributor-saas && cd distributor-saas`. Never paste a password or token into a chat or a file.
4. Create the Python environment and install: `python3.12 -m venv .venv && source .venv/bin/activate && make setup PY=python`.
5. Start the database and prepare it: `make db-up`, then `make db-migrate PY=python`. (A Postgres container you already run
   on another port, such as 5332, does not clash: this one uses 5432.)
6. *(Not yet confirmed.)* Start the API in that terminal: `PYTHON=python make run-api`. Leave it running.
7. *(Not yet confirmed.)* Open a **second** Ubuntu terminal and start the web app: `cd ~/distributor-saas/web && npm ci && npm run dev`.
8. *(Not yet confirmed.)* Open <http://localhost:5173> in your Windows browser. Sign-up codes are written to `build/mail/outbox.jsonl` in the project folder (the same
   local mail file as the demo); open that file to read the code.

**Coming back later**

1. Start **Docker Desktop** and wait for "Engine running".
2. Open Ubuntu: the **Ubuntu** Start menu app, or `wsl -d Ubuntu` in PowerShell (`wsl -l -v` lists the exact name; this is
   also how you get back in after `wsl --shutdown`). Then `cd ~/distributor-saas && source .venv/bin/activate`.
3. `make db-up` (your database and data are kept between runs).
4. Start the API again (`PYTHON=python make run-api`) and, in a second Ubuntu terminal, the web app (`cd ~/distributor-saas/web && npm run dev`).
   The API keeps sign-ins in memory, so after a restart you sign in again.

## 3. What is, and is not, real in this demo

- The web pages, the server, the database and the upload pipeline are the real product code at the milestone
  you checked out (R1-M3 at the time of writing).
- **There is no real Amazon, Flipkart or Meesho reader yet** (they arrive in R1-M4). So the demo ships three
  stand-in readers for one **invented** layout, "demo orders", for files named `demo-*.csv`. Real marketplace
  reports are rejected as "We can't read this file's columns" until R1-M4. Everything the demo says about
  the file (its layout is unchecked) is true.
- Sign-in uses a stand-in for Cognito (accounts kept in a file in the demo's storage when run with Docker, in memory otherwise). Email is replaced by the codes in your terminal.
- **Team invitations** (Settings, Your team): no email is sent in the demo. After you press Send invitation, the
  terminal that shows the sign-up codes (`./demo.sh codes`) prints `INVITATION for <email>` and the accept link
  (the same text the real email carries: "<inviter> invited you to join <business> as <role>", then "Accept the
  invitation: <link>"). Use a second browser or a private window. The link works once, for 7 days, only for the
  invited email, and is not shown on the Team page or in the API log.
- **Two-step sign-in** (Settings, Two-step sign-in): an authenticator app on your phone cannot give the right code
  here, because the stand-in has its own code. When you press Turn on, and each time you sign in with it on, the
  demo prints `TWO-STEP CODE for <email>: 123456` in the same terminal as the sign-up codes (`./demo.sh codes`
  shows them again), and the page says so. Type that code. Real Cognito and a real phone app work as normal
  outside the demo. If the page does not answer within 20 seconds it says it could not reach the server.
- The own-invoice Excel reader is real (R1-M5). Its sample is read, previewed and can be confirmed into documents (R1-M7, step 14 below). The PDF reader arrives in R1-M6. Confirming Amazon, Flipkart or Meesho files is refused on purpose, until the CA settles how their rows are treated.
- Retention (clean-up of old uploads) is switched off, as it ships.
- **PDF previews are real** (#387). **Preview PDF** on a saved draft invoice draws the PDF with the same renderer
  code, templates and fonts as the cloud (D-042): a `renderer` piece in the demo watches the render requests and
  turns each into a PDF in a second or two. The first `./demo.sh` after this change builds it, which downloads its
  pinned packages and fonts and adds a few minutes, once. If a preview never comes, `docker compose -p gstdemo logs renderer` shows why
  (it logs only the kind of error, never invoice contents). After three failed tries it marks the preview as failed,
  and the page says the PDF could not be made.
- **Ready-made customers and products.** The Demo Traders account starts with 5 made-up customers and 10 made-up
  products (`demo/demo_data.py`), so you can make an invoice without typing a customer or product first. Names say
  "(made up)" or "(demo)"; the GSTINs have a correct check character but belong to nobody.

  | Customer | GSTIN | State | Tests |
  |---|---|---|---|
  | Demo Retail Kolkata | 19DEMOC1111C1Z7 | West Bengal (19) | B2B, same state (CGST + SGST) |
  | Demo Wholesale Mumbai | 27DEMOD2222D1Z1 | Maharashtra (27) | B2B, other state (IGST) |
  | Demo Walk-in Buyer Howrah | none | West Bengal (19) | B2C, same state |
  | Demo Home Buyer Patna | none | Bihar (10) | B2C, other state (large or small by invoice value) |
  | Demo Distributor Delhi, ships to Siliguri | 07DEMOE3333E1ZU | Bill To Delhi (07), Ship To West Bengal (19) | Bill To and Ship To in different states |

  | Code | HSN / SAC | Unit | GST | Tests |
  |---|---|---|---|---|
  | DEMO-TSHIRT | 6109 | PCS | 5% | 4-digit HSN, has a barcode |
  | DEMO-FABRIC | 520811 | MTR | 5% | 6-digit HSN, price with paise (120.75) |
  | DEMO-CREAM | 33049910 | NOS | 18% | 8-digit HSN |
  | DEMO-HAMPER | none | BOX | 18% | Missing HSN |
  | DEMO-SODA | 22021010 | BTL | 40% | highest rate |
  | DEMO-RING | 7113 | GMS | 3% | weight unit, high price |
  | DEMO-CONSULT | SAC 998311 | OTH | 18% | a service |
  | DEMO-RICE | 1006 | KGS | nil-rated | no rate |
  | DEMO-BOOK | 4901 | NOS | exempt | no rate |
  | DEMO-DIESEL | 2710 | LTR | non-GST | outside GST |

  Every rate applies from 01-02-2026. 12% and 28% are not used because the app's rate list no longer has them from
  that date. The HSN and rate pairs give a spread of cases to test; they are not tax advice. SEZ and export
  customers are not in the list because the app has no SEZ or export invoices yet. These customers and products
  exist only in the local demo, never in staging or production.

## 3b. Trying the GSTIN lookup on sign-up

The demo runs a **fake** lookup (made-up details, never real data). Sign up as yourself, and on "Your business and GST" type any
well-formed GSTIN, for example `19AAPFU0939F1ZS`: the legal name, trade name and address fill with "Demo Traders ..." and a line says
they are made-up demo details. Type over any of them, or ignore them. A GSTIN whose 13th character is `9` finds nothing, `8` shows a
cancelled registration, `7` makes the lookup fail with a plain message; the form works by hand in every case. A real provider is not
connected: see docs/GSTIN_LOOKUP.md.

## 4. Test guide for R1-M3 (uploading your reports)

Sample files are in the **`demo\samples`** folder (`demo/samples`). Use the ready-made account for steps 1 to 12:
the sample files carry that made-up business's GSTIN (`19DEMOA1234A1Z5`), and a GSTIN can belong to only one
business. Step 13 is where you sign up as yourself.

| # | Do this | You should see |
| --- | --- | --- |
| 1 | Sign in. On Home, click **Upload your reports**. | A page "Upload your reports" with four cards: Amazon, Flipkart, Meesho, Your own sales invoices (Excel). The page says every section is optional. |
| 2 | Amazon card: choose `demo-orders-good.csv`, click **Upload**. | "Reading your file..." and then **Read.** |
| 3 | Flipkart card: choose `demo-orders-held-rows.csv`, **Upload**. | **Read.** The page shows only the status; the next step shows what the server made of it. |
| 4 | Open a **second** PowerShell window (the first one is busy showing the sign-in codes) and run `.\demo.ps1 status` | The Flipkart file made one preview with 2 new rows, 1 skipped (a zero-value cancel) and **2 held rows**: DEMO-2002 "HSN missing" and DEMO-2003 "Quantity missing". The Flipkart section says "rows held". |
| 5 | Amazon card: choose `demo-orders-wrong-gstin.csv`, **Upload**. | A red message: **This file is for a different GSTIN than your business.** Nothing is kept. |
| 6 | Amazon card: choose `not-a-report.csv`. | A red message: **We can't read this file's columns. Check it is the right report.** |
| 7 | Meesho card: choose `demo-orders-bundle.zip` (a zip of two files). | **Read.** `.\demo.ps1 status` shows two previews from it (3 rows and 2 rows). |
| 8 | Your own sales invoices card: choose `demo-own-invoices.xlsx`, **Upload**. | **Read.** `.\demo.ps1 status` shows a preview of your own invoices with new rows. Step 14 confirms it. |
| 9 | Amazon card: upload `demo-orders-good.csv` again. | **Read.** No duplicate rows are made: the same file is recognised. |
| 10 | While a file says "Reading...", reload the page. | The card keeps following the upload and finishes. |
| 11 | Set a held row aside: `.\demo.ps1 tool set-aside DEMO-2002 "Checked with the seller: not ours"` | `done`. `.\demo.ps1 status` shows the row as decided, and the Flipkart section now says 1 row held. Set `DEMO-2003` aside too and it says **ready**. |
| 12 | Throw a preview away: take the run id from `.\demo.ps1 status` and run `.\demo.ps1 tool discard <run id>` | `discarded`. That section goes back to "not uploaded", and you can upload the file again. |
| 13 | Sign out, sign up as yourself (code from the terminal), create a different business. Look at its Upload page. | It is empty: you cannot see Demo Traders' files. |
| 14 | Confirm your own invoices: take the run id from `.\demo.ps1 status`, then `.\demo.ps1 tool confirm-check <run id>`, then `.\demo.ps1 tool confirm <run id>` | `confirm-check` lists anything that stops a confirm (for example a profile not yet verified). The demo sets `DEMO_READERS=1`, which opens that gate for this synthetic file only; on a real deployment it stays shut until the owner's real-file check. `confirm` prints the number of documents and lines made. Running it again changes nothing. |

The on-screen GSTR-1 draft built from confirmed documents arrives with a later part of R1-M7. Every figure there is a draft built from the uploaded files and is not filed.

Things that are deliberately not there yet: the preview and "held rows" screens in the browser (the web shows
each upload's status; `status` shows the rest), "accept this row as the file states it" (switched off until the
owner and the CA decide), and real marketplace layouts (R1-M4).

Other helper commands: `.\demo.ps1 upload amazon demo\samples\demo-orders-good.csv` (the same upload without the
browser), `.\demo.ps1 tool status`. On Mac and Linux use `./demo.sh` in place of `.\demo.ps1`.

The helper commands read the sample files from inside the demo image, so `upload` and `tool` work only for files in the repo's `demo\samples` folder. A file of your own, kept anywhere else, is not found until it is in that folder and the image is rebuilt.

## 4b. Test guide: support access (giving it, and opening a business as support)

Support is a separate kind of account. Nothing in the app can make one: the account's flag is set once in the demo's
database, as shown in step 2. Everything below is made-up demo data.

| # | Do this | You should see |
| --- | --- | --- |
| 1 | Signed in as the demo user (owner of Demo Traders), open **Settings**, then **Support access**. Click **Give support read-only access**. | A message "Support can view your business until ... This is in your audit log." with a link **See it in the audit log**, and a card "Support can view your business". |
| 2 | Make a support account. Sign out, sign up as yourself with a different email (code from `./demo.sh codes`), then in a terminal run: `docker compose -f docker-compose.demo.yml exec db psql -U postgres saas -c "update identity.users set is_support = true where email = 'YOUR-EMAIL';"` | `UPDATE 1`. |
| 3 | Sign out and sign in again with that account. | You land on **Turn on two-step sign-in first** (support accounts need it). |
| 4 | Click **Turn on two-step sign-in**, press Turn on, and type the `TWO-STEP CODE` the demo prints (`./demo.sh codes` shows it again). | Two-step sign-in is on. |
| 5 | Open `/support` (or sign out and sign in again, typing a new two-step code). | **Businesses you can view**, listing Demo Traders with "access ends ...". |
| 6 | Click **Demo Traders**. | Its Home. The page is read-only: anything that changes data is refused. |
| 7 | Sign out, sign in as the demo user again, open **Settings, Audit log** (or use **See it in the audit log** on the Support access page). | Entries "Gave support access" and "Support viewed the business" (one for each page support opened). |
| 8 | On the Support access page click **End access now**. Reload `/support` as the support account. | Demo Traders is gone from the list, and "Ended support access" is in the audit log. |

Limits: there is no support console beyond this list and the read-only view, and no tool yet to make a support
account in production (the same database change is made by whoever holds the database owner login).

## 5. If it does not open

Work down this list.

1. **"Docker is not installed / not running."** Open Docker Desktop and wait for **Engine running**. The whale
   icon in the taskbar stops moving when it is ready. Then run `.\demo.ps1` again. If Docker Desktop says
   virtualization is disabled, turn on virtualization in the BIOS/UEFI (an option usually called VT-x, SVM or
   "Virtualization Technology") and restart.
2. **"Port 5173 is already used."** Another program has the address. Find it:
   `Get-NetTCPConnection -LocalPort 5173 -State Listen | Select-Object OwningProcess` then
   `Get-Process -Id <that number>`. Close it (often a leftover `npm run dev` or `vite` window), or restart the
   computer, then run `.\demo.ps1` again.
3. **A Windows Firewall question appears.** The demo only listens on this computer (`127.0.0.1`), so you can press
   **Cancel**; it does not need network access. If your browser still cannot reach `localhost:5173`, turn off any VPN
   or "web protection" extension for a moment and try again.
4. **The browser says "can't be reached" but the box said ready.** The page may still be starting. Wait a minute,
   refresh, and run `.\demo.ps1 status`. If it prints `Sections: ...` the server is up. If it says it cannot
   sign in, wait a minute (sign-in is rate limited) and try once more.
5. **The page opens but says "sign in again" in a loop, or the ready-made account is refused.** The server was
   restarted behind your back, which makes it forget its sign-ins. Run `.\demo.ps1 stop`, then `.\demo.ps1`.
6. **The build failed (red lines).** The usual causes are no internet while it builds, or Docker is out of disk
   space or memory (Docker Desktop > Settings > Resources). Free space, then `.\demo.ps1 stop` and `.\demo.ps1`.
7. **"unknown flag: --wait" or "compose" is not a command.** Docker Desktop is too old. Update it to 4.20 or newer.
8. **"Email me a code" greys out and nothing happens, or the code step says "did not accept the address".** Open the
   page at exactly `http://localhost:5173` (the address the green box printed), not an IP address or a computer
   name: the server only accepts sign-in from that address. A sign-up request that gets no answer is given up
   after 20 seconds and the screen says it could not reach the server, so the button works again. The demo sends
   no email: the 6-digit code appears in the terminal window where you started the demo (`./demo.sh codes`
   shows it again), and the sign-up screens in the demo say so. If the request itself keeps failing, run
   `docker compose -f docker-compose.demo.yml logs api` and send the last 30 lines.
9. **Sign-in or the page says "The server is taking too long to answer".** The browser gave up waiting after 20 seconds. The
   server is running but one request is slow; it is not "unreachable". Run `./demo.sh check` (or `.\demo.ps1 check`): every
   line should say `HTTP 200` in well under a second. If it does, press **Try again**. If it does not, or it keeps
   happening, go to "If something fails, send this" below. Known causes: a slow Docker disk (the project folder on the
   Windows disk, `/mnt/c`, with WSL), and a database connection that went dead while the computer slept (guarded against in the code from this change on:
   the API now notices a dead database connection within seconds; start the demo again after pulling).
10. **Where to look.** The page is `http://localhost:5173`. The API has no address of its own on your computer: it runs
    inside Docker and is reached through the page, so `http://127.0.0.1:8000` will never open and that is correct. To test
    the API, use `http://localhost:5173/api/v1/health` (it should print `{"status":"ok"}`).
11. **After every `git pull`, run `./demo.sh` (or `.\demo.ps1`) again.** It rebuilds from the files you now have and starts
    clean (it stops and forgets the old one first). Opening the page without doing this shows the old version. Then
    reload any Kartaa tab you still have open (a tab left open keeps running the old app until it is reloaded).

### WSL (Windows): keep the project inside Ubuntu

Docker Desktop with WSL is slow when the project folder is on the Windows disk (`/mnt/c/...`): every build copies the folder
across, and a start can take many minutes. Keep it in the Ubuntu home folder instead:

```bash
cd ~
git clone https://github.com/pankajkumar-codes/distributor-saas.git   # or: cp -r /mnt/c/Users/<you>/distributor-saas ~/distributor-saas
cd ~/distributor-saas
./demo.sh stop        # only if an older demo is still running from the old folder
./demo.sh
```

From then on work only in `~/distributor-saas`. (The Windows folder keeps working, just slower. The demo's database keeps
its data in memory, not on any disk, so it never waits for the disk.)

### If something fails, send this

1. In the project folder run `./demo.sh logs` (PowerShell: `.\demo.ps1 logs`). It writes **`demo-logs.txt`** holding the
   container list and the logs of every piece (web, API, database, migrations, codes) with times. Made-up data only.
2. Send that file and a screenshot of the browser error, with the time it happened. Also run `./demo.sh check` and paste
   its output.
3. Live view while you reproduce it: `docker compose -p gstdemo logs -f api web db` (Ctrl+C to stop watching).
   `docker compose -p gstdemo ps` lists the pieces. The project name is `gstdemo`.
4. **At the moment it fails** (page says "We couldn't reach the server"), run these four, in this order, and send the results:
   1. inside the web container: `docker compose -p gstdemo exec web wget -q -T 5 -O - http://127.0.0.1:5173/api/v1/health`
   2. from WSL or Mac/Linux: `curl -m 10 -i http://127.0.0.1:5173/api/v1/health`
   3. from Windows PowerShell: `curl.exe -m 10 -i http://127.0.0.1:5173/api/v1/health`
   4. `docker compose -p gstdemo logs --since 5m web api`, and a screenshot of the browser's Network tab (F12) showing
      the failed request's status (failed, blocked, cancelled or pending).
   If (1) answers and (2) or (3) hang, Docker's port forwarding between your computer and the container is the problem, not
   the demo; `./demo.sh check` runs (1) for you. If (1) hangs, the API itself is frozen (it runs some database calls on its event loop, so one stuck database call stops every request, even `/health`); `docker compose -p gstdemo restart api` frees it, and accounts and signed-in browsers are kept (never restart only the database: it lives in memory and would lose its data). Also send `./demo.sh check` (it lists CPU and memory per piece).
5. More detail from the API: `UVICORN_LOG_LEVEL=debug ./demo.sh` (the database already logs any statement slower than
   half a second, and lock waits).

## 6. How it is built (for the team)

`docker-compose.demo.yml` starts PostgreSQL 16, applies every migration (`migrator.local`, the same code CI
uses), starts the API with `PLATFORM_ENV=local` (jobs run inline, files go to a local folder, mail goes to a file)
and `DEMO_READERS=1`, serves the built web app with nginx (`demo/nginx.conf`: it passes `/api` to the API, opening a fresh connection for every request and giving up after 3 s to connect, so no stuck connection can wedge the page), and runs
`demo/watch_codes.py` to print codes. `demo/seed.py` signs the demo user up through the API's own sign-up path
and creates the made-up business, then adds the customers and products in `demo/demo_data.py` through the same
API (only the ones missing, so a re-run adds nothing). Sample files are built by `demo/make_samples.py`; a test keeps the committed
files equal to the generator's output and checks each file does what section 4 says.
The `renderer` piece (`demo/render_watch.py`, image target `renderer` in `demo/Dockerfile`) is built by
`scripts/build_renderer.py` from the Lambda's own locks for this computer's processor, runs with no network, and
calls `renderer.handler.render_one` on each new `render-input/.../input.json` in the shared `build` volume, writing
`documents/.../document.pdf` (or `failed.json` after 3 tries) the way the Lambda writes to S3. The API is unchanged:
locally it still only records the render message (`app/src/app/runtime.py`), and nothing about AWS changes.
`app/src/app/demo_readers.py` registers the stand-in readers only when `DEMO_READERS=1` and the environment is
local or test (never on Lambda).
