# JARVIS Project Status

Τελευταία ενημέρωση: 2026-08-02

Σκοπός αυτού του αρχείου: μία γρήγορη ματιά για το "τι έχουμε χτίσει, τι μένει, τι έχει αποφασιστεί αλλά όχι υλοποιηθεί" — χωρίς να χρειάζεται να ψάχνουμε παλιά chats. Ενημερώνεται στο τέλος κάθε session μαζί με το README.

---

## Ολοκληρωμένα

| Feature | Τι κάνει | Σημειώσεις |
|---|---|---|
| **Core orchestrator** | FastAPI service, tool discovery από manifests, confirm-flow, audit logging (SQLite) | Θεμέλιο όλων των υπολοίπων |
| **Emergency protocols** (SNOWFALL / BLACKOUT / DAYBREAK) | SNOWFALL: instant soft lockdown (κόβει writes) μέσω chat. BLACKOUT: hard stop του orchestrator, μόνο SSH+`/confirm`. DAYBREAK: recovery, μόνο SSH, ποτέ μέσω chat | DAYBREAK σκόπιμα ποτέ μέσω chat — recovery δεν πρέπει να περνάει από το ίδιο κανάλι που πιθανώς προκάλεσε το πρόβλημα |
| **Kill switch** | Σταματά μόνο Ollama + Open WebUI, όχι τον orchestrator | Πιο ήπιο από BLACKOUT |
| **Backups** (`protocol_permafrost`) | `backup.sh`/`restore.sh`, auto-discovery Docker volumes, 7-run retention, external USB sync, `--test` sandbox mode στο restore | Πλήρως tested, safety-net πριν από κάθε overwrite |
| **Sandbox** (gVisor) | Python code execution, πλήρως απομονωμένο (no network, no host fs, tmpfs only) | 15-point security test passed, καμία confirmation δεν χρειάζεται (μηδενικό blast radius) |
| **`diagnose_system`** | Read-only, πλήρης εικόνα: container status/health/restarts, error-pattern log scan, disk usage breakdown | 2026-08-01 |
| **`repair_system`** | `clean_docker_disk` (συντηρητικό, 24h filter) + `clean_build_cache` (πλήρες, πάντα ασφαλές) | 2026-08-01, confirm-required. **ΕΝΗΜΕΡΩΣΗ 2026-08-01 (αργότερα την ίδια μέρα): `clean_docker_disk` προσωρινά μη λειτουργικό μετά το Docker Policy Broker Phase 1 — βλ. παρακάτω** |
| **System prompt** (Open WebUI) | Καθοδηγεί diagnose→propose→confirm workflow | Ήταν κενό πριν, πρώτη φορά μπήκε 2026-08-01 |
| **README** | Πλήρης user guide (quick access, tools, protocols, backup/restore, security, troubleshooting) | Ενημερώνεται σε κάθε session |
| **Docker Policy Broker — Phase 1** (proxy layer + mount split) | Ο orchestrator δεν έχει πλέον καθόλου mount `/var/run/docker.sock`. 3 dedicated docker-socket-proxy instances (read/lifecycle/maintenance), κάθε ένα σε δικό του internal Docker network, pinned με digest. Mount split: `policy.yaml`, `tools/`, `lib/`, scripts όλα `:ro`· μόνο `logs/` και `jarvis-backups/` `:rw`. Orchestrator ξεκινά καθαρά, βασική συνομιλία λειτουργική. | 2026-08-01. Βλ. λεπτομερή ενότητα παρακάτω |
| **Docker Policy Broker — tools code update** (`DOCKER_HOST` routing) | Νέο `lib/docker_env.py` helper (`docker_env(proxy)` → env dict με σωστό `DOCKER_HOST`). Routing ολοκληρωμένο σε **όλα τα 7/7 tools**: `restart_container`, `stop_container`, `start_container`, `check_docker_status`, `diagnose_system` (2026-08-01), `repair_system`, `sandbox`, `protocol_permafrost` (2026-08-02). | 2026-08-01/02. **✅ Ολοκληρωμένο πλήρως.** Βλ. λεπτομέρειες παρακάτω |
| **Docker Policy Broker — negative tests** | Επιβεβαιώθηκε: write μέσω read proxy → 403, read μέσω lifecycle proxy → 403, Vaultwarden ως target σε `restart_container` → απορρίπτεται στο Python policy layer πριν καν φτάσει σε proxy | 2026-08-02 |

---

## 🔧 Docker Policy Broker — λεπτομέρειες (ενεργό, πολυ-session project)

### Τι ολοκληρώθηκε σήμερα (2026-08-01)

