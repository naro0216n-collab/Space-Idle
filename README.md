# 宇宙開発Idle Simulation / WebUI v0.4.5

ゲーム性評価段階のSimulation Coreです。現段階では旧仕様・旧セーブとの後方互換を要件とせず、ゲームモデルとして妥当な構造への破壊的変更を優先します。数値は評価用の仮値であり、テストも個別の価格・所要日数・生産量を固定することを目的にしません。

## 現在のゲーム性評価範囲

地球側研究基盤から開始し、低軌道物流、月圏物流、月資源探査、ロボット拠点、初期ISRU、現地材料加工、推進剤生産、月面からの輸送までを一つのSimulation Coreで検証します。

主なメカニクス:

- 地点別の所有在庫、保管容量、入出庫フロー
- 倉庫の物理容量と、給電・環境条件を反映した保管サービス容量の分離
- 電力の優先配分、同順位設備への比例配分、部分稼働
- 施設・資産が供給する建設能力と複数案件への配分
- 建設資材の輸入・現地材置換・材料種の明示選択
- 建設案件ごとの調達元、経路、輸送方式指定
- 複数Leg物流、輸送待ち、輸送中、到着待機
- 打上げヴィークル／宇宙船の個体保有、現在位置、搭載推進剤、航行・整備状態
- Powered Ascent / Spaceflight / Landing / Atmospheric Entry の物理Operation別適合判定
- 定期物流の自動運転と手動停止/再開
- Theory / Prototype / Demonstrationを共通SiteRequirementsで表現する研究
- 段階的資源探査と有限埋蔵量
- 採掘・加工・電解・推進剤製造等の産業フロー
- 電力、原料、保管、物流、環境、能力等のblocker / limiting-factor Query

## Spatial / Facilityモデル

Generic CoreはEarth、Moon、Mars等の固有地点名による分岐を持ちません。

Locationは `SpatialNodeDef` と型付きEnvironment Facetで表現し、施設やSystemはLocation IDではなく環境条件とCapabilityを評価します。施設定義はLocationから独立し、実際の設置地点はFacilityState / BuildProjectが保持します。

施設は以下を分離します。

- 設置可能な環境条件
- 現在運転可能な環境条件
- 施設が物理的に存在することで供給するInfrastructure Capability
- 手動停止・環境・給電を反映したActive / Available Capability

このため、環境改変を見越した先行建設や、同一施設定義の別天体への再利用を地点IDの例外追加なしで扱えます。

## 倉庫と物流

資源はフロー中心ですが、所有在庫と保管能力もゲーム上の制約です。

保管は物理容量とサービス容量を分離します。給電を必要とする極低温貯蔵等では、電力不足によって新規受入能力が低下しても、既存在庫を即時消去しません。必要に応じて `unserviced_occupied_t` として観測できます。

長距離輸送中の貨物は目的地倉庫を事前予約しません。目的地の保管容量は実到着時にだけ判定します。荷卸しできない貨物は物流側の到着待機状態に残り、輸送経路側へバックプレッシャーを発生させます。

Cargoおよび建設調達では、プレイヤーは出発地と最終目的地だけを指定してEnd-to-End輸送を依頼できます。経路を未指定ならCoreが一貫した自動方針で直行Routeまたは複数Legを選択し、中継ノードごとに再発送操作を要求しません。経路と各Legの輸送方式を明示指定することもでき、その場合は指定方式が利用不能でも別方式へ勝手にフォールバックしません。LEOや月周回軌道は実在する在庫・補給・積替え拠点ですが、プレイヤー操作上の必須経由点ではありません。

天体そのもの (`CelestialBodyDef`) と、在庫・施設が存在する経済ノード (`SpatialNodeDef`) を分離します。地球地表とLEO、月周回軌道と各月面地域はそれぞれ独立したSurface / Orbital Nodeであり、天体はそれらを束ねる物理的な親概念です。

輸送路は「契約輸送専用」「月面着陸船専用」のような用途区分を持ちません。Routeは端点と `Powered Ascent / Spaceflight / Landing / Atmospheric Entry` の物理Operation列、必要Δv、基準所要時間、端点インフラ等を定義します。ヴィークル側の実性能との照合で利用可否を決めるため、名称や「宇宙船／打上げヴィークル」という表示分類そのものは許可条件ではありません。

