# Try the product on your own computer (local demo)

This runs the whole product on your computer, so you can click through a milestone yourself.
Everything in it is made up: a made-up business, made-up sample files, a throwaway database. It never
touches AWS, never sends email, and never holds real tax data.

You need **only Docker**. You do not need Node, Python, Git bash, `make` or WSL on Windows.

Quick start on Windows: install Docker Desktop (section 1), open PowerShell in this folder, run
`.\demo.ps1`, open `http://localhost:5173`.

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
      password:  seven lamps under a bridge
```

Open that address in your browser. Leave the PowerShell window open: **sign-up and password-reset codes
appear in it** (the demo prints them instead of emailing them). Press Ctrl+C to stop watching for codes;
the demo keeps running. `.\demo.ps1 codes` watches again.

Stop it, and throw away everything it held, with `.\demo.ps1 stop`. **Every start begins empty**: the demo's
sign-in lives in memory, so anything you did is forgotten when it stops. That is expected.

### Mac and Linux

Install Docker Desktop (Mac) or Docker Engine with the Compose plugin (Linux), start it, then in this folder:

```bash
./demo.sh          # or: make demo
./demo.sh stop     # or: make demo-stop
```

It does the same things and prints the same box.

### Windows with WSL (only if the PowerShell way does not work for you)

First time:

1. In PowerShell: `wsl --install -d Ubuntu`. Restart Windows if asked, open the **Ubuntu** app and make a
   username and password. (A `docker-desktop` entry in `wsl --status` is Docker's own and is not usable for this.)
2. Docker Desktop > Settings > Resources > WSL integration: switch on **Ubuntu**, Apply & restart. In Ubuntu,
   `docker ps` must print a table, not "permission denied". If it still fails: `sudo usermod -aG docker $USER`,
   close and reopen Ubuntu.
3. In Ubuntu: `sudo apt update && sudo apt install -y make git curl`.
4. The repository is private, so sign in to GitHub first. Install the GitHub CLI
   (<https://github.com/cli/cli/blob/trunk/docs/install_linux.md>), then `gh auth login`: GitHub.com, HTTPS,
   authenticate Git: Yes, log in with a web browser. Never type a GitHub password at a `git clone` prompt and
   never paste a token into a chat.
5. Clone **inside the Linux home folder**, not under `/mnt/c` (slow, and file-permission problems):
   `cd ~ && git clone https://github.com/pankajkumar-codes/distributor-saas && cd distributor-saas`
6. `./demo.sh` (the same as `make demo`). Open `http://localhost:5173`.

Every later time (for example after `wsl --shutdown` or a restart):

1. Start Docker Desktop and wait for **Engine running**.
2. Open Ubuntu: the **Ubuntu** Start menu app, or `wsl -d Ubuntu` in PowerShell (`wsl -l -v` lists the names).
3. `cd ~/distributor-saas && git pull && ./demo.sh`. `git pull` brings the newest milestone. Run
   `./demo.sh stop` first if an older demo is still running. Each start begins empty.

If you cloned under `/mnt/c/...` already, it works but is slow; move to the home folder when convenient.

## 3. What is, and is not, real in this demo

- The web pages, the server, the database and the upload pipeline are the real product code at the milestone
  you checked out (R1-M3 at the time of writing).
- **There is no real Amazon, Flipkart or Meesho reader yet** (they arrive in R1-M4). So the demo ships three
  stand-in readers for one **invented** layout, "demo orders", for files named `demo-*.csv`. Real marketplace
  reports are rejected as "We can't read this file's columns" until R1-M4. Everything the demo says about
  the file (its layout is unchecked) is true.
- Sign-in uses an in-memory stand-in for Cognito. Email is replaced by the codes in your terminal.
- Own-invoice Excel and PDF readers come in R1-M5 and R1-M6, so those uploads are refused in plain words.
- Retention (clean-up of old uploads) is switched off, as it ships.

## 4. Test guide for R1-M3 (uploading your reports)