- **3 proxy instances** (`docker-read-proxy`, `docker-lifecycle-proxy`, `docker-maintenance-proxy`) βασισμένα στο `tecnativa/docker-socket-proxy`, pinned με digest (`@sha256:1f5038b54f06...`), το καθένα με μόνο τα API sections που πραγματικά χρειάζεται:
  - **read-proxy**: `CONTAINERS=1, SYSTEM=1, POST=0` — read-only, καλύπτει diagnose_system + verification steps
  - **lifecycle-proxy**: `POST=1, CONTAINERS=0, ALLOW_START/STOP/RESTARTS=1` — μόνο τα 3 lifecycle endpoints
  - **maintenance-proxy**: `POST=1, CONTAINERS=1, BUILD=1, SYSTEM=0, IMAGES=0, NETWORKS=0` — για sandbox's `docker run` και permafrost's `backup.sh`
- **Dedicated internal networks** ανά proxy (`docker-read-net`, `docker-lifecycle-net`, `docker-maintenance-net`) — μόνο ο orchestrator συνδέεται σε όλα, το Open WebUI/Ollama (στο κοινό `jarvis-ai-net`) δεν βλέπουν καν τα proxies
- **Healthchecks** σε όλα τα proxies + `depends_on: condition: service_healthy` στον orchestrator
- **Mount split** στον orchestrator: `policy.yaml`, `tools/`, `lib/`, `backup.sh`, `kill-switch.sh`, τα protocol scripts, `smoke_test.sh` → `:ro`. Μόνο `logs/` και `jarvis-backups/` → `:rw`. Το `orchestrator/` source directory αφαιρέθηκε εντελώς από τα mounts (είναι baked στο image) — **εκτός** από `schema.sql`, το οποίο *δεν* είναι baked (το Dockerfile κάνει `COPY main.py errors.py subprocess_wrapper.py audit.py .` ρητά, όχι wildcard) και χρειάστηκε δικό του στοχευμένο `:ro` mount μετά από πραγματικό startup crash στο testing.
- **Port 8001**: παρέμεινε `127.0.0.1:8001:8001` (όχι `0.0.0.0`) — συντηρητική επιλογή, δεν επιβεβαιώθηκε με σιγουριά πώς ακριβώς το Open WebUI καλεί σήμερα τον orchestrator (πιθανώς UI-configured connection, όχι env var — το `OPENAI_API_BASE_URL` env var του Open WebUI container βρέθηκε κενό).
- Live tested: όλα τα 3 proxies επιβεβαιώθηκαν standalone (read επιτρέπει ps/μπλοκάρει stop, lifecycle μπλοκάρει ps/επιτρέπει restart, maintenance επιτρέπει system df) πριν συνδεθούν με τον orchestrator. Orchestrator ξεκινά καθαρά (`Uvicorn running on http://0.0.0.0:8001`), βασική συνομιλία μέσω Open WebUI επιβεβαιωμένα λειτουργική.
- Backup (PERMAFROST, SSH) τρέχτηκε πριν την αλλαγή ως safety net — όλα τα 8 Docker volumes (συμπ. Vaultwarden) OK. Δύο άσχετα, προϋπάρχοντα issues ανακαλύφθηκαν παράλληλα (βλ. "Νέα ευρήματα" παρακάτω), δεν μπλόκαραν τη σημερινή δουλειά.

### ✅ Ολοκληρώθηκε σήμερα — `lib/docker_env.py` helper + routing σε 5 tools

Νέο helper `~/jarvis/lib/docker_env.py`: `docker_env(proxy)` όπου `proxy` ∈ {"read", "lifecycle", "maintenance"}, επιστρέφει `{**os.environ, "DOCKER_HOST": ...}`. Ρίχνει `ValueError`/`RuntimeError` σε άγνωστο proxy name ή λείπον env var, αντί για σιωπηλό fallback. Import pattern: `sys.path.insert(0, "/app/jarvis/lib")` πριν το `from docker_env import docker_env` — **όχι** `from lib.docker_env import ...` (το `lib/` δεν είναι package, δεν έχει `__init__.py`· το flat-import lookup γίνεται μέσω `sys.path.insert`, ίδιο pattern με το προϋπάρχον `redact.py`).