打上げヴィークルと宇宙船はState遷移を分けます。再使用打上げヴィークルは地表→軌道輸送を実行しても通常は地表側へ残り、回収・ターンアラウンドへ入ります。宇宙船は永続個体として実際にSpatial Node間を移動し、現在位置、航行先、搭載推進剤、整備状態を保持します。軌道専用宇宙船は打上げヴィークルのペイロードとして地表から軌道へ搬入でき、地表上昇能力を持つ統合型宇宙船なら自身でPowered Ascentを実行して軌道へ移動できます。`Launch` は打上げ運用・Mission上の概念であり、地球用と月面用を分ける別々の適合キーにはしません。

地球地表→月面の連続Mission、LEO→月面直行、LEO→月周回軌道→月面という積み替え経路を並存させます。直行可否は必要Operationを一つのVehicleまたは外部Serviceが満たせるかで決まり、中継経路は補給・積替え・機体分業によって有利になり得ます。LEO等の軌道拠点は「必ず通る進行ゲート」ではなく、投資によって物流コストや再使用性を改善する選択肢です。外部輸送はRouteへ埋め込まれた特別容量ではなく独立した `ExternalTransportServiceDef` として同じ輸送モード集合へ参加します。

輸送実行は `TransportMissionState` として保持し、Cargo、現在Leg、Carrier、搭載された後続Vehicle、到着待機を一つのMission連続性として管理します。同じ宇宙船がCargoを積載したまま中継点を通過する場合はStorageへ強制荷卸しせず、別Vehicle/Serviceへ積み替える場合だけ実際の `cargo_transfer` 能力を要求します。給油もRoute通行許可ではなく `vehicle_refueling` サービスを利用する実処理です。Vehicleのturnaroundは必要に応じて整備Infrastructure、資金、交換資材を要求できます。

## 建設と現地生産

建設能力はLocation固有の固定値ではありません。建設設備や移送可能な建設機械等から発生するフローとして扱います。複数案件へ配分でき、同一日の途中で案件が完成した場合は余剰能力を残案件へ再配分します。

現地材は「建設地点に特定工場が存在すること」では判定しません。資源を実際に生産し、必要なら別拠点へ輸送し、建設地点の在庫として利用します。代替材が複数ある場合は案件・部材単位で使用材料を指定できます。

## 研究・探査

研究の各段階は共通の `SiteRequirements` を使用します。

- Theory: 研究設備が置かれた地点で必要な環境・Capabilityを満たすこと
- Prototype: プレイヤーが試作地点を選択し、必要資源とSiteRequirementsを満たすこと
- Demonstration: プレイヤーが実証地点を選択し、実際に利用可能なCapabilityと環境条件を満たした日だけ進行すること

探査情報は、存在確率 → 濃度情報 → 埋蔵量情報の順に段階的に公開します。完了した探査キャンペーンは探査能力を消費し続けず、余剰能力は同じ地点の未完了キャンペーンへ再配分されます。

## 手動停止 / 再開

反復運転を自動化しながらプレイヤーが介入できるよう、以下は設定・進捗を保持したまま停止/再開できます。

- 施設
- 建設案件
- 研究
- 探査
- 定期物流

施設停止は生産、採掘、発電、建設能力、研究・探査能力、Available Capabilityへ一貫して反映します。安全維持や保冷に必要なstandby負荷を持つ施設は、停止してもその負荷を回避できません。

## Application API

UI/HTTP層は `Simulation` や各Domain Serviceを直接操作せず、`space_idle.application.GameApplication` のCommand/Query境界を使用します。

Commandは建設、資材選択、調達・輸送設定、設備運転、研究、探査、物流、契約、時間進行等のプレイヤー意図を表します。Queryは世界概要、地点、建設候補・案件、物流、研究、探査、契約をimmutable DTOとして返します。

表示用名称と内部IDは分離しています。ゲーム固有の日本語表示名はcontent側Definitionに置き、Generic Coreの判定ロジックへ名称を持ち込みません。

ゲーム固有Contentは一つの巨大Definitionファイルへ集積せず、`base_ids / base_requirements / base_spatial / base_facilities / base_transport / base_industry / base_construction / base_progression / base_catalog` 等のbuilderへ分離しています。`base_game.py` はIDの便宜的な公開面であり、Simulation組立は `composition/base_simulation.py` が担当します。地球～月は現時点のプレイ可能範囲であり、地理別の独立「Earth–Moon content pack」とは扱いません。火星等の追加時も同じ連続したベースゲームへDefinitionを合成し、開始条件や評価範囲が必要なら別のScenario/Bootstrap責務として分離します。

## 仕様変更時の責務境界

