# PRD: DNA Matrix (Sherlock) — Openbot Integration

## Document Control
| Field | Value |
|-------|-------|
| Version | 1.0 |
| Status | APPROVED |
| Last Updated | 2026-02-01 |

---

## 1. Executive Summary

Integrate the DNA Matrix repository with Openbot to enable automated clone-and-test workflows. DNA Matrix is a sports parlay risk evaluation engine with the Sherlock audit module. This integration allows Openbot to:
- Clone the DNA repo to a disposable workdir
- Run the test suite automatically
- Produce proof artifacts (receipts + logs)
- Never modify the origin repository

---

## 2. Project Identity

| Field | Value |
|-------|-------|
| Project Name | DNA Matrix (dna-matrix) |
| Description | Sports parlay risk evaluation engine with Sherlock audit module |
| Repository | https://github.com/launchplugai/DNA |
| Branch | main |
| Language | Python 3.12 |
| Framework | FastAPI / Uvicorn |
| Test Framework | pytest |

---

## 3. Automation Contract (LOCKED)

### 3.1 Setup Command
```bash
pip install -r requirements.txt
```

### 3.2 Test Command
```bash
pytest app/tests -v
```

### 3.3 Expected Results
| Metric | Value |
|--------|-------|
| Total Tests | 840 |
| Expected Pass | 831 |
| Expected Fail | 9 (known — test_debug.py) |
| Runtime | ~5 seconds |
| Exit Code | 0 (pytest exits 0 even with expected failures) |

### 3.4 Health Endpoint
| Field | Value |
|-------|-------|
| URL | `/health` |
| Method | GET |
| Success Code | 200 |
| Success Response | `{"status": "healthy", ...}` |

---

## 4. Dependencies & Isolation

### 4.1 External Dependencies
| Dependency | Required for Tests | Required for Prod |
|------------|-------------------|-------------------|
| Database | ❌ No | ❌ No |
| Network | ❌ No | Optional |
| OpenAI API | ❌ No | Optional (OCR, TTS) |
| Stripe | ❌ No | ❌ No (dormant) |

### 4.2 Environment Variables
| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| ENV | No | `test` (auto-set by conftest.py) | Environment name |
| DNA_RATE_LIMIT_MODE | No | `ci` (auto-set by conftest.py) | Rate limit mode |
| LEADING_LIGHT_ENABLED | No | `false` | Enable evaluation API |
| SHERLOCK_ENABLED | No | `false` | Enable Sherlock |
| OPENAI_API_KEY | No | (none) | For image OCR + TTS |

### 4.3 Isolation Guarantee
✅ **Tests run in complete isolation**
- Network calls: Mocked
- Database: In-memory only
- Filesystem: No writes
- Port binding: None (uses TestClient)
- State pollution: None (independent tests)

---

## 5. Repository Structure

```
DNA/
├── app/                      # FastAPI application (main test target)
│   ├── main.py              # Entrypoint
│   ├── config.py            # Environment config
│   ├── airlock.py           # Input validation
│   ├── pipeline.py          # Evaluation facade
│   ├── routers/             # HTTP endpoints
│   │   ├── web.py           # Web UI
│   │   ├── leading_light.py # Evaluation API
│   │   ├── history.py       # History endpoints
│   │   └── debug.py         # Debug endpoints (not implemented)
│   └── tests/               # 28 test files, 840 tests
│
├── dna-matrix/core/         # Core evaluation engine (FROZEN)
│   ├── evaluation.py        # DO NOT MODIFY
│   ├── parlay_reducer.py
│   └── correlation_engine.py
│
├── sherlock/                # Audit engine (v1.0.0)
│   ├── engine.py
│   ├── models.py
│   └── audit.py
│
├── alerts/                  # DORMANT (Sprint 4)
├── context/                 # DORMANT (Sprint 3)
├── auth/                    # DORMANT (Future)
├── billing/                 # DORMANT (Sprint 5)
├── persistence/             # DORMANT (Future)
│
├── requirements.txt
├── pyproject.toml
├── conftest.py              # Auto-sets test environment
└── Procfile
```

---

## 6. Constraints & Risks

### 6.1 Hard Constraints
| Constraint | Description |
|------------|-------------|
| Core Engine FROZEN | `dna-matrix/core/evaluation.py` must NEVER be modified |
| Dormant Modules | `alerts/`, `context/`, `auth/`, `billing/`, `persistence/` must NOT be activated |
| Test Scope | Only run `pytest app/tests -v` — dormant module tests will error |

### 6.2 Known Test Failures
9 tests in `test_debug.py` fail intentionally (endpoints not implemented). This is expected and does not indicate a problem.

### 6.3 Pydantic Warning
`sherlock/models.py:294` uses deprecated config syntax. This is cosmetic and does not affect tests.

---

## 7. Openbot Configuration

### 7.1 Config File (`/etc/openbot/config.yaml`)
```yaml
target_repo: "https://github.com/launchplugai/DNA"
target_branch: "main"
command: "pip install -r requirements.txt && pytest app/tests -v"
health_url: "http://localhost:8000/health"
```

### 7.2 Systemd Trigger
```bash
sudo systemctl start openbot-run
```

### 7.3 Manual CLI
```bash
openbot run \
  --target-repo https://github.com/launchplugai/DNA \
  --target-branch main \
  --command "pip install -r requirements.txt && pytest app/tests -v"
```

---

## 8. Success Criteria

### 8.1 Phase 1 — Clone & Test
- [ ] Openbot clones DNA repo to `/var/lib/openbot/workdir/target`
- [ ] Dependencies install successfully
- [ ] Tests run and produce expected results (831 pass, 9 fail)
- [ ] Receipt JSON written to `/var/lib/openbot/receipts/`
- [ ] Log file written to `/var/lib/openbot/logs/`
- [ ] Origin repo is NEVER modified

### 8.2 Phase 2 — Health Monitoring (Future)
- [ ] Openbot can hit `/health` endpoint after test run
- [ ] Health status recorded in receipt

### 8.3 Phase 3 — Scheduled Runs (Future)
- [ ] Cron/timer triggers automated runs
- [ ] Alerts on test regression

---

## 9. Sprint Breakdown

| Sprint | Ticket | Description |
|--------|--------|-------------|
| S0 | S0-01 | EC2 + SSM Trust Foundation |
| S1 | S1-01 | DNA Sherlock Clone-and-Test Runner |
| S1 | S1-02 | DNA Sherlock Receipt Validation |
| S1 | S1-03 | DNA Sherlock Health Check Integration |
| S2 | S2-01 | Bet App Integration (pending info) |

---

## 10. Out of Scope

- Deployment of DNA Matrix
- Modification of DNA Matrix code
- Activation of dormant modules
- Database provisioning
- Production infrastructure

---

## 11. Appendix

### A. Sample Receipt (Expected)
```json
{
  "receipt_version": "v1",
  "timestamp": "2026-02-01T19:30:00Z",
  "run_id": "abc123-def456",
  "target_repo": "https://github.com/launchplugai/DNA",
  "target_branch": "main",
  "commit_sha": "a52d1e0...",
  "test": {
    "command": "pip install -r requirements.txt && pytest app/tests -v",
    "exit_code": 0,
    "summary": "passed",
    "log_path": "/var/lib/openbot/logs/abc123-def456.log"
  },
  "health": null,
  "overall_status": "SUCCESS",
  "errors": [],
  "policies_loaded": ["protected_paths", "escalation_rules", "receipt_schema"]
}
```

### B. Test Output (Expected)
```
============================= test session starts ==============================
collected 840 items
...
831 passed, 9 failed in 5.23s
```