**Routing ολοκληρωμένο και standalone-tested (`docker exec jarvis-orchestrator sh -c 'TOOL_ARG_...=... python3 .../script.py'`):**
- `restart_container` — `docker restart` → lifecycle, `docker inspect` → read. **Επιπλέον end-to-end tested μέσω chat + `/confirm`.**
- `stop_container` — `docker stop` → lifecycle, `docker inspect` → read.
- `start_container` — `docker start` → lifecycle, `docker inspect` → read. (Πρώτη προσπάθεια είχε ξεχάσει το `env=` στο ίδιο το `docker start` block ενώ το `docker inspect` ήταν ήδη σωστό — εντοπίστηκε από "Cannot connect to the Docker daemon at unix:///var/run/docker.sock" στο standalone test, διορθώθηκε.)
- `check_docker_status` — `docker ps -a` → read. Χρειάστηκε γιατί το `diagnose_system` το καλεί έμμεσα· χωρίς αυτό το JARVIS "έβλεπε" μηδέν containers.
- `diagnose_system` — και τα 4 subprocess calls (`docker ps -a`, `docker inspect`, `docker logs`, `docker system df`) → read. Προστέθηκε επίσης explicit error surfacing (`{"error": ...}`) στο `get_containers`/`get_disk_usage` αντί για σιωπηλά κενά αποτελέσματα όταν αποτυγχάνει το subprocess.

**Μάθημα από τη σημερινή δουλειά (για τα tools που μένουν):** μετά από κάθε αλλαγή σε αρχείο με πολλαπλά `subprocess.run`, να γίνεται `grep -c 'subprocess.run'` έναντι `grep -c 'env=docker_env'` πριν το standalone test — το `start_container` bug ήταν ακριβώς αυτό, ένα block ξεχάστηκε ενώ το άλλο ήταν σωστό.

**2026-08-02: ολοκληρώθηκαν και τα 3 εναπομείναντα tools.** Routing 5/5 subprocess calls σε `repair_system`, 1/1 σε `sandbox`, dual-proxy σε `protocol_permafrost`/`backup.sh`. Λεπτομέρειες παρακάτω.

### ✅ 2026-08-02 — `repair_system` routing + buildx CLI incompatibility (νέο εύρημα)

Routing πρόσθεσε `env=docker_env(...)` σε όλα τα 5 subprocess calls (`preview`/`clean_docker_disk`/`clean_build_cache`, read+maintenance mix). Standalone tested `confirmed=false` και `confirmed=true`.

**`clean_docker_disk`**: παραμένει μπλοκαρισμένο όπως ήδη γνωστό (NETWORKS/IMAGES όχι ανοιχτά, σκόπιμα).

**`clean_build_cache`**: routing μόνο του δεν αρκούσε — `docker builder prune` είναι buildx CLI command, όχι απλό daemon API call. Buildx κρατάει δικό του context state (`~/.docker/buildx/`) που δεν υπάρχει μέσα στον orchestrator· χωρίς αυτό ψάχνει για dedicated BuildKit container (`buildx_buildkit_default`) που δεν υπάρχει ούτε μπορεί να δημιουργηθεί μέσω του στενού maintenance proxy. Δοκιμάστηκαν `docker context create` + `buildx create --driver docker` — σκάει με "additional instances of driver docker cannot be created" (ο `docker` driver επιτρέπεται μόνο μία φορά, buildx-wide, ανεξαρτήτως context name).

**Λύση**: παράκαμψη του buildx CLI εντελώς, απευθείας κλήση του υποκείμενου Docker Engine API endpoint `POST /build/prune` μέσω `urllib` (βλ. `_build_prune_via_api()` στο `repair_system/script.py`). Καλύπτεται πλήρως από το ήδη υπάρχον `BUILD=1, POST=1` στο maintenance proxy, καμία επιπλέον permission δεν χρειάστηκε. Επιβεβαιωμένο standalone: `"status": "success"`, `caches_deleted`, `space_reclaimed_bytes`.

### ✅ 2026-08-02 — `sandbox` routing + gVisor isolation επιβεβαιωμένο μετά το routing

1 subprocess call (`docker run --runtime=runsc ...`) → maintenance proxy. Πριν το routing επιβεβαιώθηκε ρητά ότι το `--runtime=runsc` flag περνάει καθαρά μέσω proxy (δεν κάνει σιωπηλό downgrade σε `runc`) — δοκιμή `/proc/version` μέσα στο container επέστρεψε `Linux version 4.19.0-gvisor ...`, το gVisor fingerprint. Επιβεβαιωμένο ξανά end-to-end μετά το routing, μέσω του πραγματικού tool script.

### ✅ 2026-08-02 — `protocol_permafrost`/`backup.sh` dual-proxy routing

`backup.sh` χρειάζεται **δύο** proxies ταυτόχρονα, όχι έναν: `discover_volumes()` (`docker volume ls`, read-only) → read proxy· `backup_volume()` (`docker run -v` per volume) → maintenance proxy. Ένα μοναδικό global `DOCKER_HOST` δεν αρκεί.

