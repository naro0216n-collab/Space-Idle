# Development

## 作業の前提

- `develop`：通常開発の共有正本。検証済みの責務単位をpublishする。
- `main`：ユーザーが承認した成果を統合する正準branch。
- `publish`：Publish Gatewayがtransportを受け取るcontrol branch。
- `temp`：ユーザー指定またはworkflow・publish経路の隔離検証に用いるbranch。

実装・検索・テスト・commitは、通常、単一のローカルrepoの`develop`で行う。成立したlocal commitを保持したまま、責務単位のcheckpointを`develop`へpublishする。ゲーム本体versionの更新と`develop`から`main`への統合は、ユーザー承認後に実施する。

作業開始時に`docs/README.md`、`docs/development-principles.md`、変更に関係する`docs/design.md`、`docs/architecture.md`を読む。UI変更には`docs/ui.md`も参照する。仕様判断では現行コード・既存テスト・fixture・暫定Contentより正準文書を優先する。

## ローカル作業環境

### 最新の`develop`を復元する

最新`develop`の**成功したFast CI**から`source-snapshot` artifactを取得する。artifact内の`repository.bundle`を使い、次のようにローカルrepoを復元する。

```bash
unzip source-snapshot.zip -d source-artifact
branch="$(cat source-artifact/.source-branch)"
git clone -b "$branch" source-artifact/repository.bundle space-idle-local
cd space-idle-local
python scripts/publish_request.py init
```

`init`がartifactの基点を記録し、repo-local Git identityとpublish基点を設定する。復元が失敗した場合は、`source-snapshot`の生成・取得経路を修復し、同じ復元手順を再実行する。最新のローカル環境が構築済みなら継続利用する。

### 依存関係を導入する

