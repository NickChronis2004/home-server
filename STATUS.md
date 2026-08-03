# JARVIS Project Status

Τελευταία ενημέρωση: 2026-08-03

Σκοπός αυτού του αρχείου: μία γρήγορη ματιά για το "τι έχουμε χτίσει, τι μένει, τι έχει αποφασιστεί αλλά όχι υλοποιηθεί" — χωρίς να χρειάζεται να ψάχνουμε παλιά chats. Ενημερώνεται στο τέλος κάθε session μαζί με το README.

---

## Ολοκληρωμένα

| Feature | Τι κάνει | Ημερομηνία |
|---|---|---|
| **Core orchestrator** | FastAPI service, tool discovery από manifests, confirm-flow, audit logging (SQLite) | — |
| **Emergency protocols** (SNOWFALL / BLACKOUT / DAYBREAK) | SNOWFALL: instant soft lockdown μέσω chat. BLACKOUT: hard stop του orchestrator, μόνο SSH. DAYBREAK: recovery, μόνο SSH, ποτέ μέσω chat | — |
| **Kill switch** | Σταματά μόνο Ollama + Open WebUI, όχι τον orchestrator | — |
| **Backups** (`protocol_permafrost`) | `backup.sh`/`restore.sh`, auto-discovery Docker volumes, 7-run retention, external USB sync, `--test` sandbox mode | — |
| **Sandbox** (gVisor) | Python code execution, πλήρως απομονωμένο | — |
| **`diagnose_system`** | Read-only, πλήρης εικόνα: container status/health/restarts, log scan, disk usage | 2026-08-01 |
| **`repair_system`** | `clean_docker_disk` (μη λειτουργικό, βλ. known limitations) + `clean_build_cache` (λειτουργικό) | 2026-08-01 |
| **Docker Policy Broker** | 3 dedicated proxies (read/lifecycle/maintenance), κανένα άμεσο mount `docker.sock`, mount split (`:ro` παντού εκτός `logs/`, `jarvis-backups/`). Routing ολοκληρωμένο σε 7/7 tools. Negative tests περασμένα | 2026-08-01/02 |
| **`summarize_inbox`** | Read-only IMAP, CSD UoC mailbox, explicit readonly mode | 2026-08-02 |
| **Loki + Grafana** | Centralized log aggregation, isolated `observability-net`, Grafana port 3002 | 2026-08-03 |
| **`list_recent_backups`** | Read-only listing των backup runs — μέγεθος, volumes, USB sync, per-component OK/FAIL/WARN | 2026-08-03 |
| **`os-helper`** | Host-side systemd daemon, 3 read-only endpoints (failed units, disk health, network state) | 2026-08-03 |
| **`ufw`** | Ενεργοποιήθηκε στο host, με SSH+os-helper rules | 2026-08-03 |

---

## 🔧 Docker Policy Broker — τεχνικές λεπτομέρειες

### Αρχιτεκτονική

3 proxy instances (`docker-read-proxy`, `docker-lifecycle-proxy`, `docker-maintenance-proxy`), `tecnativa/docker-socket-proxy`, pinned με digest, το καθένα στο δικό του internal network:

- **read-proxy**: `CONTAINERS=1, SYSTEM=1, VOLUMES=1, POST=0` — read-only
- **lifecycle-proxy**: `POST=1, CONTAINERS=0, ALLOW_START/STOP/RESTARTS=1` — μόνο 3 lifecycle endpoints
- **maintenance-proxy**: `POST=1, CONTAINERS=1, BUILD=1, SYSTEM=0, IMAGES=0, NETWORKS=0`

Mount split στον orchestrator: `policy.yaml`, `tools/`, `lib/`, scripts όλα `:ro`. Μόνο `logs/` και `jarvis-backups/` `:rw`. Port 8001 σε `127.0.0.1` μόνο.

`lib/docker_env.py`: `docker_env(proxy)` → env dict με σωστό `DOCKER_HOST`. Import pattern: `sys.path.insert(0, "/app/jarvis/lib")` (flat import, `lib/` δεν είναι package).

