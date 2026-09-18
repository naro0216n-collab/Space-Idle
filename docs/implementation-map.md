# 現行実装対応表（非正準）

本書はmigrationや監査時に、正準Domain契約と現行コード上の責務所在を対応付けるための補助資料である。

`docs/design.md` と `docs/architecture.md` が正準仕様であり、本書のファイル名、module構成、既存責務分担を設計根拠にしない。実装を確認する前に対応する正準節を読み、現行実装が異なる場合は正準責務へ移行する。

この節はmigrationや監査時に責務の所在を追跡するための参考であり、ファイル名や現行module構成を正準Architectureとはしない。実装は上記Domain契約へ従って統廃合してよく、この表に実装を合わせるためにArchitectureを変更しない。

| 領域 | 参考責務 |
|---|---|
| `spatial.py` | Star System、Celestial Body、Surface Cell graph、Spatial context / transport geometry、Operational Node / Location territory、Environment State |
| `site.py` | SiteRequirements / Capability / Service Capacity Requirement |
| `facilities.py` | Facility Definition / State / placement scope / Capability / Service Capacity supply |
| `power.py` | Power配分 |
| `catalog.py` / `inventory.py` / `storage.py` / `storage_domain.py` | Resource→Storage Pool compatibility / Inventory・Reservation・Stock admission / Facility・Infrastructure由来Physical・Usable Storage Capacity projection |
| `industry.py` / `production/` | Process inputs / outputs / production flow / Resource Potential extraction response |
| `construction/` / `projects.py` | Construction Recipe、Project、調達、能力配分 |
| maintenance domain | Facility maintenance demand / fulfillment |
| `transport/` / movement domain | Movement Operation / Plan / Execution、Vehicle Definition、Fleet State、Vehicle production、Transport Allocation、派生Service Plan / Capacity、Fleet relocation |
| `logistics.py` / logistics domain | Supply Requirement、Target Stock、sparse hard Supply Routing Constraint、existing network上のcanonical source/path selection、共有Transport Capacity配分、Cargo Flow Segment、handoff / arrival waiting |
| `research.py` | Research Point、Technology State、Research Project / stage、Operational Experience |
| exploration domain | Scientific Exploration Campaign / Fleet reservation / RP reward |
| `survey.py` | Surface Cell Resource Knowledge、Survey Campaign |
| `simulation.py` | canonical daily tick / phase orchestration / snapshot / allocation sequencing / equivalent fast-forward |
| `application*.py` | Command / Query / DTO |
| `persistence.py` | Snapshot / Load / Offline resume |
| `validation.py` | Configuration / Runtime invariant |
| `content/` | ゲーム固有Definition |
| `composition/` | DomainとContentの配線 |

現行実装が正準Domain契約と一致しない箇所は、この表や既存moduleを互換層として温存せず、変更単位ごとに正準責務へ統合する。

---