Υλοποίηση: το `backup.sh` πήρε δύο μικρά wrappers, `docker_read()`/`docker_maintenance()` (`docker ${VAR:+-H "$VAR"} "$@"` — no-op fallback σε local socket όταν οι μεταβλητές είναι unset, άρα SSH/manual usage δεν επηρεάζεται καθόλου). Το `protocol_permafrost/script.py` περνάει ρητά `DOCKER_READ_PROXY`/`DOCKER_MAINTENANCE_PROXY` στο env του subprocess (όχι το `docker_env()` helper — αυτό θέτει ένα μοναδικό `DOCKER_HOST`, εδώ χρειάζονταν δύο side-by-side).

Χρειάστηκε επίσης: **`VOLUMES=1` προστέθηκε στο read proxy** (`discover_volumes()` έπαιρνε 403 χωρίς αυτό — δεν υπήρχε καθόλου `VOLUMES` env var πριν, default `0`). Πρώτη προσπάθεια πρόσθεσε `VOLUMES=1` αλλά ξέχασε ότι υπήρχε ήδη `VOLUMES=0` παρακάτω στην ίδια "Ρητά κλειστά" λίστα — το τελευταίο σε YAML list-style environment νικάει, οπότε το compose συνέχιζε να διαβάζει `0` ακόμα και μετά από πλήρες `stop`/`rm`/`up` του proxy. Διορθώθηκε αφαιρώντας το παλιό duplicate. **Μόνο στο read proxy** (`POST=0` ήδη εγγυάται read-only εκεί) — ρητά όχι στο maintenance proxy, ώστε να μη φαρδύνει το ήδη-φαρδύ maintenance scope για κάτι που είναι εννοιολογικά read-only.

### 🔴 2026-08-02 — σοβαρό bug βρέθηκε + διορθώθηκε: self-referential tar στο `backup_config()`

Κατά το πρώτο end-to-end test του νέου permafrost routing, το backup κρεμόταν επ' αόριστον (>10 λεπτά, timeout) χωρίς καμία πρόοδο. Ρίζα: `backup_config()`'s `tar` του `$JARVIS_HOME` **δεν εξαιρούσε το ίδιο το `jarvis-backups/` directory**, το οποίο βρίσκεται μέσα στο `$JARVIS_HOME`. Ο tar σκάναρε αναδρομικά μέσα στο `jarvis-backups/`, έβρισκε προηγούμενα backup run directories (το καθένα με δικό του `jarvis-config.tar.gz`), και προσπαθούσε να συμπεριλάβει το **ίδιο του το output αρχείο** που έγραφε ζωντανά τη στιγμή εκείνη — unbounded self-referential growth, όχι κλασικό zip-bomb αλλά μηχανικά παρόμοιο αποτέλεσμα. Επιβεβαιωμένο στην πράξη: διαδοχικά αποτυχημένα runs μεγάλωναν 7.6GB → 23GB → 35GB, το καθένα καταπίνοντας το προηγούμενο. Δίσκος έφτασε στιγμιαία 129GB χρήση πριν τον καθαρισμό (`sudo rm -rf` στα προβληματικά backup dirs — χρειάστηκε sudo γιατί τα αρχεία ανήκουν σε root, δημιουργημένα μέσα στον orchestrator container).

**Fix**: προστέθηκε `--exclude="${base}/$(basename "$BACKUP_ROOT")"` στο `backup_config()`'s tar command. Επιβεβαιωμένο end-to-end: πλήρες PERMAFROST run ολοκληρώθηκε σε 51 δευτερόλεπτα (ήταν >10 λεπτά/timeout πριν), `jarvis-config: OK`, όλα τα 8 volumes OK (συμπ. vaultwarden), backup directory μέγεθος 974MB (λογικό, ήταν 35GB). **Αυτό το bug επηρέαζε και το SSH-manual usage** του `backup.sh`, όχι μόνο το JARVIS-triggered path — ήταν ήδη καταγεγραμμένο ως άγνωστο `jarvis-config:FAIL` από το 2026-08-01, τώρα βρέθηκε η πλήρης αιτία και διορθώθηκε μόνιμα.

### ✅ Νέο εύρημα + fix: confirmation-flow bug στο system prompt (ξεχωριστό από το proxy routing)

Μετά τη διόρθωση του routing, το `restart_container` εξακολουθούσε να μην ενεργοποιείται σωστά μέσω chat — το JARVIS απαντούσε σε φυσική γλώσσα ("γράψε /confirm") **χωρίς να έχει καλέσει το tool** με `confirmed=false`, οπότε δεν υπήρχε ποτέ pending file και το πραγματικό `/confirm` του χρήστη έβγαζε "There is no pending action". Επιβεβαιώθηκε μέσω audit log (`tool_calls` table, στήλες `tool_name`/`confirmed`) — μόνο `diagnose_system` calls, κανένα `restart_container`.

