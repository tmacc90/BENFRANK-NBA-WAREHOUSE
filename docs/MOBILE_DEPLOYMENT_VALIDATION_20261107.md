# BENFRANK NBA mobile deployment validation — November 7, 2026

The mobile application, Docker build and one genuine future-game framework run
are verified. A Render service has **not** been created, and there is **no working
Render URL yet**. The Render integration is available but is not enabled in this
session; no Render credentials are present. Applying the existing paid blueprint
also requires the owner's approval. No changes were merged into main.

The tested application code is commit
`d4297a3100fb5b1318728be893451d534372cce3` on
`benfrank-60-question-interrogation-20261106` in
[tmacc90/BENFRANK-NBA-WAREHOUSE](https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/tree/benfrank-60-question-interrogation-20261106).

## Verified checks

| Check | Result | Evidence / limitation |
|---|---|---|
| GitHub repository and branch access | PASSED | Changes committed to the specified development branch |
| Official Render blueprint JSON Schema | PASSED | Explicit branch, Docker runtime, secret generation and 5 GB disk |
| Software suite | PASSED | 377 tests locally (Python 3.12) and in Actions (Python 3.11) |
| Docker image build | PASSED | Latest mobile Actions job built the deployment image |
| Container readiness and storage mount | PASSED | Real Docker bind mount, writable storage and authenticated routes |
| iPhone 13 and iPad Pro 11 browser checks | PASSED — emulation | WebKit; no horizontal overflow or JavaScript errors |
| Mobile authentication and interaction | PASSED | Wrong token rejected, job submitted/polled, receipt/ZIP downloads, reload and job reopening |
| Production website on physical Apple devices | PENDING | Requires the Render HTTPS URL and physical devices |
| Genuine future-game prop | PASSED — local API | Aaron Gordon points 13.5, DEN at IND, November 7 |
| Actual stored job reopened in a new process | PASSED | Terminal job and original index retained; authenticated receipt SHA matched |
| Render deploy, HTTPS and disk restart | BLOCKED | Render integration access and owner cost approval required |

Latest successful verification runs:

- [Mobile browser, Docker and API validation](https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/actions/runs/42398250017)
- [377-test regression suite](https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/actions/runs/42398250044)
- [60-question software checks](https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/actions/runs/42398250161)

The initial general test run failed because it installed only the old core
dependencies after mobile integration tests were added. Root requirements and
the Docker copy/install order were repaired; the latest runs above passed.

The browser test's engine work is an explicitly blocked software fixture.
It verifies UI/API behavior and downloads; the genuine prediction was executed
separately through the local authenticated API. Neither test establishes
production behavior on Render or physical Apple hardware.

## Genuine forward execution receipt

Aaron Gordon, **NBA points 13.5**, Denver at Indiana. Tipoff from ESPN:
**November 7, 2026, 2:00 PM Pacific** (`2026-11-07T22:00Z`). The exact native
PrizePicks line was captured at `2026-11-07T17:41:26.422530+00:00`.
The local API job was submitted at `17:41:17 UTC`; framework execution finished
at `17:43:26 UTC`, before its requested `21:45 UTC` deadline and tipoff.

Job: `9592a26a5a0e45df92409dbaaa04531a`.

| Stage | Recorded result |
|---|---|
| Schedule, native exact line and player identity | EXECUTED |
| Acquisition and source reconciliation | EXECUTED; 94 accepted target appearances, 87 with independent source agreement, zero target disagreements quarantined |
| Historical windows | EXECUTED; L5/L10/L15/L20/L25/L32/L52 plus current season, previous season and available archive |
| Player profiles, projected roles and matchup inputs | EXECUTED; estimates and missing tracking inputs retain their labels |
| Main physical simulation | **25,000 complete sequential games**, stored trace and hash chain |
| Adversarial stress | **2,000 downside + 2,000 upside complete games**, separately stored traces |
| Trace re-verification | All trace chains reread; 15 predeclared complete-game samples independently reexecuted |
| Blind model | Separate process and line-blind numeric payload verified; predictive accuracy not independently certified |
| Sensitivity | Same main trials rethresholded at alternative lines, including +0.5 and +1.0; no extra trial count claimed |
| 100-question Player DNA audit | Audit executed; **5** items had available evidence, 95 remained unavailable |
| 60-question interrogation | All questions audited; **27 verified**, remaining questions retain their explicit states; certification false |
| Prediction freeze and receipt storage | EXECUTED; immutable forward ledger entry before tipoff |
| Postgame grading | PREPARED_PENDING_FINAL; this report does not claim grading ran |

| Window | OVER | UNDER | PUSH | Games |
|---|---:|---:|---:|---:|
| L5 | 3 | 2 | 0 | 5 |
| L10 | 6 | 4 | 0 | 10 |
| L15 | 9 | 6 | 0 | 15 |
| L20 | 11 | 9 | 0 | 20 |
| L25 | 14 | 11 | 0 | 25 |
| L32 | 19 | 13 | 0 | 32 |
| L52 | 33 | 19 | 0 | 52 |
| Current season | 4 | 3 | 0 | 7 |
| Previous season | 24 | 12 | 0 | 36 |
| Available archive | 52 | 42 | 0 | 94 |

The main model chose **OVER** with projection **16.74** and raw conditional
OVER share **65.50%**. The Blind projection was **13.4246**, an **UNDER** lean.
Downside stress reversed the main pick; the forecast is **FRAGILE**. There were
4,283 void trials among the 25,000 main trials. The displayed raw share is
conditional on played, non-push trials and is **not** a calibrated hit probability.
The first UNDER line in the simulated support was **16.5**.

Sources retained 121 capture records: 117 ESPN, one native PrizePicks and three
independently attributed NBA statistical archive records. The direct NBA CDN
schedule request returned HTTP 403; that failure is retained. The framework used
ESPN schedule/depth/injury/log/box sources and its permitted pinned archive route.
Seven accepted target appearances had one provider only. Source correction vintage,
full career coverage, some tracking inputs and independent model accuracy remain
unverified. All protected warehouse/rule/receipt hashes checked by the runner
were preserved; existing repository data and historical receipts were not deleted.

Execution receipt SHA-256:
`a31617834cae29162fe2b1abe780af00e2245aa260ea961a5dc9b5f4010d5ec5`.

Prediction receipt SHA-256:
`de1f55500a4f6970a3f5ab8ac30e0bcfe1d42a35d97bf1bf7bb004e89b99fd16`.

[Machine-readable validation details](../diagnostics/mobile-validation-20261107.json)
retain seeds, stage statuses, trace hashes, source failures and sensitivity results.

## Deployment awaiting approval

The prepared blueprint selects `benfrank-nba-mobile`, Starter compute and a 5 GB
persistent disk at `/var/lib/benfrank`. Published base pricing checked November 7:
**$7/month + $1.25/month = $8.25/month**, before taxes, workspace charges or usage
beyond included allowances. The account's actual quote has not been inspected.
See [Render pricing](https://render.com/pricing) and
[persistent disk requirements](https://render.com/docs/disks).

Enable the Render integration for this session and approve that paid plan before
applying the blueprint. Then verify account/service access, deploy this tested
branch, obtain the actual HTTPS URL, test its token and mounted disk across a
restart, open it on real iPhone/iPad hardware, and run a fresh qualifying future
prop on Render. Keep main unmerged until those production checks pass.