### Routing — 7/7 tools

`restart_container`, `stop_container`, `start_container`, `check_docker_status`, `diagnose_system`, `repair_system`, `sandbox` — όλα routed. `protocol_permafrost` χρειάστηκε **dual-proxy** routing (`docker_read()`/`docker_maintenance()` wrappers στο `backup.sh`, no-op fallback σε local socket για SSH/manual usage).

### Bugs βρέθηκαν + διορθώθηκαν

- **`start_container`**: ένα από τα δύο subprocess calls ξέχασε το `env=docker_env(...)`. Μάθημα: μετά από κάθε multi-call routing change, `grep -c 'subprocess.run'` έναντι `grep -c 'env=docker_env'`.
- **`clean_build_cache`**: `docker builder prune` είναι buildx CLI command, όχι daemon API call — δεν δουλεύει μέσω proxy (buildx context state δεν υπάρχει μέσα στον orchestrator). Fix: απευθείας `POST /build/prune` μέσω `urllib`, καλύπτεται ήδη από `BUILD=1, POST=1`.
- **`VOLUMES=1` duplicate στο read proxy**: πρώτη προσπάθεια πρόσθεσε `VOLUMES=1` αλλά υπήρχε ήδη ξεχασμένο `VOLUMES=0` παρακάτω στο ίδιο compose block — το τελευταίο σε YAML list-style environment νικάει.
- **🔴 Self-referential tar στο `backup_config()`** (σοβαρό): το tar του `$JARVIS_HOME` δεν εξαιρούσε το `jarvis-backups/` directory (μέσα στο ίδιο `$JARVIS_HOME`), οπότε προσπαθούσε να συμπεριλάβει το ίδιο του το output αρχείο — unbounded growth, 7.6GB → 23GB → 35GB σε διαδοχικά failed runs, δίσκος έφτασε 129GB χρήση. Fix: `--exclude` του backup output directory. Επηρέαζε και το SSH-manual path, όχι μόνο JARVIS-triggered.
- **Confirmation-flow bug (system prompt)**: το JARVIS απαντούσε "γράψε /confirm" σε φυσική γλώσσα χωρίς να καλεί το tool με `confirmed=false` πρώτα — ποτέ δεν δημιουργούνταν pending action. Fix: ρητή οδηγία στο system prompt να καλείται πάντα το tool πρώτα.

### Γνωστοί περιορισμοί (σκόπιμα, όχι bugs)

- **Lifecycle proxy δεν κάνει per-container filtering** — μόνο επίπεδο ενέργειας. Vaultwarden protection είναι αποκλειστικά στο Python `policy.yaml` layer.
- **Maintenance proxy είναι το πιο φαρδύ** (`POST=1, CONTAINERS=1`) — sandbox/permafrost χρειάζονται πραγματικά container-create access.
- **`clean_docker_disk` μη λειτουργικό** — χρειάζεται `NETWORKS`/`IMAGES` που σκόπιμα δεν ανοίξαμε.

### Backup regression (αποδεκτό)

Μετά το mount split, το backup δεν περιλαμβάνει πλέον `README.md`, `STATUS.md`, `docker-compose.proxies.yml`, `.git/` — ζουν ήδη στο GitHub repo.

### Μελλοντικό — custom broker (ρητά εκτός scope)

Αξιολογήθηκε, αποφασίστηκε συνειδητά όχι τώρα: custom FastAPI broker (Docker SDK) με sanitized endpoints, ξεχωριστοί fixed-function agents (maintenance/permafrost/sandbox), lifecycle broker με πραγματικό per-container policy. Θα αξιολογηθεί ξανά αν το threat model αλλάξει (π.χ. exposure πέρα από Tailscale-only, περισσότεροι χρήστες).

---

## 📧 `summarize_inbox` — τεχνικές λεπτομέρειες (2026-08-02)