将来の大規模化後も、仕様変更の理由から変更箇所を予測できることを重視しています。単なるファイル分割ではなく、Content Definition、Composition Root、Domain Logic、Application Contract、Persistence / Validationを別責務として扱います。

- `content/` はゲーム固有Definitionと初期状態だけを所有し、ApplicationやComposition Rootを参照しない
- `composition/` はContentをDomain Serviceへ配線し、Base Gameで有効な `DomainExtension` を選択する
- `bootstrap.py` だけがComposition・Catalog・Applicationを最終的に組み合わせる
- `logistics.py` はFacadeとし、`transport/` がmodel / operation evaluator / compatibility / fleet / planning / orders / executionを所有
- `projects.py` はFacadeとし、`construction/` がrules / planning / procurement / executionを所有
- `industry.py` はFacadeとし、`production/` がprocess selection / allocation planning / executionを所有
- `research.py` はFacadeとし、research model / workflow / capacity / executionを分離
- Survey知識進行とExtractionは別Serviceとして所有
- ApplicationはDomain別Command contract / handlerとQuery DTO / projectorへ分離し、具体Contentを参照しない
- Technology unlockは `Simulation.technology` が単一所有し、Researchは更新、Construction/Transport等は参照する
- Vehicleは輸送性能 `TransportPerformanceProfile`、運用費 `VehicleEconomicsSpec`、製造 `VehicleProductionSpec`、整備 `VehicleMaintenanceSpec` を合成する
- Transport Operationは固定EnumではなくOperation IDと `OperationEvaluatorRegistry` で拡張し、新Operation追加で中央switchを増築しない
- Persistence、Configuration Validation、Runtime Validation、Resource参照は各Domainの `DomainExtension` が宣言し、中央処理は登録Extensionを実行するだけにする
- Vehicle / Mission / Project / Research / Contract等の主要状態はDomain所有Enumで管理する

Architecture Testでは、Core/Domain→Application・Content・Composition等の逆依存、Content→Application等の逆依存、star import、主要Mixin実装間の循環依存を検出します。また、任意Transport Operationを中央Enum変更なしで登録できることや、Application Commandの設定値がDomainへ保持されることも構造テストしています。

Simulationの日次処理順はゲームルールそのものなので、汎用イベントバスへ隠さず `Simulation.advance_days()` に明示的に残します。変更局所性のために、意味のある処理順序まで分散・自動登録しない方針です。

## UI向けDefinition / Report

`v0.4.5` では開発用WebUIをApplication境界だけで実装できるよう、UI契約を拡張しています。Core/Domain内部オブジェクトをUIへ公開しません。

`GetCatalog` は従来のResource / Facility / Vehicle / CelestialBody / Locationに加え、以下の静的Definitionを返します。

- Process Definitionと入出力
- Research Definition、前提研究、Theory / Prototype / DemonstrationのSiteRequirements
- Route Definition、Operation列、必要技術、端点SiteRequirements
- External Transport Service DefinitionとOperation性能
- Facilityの設置環境・運転環境条件

状態系Queryには次を追加しています。

- `GetFlowReport(location_id)`：地点の電力、建設能力、資源別のローカル産業生産/消費rateと、物流の出発待ち・輸送中・到着待機mass、現在の制約
- `GetBottlenecks(location_id=None)`：Facility / Industry / Extraction / Construction / Storage / Logistics / Research / Survey / Contractの停止・律速要因を正規化した`IssueRow`として取得
- `GetLogisticsSummary()`：物流全体の軽量サマリ
- `GetRoutes(...)` / `GetVehicles(...)` / `GetCargoOrders()` / `GetLogisticsRules()` / `GetTransportMissions()`：従来の巨大な`GetLogistics()`を用途別に分割

`GetLogistics()` はCore検証・後方の内部利用用に残していますが、WebUIでは分割Queryを基本とします。特にiPadではRoute一覧取得時にmode詳細を含めず、選択したRouteだけmodeを取得する前提です。

## 開発用WebUI（iPad）

`v0.4.5` はAPI Server自身がWebUIを同一Originで配信します。PC側でServerを一つ起動し、同一LAN上のiPad SafariからPCのIPv4アドレスを開きます。API専用URLではなくルートURLを使用します。

```text
http://<PCのLAN IPv4>:8765/
```

Windowsではリポジトリ直下の `start_ipad_server.bat` を実行するとLAN IPv4候補を表示して `0.0.0.0:8765` でServerを起動します。初回にWindows Firewallの確認が出た場合は、利用しているプライベートネットワークでPythonの受信を許可する必要があります。PCとiPadは同一LANへ接続してください。