必要環境：Python 3.11以上、pytest。ブラウザ検証にはPlaywright 1.57以上と対象browserを使用する。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -U pip pytest
python -m pip install -e .
```

Browser E2Eが必要な場合：

```bash
python -m pip install -e '.[e2e]'
python -m playwright install chromium
```

### 実装・ローカル検証

DomainからApplication、Persistence、Content、UIまで、変更した責務に必要な層を接続して検証する。テストの選定・改廃は`docs/development-principles.md` §6に従い、現在の不変条件・状態遷移・保存則を優先する。検証とpublishは、整合した責務のcheckpointを単位とする。

```bash
git diff --check
python scripts/local_test_run.py start -- -q --durations=20
python scripts/local_test_run.py status <startで返されたrun_id>
```

ローカルpytestは`scripts/local_test_run.py`の`start`で起動し、返されたrun IDを`status`へ渡してpytestの終了コードと判定結果を確認する。対象を絞る場合は`start --`以降へpytestのtargetを指定する。実行ツールのtimeout後も、`status`でテスト結果を確認する。

通常の契約テストは`tests/`に集約し、`pytest`の既定収集およびFast CIではこの集合を実行する。バランス調整の数量台帳・研究期間・Definition依存Graphの固有契約を`evaluation_tests/`に置き、Content・分析機構の変更や調整作業で明示実行する。評価結果から共通の不変条件が判明した場合は、値や攻略順を固定せず、所有するDomain・Application契約のテストへ組み込む。

```bash
python scripts/local_test_run.py start -- evaluation_tests -q
python scripts/local_test_run.py status <startで返されたrun_id>
```

Publish Gateway、helper、CI/E2E harnessの変更は`development_tests/`で検証する。ブラウザ受入Scenarioは`playwright/`に置く。実ブラウザ、clean install、OS差等の検証はGitHub CIで実施する。

### 作業ファイルと成果物

実装中の試行用スクリプト、単発のGameplay検証、分析用JSON、patch、ログ、実行途中の出力は、ローカル作業環境の一時領域で作成・実行・整理する。検証を継続的に使う場合は、正準契約に基づくテストとしてrepoに組み込み、関連検証とcommitへ進める。必要な検証結果は報告本文、commit済みファイル、またはGitHub CI artifactとして残す。

ChatGPT Libraryには、ユーザーが保存・再利用する完成成果物を登録する。Projectに紐づくファイルはProjectの資料管理として扱う。ローカル作業の一時出力を共有する必要がある場合は、用途を終えた時点で利用可能な管理経路から回収する。既存の残存ファイルが報告された際は、保存目的と登録先を確認し、通常LibraryのファイルはそのLibrary IDを指定して削除し、Project所属のファイルはProject側の管理機能で整理する。Libraryの削除操作はゴミ箱への移動として扱う。

通常publishに必要な例外的なLibrary中継は、以下の固定LauncherとExecutorに一元化する。

## `develop`へのpublish

### 使用する経路

| 変更内容 | 標準helper | 反映先 |
|---|---|---|
| 通常のゲーム・開発基盤変更 | `scripts/publish_request.py` | Publish Gateway経由で`develop` |
| `.github/workflows/**`だけの変更 | `scripts/workflow_maintenance.py` | `develop` |
| Publish Gateway control planeの変更 | `scripts/publish_control_maintenance.py` | `publish` |

Publish Gateway workflowを変更する際は、Publish control maintenanceによるcontrol plane更新を先に完了する。その他のworkflow変更と通常変更は責務単位でcommitを分け、表に示したhelperを使用する。各helperが出力したpacketは、その順序で適用する。

### Connectorの一時ファイル管理

通常publishのConnector入力は、ローカルrepoの`.git/space-idle-publish-transaction/`に保持する。`connector-plan`が出力した`execution_index`を固定Launcherへ渡すと、Launcherが共有`develop`上のExecutorを呼び出す。`execution_index`の親ディレクトリ名はpacket件数を、ファイル名はtransaction IDを示し、Executorは原本indexと全packetのパスを登録前に確定できる。ChatGPT Libraryの`/temp/`作成と原本入力の一括登録を同じ操作へ統合し、登録結果のIDで直接読取・原本照合する。検証済み入力は削除の成功応答を確認してからGitHubへ書き込む。Library上の削除はゴミ箱への移動である。

通常の成功経路でLibrary一覧や削除後の全件再列挙は行わない。再試行時の既存登録は同じtransactionの決定論的なパスだけ上書きし、登録・読取・削除の応答が失敗または不確定となった場合は、transactionに限定した一覧・回収を行い、回収を確認できなければGitHubへ書き込まない。無関係なLibraryファイルや別transactionのファイルを操作しない。

Executorの登録・読取・削除が完了した後、同じ実行の中でGitHub transportのtree生成、commit作成、`publish` ref更新を行う。中断または一時ファイル操作の失敗時は、保存済みtransactionを使用して「中断・失敗時の再開」から続ける。通常publishの実行者が扱う入力は`execution_index`と固定Launcherのsourceであり、packet数やpayload規模にかかわらず同じ手順を使う。

### 通常publishの手順

1. 責務単位の関連検証を完了し、ローカル`develop`にcommitする。
2. `python scripts/publish_request.py prepare`でpublish requestを作成する。
3. publish直前にGitHubのheads一覧を1回取得し、観測した`develop`と`publish`のHEADを`connector-plan`に指定する。
4. 返された`execution_index`の絶対パスを`INDEX_PATH`に指定し、`scripts/publish_connector_launch.js`の固定sourceをそのまま1回の`functions.exec`で実行する。Launcher／ExecutorがLibrary中継とGitHub transportを完了する。
5. 返却されたtransport commitに対応するPublish Gateway runが`completed / success`になったことを確認し、transport commit SHA、run ID、結論を`record`へ渡す。runの完了までtransactionを保持し、その間は独立したローカル作業を進めてよい。
6. 次のpublishを始める際に直前Fast CIの結果を確認する。Fast CIが失敗していれば原因を修正したcheckpointで次のpublishへ進む。

```bash
python scripts/publish_request.py prepare
python scripts/publish_request.py connector-plan \
  --develop-head <current-develop-head> \
  --publish-head <current-publish-head>
# execution_indexの絶対パスをINDEX_PATHへ指定して固定Launcherをfunctions.execで実行
python scripts/publish_request.py record \
  --gateway-transport-commit <transport-commit> \
  --gateway-run-id <gateway-run-id> \
  --gateway-conclusion success
```

`functions.exec`では先頭に`const INDEX_PATH = '<execution_index>';`を定義し、その後に`scripts/publish_connector_launch.js`の内容を続けて実行する。Launcherのsourceはローカルrepoから取得し、ExecutorのsourceはLauncherが共有`develop`から取得する。

### 中断・失敗時の再開

| 到達状態 | 続行手順 |
|---|---|
| `publish` ref更新前 | 保存済みtransactionの`execution_index`で固定Launcherを再実行する。入力や回収処理の問題は原因を解消したうえで同じtransactionから続ける。 |
| `publish` ref更新済み | 該当transport commitのPublish Gateway runを確認する。成功時は`record`し、Gateway側の一時的な障害は同じrunの再実行で扱う。 |
| `record`済み | ローカル開発を続行する。次のpublish判断時に前回Fast CIの結果を確認する。 |

ref更新前のtransactionを取り消す際は、最新の`develop`と`publish`のHEADを取得して`cancel`へ渡す。helperが取消条件を満たさないと判定した場合は、その状態を維持し、標準recoveryの適用条件を解消する。

```bash
python scripts/publish_request.py cancel \
  --develop-head <current-develop-head> \
  --publish-head <current-publish-head>
```

### Workflow maintenance

`.github/workflows/**`だけの変更に使用する。

1. 変更をcommitし`prepare`する。取得したremote`develop` HEADで`connector-plan`を生成する。
2. helperの`create_tree` packetを順に実行し、指示された期待tree照合、`create_commit`、non-forceの`develop` ref更新を行う。
3. 更新commit SHAを`record-update`へ渡す。完了後は最新Fast CIの`source-snapshot`でローカルrepoを復元し、`publish_request.py init`する。

```bash
python scripts/workflow_maintenance.py prepare
python scripts/workflow_maintenance.py connector-plan \
  --develop-head <current-develop-head>
# helperが生成したGitHub操作を出力順に実行
python scripts/workflow_maintenance.py record-update \
  --commit-sha <create-commit-result-sha> \
  --result success
```

### Publish control maintenance

Publish Gateway control planeの変更に使用する。

1. 変更をcommitし`prepare`する。取得したremote`publish` HEADで`connector-plan`を生成する。
2. helperの`create_tree` packetを順に実行し、指示された期待tree照合、`create_commit`、non-forceの`publish` ref更新を行う。
3. 更新commit SHAを`record-update`へ渡す。

```bash
python scripts/publish_control_maintenance.py prepare
python scripts/publish_control_maintenance.py connector-plan \
  --publish-head <current-publish-head>
# helperが生成したGitHub操作を出力順に実行
python scripts/publish_control_maintenance.py record-update \
  --commit-sha <create-commit-result-sha> \
  --result success
```

Maintenanceのpacket実行・照合に失敗した場合は、同じtransactionの手順から再実行する。ref競合やGateway検証失敗の原因を解消してから、次の更新へ進む。

## CI

- **Fast CI**：`develop`へのpublish後、Unit / architecture、clean package install、Chromium direct HTTP smoke、次回復元用`source-snapshot`を検証する。run結果は次のpublish判断に必要な時点で確認する。
- **Full Validation**：`main`反映候補、ユーザー要求、Persistence schema変更、Simulation Orchestrator処理順変更、package / server / launcher変更、Fast CIの範囲外となるOS・ブラウザ検証に使用する。Gameplay、Windows、WebKitは該当変更の検証時に実行する。

バランス調整は通常pytest/Fast CIの合否判定ではなく、`docs/design.md` §22と`docs/architecture.md` §17.1の全体系評価として行う。公開入口は`python scripts/analysis_balance.py`。登録Technologyの要求と設備構成はPlanのPhaseを通して同一数量台帳で評価する。表示世代全体の費用集計や研究専用の並行評価モードは提供しない。経済Planの各Phaseに`research_goal: {"node": "<Node>", "research_ids": ["<Technology-ID>"], "include_prerequisites": true}`を指定すると、前提DAGと登録StageのRP・Research execution・Resource要求をそのPhaseの施設・輸送・維持・投資と共通台帳で比較できる。Phaseへ投入されたStageは完了・解放済みとは見なさず、期間中の並行配分やResearch Site成立は別の条件として表示される。研究以外の活動は同じPlanにProcess、Extraction、施設増設、Vehicle製造・運用、研究Provider、Movement等を指定する。Facilityを増設する場合は、投資期の`facility_investments: [{"node": "<Node>", "facility": "<Facility-ID>", "units": 1}]`で投資Resource・construction workを計上する。以降の任意のPhaseの`facilities`へ完成済みと仮定する設備を**明示して**初めて、そのPhaseの稼働能力を条件付き計上する。初期既設Facilityは`initial_facilities`に指定し、各Phaseの保有数量は初期保有数と過去の投資数量を超えられないが、投資全数が翌Phaseに完成したと仮定する必要はない。Vehicleは`vehicle_builds: [{"node": "<Node>", "vehicle": "<Vehicle-ID>", "units": 1}]`で製造期の資材・Serviceを計上し、別Phaseの明示的な`fleet`保有構成でのみ完成後のFleet能力を条件付き計上する。製造注文そのものからFleet数量を自動増加させない。Fleetの保有数量は初期保有と先行した製造注文の数量以内とする。FacilityのLevel比較では`initial_facilities`と各Phaseの`facilities`に必要時だけ`"level": 2`等を明示する。初期保有は既存Levelという仮定であり、後続Phaseで選択した上位Level数は、そのLevelに達した初期保有数と、以前のPhaseで`upgrade_projects`として計上した登録Upgradeの数量を超えられない。Upgradeは当該PhaseでResourceとConstruction workを消費するが、同PhaseのProvider性能や採掘能力は増えない。後続PhaseでLevelを明示したときだけResearch ProviderのRP生成・実行・貯蔵能力と累積投資に応じたMaintenanceを評価する。設備・Vehicleの取得可否や完了時期は数量評価では確定しない。上流Processは対応可能な`facilities`行の`process`と`duty`として明示し、登録Processの投入・産出、取得済みと仮定した設備の共通稼働能力・Power・維持・Resource負担を同じNode別数量台帳で評価する。未選択の設備・Processや供給元は自動取得・生成しない。通常は選択された制約と数量の判断概要を表示する。`--details`を指定した場合だけ同じProjectionの詳細と出典を表示する。

初期構成を登録Scenarioから参照する場合、Planに`"movement_reference": "applied_scenario", "opening_from_reference": true`を指定する。この場合は同じ独立Compositionへ適用済みのScenarioからInventory Stock、施設保有数・Level、Fleet保有数、Research Point残高、取得済みTechnologyを一度読み、分析期間の開始条件とする。研究目標の前提DAGは取得済みTechnologyを再要求せず、Survey進捗は各活動の`starting_progress`を省略したときだけSurvey Domainの既存進捗を参照する。Researchを含む別の初期条件は`initial_completed_technologies`で明示でき、通常のcase比較で変数として扱う。`extraction_sites`で選択した開発Cellについても、`opening_from_reference`時にはSurvey DomainのResource別Knowledgeを参照し、明示した`knowledge`行だけ分析者の条件として上書きする。いずれもCell開発や資材着荷を成立させない。`initial_stock`等の手書き初期値と併用せず、異なる初期案ではそれぞれ明示したPlanを比較する。Scenarioに存在する施設・Fleetを全稼働させるわけではなく、Phaseに選択した活動と割当だけを数量台帳へ計上する。初期Scenarioで他用途に拘束中のFleetは`opening_fleet_precommitments`に保有量・free量を示し、各Phaseの`fleet_availability_constraints`で選択した新規用途の必要数量、既存拘束を除いた利用可能数量、再配分が必要な数量を対照する。既存拘束の自動解放・実際の再配分は行わず、不足があれば条件付きのまま残す。これはday-0 Runtimeの読取であってGame Stateを更新しない。独立Applicationを渡した評価では、同様に適用済みScenarioのDomain-owned openingを参照できる。

Worldの物理条件も調整対象とする。`world_context_sweep`に`plan`と`contexts: "all"`を指定すると、登録済みのSurface Cellと周回等の非Surface World Contextの双方を同じ活動構成で個別評価する。Surface専用活動を使う場合は`contexts: "all_surface"`または明示したContext ID配列を指定する。Plan内の`$world_context`参照だけを置換し、実登録Domainの立地条件を尊重する。未設立のCellや周回ContextへInventory、Operational Node、輸送経路を自動生成しない。`reference_context`に選択済みContext IDを明示すると、他Contextで同じPlanを評価した差を通常の共通数量比較から示す。基準地点の自動選定、順位付け、異なるNode間の資材相殺は行わない。

`--content-variant`と`--content-impact`は通常Definitionと同じ独立CompositionでWorld側の調整案も比較する。例えば`[{"kind":"world_cell","id":"<Surface Cell ID>","field":"resource_potential","resource_id":"<Resource ID>","value":12.5}]`はそのCellのResource Potential変更、`world_cell`の`geology_accessibility`／地形／面積／座標は物理立地の変更、`world_environment`の`facet`／`field`は登録された環境係数の変更、`world_body`・`world_node`・`world_system`は登録天体・周回Context・恒星系の輸送幾何等の変更を表す。これらをFacility、Provider、Process、Vehicle等の変更と一つの仮説へ組み合わせられる。World IDや現行値を正準目標として固定せず、変更前後は独立に通常Validationを通す。数値の差は条件付きの物量・能力・制約変化であり、設立・輸送・研究の実成立やContent案の採否ではない。

比較ケースの条件は特定の研究・拠点・設備・Fleetに固定しない。`base_plan`を持つ`cases`の`updates`では、`{"collection":"initial_stock","match":{"node":"<Node>","resource":"<Resource>"},"set":{"amount_t":10}}`のように既存行を明示して編集する。任意のPlan／Phaseの活動行は`collection`・必要時の`phase`・既存フィールドの`match`・`set`で一意に選択し、`action:"add"`と`row`で活動を追加、`action:"remove"`で選択活動を外せる。`research_goal`はPhaseの`set`で研究DAG選択を変更する。`phase`の`set`では`days`、`reference_day`、`assumed_funds_musd`を変更可能とする。`initial_research_points`と`start_day`はPlan全体の`value`で、`solar_yield`はNodeを`match`して変更・追加・削除できる。追加行も通常のPlan検証に従い、取得済み設備・実物流・技術取得を自動生成しない。Worldの参照時刻はPlanの`start_day`（省略時0）からPhaseの日数だけ進み、Phaseの`reference_day`および`solar_sites`・採掘・Transport活動の明示`day`があればその参照条件を使用する。これはWorldの定点参照であり、期間中のWorld変動や実完了日時をシミュレートしない。異なる参照時刻は比較結果の条件差として表示する。

Content数値変更は`{"kind":"facility","id":"<ID>","field":"<registered numeric field>","value":2.0}`等の登録済みDomain Definition上の数値を編集する。実Dataclassの入れ子数値フィールドは点区切りで指定でき、`{"kind":"research_provider","id":"<ID>","field":"levels.generation_points_per_day","selector":{"level":2},"value":50.0}`のように登録済みのtuple項目は実フィールドで一意に選択する。研究Stage、FacilityのService、Vehicleの製造・性能、Transport Movement Rule、電力、採掘・探査・Provider等は同じDefinition更新とComposition validationを経由する。Resource別のRecipe数量や前提Technologyなど、数値Scalarでない項目は対応する型付き編集を用いる。未登録ID・不正型・異なるStateの暗黙採用は認めない。入力値、登録Content、World係数、Scenario参照、条件付き計算結果を混同せず、いずれも現在の値を調整目標や理想値として固定しない。

設備・稼働・立地・輸送・時間の代替構成は、同じPlan条件を持つ`cases`で比較する。登録Definition変更の仮説を比較する場合は`--content-variant <changes.json> --content-impact`を指定し、同じ初期条件・活動・期間で変更前後の独立Compositionを比較する。変更仮説、Player判断、結果の副作用、採否と未判定条件は比較結果を根拠に分析者が判断・記録する。CLIは記録した文章をそのまま転記する機構を持たない。最適攻略順、世代の理想研究日数、必須施設数を設けない。`--content-variant`のみを指定すると変更後条件の単独評価となる。Planとcaseの概要は同じ数量Projectionから導出する。新しいTechnology／Process／Assetが変更前に存在しない場合は、共有の発展目標と共通初期条件を伴う`{"development_goal": "...", "baseline_plan": {...}, "edited_plan": {...}}`を入力し、変更前／後に実際に選ぶ別の活動構成を明示する。存在しない活動は0費用とみなさず、両者の成果の同一性を保証しない。Research ProviderのRP生成・Pool容量・実行性能は登録Provider IDとLevelを指定して変更比較する。

輸送容量・往復Cycle・片道Latencyの比較で標準Scenarioの初期Networkを根拠とする場合、Planのトップレベルへ`"movement_reference": "applied_scenario"`を指定する。未指定の`definitions_only`は初期Movement Stateを構築しないため、登録Definitionだけでは未成立となる経路に容量を与えない。前者は独立した初期ScenarioのTransport Domain previewを参照するだけで、実Cargoを着荷させず、Player操作・時刻進行・初期Stockの暗黙採用も行わない。Case比較・Content変更前後のMovement参照基準は共通にし、実際の別拠点への着荷や将来のInfrastructure獲得は条件付きのまま扱う。

数量評価はGame State/実Allocationではない。`evaluation_tests/`は台帳の保存則、Definition反映、研究前提、未充足・非二重計上等の汎用契約を検証する。機能上の疑義は所有DomainやApplicationの通常契約テストで短く検証する。Game Commandを自動投入する独立ReplayやPareto比較をバランス評価の別経路として保持しない。

Browser E2Eは`playwright/run_suite.py <scenario...>`へ対象Scenarioを明示して実行する。各Scenarioは独立したBrowserContext、GameRuntime、保存用一時ディレクトリ、HTTP serverを使用し、状態を共有しない。

## iPad development server

Windowsでは`start_ipad_server.bat`、macOS/Linuxでは`start_ipad_server.sh`を実行し、同じLAN上のiPadからPCのLAN IPv4とport 8765へ接続する。

```text
http://<PC LAN IPv4>:8765/
```

Playwright WebKitは実機iPad Safariと同一ではない。端末固有のSleep、LAN、Firewall、タッチ操作は実機で検証する。