Read-only IMAP (`mailhost.csd.uoc.gr:993`), explicit `readonly=True` στο `select()` — πρωτόκολλο-επίπεδο εγγύηση, όχι μόνο "δεν γράψαμε write code". Secrets στο `orchestrator/.env` (**όχι** `~/jarvis/.env` — δεν υπάρχει). Default `mode=since` (χθες) — το `mode=unseen` δοκιμάστηκε πρώτα, πολύ θορυβώδες.

**Bugs:** manifest schema mismatch (πρώτη εμφάνιση αυτού του pattern bug, βλ. παρακάτω η γενική ενότητα) · `.env` path confusion (`orchestrator/.env`, όχι root) · `docker restart` δεν ξαναδιαβάζει `.env` (χρειάζεται `--force-recreate`) · directory typo (`summirize_inbox`) · HTML-only emails έδιναν raw markup (fix: strip tags μέσω stdlib `html.parser`).

**Δεν υλοποιήθηκε (συνειδητά):** cron-triggered daily run + Open WebUI message-posting — μένει on-demand μόνο, απλούστερο.

---

## 📊 Loki + Grafana — τεχνικές λεπτομέρειες (2026-08-03)

Loki + Promtail (host-level, `docker_sd_configs` auto-discovery, **όχι** driver plugin — μηδενικές αλλαγές σε υπάρχοντα services) + Grafana, σε δικό τους isolated `observability-net`. Grafana στο port **3002** (3000 = open-webui, 3001 = uptime-kuma, και τα δύο ήδη κατειλημμένα). 7-day retention.

**Bug:** custom timestamp-extraction regex στο Promtail pipeline προκαλούσε `"timestamp too new"` errors στο Loki — fix: αφαιρέθηκε εντελώς, εμπιστευόμαστε το native Docker envelope timestamp αντί να το ξαναμαντεύουμε από το log text.

Ξεχωριστό, ανεξάρτητο compose project (`~/jarvis-observability/`) — δεν αγγίζει τίποτα από το `docker-compose.proxies.yml`. JARVIS δεν queries το Loki μέσω chat σήμερα (θεωρήθηκε περιττό — το ήδη υπάρχον `get_container_logs` καλύπτει το καθημερινό use case).

---

## 📦 `list_recent_backups` — τεχνικές λεπτομέρειες (2026-08-03)

Read-only, καμία proxy (pure filesystem read). Διαβάζει backup directories + `backup.log`.