Sample files are in the **`demo\samples`** folder (`demo/samples`). Use the ready-made account for steps 1 to 12:
the sample files carry that made-up business's GSTIN (`19DEMOA1234A1Z5`), and a GSTIN can belong to only one
business. Step 13 is where you sign up as yourself.

| # | Do this | You should see |
| --- | --- | --- |
| 1 | Sign in. On Home, click **Upload your reports**. | A page "Upload your reports" with four cards: Amazon, Flipkart, Meesho, Your own sales invoices (Excel). The page says every section is optional. |
| 2 | Amazon card: choose `demo-orders-good.csv`, click **Upload**. | "Reading your file..." and then **Read.** |
| 3 | Flipkart card: choose `demo-orders-held-rows.csv`, **Upload**. | **Read.** The page shows only the status; the next step shows what the server made of it. |
| 4 | In PowerShell: `.\demo.ps1 status` | The Flipkart file made one preview with 2 new rows, 1 skipped (a zero-value cancel) and **2 held rows**: DEMO-2002 "HSN missing" and DEMO-2003 "Quantity missing". The Flipkart section says "rows held". |
| 5 | Amazon card: choose `demo-orders-wrong-gstin.csv`, **Upload**. | A red message: **This file is for a different GSTIN than your business.** Nothing is kept. |
| 6 | Amazon card: choose `not-a-report.csv`. | A red message: **We can't read this file's columns. Check it is the right report.** |
| 7 | Meesho card: choose `demo-orders-bundle.zip` (a zip of two files). | **Read.** `.\demo.ps1 status` shows two previews from it (3 rows and 2 rows). |
| 8 | Your own sales invoices card: choose `demo-own-invoices.xlsx`. | A red message: **We can't read this kind of report yet.** (Reading your own invoices is a later milestone.) |
| 9 | Amazon card: upload `demo-orders-good.csv` again. | **Read.** No duplicate rows are made: the same file is recognised. |
| 10 | While a file says "Reading...", reload the page. | The card keeps following the upload and finishes. |
| 11 | Set a held row aside: `.\demo.ps1 tool set-aside DEMO-2002 "Checked with the seller: not ours"` | `done`. `.\demo.ps1 status` shows the row as decided, and the Flipkart section now says 1 row held. Set `DEMO-2003` aside too and it says **ready**. |
| 12 | Throw a preview away: take the run id from `.\demo.ps1 status` and run `.\demo.ps1 tool discard <run id>` | `discarded`. That section goes back to "not uploaded", and you can upload the file again. |
| 13 | Sign out, sign up as yourself (code from the terminal), create a different business. Look at its Upload page. | It is empty: you cannot see Demo Traders' files. |

Things that are deliberately not there yet: the preview and "held rows" screens in the browser (the web shows
each upload's status; `status` shows the rest), "accept this row as the file states it" (switched off until the
owner and the CA decide), and real marketplace layouts (R1-M4).

Other helper commands: `.\demo.ps1 upload amazon demo\samples\demo-orders-good.csv` (the same upload without the
browser), `.\demo.ps1 tool status`. On Mac and Linux use `./demo.sh` in place of `.\demo.ps1`.

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
8. **Still stuck?** Save the logs and send them with a screenshot of the PowerShell window:

```powershell
docker compose -f docker-compose.demo.yml logs --no-color > demo-logs.txt
```

The logs contain only made-up data and the sign-up codes shown on screen.

## 6. How it is built (for the team)

`docker-compose.demo.yml` starts PostgreSQL 16, applies every migration (`migrator.local`, the same code CI
uses), starts the API with `PLATFORM_ENV=local` (jobs run inline, files go to a local folder, mail goes to a file)
and `DEMO_READERS=1`, serves the built web app with `vite preview` (which passes `/api` to the API), and runs
`demo/watch_codes.py` to print codes. `demo/seed.py` signs the demo user up through the API's own sign-up path
and creates the made-up business. Sample files are built by `demo/make_samples.py`; a test keeps the committed
files equal to the generator's output and checks each file does what section 4 says.
`app/src/app/demo_readers.py` registers the stand-in readers only when `DEMO_READERS=1` and the environment is
local or test (never on Lambda).
