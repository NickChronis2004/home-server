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
| **`repair_system`** | `clean_docker_disk` (συντηρητικό, 24h filter) + `clean_build_cache` (πλήρες, πάντα ασφαλές) | 2026-08-01, confirm-required |
| **System prompt** (Open WebUI) | Καθοδηγεί diagnose→propose→confirm workflow | Ήταν κενό πριν, πρώτη φορά μπήκε 2026-08-01 |
| **README** | Πλήρης user guide (quick access, tools, protocols, backup/restore, security, troubleshooting) | Ενημερώνεται σε κάθε session |

---

## Επόμενο στη σειρά (ήδη αποφασισμένη προτεραιότητα)

Ρίζα του project roadmap (Backups → Sandbox → Email/reports → Database editing), τα δύο πρώτα έγιναν:

1. **Email/daily reports** — read-only, βασισμένο στο ήδη υπάρχον audit.db. Χαμηλό ρίσκο, immediate value.
2. **`reconnect_network`** — τρίτο repair_type, μισό σχεδιασμένο (Docker network inspect για containers που δεν επικοινωνούν)
3. **Database editing/rollback** — χρειάζεται δικό του ασφαλή σχεδιασμό, πιθανώς TOTP-level confirmation

## Security/production-learning track (νέα σειρά, αποφασίστηκε 2026-08-01)

Ξεχωριστό, παράλληλο track — production-grade security patterns για μαθησιακή αξία (offensive/defensive security ενδιαφέρον):

1. **Docker Policy Broker + rootless Docker** — το πιο σημαντικό: σήμερα ο orchestrator έχει πλήρες read-write στο `docker.sock`, δηλαδή απεριόριστη πρόσβαση στον Docker daemon πέρα από το allowlist των tools. Στόχος: ενδιάμεσο layer που περιορίζει τι μπορεί να ζητηθεί, ώστε ο orchestrator να μην έχει καν το raw socket access. Μεγάλο, πολυ-session project.
2. **Trivy** — container vulnerability scanning (CVEs σε images πριν τρέξουν). Χαμηλό effort, θα μπει σαν νέο read-only tool πάνω στο ήδη υπάρχον manifest pattern.
3. **AIDE / File Integrity Monitoring** — ειδοποίηση αν αλλάξει κρίσιμο αρχείο (`policy.yaml`, `backup.sh`, `.env`). Στοχευμένο, μικρό effort.
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

## Ανοιχτά ερωτήματα / decisions που θα χρειαστούν σε επόμενο session

- Ποια ακριβώς Docker API calls χρειάζεται σήμερα κάθε tool (restart/stop/start/system prune/builder prune/system df) — βήμα προαπαιτούμενο πριν σχεδιαστεί ο Policy Broker
- Αν το Loki/Grafana τελικά αντικαταστήσει ή απλά συμπληρώσει το email/daily reports feature
- Πότε ρεαλιστικά αξίζει το hardware upgrade (custom build, RTX 2060/3060, €400-600) — π.χ. "όταν θέλουμε να προσθέσουμε Wazuh" θα μπορούσε να είναι το practical trigger point αντί για αόριστο timeline