Ρίζα: το system prompt του Open WebUI μοντέλου ("jarvis") έλεγε "πρότεινε ρητά... ζήτα πάντα επιβεβαίωση" χωρίς να διευκρινίζει ότι η ζήτηση επιβεβαίωσης πρέπει να γίνεται **μέσω κλήσης του tool** (`confirmed=false`), όχι με περιγραφή σε φυσική γλώσσα. Διορθώθηκε το system prompt (Workspace → Models → jarvis → Προτροπή Συστήματος): προστέθηκε ρητή οδηγία να καλείται πάντα το tool με `confirmed=false` πρώτα, ποτέ να μην περιγράφεται η ενέργεια αντί να κληθεί το tool. Επιβεβαιώθηκε end-to-end μετά το fix: audit log δείχνει σωστό δίδυμο `confirmed=0` → `confirmed=1`, πραγματικό restart επιτυχές μέσω chat.

**Σημείωση:** ξεχωριστό, μικρότερο side-finding από το ίδιο testing — το JARVIS δεν κάνει καλό fuzzy-matching σε container aliases ("restart Kuma" δεν αναγνωρίστηκε ως "uptime-kuma", το μοντέλο ρώτησε κάτι άλλο αντί να ζητήσει διευκρίνιση ή να προχωρήσει). Δεν διορθώθηκε σήμερα, δεν ήταν στο scope — καταγράφεται για μελλοντικό system-prompt tuning.

### Γνωστοί, καταγεγραμμένοι περιορισμοί (σκόπιμα όχι λυμένοι σε αυτό το Phase)

- **Lifecycle proxy δεν κάνει per-container filtering.** Φιλτράρει σε επίπεδο ενέργειας (`ALLOW_RESTARTS` κλπ), όχι ανά container name. Το Vaultwarden protection παραμένει αποκλειστικά στο Python `policy.yaml` layer — ένας orchestrator με πλήρες RCE θα μπορούσε θεωρητικά να το παρακάμψει μιλώντας απευθείας στο proxy. Πραγματική λύση: dedicated lifecycle broker με δικό του per-container policy (μεγαλύτερο, μελλοντικό project — βλ. "Μελλοντικό — custom broker" παρακάτω).
- **Maintenance proxy είναι το πιο "φαρδύ"** (`POST=1, CONTAINERS=1`) — sandbox's και permafrost's `docker run` πραγματικά χρειάζονται container-create-level access. Ένα RCE εκεί θα μπορούσε θεωρητικά να δημιουργήσει container με host mounts. Ίδια μελλοντική λύση: fixed-function agents.
- **`clean_docker_disk` προσωρινά μη λειτουργικό.** Χρειάζεται `NETWORKS`/`IMAGES` access που σκόπιμα δεν ανοίξαμε (θα φάρδαινε το ήδη-φαρδύ maintenance proxy για ένα convenience cleanup tool). Θα επιστρέψει μαζί με τον μελλοντικό maintenance agent. `clean_build_cache` δουλεύει κανονικά (μόνο χρειάστηκε `BUILD=1`).
- **`ALLOW_RESTARTS` του upstream project καλύπτει stop|restart|kill**, όχι μόνο restart, ό,τι κι αν λέει το όνομά του. Δεν αλλάζει τίποτα στο δικό μας use case (ήδη θέλουμε και τα τρία), απλά καταγεγραμμένο.

### Γνωστό backup regression (αποδεκτό εν γνώσει)