UIは次の2ビューを上部の固定切替で排他的に表示します。同時表示はしません。

- **拠点運用**: Spatial Node一覧、地点概要、設備、在庫・フロー、建設、研究、探査、契約、固定Inspector
- **物流ネットワーク**: Route一覧、ノード/Routeネットワーク図、輸送資産、Cargo、選択Routeのmode/blocker詳細、貨物登録

主要CommandもWebUIから発行できます。時間進行、設備停止/再開・電力優先度、建設計画、研究開始/停止/再開・配分、探査開始/停止/再開・配分、契約受諾/辞退、Cargo登録、Save/LoadをApplication API経由で実行します。Commandは画面が保持するrevisionを `If-Match` へ渡すため、別タブ等で状態が先に変化した場合は古い操作をそのまま上書きせず再取得します。

### iPad画面条件

開発UIの基準は**横持ちの通常サイズiPad**です。iPad mini向け最適化は対象外です。CSS上の設計最小幅は1180pxとし、横画面の情報構造を固定します。

縦持ち時にも「非対応」画面へ切り替えたり、情報を縦1列へ再構成したりしません。横持ち用の同じレイアウトをそのまま表示し、実効幅が不足する場合は横スクロールで閲覧します。これは縦持ちを別UIとしてサポートするという意味ではなく、表示内容・配置を隠したり置換したりしないための挙動です。

Safariのhoverを前提にせず、主要操作は44px以上のタッチ領域を確保しています。開発段階ではService Workerを使用しないため、WebUI更新時に古いPWA cacheが残ることも避けています。

## Development API Server

`v0.4.5` では `GameRuntime` とHTTP API Adapterを追加しています。HTTP層はゲームルールを持たず、JSONをApplication Command/Queryへ変換するだけです。`GameRuntime` が一つの正準 `GameApplication` セッションを所有し、複数HTTP requestからのCommand / Save / Load / New Gameをロック下で直列化します。

起動例：

```bash
python -m space_idle.api --host 0.0.0.0 --port 8765 --save-dir saves
```

同一LAN上のiPadからWebUIを開く例：

```text
http://192.168.1.20:8765/
```

疎通確認だけを行う場合は `http://192.168.1.20:8765/api/v1/health` を使用できます。

主要endpoint：

```text
GET  /api/v1/health
GET  /api/v1/session
GET  /api/v1/commands/schema
GET  /api/v1/catalog
GET  /api/v1/world
GET  /api/v1/locations/{id}
GET  /api/v1/locations/{id}/flow
GET  /api/v1/locations/{id}/build-options
GET  /api/v1/bottlenecks?location_id=...
GET  /api/v1/projects?location_id=...
GET  /api/v1/logistics/summary
GET  /api/v1/logistics/routes                 # mode詳細なしが既定
GET  /api/v1/logistics/routes/{route_id}      # 選択Routeのmode詳細
GET  /api/v1/logistics/vehicles
GET  /api/v1/logistics/orders
GET  /api/v1/logistics/rules
GET  /api/v1/logistics/missions
GET  /api/v1/transport-plans?source_id=...&destination_id=...
GET  /api/v1/research
GET  /api/v1/surveys
GET  /api/v1/contracts
POST /api/v1/commands
POST /api/v1/session/new
POST /api/v1/session/save
POST /api/v1/session/load
```

Command request例：

```json
{
  "type": "AdvanceTime",
  "payload": {"days": 7}
}
```

状態変更が成功するたびに`revision`が単調増加します。GET応答にはrevisionベースのETagを付け、未変更なら`304 Not Modified`を返せます。Commandでは任意で`If-Match: "rev-N"`を送り、再接続や別タブで画面状態が古い場合は`409 revision_conflict`として拒否できます。大きなJSON応答はクライアントが`Accept-Encoding: gzip`を送ればgzip圧縮します。Catalogはcontent単位のETagで長めにキャッシュできます。これらはiPad上での不要な再転送を抑えるためのApplication/API側最適化であり、Simulationルールには影響しません。

開発用CORSは既定で`*`です。特定Originへ絞る場合は`--cors-origin`を繰り返し指定します。認証はまだ実装していないため、Serverは信頼できるローカルネットワーク内でのみ使用してください。

将来のiPad PWA/WebUIをHTTPSで配信する場合、HTTPSページからHTTP APIを呼ぶ構成を避けるためAPIもTLS化できます。

```bash
python -m space_idle.api --host 0.0.0.0 --port 8765 \
  --tls-cert cert.pem --tls-key key.pem
```

