# JARVIS Project Status

Τελευταία ενημέρωση: 2026-08-01

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
| **Docker Policy Broker — tools code update** (`DOCKER_HOST` routing) | Νέο `lib/docker_env.py` helper (`docker_env(proxy)` → env dict με σωστό `DOCKER_HOST`). Ενημερώθηκαν: `restart_container`, `stop_container`, `start_container`, `check_docker_status`, `diagnose_system`. Κάθε write ενέργεια → **lifecycle**, κάθε read/inspect/verification → **read**. Όλα standalone-tested (`confirmed=false` και `confirmed=true`), `restart_container` επιπλέον end-to-end tested μέσω chat. | 2026-08-01. **restart/stop/start_container: ✅ ολοκληρωμένα. repair_system, sandbox, protocol_permafrost: εκκρεμούν, βλ. παρακάτω** | |

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

**Ακόμα εκκρεμούν:** `repair_system` (3 subprocess calls, read + maintenance), `sandbox` (`docker run` → maintenance), `protocol_permafrost`'s `backup.sh` (`docker run -v` per volume → maintenance). Μέχρι να ολοκληρωθούν, αυτά τα 3 tools θα αποτυγχάνουν αν κληθούν.

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

Ρίζα του project roadmap (Backups → Sandbox → Email/reports → Database editing), τα δύο πρώτα έγιναν:

1. **Docker Policy Broker Phase 1 — tools code update, συνέχεια** (άμεση προτεραιότητα): 5 από τα 7 tools ολοκληρώθηκαν (`restart/stop/start_container`, `check_docker_status`, `diagnose_system`) — βλ. λεπτομέρειες παραπάνω. Μένουν: `repair_system` (3 subprocess calls, read + maintenance), `sandbox` (docker run → maintenance), `protocol_permafrost`'s `backup.sh` (docker run -v → maintenance). Μετά από αυτά: negative tests (create/exec μέσω read/lifecycle πρέπει να αποτυγχάνουν) + επιβεβαίωση ότι το Vaultwarden protection παραμένει άθικτο.
2. **Email/daily reports** — read-only, βασισμένο στο ήδη υπάρχον audit.db. Χαμηλό ρίσκο, immediate value.
3. **`reconnect_network`** — τρίτο repair_type, μισό σχεδιασμένο (Docker network inspect για containers που δεν επικοινωνούν). Σημείωση: θα χρειαστεί επίσης να αποφασιστεί ποιο proxy το καλύπτει (κανένα από τα 3 σημερινά proxies δεν έχει `NETWORKS=1` ενεργό).
4. **Database editing/rollback** — χρειάζεται δικό του ασφαλή σχεδιασμό, πιθανώς TOTP-level confirmation

## Security/production-learning track

Ξεχωριστό, παράλληλο track — production-grade security patterns για μαθησιακή αξία (offensive/defensive security ενδιαφέρον):

1. **Docker Policy Broker + rootless Docker** — Phase 1 (proxy layer + mount split) **ολοκληρώθηκε 2026-08-01**, βλ. λεπτομερή ενότητα παραπάνω. Tools code update εκκρεμεί (βλ. "Επόμενο στη σειρά" #1). Custom broker/agents παραμένουν μελλοντικό, μεγαλύτερο project.
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
- **`backup_config` step (`jarvis-config`) απέτυχε (FAIL) σε πρόσφατο run**, πιθανώς permission-related μετά τη δημιουργία νέων αρχείων (`docker-compose.proxies.yml`) στο `~/jarvis`. Δεν διερευνήθηκε περαιτέρω σήμερα — δεν μπλόκαρε τα volumes (αυτά όλα πέτυχαν κανονικά). **Χρειάζεται έλεγχος σε επόμενο session.**
- **Ασφάλεια credentials**: κατά τη διάρκεια debugging, το `OPENAI_API_KEY` εμφανίστηκε σε καθαρό κείμενο σε chat μέσω `docker inspect ... Config.Env`. Επιβεβαιώθηκε ότι το `.env` δεν είναι committed στο git repo. Συστήθηκε revoke+νέο key ως προφύλαξη (ανεξάρτητα από το αν διέρρευσε αλλού) — **έλεγξε αν έγινε.**

---

## Ανοιχτά ερωτήματα / decisions που θα χρειαστούν σε επόμενο session

- Tools code update (DOCKER_HOST per proxy) — βλ. πάνω, άμεση προτεραιότητα
- Έλεγχος του `jarvis-config` backup FAIL — τι ακριβώς permission issue
- Ποια ακριβώς Docker API calls χρειάζεται σήμερα κάθε tool (ήδη χαρτογραφήθηκε πλήρως στο σημερινό session — βλ. πίνακα στην αρχή της compose file τεκμηρίωσης)
- Αν το Loki/Grafana τελικά αντικαταστήσει ή απλά συμπληρώσει το email/daily reports feature
- Πότε ρεαλιστικά αξίζει το hardware upgrade (custom build, RTX 2060/3060, €400-600) — π.χ. "όταν θέλουμε να προσθέσουμε Wazuh" θα μπορούσε να είναι το practical trigger point αντί για αόριστο timeline
- Πότε αξίζει να ξεκινήσει το custom broker/agents project (βλ. "Μελλοντικό — custom broker" παραπάνω) — π.χ. αν αλλάξει το threat model