Μετά το mount split, το `protocol_permafrost` (μέσω `backup.sh`'s `tar` του `$JARVIS_HOME`) βλέπει πλέον μόνο ό,τι είναι ρητά mounted στον orchestrator — `tools/`, `lib/`, `policy.yaml`, scripts, `logs/`. **Δεν** περιλαμβάνει πλέον `README.md`, `STATUS.md`, `docker-compose.proxies.yml`, `.git/`, ή το `orchestrator/` source directory (πέρα από το mounted `schema.sql`). Απόφαση: αποδεκτό — αυτά τα αρχεία ζουν ήδη στο GitHub repo, δεν χρειάζονται μέσα στο disaster-recovery tarball.

### Μελλοντικό — custom broker (ρητά ΕΚΤΟΣ scope σήμερα, μεγαλύτερο project)

Καταγεγραμμένη ιδέα από εξωτερικό feedback (ChatGPT review), αξιολογήθηκε και αποφασίστηκε συνειδητά να ΜΗΝ γίνει τώρα — scope creep σε σχέση με το "mount split + proxies" που ήταν ο στόχος του session:

- Custom FastAPI broker (Docker SDK, όχι subprocess CLI) που εκθέτει μόνο sanitized, υψηλού επιπέδου endpoints (`POST /v1/operations/prepare`, κλπ) αντί για category-level Docker API passthrough
- Ξεχωριστοί fixed-function agents: `maintenance-agent` (μόνο `POST /clean-build-cache`, `POST /clean-docker-disk`, χωρίς raw Docker API προς τον orchestrator), `permafrost-agent` (μόνο `POST /run-backup`), `sandbox-runner` (πιθανώς ξεχωριστός rootless Docker daemon)
- Lifecycle broker με πραγματικό per-container policy (aliases → πραγματικά container names, reject οτιδήποτε εκτός allowlist, στο ίδιο το broker αντί για μόνο στο Python tool layer)

Θα αξιολογηθεί ξανά όταν/αν το threat model αλλάξει (π.χ. αν το JARVIS εκτεθεί ποτέ πέρα από Tailscale-only, ή αν προστεθούν περισσότεροι χρήστες/agents).

---

## Επόμενο στη σειρά (ήδη αποφασισμένη προτεραιότητα)

Ρίζα του project roadmap (Backups → Sandbox → Email/reports → Database editing):

1. ~~Docker Policy Broker Phase 1 — tools code update~~ **✅ Ολοκληρώθηκε πλήρως 2026-08-02** (7/7 tools routed, negative tests περασμένα, Vaultwarden protection επιβεβαιωμένο άθικτο). Βλ. λεπτομέρειες παραπάνω.
2. **Email/daily reports** — read-only, βασισμένο στο ήδη υπάρχον audit.db. Χαμηλό ρίσκο, immediate value. Ρεαλιστικά ξεχωριστό session (SMTP setup/credentials, scheduling, format design) — όχι quick add-on.
3. **`reconnect_network`** — τρίτο repair_type, μισό σχεδιασμένο (Docker network inspect για containers που δεν επικοινωνούν). Σημείωση: θα χρειαστεί επίσης να αποφασιστεί ποιο proxy το καλύπτει (κανένα proxy δεν έχει `NETWORKS=1` ενεργό σήμερα).
4. **Database editing/rollback** — χρειάζεται δικό του ασφαλή σχεδιασμό, πιθανώς TOTP-level confirmation

## Security/production-learning track

Ξεχωριστό, παράλληλο track — production-grade security patterns για μαθησιακή αξία (offensive/defensive security ενδιαφέρον):

1. **Docker Policy Broker + rootless Docker** — Phase 1 (proxy layer + mount split, 2026-08-01) + tools code update (7/7 tools, negative tests, 2026-08-02) **✅ πλήρως ολοκληρωμένο**, βλ. λεπτομερή ενότητα παραπάνω. Custom broker/agents παραμένουν μελλοντικό, μεγαλύτερο project (βλ. "Μελλοντικό — custom broker").
2. **Trivy** — container vulnerability scanning (CVEs σε images πριν τρέξουν). Χαμηλό effort, θα μπει σαν νέο read-only tool πάνω στο ήδη υπάρχον manifest pattern.
3. **AIDE / File Integrity Monitoring** — ειδοποίηση αν αλλάξει κρίσιμο αρχείο (`policy.yaml`, `backup.sh`, `.env`). Στοχευμένο, μικρό effort. Σημείωση: μετά το mount split αυτά τα αρχεία είναι πλέον ήδη `:ro` μέσα στον orchestrator, που μειώνει (όχι μηδενίζει) την πρακτική αξία αυτού του item — ο host-side κίνδυνος παραμένει.
4. **Loki + Grafana** (centralized logging) — μαζεύει logs από όλα τα containers σε ένα σημείο, καλό troubleshooting tool, πιθανώς επικαλύπτεται με το email/reports feature.

**Αποφασισμένο να μπει αργότερα, όχι τώρα:**
- **Wazuh (SIEM/HIDS)** — μεγάλη εκπαιδευτική αξία, αλλά στο τρέχον 16GB laptop θα πιέσει σοβαρά τη μνήμη (χρειάζεται ρεαλιστικά 4-8GB+ αφιερωμένα). Περιμένει το dedicated hardware upgrade.
- **Suricata/Zeek** — χρειάζεται span/mirror port από managed switch, δεν έχει πραγματική αξία στο τρέχον network topology.
- **VLAN segmentation** — χρειάζεται managed switch (εξωτερική αγορά, δεν έχεις ακόμα).
- **Traefik (reverse proxy)** — το Tailscale ήδη καλύπτει το μεγαλύτερο μέρος της αξίας του (encryption + implicit auth) όσο όλα παραμένουν εσωτερικά, όχι δημόσια εκτεθειμένα.
- **CrowdSec** — χαμηλή αξία χωρίς public-facing SSH/nginx (όλα ήδη πίσω από Tailscale).
- **Secrets management (Vault)** — overkill για το τρέχον μέγεθος, το `.env` με 600 permissions ήδη καλύπτει το πρακτικό ρίσκο.
- **Canary tokens** — καλή άσκηση, χαμηλή προτεραιότητα.

---

## Νέα ευρήματα (2026-08-01, ανεξάρτητα από το Docker Policy Broker)

- **`backup.sh`'s `sync-external` step είναι πολύ αργό σε αυτό το hardware**, όχι κρεμασμένο — ένα πλήρες sync στο εξωτερικό USB (`/mnt/backup_external`, `/dev/sdc1`, ext4) τρέχει στα ~1.6MB/s effective throughput. Ένα 2.8GB αρχείο μόνο του χρειάζεται ~20-30 λεπτά. Δεν είναι bug, είναι hardware bottleneck (πιθανό USB 2.0 ή αργός δίσκος). Αν χρειαστεί ποτέ πιο γρήγορο sync, θα χρειαστεί καλύτερο USB 3.0 setup/δίσκο — όχι script fix.
- ~~`backup_config` step (`jarvis-config`) απέτυχε (FAIL) σε πρόσφατο run~~ **✅ Διερευνήθηκε και διορθώθηκε 2026-08-02** — δεν ήταν permission issue, ήταν self-referential tar bug (βλ. λεπτομερή ενότητα παραπάνω).
- **Ασφάλεια credentials**: κατά τη διάρκεια debugging, το `OPENAI_API_KEY` εμφανίστηκε σε καθαρό κείμενο σε chat μέσω `docker inspect ... Config.Env`. Επιβεβαιώθηκε ότι το `.env` δεν είναι committed στο git repo. Συστήθηκε revoke+νέο key ως προφύλαξη (ανεξάρτητα από το αν διέρρευσε αλλού) — **έλεγξε αν έγινε.**

---

## Ανοιχτά ερωτήματα / decisions που θα χρειαστούν σε επόμενο session

- ~~Tools code update~~ ✅ Ολοκληρώθηκε 2026-08-02
- ~~Έλεγχος του `jarvis-config` backup FAIL~~ ✅ Βρέθηκε η αιτία (self-referential tar) και διορθώθηκε 2026-08-02
- **Επιβεβαίωση αν έγινε revoke του `OPENAI_API_KEY`** — ανοιχτό από 2026-08-01, ακόμα δεν ελέγχθηκε
- Αν το Loki/Grafana τελικά αντικαταστήσει ή απλά συμπληρώσει το email/daily reports feature
- Πότε ρεαλιστικά αξίζει το hardware upgrade (custom build, RTX 2060/3060, €400-600) — π.χ. "όταν θέλουμε να προσθέσουμε Wazuh" θα μπορούσε να είναι το practical trigger point αντί για αόριστο timeline
- Πότε αξίζει να ξεκινήσει το custom broker/agents project (βλ. "Μελλοντικό — custom broker" παραπάνω) — π.χ. αν αλλάξει το threat model

## Νέα προσθήκη: `summarize_inbox` (2026-08-02)

Νέο read-only tool: διαβάζει το CSD UoC mailbox (`mailhost.csd.uoc.gr`, IMAP over SSL, θύρα 993) και δίνει headers + short body preview στο μοντέλο για σύνοψη. **Δεν** αγγίζει Docker/proxies καθόλου — απευθείας IMAP call, ξεχωριστό μονοπάτι από όλα τα υπόλοιπα tools.

**Ασφάλεια:**
- IMAP session ανοίγει σε **explicit readonly mode** (`select(mailbox, readonly=True)`) — πρωτόκολλο-επίπεδο εγγύηση, όχι απλά "δεν γράψαμε write code". Καμία `STORE`/`EXPUNGE`/`COPY` εντολή δεν στέλνεται ποτέ.
- Νέα secrets στο `orchestrator/.env` (**όχι** στο `~/jarvis/.env` — αυτό δεν υπάρχει, ζει μέσα στο `orchestrator/` directory): `CSD_MAIL_USER`, `CSD_MAIL_PASSWORD`. Ίδιο 600-permission pattern με τα υπόλοιπα.
- Privacy note: το περιεχόμενο των emails περνάει από το GPT-4o (εξωτερικό, tool-calling μοντέλο) για τη σύνοψη — συνειδητή εξαίρεση στο "local-first" principle, ίδιο σκεπτικό με το γιατί χρησιμοποιούμε GPT-4o για tool-calling γενικά.
- Auth: plain password πάνω από TLS (όχι OAuth — το ίδρυμα δεν το υποστηρίζει). Άρα ένα compromise του server ισοδυναμεί με compromise του πανεπιστημιακού λογαριασμού, όχι μόνο ενός isolated API key — μεγαλύτερο stake από π.χ. το OpenAI key.

**Default συμπεριφορά:** `mode=since`, με `since_date` default "χθες" αν δεν δοθεί ρητά. Το `mode=unseen` (unread flag) υπάρχει σαν επιλογή αλλά **δεν** είναι default — δοκιμάστηκε πρώτα, βγήκε πολύ θορυβώδες γιατί υπήρχαν μήνες συσσωρευμένα unread newsletters/spam. `since yesterday` είναι πιο υγιές default.

**Επεκτασιμότητα:** read-only τώρα, αλλά σχεδιασμένο ώστε reply/mark-as-read/delete να μπουν αργότερα σαν *ξεχωριστό*, νέο write-capable tool με δικό του confirm-required tier — όχι flag flip πάνω σε αυτό. Ίδιο σκεπτικό με το read/lifecycle/maintenance proxy split του Docker Policy Broker.

**Bugs βρέθηκαν + διορθώθηκαν κατά την υλοποίηση:**

1. **Manifest schema mismatch.** Πρώτη γραφή του manifest ακολούθησε JSON-Schema-style `parameters: {type: object, properties: {...}}` — έσκαγε στο `main.py`'s `build_openai_tools_schema()` με `AttributeError: 'str' object has no attribute 'get'`, γιατί ο orchestrator περιμένει `parameters` σαν **λίστα** από `{name, type, description, required}` dicts (ίδιο σχήμα με το `restart_container`), όχι JSON Schema object. Διορθώθηκε ευθυγραμμίζοντας με το πραγματικό σχήμα.
2. **`.env` δεν είναι στο `~/jarvis/`.** Ζει σε `~/jarvis/orchestrator/.env` — μπερδεύτηκε αρχικά επειδή το `docker-compose.proxies.yml` είναι στο root του `~/jarvis/`, αλλά το `env_file:` directive δείχνει μέσα στο `orchestrator/`.
3. **`docker restart` δεν ξαναδιαβάζει `.env`.** Μετά την προσθήκη των νέων credentials, `docker restart jarvis-orchestrator` δεν έφερε τα νέα env vars μέσα στον container — env vars μπαίνουν μόνο στη δημιουργία του container, όχι σε κάθε restart. Χρειάστηκε πλήρες recreate: `docker compose -f docker-compose.proxies.yml up -d --force-recreate jarvis-orchestrator`. Ίδιο ισχύει προφανώς και για μελλοντικά `.env` changes.
4. **Directory typo.** Πρώτο αντίγραφο των tool αρχείων κατέληξε σε `tools/summirize_inbox/` (λάθος γράμμα) αντί για `tools/summarize_inbox/` — ο orchestrator έψαχνε στο σωστό path, δεν έβρισκε τίποτα. Διορθώθηκε με `mv`.
5. **HTML-only emails έδιναν raw markup.** Emails χωρίς `text/plain` alternative (συνηθισμένο σε predatory-journal spam) έδιναν ωμό `<!DOCTYPE html>...` στο preview. Προστέθηκε fallback: αν δεν υπάρχει plain text part, γίνεται strip tags/script/style μέσω `html.parser` (stdlib, καμία νέα dependency) πριν το preview.
6. **Cached tool-discovery.** Μετά τη διόρθωση του manifest, ένα `docker logs --tail` έδειχνε ακόμα το παλιό traceback — ήταν απλά παλιά, μη-φρέσκια γραμμή στο log, όχι νέο event. Το πραγματικό confirm ήρθε δοκιμάζοντας ξανά μετά από recreate και βλέποντας νέο timestamp με επιτυχές `tool=summarize_inbox ... success=True`.

**Παρατηρήθηκε, όχι διορθωμένο:** το system prompt περνάει `confirmed=false` σαν param ακόμα και σε αυτό το read-only tool (κατάλοιπο από το γενικό confirm-flow instruction για write-tools). Δεν σπάει τίποτα — το tool code αγνοεί άγνωστα args — αλλά ίσως αξίζει μελλοντικό system-prompt tuning ώστε να μην περνάει `confirmed` σε read-only tools καθόλου.

**Δεν υλοποιήθηκε (συνειδητή απόφαση):** αρχικό σχέδιο περιλάμβανε cron-triggered daily run + Open WebUI message-posting integration για αυτόματη πρωινή σύνοψη. Αποφασίστηκε να μείνει καθαρά **on-demand μέσω chat** — απλούστερο, καμία επιπλέον υποδομή (κανένα cron, καμία ανάγκη να ψάξουμε το Open WebUI message-posting API).
