# TUI Trust and Risk Improvements

## Summary

Add explicit source freshness, a persistent replication-safety banner, and stronger byte-throughput visibility. Keep implementation changes in this repository; represent required changes in neighboring repositories with GitHub issues.

The banner must distinguish known safety deficits from missing evidence. It must not infer backlog convergence from unrelated cluster-wide activity or let failures in observational sources imply a replication-safety problem.

## Source contracts and freshness

Track last attempt and last successful response separately for each independently fetched source. A successful empty response is a success, not a fetch failure. Preserve the last successful value when a later attempt fails.

| Source | Scope | Polling contract | Stale | Expired | Safety-banner effect |
| --- | --- | --- | ---: | ---: | --- |
| `/replication` distribution and site distribution | cluster | Fetched from a responding peer during each global poll | 30 s | 120 s | Governs replication evidence and safety classification |
| `/replication` velocity | cluster | Returned with `/replication`, but may be absent on older servers | 30 s | 120 s | Describes activity only; absence is `unavailable`, not zero |
| `/nodes` | observer/cluster view | Fetched during each global poll | 30 s | 120 s | Supplies last-known reachability evidence; source age must be shown in conclusions derived from it |
| heartbeat matrix | per observer | `/nodes` fetched concurrently from all peers during a global poll | 30 s | 120 s | Observational only; may warn on the Heartbeats tab but does not by itself raise replication risk |
| `/status` | per node | One node polled per second in the rolling loop | 30 s | 120 s | Supplies last-known sole-holder evidence; source age must be shown when used in the banner |
| `/traffic` | per node | Fetched with the rolling node poll | 30 s | 120 s | Observational only; never raises replication risk |
| `ntx /status` | per ingest node | All currently known ingest nodes polled concurrently every 120 s | 300 s | 600 s | Ingest health only; never raises replication risk |

Verify that the rolling and global poll schedules, endpoint timeouts, and maximum expected peer count can normally refresh each source before its stale boundary. If that guarantee does not hold, derive the thresholds from the actual worst-case cadence rather than retaining the numbers above. Use `refresh_seconds` as the global-poll cadence rather than leaving the setting inert.

For every fetch path, propagate success explicitly. Do not use truthiness to distinguish success from failure: `{}`, `[]`, and zero-valued distributions may be valid successful responses. For aggregate fetches such as the heartbeat matrix, retain per-observer success so a partial result is not represented as complete success.

### Rendering stale and expired data

- Mark stale values visibly and include their age where operationally useful.
- Suppress expired volatile activity: claims, transfer rates, traffic samples, ingest rates, and replication velocity.
- Preserve last-known sole-holder counts and node reachability as safety evidence after expiry, but label both with source age. Never present mixed-age evidence as current.
- Keep `--` for a sensor a host genuinely lacks and `?` for expected-but-missing data.
- Add a `Seen` age column to the Nodes table based on the last successful `/status` response.
- Count the set union of configured bootstrap nodes and currently discovered nodes in the Nodes-tab title. Exclude retired and evicted nodes, deduplicate by canonical FQDN, and do not conflate short names with FQDNs.

## Persistent replication-safety banner

Add a banner visible on every tab. Classify replication evidence using these ordered states:

1. `CRITICAL`: current or last-known evidence reports commits at zero sites; or sole copies were last known on a node whose current or last-known `/nodes` state is unreachable or dead. Include the ages of both evidence sources when either is stale or expired.
2. `UNKNOWN`: replication distribution or site-distribution evidence has never been obtained, is expired without usable last-known safety evidence, or cannot be interpreted under the verified API contract.
3. `WARN`: current or stale replication evidence reports sole-copy, single-site, or below-target commits; or replication safety evidence is stale.
4. `OK`: replication distribution, site distribution, and required reachability evidence are current, interpretable, and report no known deficit.

Traffic, heartbeat, and ingest freshness do not affect this banner. Their own views should show missing, stale, or expired state locally.

Use the API’s exact terminology. Verify whether `site_distribution[0]` means zero storage sites, zero reachable sites, or another state before choosing banner text; do not add “reachable” unless the endpoint contract supports it.

Show only the highest severity in the banner, but do not discard confidence information needed to interpret it. If a critical conclusion relies on stale evidence, say `last known` and include its age. `UNKNOWN` takes precedence over warnings that require the missing evidence, while independently supported critical evidence remains `CRITICAL`.

### Backlog activity language

For a sole-copy, single-site, or below-target backlog:

- If current velocity is at least 0.1 copies/minute, say `replication active` and include copies/minute and bytes/second.
- If current velocity is below 0.1 copies/minute, say `no material replication activity` and include the measured rates.
- If velocity is absent, unsupported, stale, expired, malformed, or otherwise invalid, say `replication activity unavailable`; do not coerce it to zero.
- Do not say the at-risk backlog is `converging` or `stalled`: cluster-wide copy throughput does not establish whether that specific backlog is shrinking.

Treat negative, non-finite, or structurally invalid velocity values as unavailable. Keep the 0.1 copies/minute display threshold explicit and covered by boundary tests.

## Byte visibility

- Make current bytes/second prominent beside copies/minute in the risk banner and velocity widget when velocity is valid.
- Clearly label replication and site-risk figures as commit counts.
- Do not estimate bytes at risk or query a node-local SQLite database.
- File a `tfcs` GitHub issue requesting backward-compatible `bytes_distribution` and `site_bytes_distribution` fields from `/replication`.
- Make no code changes in the neighboring `tfcs` repository.

## Tests and verification

Add deterministic freshness and risk-classification tests using an injected monotonic clock.

Cover:

- exact fresh/stale/expired boundaries and last-attempt versus last-success behavior;
- successful empty responses versus failed responses;
- preservation and age labeling of last-known safety evidence;
- removal of expired volatile data;
- per-observer partial success in heartbeat polling;
- concurrent ingest polling, including one endpoint failing or timing out;
- severity precedence with independent critical evidence and missing replication evidence;
- unknown, unsupported, malformed, stale, expired, zero, threshold, and positive velocity;
- sole-holder evidence combined with current, stale, expired, and missing reachability evidence;
- canonical node counting with configured, discovered, retired, evicted, and duplicate nodes;
- source-local warnings that do not affect the replication-safety banner.

Add Textual pilot tests for the persistent banner, source-age display, stale styling, expired-value suppression, and rendered node count. Tests should advance the injected clock and trigger the same refresh path used by the running application so time-based transitions render without requiring a new network message.

Run tests, compilation, TOML parsing, and `git diff --check`. Then launch the real TUI on the tailnet and observe every affected view through at least one polling transition before reporting success. A diff or pilot test alone is not runtime verification.

## Repository boundaries

- All code and configuration changes stay in TFC.
- Cross-repository requirements are filed as GitHub issues only.
- The cluster remains read-only from this repository.
- Do not perform live-host actions on `scott` as part of this work.
