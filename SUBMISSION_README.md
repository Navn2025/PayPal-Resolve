# Resolve documentation library

This package contains PDFs only. Source code, credentials, databases, Markdown,
videos and generation scripts are excluded. Application source remains a separate delivery.

## PDF reading order

| PDF | Contents |
| --- | --- |
| 00 Documentation index | Reading guide and final document inventory. |
| 01 Technical architecture | System overview, architecture, workflows and quick setup. |
| 02 Implementation guide | Backend services, reconciliation, execution, AI, aftercare and SDK. |
| 03 Database design | Complete SQLite field dictionary, keys, constraints, indexes and migration catalog. |
| 04 API reference | All current OpenAPI operations, parameters, responses and component schemas. |
| 05 Installation and deployment | Component setup, example configuration, identity and hosted readiness. |
| 06 Illustrated user manual | Existing 51-page merchant/buyer manual and SDK appendix. |
| 07 Testing and security | Recorded tests, account-backed evidence, controls and remaining gaps. |
| 08 Operations and integrations | Customer workflows, provider integrations, Postman and application inventory. |
| 09 Engineering log | Full maintained development history, decisions and validation. |

Reviewers should start with the technical architecture and illustrated manual.
Developers can then follow the implementation, database and API references.
Use installation/deployment with the separately delivered application source.
The engineering log retains the reasoning and explicit corrections behind changes.

## Edition and evidence

Compiled on 12 November 2026. The illustrated manual retains its 11 November
edition and original screenshots. The architecture guide is the 12 November
submission edition. Other source chapters retain their recorded dates and scopes.

The API reference describes the current 178-operation contract. The older audit
ledger covers 175 operations; that result does not establish new coverage of all
current routes. Recorded application tests were not rerun for these PDFs. PayPal
demonstrations use Sandbox test funds. AI recommendations remain separate from
merchant authorization and payment execution.

The database inventory uses a new disposable SQLite database initialized from
immutable migrations. It does not access the owner's database or prove hosted
PostgreSQL acceptance. Historical local, simulated and account-backed results
are identified separately in the testing/security and engineering volumes.

## Package checks

The archive contains exactly the ten named PDFs. The build verifies readable
PDFs, final page counts, ZIP CRC integrity, matching document hashes and the
35,000,000-byte submission limit. Final page counts appear in this PDF index.