**Bugs:**
- **Log-block parsing**: το parser περίμενε γραμμή `"Backup completed"` για να κλείσει κάθε run block — δεν υπάρχει πάντα σε αυτή τη μορφή στο πραγματικό log. Fix: το block κλείνει στον επόμενο header ή EOF, όχι σε συγκεκριμένο footer text.
- **Many-to-one timestamp matching** (σοβαρότερο): naive "nearest absolute distance" matching επέτρεπε σε ένα directory run να "κλέψει" το log summary ενός **γειτονικού, διαφορετικού** run (ένα dry-run block ήταν χρονικά πιο κοντά σε λάθος directory απ' ό,τι το δικό του σωστό summary, επειδή το πραγματικό run πήρε πάνω από ένα λεπτό να τρέξει). Fix: forward-only, one-to-one matching — ένα log summary πρέπει να είναι ίσο ή μεταγενέστερο του directory start time, και κάθε log entry καταναλώνεται μία φορά.
- **`~` resolve-άρει σε `/root`**: βλ. γενική ενότητα bugs παρακάτω.

---

## 🖥️ `os-helper` — τεχνικές λεπτομέρειες (2026-08-03)

### Σκοπός & αρχιτεκτονική

Πρώτο host-OS-level tooling — μέχρι τώρα όλα τα tools έβλεπαν τον κόσμο μόνο μέσα από Docker. Ξεχωριστό systemd service στο host (`os-helper.service`, Python stdlib `http.server`, port 8787), **όχι** container — το `systemctl --failed` χρειάζεται πρόσβαση στο systemd D-Bus socket του host, που μέσα από container θα σήμαινε `--pid=host` ή αντίστοιχο, σπάζοντας το isolation μοντέλο. Ο orchestrator μιλάει μέσω `host.docker.internal:8787` (`extra_hosts` στο compose).

### Privilege separation για SMART data

Αρχικό σχέδιο (`sudo smartctl` μέσα στο `os-helper.service`) απέτυχε — το `NoNewPrivileges=true` απενεργοποιεί **και** sudo **και** file capabilities (`setcap`) κατά το `execve()`, όχι μόνο setuid binaries. Τελική λύση, πλήρης privilege separation:

```
jarvis-smart-snapshot.timer (κάθε 5 λεπτά)
        ↓
jarvis-smart-snapshot.service [root, oneshot, hardcoded device list, καμία network exposure]
        ↓ atomic write
/run/jarvis-os-helper/smart-health.json
        ↑ read-only
os-helper.service [jarvis-oshelper user, NoNewPrivileges=true]
```

Το `os-helper.service` ποτέ δεν καλεί `smartctl` απευθείας. `get_disk_health` reports `age_seconds`/`stale`.

### Bugs βρέθηκαν + διορθώθηκαν

1. **Manifest schema mismatch** (ξαναβρέθηκε — ήδη καταγεγραμμένο από το `summarize_inbox` session): `tier` → έπρεπε `privilege_tier`, `parameters: {}` → έπρεπε `parameters: []` (λίστα, ποτέ dict). 4 tools επηρεάστηκαν (τα 3 os-helper + `list_recent_backups`). Τώρα τεκμηριωμένο στο README ως μόνιμο checklist item.
2. **`sys.path.insert` λάθος directory depth**: `lib/` είναι **αδερφός** του `tools/` κάτω από `/app/jarvis/` (δύο ξεχωριστά compose mounts), όχι εμφωλευμένο μέσα του. Χρειαζόταν `../../lib`, όχι `../lib`.
3. **`~` resolve-άρει σε `/root`**: ο orchestrator process τρέχει σαν root μέσα στο container. Standalone SSH tests (`~` = `/home/nickchronis2004`) έδειχναν sw δουλεύει, production όχι. Fix: hardcoded `/app/jarvis/jarvis-backups` αντί για `os.path.expanduser("~/...")`.
4. **`docker restart` δεν αρκεί για compose-level αλλαγές**: το `extra_hosts` directive χρειάστηκε πλήρες `--force-recreate` — ίδιο μάθημα με το `.env` finding του `summarize_inbox` session, τώρα επιβεβαιωμένο ότι ισχύει γενικά, όχι μόνο για env vars.

**Παρατήρηση:** τα bugs #2 και #3 είναι και τα δύο παραλλαγές του ίδιου υποκείμενου λάθους — υπόθεση για το πώς μοιάζει το filesystem/environment μέσα στον container, χωρίς πρώτα να το επιβεβαιώσω. Το νέο "Adding a New Tool" checklist στο README υπάρχει ρητά γι' αυτό.

### Known limitation (hardware, όχι bug)

Το εξωτερικό USB backup drive (`/dev/sdc`) δεν υποστηρίζει SMART passthrough μέσω του συγκεκριμένου USB-bridge chipset του (Genesys Logic, VID:PID `0x05e3:0x0749`) — επιβεβαιωμένο με `smartctl --scan-open` (δεν βρίσκει το device κάτω από κανένα `-d` type, hardware/firmware περιορισμός, όχι διορθώσιμο από λογισμικό). Δύο επιπλέον `/dev/sda`/`/dev/sdb` slots (USB card-reader, συνήθως άδειο) αναγνωρίζονται σωστά σαν "no medium present".

### Deployment

Host-side σε `/opt/jarvis/os-helper/`, dedicated unprivileged user `jarvis-oshelper` για το κύριο daemon, root μόνο για τον snapshot collector. JARVIS-side tools σε standard `~/jarvis/tools/<name>/` pattern, νέο shared `~/jarvis/lib/os_helper_client.py`. End-to-end tested μέσω chat.

---

## 🔥 `ufw` — ενεργοποίηση + Tailscale finding (2026-08-03)

### Τι έγινε

`ufw` ήταν εγκατεστημένο αλλά **inactive** στο host — το rule για port 8787 (`172.16.0.0/12`) υπήρχε στη ρύθμιση αλλά δεν επιβαλλόταν. Ενεργοποιήθηκε προσεκτικά: πρώτα `sudo ufw allow ssh` (επιβεβαιωμένο SSH port 22 πρώτα), Termux στο κινητό δοκιμάστηκε ως δεύτερο ανεξάρτητο access channel πριν το `enable`, μετά `sudo ufw enable`. Καμία απώλεια πρόσβασης.

### Εύρημα: το ufw rule δεν εμποδίζει tailnet κίνηση

Verification test (curl από το κινητό μέσω Termux, διαφορετική Tailscale συσκευή) έδειξε ότι το port 8787 **παρέμενε προσβάσιμο** παρά το `ufw` rule. Αιτία: Tailscale `ShieldsUp: false` (επιβεβαιωμένο μέσω `tailscale debug prefs`) — το Tailscale έχει δικό του netfilter/routing layer (`NetfilterMode: 2`) που διαχειρίζεται incoming tailnet κίνηση **ανεξάρτητα** από το OS-level `ufw`, πριν καν η κίνηση περάσει από το filtering chain που θα έβλεπε "κανονική" εξωτερική κίνηση.

### Απόφαση: αποδεκτό ως έχει

Το πραγματικό access-control boundary για το `os-helper` (και για κάθε service σε αυτό το host) είναι και παραμένει το Tailscale tailnet membership αυτό καθαυτό — μόνο οι 3 δικές μας συσκευές (homeserver, desktop, κινητό) μπορούν να το φτάσουν, ίδιο μοντέλο με κάθε άλλο service του stack. Το `ufw` rule παραμένει σαν δεύτερο layer defense, θα ενεργοποιούνταν αν ποτέ αλλάξει η Tailscale ρύθμιση.

**Εναλλακτικές που αξιολογήθηκαν και απορρίφθηκαν:**
- `tailscale up --shields-up` — θα έλυνε το πρόβλημα, αλλά global policy change (μπλοκάρει ΟΛΗ την incoming tailnet κίνηση σε αυτό το host), μεγαλύτερη αλλαγή απ' όσο χρειάζεται.
- Tailscale ACLs (admin console) — πιο σωστό/στοχευμένο, χρειάζεται web dashboard access, ξεχωριστό μελλοντικό task αν χρειαστεί ποτέ πιο αυστηρό per-service policy.

---

## Γενικό μοτίβο bugs σήμερα (2026-08-03) — άξιζε να καταγραφεί ξεχωριστά

Τρία ξεχωριστά bugs σήμερα (manifest format, `sys.path` depth, `~` expansion) ήταν όλα παραλλαγές του **ίδιου** υποκείμενου λάθους: λανθασμένη υπόθεση για το πώς μοιάζει το filesystem/environment μέσα στον orchestrator container, χωρίς επιβεβαίωση πριν γραφτεί ο κώδικας. Το manifest-format bug μάλιστα ήταν ήδη καταγεγραμμένο από το `summarize_inbox` session και ξανασυνέβη.

**Δράση:** προστέθηκε μόνιμο "Adding a New Tool — Checklist" section στο README.md, με ρητά βήματα επιβεβαίωσης (directory layout, manifest format, `~` resolution, πότε χρειάζεται `--force-recreate`) πριν γραφτεί νέος κώδικας.

---

## Γνωστά, καταγεγραμμένα ανοιχτά θέματα

Δεν είναι bugs — καταγεγραμμένα ρητά ώστε να μην ξαναανακαλυφθούν από την αρχή:

- **`secrets(.env): FAIL` σε backup run `backup_2026-08-02_0047`** — το `.env` δεν βρέθηκε στο αναμενόμενο path τη στιγμή εκείνου του run (εντοπίστηκε μέσω του νέου `list_recent_backups`). Αν επαναληφθεί, το πιο πρόσφατο backup δεν θα έχει αντίγραφο secrets. Δεν διερευνήθηκε βαθύτερα.
- **Πιθανό race condition σε concurrent `protocol_permafrost` runs** — δύο backup runs έτρεξαν πολύ κοντά χρονικά (`22:03`/`22:04`, 1 Αυγούστου) και ο ένας πάτησε πάνω στα αρχεία του άλλου (`tar: file changed as we read it`, ορατό στο `backup.log`). Πιθανό missing lock/mutex. Δεν διερευνήθηκε.
- **Επιβεβαίωση αν έγινε revoke του `OPENAI_API_KEY`** — ανοιχτό από 2026-08-01 (εμφανίστηκε σε καθαρό κείμενο σε chat μέσω `docker inspect ... Config.Env` κατά το debugging). Ακόμα δεν ελέγχθηκε.
- **`ufw`/Tailscale interaction** — βλ. ενότητα παραπάνω, τεκμηριωμένο ρητά ως αποδεκτό, όχι bug.

---

## Επόμενο στη σειρά (προτεραιότητα)

1. **Disk-space proactive alert** — host-side systemd timer, ανεξάρτητο από AI layer. Το πιο "θα σε γλυτώσει από πρόβλημα" item στη λίστα.
2. **`os-helper` write set** — allowlisted `systemctl restart <unit>`, confirm-required. Φυσική επέκταση πάνω στο ήδη-χτισμένο read-only daemon.
3. **`reconnect_network`** — τρίτο repair_type, χρειάζεται πρώτα proxy decision (κανένα proxy δεν έχει `NETWORKS=1` σήμερα).
4. **Email/daily reports ("morning health digest")** — δεν χρειάζεται απαραίτητα SMTP: μπορεί να είναι systemd timer που τρέχει τα ήδη υπάρχοντα read-only tools (`list_recent_backups`, `get_disk_health`, `get_failed_units`) και γράφει περίληψη κάπου ορατό. Ιδέα προέκυψε 2026-08-03, μετά την τυχαία ανακάλυψη του `.env` FAIL μέσω του `list_recent_backups` — το gap που καλύπτει: κανένα σημερινό tool δεν σε ειδοποιεί proactively, όλα είναι pull (ρωτάς εσύ).
5. **Database editing/rollback** — χρειάζεται δικό του ασφαλή σχεδιασμό, TOTP-level confirmation. Αξιολογήθηκε ρητά ως **high risk / low reward** στο τρέχον στάδιο — παραμένει χαμηλή προτεραιότητα σκόπιμα, όχι απλά αναβλημένο.

### Μικρές `os-helper` επεκτάσεις (καταγεγραμμένες ιδέες, 2026-08-03)

Ίδιο daemon/pattern με το ήδη υπάρχον read-only `os-helper`:

- **`get_listening_ports`** (`ss -tlnp`) — ψηλή προτεραιότητα ανάμεσα στις μικρές ιδέες, θα έδειχνε immediate verification για πράγματα σαν το σημερινό `ufw`/port-8787 finding χωρίς χειροκίνητο SSH digging.
- **`get_memory_pressure`** (OOM killer events, `dmesg | grep -i "killed process"`) — θα εξηγούσε "γιατί έπεσε το X" σε περιπτώσεις που σήμερα φαίνονται απλά σαν "restarted".
- **`get_recent_boot_history`** (`journalctl --list-boots`) — πότε έγινε reboot/crash.
- **`get_journal_errors`** (`journalctl -p err -b`) — host-level errors, συμπληρώνει το Loki/Grafana (που βλέπει μόνο container logs).

**Ρητά εκτός scope:** process listing / `/proc` introspection γενικά — surveillance-adjacent χωρίς σαφές use case, θα χαλούσε το στενό, στοχευμένο scope που είναι το δυνατό σημείο του `os-helper` σήμερα.

### Θεωρήθηκε, αποφασίστηκε ρητά ΟΧΙ τώρα

- **Remote reboot μέσω JARVIS** — αξιολογήθηκε 2026-08-03. Πραγματικό ρίσκο: differs από `restart_container` (containerized, μικρό blast radius) γιατί αφορά το ίδιο το host — αν κάτι πάει στραβά μετά το reboot (π.χ. network config), πλήρης απώλεια πρόσβασης μέχρι physical access. Αν ποτέ χτιστεί, χρειάζεται επίπεδο σοβαρότητας αντίστοιχο του DAYBREAK/BLACKOUT, όχι τυπικό `/confirm` — πιθανόν με προ-έλεγχο ότι το Tailscale θα ξανασηκωθεί σωστά, ίσως watchdog. Δεν είναι στο roadmap σήμερα.
- **Configurable μοντέλο (`JARVIS_MODEL` env var)** — καταγεγραμμένη σκέψη, όχι επείγον. Όταν χρειαστεί: μικρή αλλαγή (env var στο `.env` αντί για hardcoded string στο `main.py`), αλλά σύσταση για A/B test tool-calling reliability πριν γίνει μόνιμη αλλαγή — το GPT-4o διαλέχτηκε συνειδητά γι' αυτό το κριτήριο, νεότερο μοντέλο δεν είναι αυτόματα καλύτερο εκεί.
- **Database query/read tool** (`query_audit_log`) — θα ήταν χαμηλού ρίσκου αν χτιζόταν, αλλά ρητά αποφασίστηκε να μείνει έξω μαζί με το edit/rollback item — δεν υπάρχει σήμερα πραγματική ανάγκη, low reward.

---

## Security/production-learning track

Παράλληλο track, μαθησιακή αξία (PJPT/PNPT):

1. **Docker Policy Broker + rootless Docker** ✅ πλήρως ολοκληρωμένο (2026-08-01/02).
2. **os-helper privilege separation model** ✅ ολοκληρωμένο (2026-08-03) — καλό, πρόσφατο παράδειγμα `NoNewPrivileges` interaction με sudo/capabilities, privileged-collector-with-shared-snapshot pattern.
3. **`ufw` + Tailscale netfilter interaction** ✅ διερευνήθηκε (2026-08-03) — καλό παράδειγμα overlay-network-vs-host-firewall αλληλεπίδρασης, σχετικό θέμα για PJPT/PNPT.
4. **Trivy** — CVE scanning σε images, χαμηλό effort, δεν έχει ξεκινήσει.
5. **AIDE / File Integrity Monitoring** — μειωμένη πρακτική αξία μετά το mount split (ήδη `:ro`), δεν έχει ξεκινήσει.

**Αποφασισμένο να μπει αργότερα, όχι τώρα:** Wazuh (RAM-heavy, περιμένει hardware upgrade), Suricata/Zeek (χρειάζεται managed switch), VLAN segmentation (χρειάζεται managed switch), Traefik (Tailscale ήδη καλύπτει την αξία του), CrowdSec (χαμηλή αξία χωρίς public-facing services), Vault (overkill), canary tokens (χαμηλή προτεραιότητα).

---

## Ανοιχτά ερωτήματα / decisions για επόμενο session

- Πότε αξίζει το hardware upgrade (custom build, RTX 2060/3060, €400-600) — π.χ. "όταν θέλουμε Wazuh" ως practical trigger αντί για αόριστο timeline.
- Πότε αξίζει να ξεκινήσει το custom broker/agents project — π.χ. αν αλλάξει το threat model.
- Αν το morning health digest (βλ. "Επόμενο στη σειρά") τελικά αντικαταστήσει ή απλά συμπληρώσει το ξεχωριστό email/reports item.
