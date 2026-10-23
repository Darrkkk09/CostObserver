# CostObserver Take-Home Project

Welcome, and thanks for taking this on! 👋

This folder has everything you need. The setup takes about 10 minutes, and **you do not need an AWS account, Docker, or any paid service**. Everything runs on your laptop.

> **Short on time?** Read [Quick start](#quick-start), [Your task](#your-task), and [The rules](#the-rules). The rest is reference.

---

## Quick start

You need **Python 3.10 or newer**.

**1. Create a virtual environment and install dependencies**

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Start the local AWS emulator** in a separate terminal (keep it running)

```bash
source .venv/bin/activate        # Windows: .venv\Scripts\activate
moto_server -p 4566
```

This runs [Moto](https://docs.getmoto.org/), a free tool that behaves like S3 and DynamoDB on `http://localhost:4566`.

**3. Load the sample data**

```bash
python scripts/setup_data.py
```

You should see `Local environment is ready.` You can run it again any time. Use `--reset` to start fresh.

**4. Check that everything works**

```bash
pytest
```

Expected: **3 passed, 1 skipped**. The skipped test turns on once you implement your first rule.

**5. Run the program**

```bash
python -m triage.main --date 2026-10-20
```

At first it says `Not implemented yet`. That's where your work begins.

---

## The story

A cloud team receives a daily file showing what each resource costs. Separately, they store details about each resource: whether it is attached, whether it must be kept, and who can reach it over the network.

Nobody is connecting the two. **Your program will**, and tell the team what deserves attention.

All data is fictional.

---

## Your task

Complete the `TODO`s in the `triage/` folder:

| File               | What to do                                                   |
| ------------------ | ------------------------------------------------------------ |
| `triage/ingest.py` | Read the usage file from S3 and look up metadata in DynamoDB |
| `triage/rules.py`  | Implement the three rules and collect data issues            |
| `triage/store.py`  | Save findings to DynamoDB without creating duplicates        |
| `triage/main.py`   | Print a readable summary                                     |
| `tests/`           | Add tests that show your rules work                          |
| `SOLUTION.md`      | Briefly explain your decisions                               |

The existing structure is a suggestion. You can reorganize the code, but please keep:

- The input locations and table names in `triage/config.py`
- The rule IDs and severities in `triage/models.py`
- The finding format described below

**Suggested time:** about 15 minutes for setup, 2 hours for the code, 45 minutes for tests, and 20 minutes for `SOLUTION.md`. If you go much over, stop and tell us what's left.

---

## The data

### Daily usage file (S3)

Location: `s3://costobserver-usage/usage/2026-10-20/daily-usage.json`
A copy is in `data/daily-usage.json` so you can read it easily.

| Field                   | Meaning                                                         |
| ----------------------- | --------------------------------------------------------------- |
| `resource_id`           | Unique resource identifier                                      |
| `resource_type`         | `ebs_volume`, `rds_database`, `ec2_instance`, or `s3_bucket`    |
| `daily_cost_usd`        | Cost for the report date                                        |
| `avg_daily_cost_7d_usd` | Average daily cost over the previous 7 days. **May be missing** |

### Resource metadata (DynamoDB table `ResourceMetadata`, key `resource_id`)

A copy is in `data/resource-metadata.json`.

| Field                  | Applies to | Meaning                                           |
| ---------------------- | ---------- | ------------------------------------------------- |
| `environment`, `owner` | All        | Context for the team                              |
| `attachment_state`     | Volumes    | `attached` or `unattached`                        |
| `unattached_since`     | Volumes    | Date the volume was detached (`YYYY-MM-DD`)       |
| `retention_required`   | Volumes    | `true` means it must be kept. **May be missing**  |
| `database_port`        | Databases  | Port the database listens on                      |
| `inbound_rules`        | Databases  | List of `{ "port": ..., "cidr": ... }` allowed in |

Some resources in the usage file may have **no metadata at all**.

---

## The rules

These are simplified rules for this exercise, not universal cloud policy.

### Rule A: `UNATTACHED_VOLUME` (severity `MEDIUM`)

Flag an `ebs_volume` when **all** of these are true:

- `attachment_state` is `unattached`
- It has been unattached for **7 days or more** (report date minus `unattached_since`)
- `daily_cost_usd` is greater than 0
- `retention_required` is explicitly `false`

**Projected monthly savings** = `daily_cost_usd × 30`, rounded to 2 decimal places.

Example: $2.00/day, unattached for 10 days, not required → finding with **$60.00/month**.

### Rule B: `PUBLIC_DATABASE` (severity `HIGH`)

Flag an `rds_database` when any inbound rule has:

- `port` equal to the database's `database_port`, **and**
- `cidr` exactly `0.0.0.0/0` (any IPv4 address)

An open port that is _not_ the database port does not count. Savings: `null`.

### Rule C: `EXPOSED_DATABASE_COST_SPIKE` (severity `CRITICAL`)

Only for databases that match Rule B. Flag when:

- `avg_daily_cost_7d_usd` is present and greater than 0, **and**
- `daily_cost_usd` is **more than** 2 × `avg_daily_cost_7d_usd` (exactly 2× does not count)

A database can have both Rule B and Rule C findings. Savings: `null`. A higher bill is a reason to investigate, not proof of an attack.

### When data is missing

Don't guess. Record a data issue instead and carry on:

| Issue code             | When                                                               |
| ---------------------- | ------------------------------------------------------------------ |
| `MISSING_METADATA`     | A usage record has no metadata item                                |
| `MISSING_FIELD`        | A field needed to check a rule is missing                          |
| `BASELINE_UNAVAILABLE` | Rule C cannot be checked because the 7-day average is missing or 0 |

Other resource types (`ec2_instance`, `s3_bucket`) have no rules in this exercise. Count them as analyzed, but they are not data issues.

---

## Expected output

### 1. Findings in DynamoDB (`PrioritizedFindings`)

One item per finding. See `examples/sample-finding.json`.

| Field                                                 | Notes                                                                         |
| ----------------------------------------------------- | ----------------------------------------------------------------------------- |
| `finding_id`                                          | `"<date>#<resource_id>#<rule_id>"` (already provided as `Finding.finding_id`) |
| `resource_id`, `rule_id`, `severity`, `analysis_date` |                                                                               |
| `evidence`                                            | The values that triggered the rule                                            |
| `recommended_action`                                  | A short, practical next step in your own words                                |
| `projected_monthly_savings_usd`                       | A number for Rule A, otherwise `null`/absent                                  |

**Running the program twice on the same date must not create duplicate items.**

Tip: DynamoDB does not accept Python `float`. Use `Decimal`, for example `json.loads(text, parse_float=Decimal)`.

### 2. A summary in the terminal

See `examples/sample-summary.txt`. It should show:

- Number of resources analyzed and number affected
- Findings by severity, most urgent first
- Total projected monthly savings (**do not count the same resource twice**)
- Data issues

---

## Tests

`tests/conftest.py` provides an `aws` fixture with an **in-memory** S3 and DynamoDB already loaded with the sample data. Tests using it do **not** need `moto_server` running.

Please cover at least:

- Each rule, both matching and not matching
- Boundaries (exactly 7 days, exactly 2×)
- Missing data
- Running twice without duplicates

---

## Submitting

1. Fill in `SOLUTION.md`.
2. Create a ZIP **without** your virtual environment or caches:

   ```bash
   zip -r firstname-lastname.zip . -x ".venv/*" "*__pycache__*" ".pytest_cache/*"
   ```

3. Upload it with the submission link in your invitation email (max 10 MB).

Please don't include passwords, API keys, or real AWS credentials.

---

## Troubleshooting

| Problem                              | Fix                                                                                                                   |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `Could not reach the local emulator` | Start `moto_server -p 4566` in another terminal                                                                       |
| Port 4566 already in use             | Run `moto_server -p 5000`, then `export AWS_ENDPOINT_URL=http://localhost:5000` (Windows: `set AWS_ENDPOINT_URL=...`) |
| Data looks wrong                     | `python scripts/setup_data.py --reset`                                                                                |
| `moto_server: command not found`     | Activate the virtual environment first                                                                                |
| Already use LocalStack?              | It works too. Point `AWS_ENDPOINT_URL` at it                                                                          |

Stuck on setup for more than 20 minutes? Reply to your invitation email. Setup problems are on us, not you.

Good luck, and enjoy it!
**The CostObserver Team**