iPad側で使用する証明書は端末から信頼できる構成にする必要があります。HTTPのみでも通常の開発WebUIは利用できますが、PWA/secure-context前提の機能を検証する段階ではWebUIとAPIを同じHTTPS前提で扱います。

実時間→Game Dayの変換率はCoreへ固定せず、Server起動時のPolicyとして明示します。Policyを設定した場合、iPad側のSafari/PWAが休止してrequestが途切れても、`GameRuntime`が次回のQuery/Command/Save時にPC側で経過実時間をまとめて通常Simulationへ反映します。したがってゲーム進行をiPadのJavaScript timerへ依存させません。Policy未設定時は実時間による自動進行を行いません。

```bash
python -m space_idle.api --offline-seconds-per-day 60 --offline-max-days 30
```

これも既存の`advance_days()`経路を使用し、Offline専用Simulation式は追加しません。

## Save / Load / Offline Progress

保存はApplication単位で行います。静的content Definitionは保存ファイルへ複製せず、現在のcontent factoryから再構築した後に可変状態Snapshotを復元します。

- schema versionとcontent idが一致しないセーブは拒否
- ゲーム性評価段階では旧schema/content migrationを実装しない
- 派生可能な倉庫容量等は保存せず、Facility・Environment等から復元後に再計算
- Environment Overlay等の動的環境状態は保存対象
- 宇宙船・打上げヴィークルの現在位置、航行状態、搭載推進剤も保存対象
- Offline Progressは別ルールを持たず通常の `advance_days` と同じSimulation経路を使用
- 端数ゲーム日は次回resumeへ繰り越し可能

## 監査・テスト方針

暫定バランス数値や旧挙動の固定を目的としたテストは増やしません。主な検証対象は次の通りです。

- 資源、予約、輸送、倉庫の会計保存
- 負値・容量超過・参照切れの防止
- 主要な状態遷移とpause/resume
- 同順位・同条件で登録順に結果が依存しないこと
- Save/Load後の将来進行同値性（Transport Mission、Vehicle handoff、製造中・整備待ちを含む）
- Offline Progressと通常進行の同値性（Vehicle製造・整備状態を含む）
- Vehicle / Cargo / 推進剤のMission連続性と直接積替え・給油Infrastructure
- Application QueryのJSON安全性
- Generic Coreへ特定天体・Location allowlistが侵入しないこと

`market.py`、`mission_stress.py`、`terraforming.py` は将来システムのアーキテクチャストレステスト用で、現在のプレイ可能範囲にはまだ統合していません。

## テスト

Core / Application / APIの通常テスト:

```bash
python -m pytest -q
```

iPad開発UIはPlaywright + Chromiumの受入試験も用意しています。実Serverを子プロセスで起動し、WebUIのHTML/CSS/JavaScriptとAPI/Simulationの実経路を使用します。このチャット実行環境ではChromiumからlocalhostへの直接遷移が管理ポリシーで遮断されるため、受入ハーネス内だけHTTPをPython bindingで中継します。アプリ本体やiPadのLAN接続経路にこのbridgeは入りません。

```bash
pip install -e ".[e2e]"
python -m playwright install chromium
python playwright/acceptance.py
```

受入試験では、少なくとも次を確認します。

- 1180×820および1194×834の通常サイズiPad横持ち相当でA/B両ビューに横overflowが発生しない
- 主要タッチ操作が44 CSS px以上
- 「拠点運用」と「物流ネットワーク」が排他的に切り替わる
- Route選択時にmode/blocker詳細を実APIから取得できる
- blocker表示へ `base.tech.*` 等の内部技術IDが露出しない
- 時間進行CommandでDayとrevisionがともに更新される
- 834×1194の縦持ち相当でも横持ち用3ペイン構造を維持し、横スクロールで表示する
- 縦持ち時に「非対応」画面へ置換しない
- console error / page error / request failureがない

`SPACE_IDLE_CHROMIUM` を設定すれば、受入試験で使用するChromium/Chrome実行ファイルを明示指定できます。

## GitHub開発環境

GitHubリポジトリの`main`をユーザー承認済みの正準ブランチ、`develop`を通常開発・統合・プレイテスト用の常設ブランチとします。`develop`から`main`への統合とバージョン表記変更は、ユーザーの明示的承認後にのみ行います。ローカルセットアップ、CI、Playwright受入試験、iPad用Server起動手順は [`DEVELOPMENT.md`](DEVELOPMENT.md) を参照してください。