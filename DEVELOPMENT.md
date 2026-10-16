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

通常の契約テストは`tests/`に集約し、Fast CIで正準契約を検証する。全体系Content調整は本体の開発CLIで任意の通常Saveまたは標準Scenarioから実GameApplicationを操作・観測する。実行入力と出力はJSONで扱い、物理ルールを再計算する独立Worksheetや擬似Game Stateは持たない。調整記録はバランス成立の合否テストではない。

実際の第1・第2段階調整では、既存Saveを始点にGameApplication Query（`GetResearch` / `GetBuildOptions` / `GetDependencyAnalytics` / `GetCargoFlows`等）から取得条件と現在状態を確認し、必要なCommandで研究・設備・Fleet・輸送を変更する。同じ期間に進行したAllocation・実Resource決済・Population・Cargo等を比較し、Contentを調整した後は同じ開始状態から再評価する。段階名は実験記録であってStateの進行ゲートではない。

開発実験の入力例（`/temp/eval.json`）：

```json
{
  "format": "space-idle.development-experiment.v1",
  "steps": [
    {"action": "queries", "queries": {
      "research": {"type": "GetResearch"},
      "projects": {"type": "GetProjects"},
      "logistics": {"type": "GetLogisticsSummary"}
    }},
    {"action": "advance", "days": 2},
    {"action": "state", "scope": {"nodes": ["base.location.earth_industrial"]}},
    {"action": "checkpoint", "name": "after-two-days"}
  ]
}
```

```bash
# 正準初期Scenarioから実行。全Query・期間集計をJSON保存、標準出力は概要のみ
python -m space_idle.dev_cli run --script /temp/eval.json --output /temp/run.json --checkpoint-dir /temp/checkpoints
# 後期産業など、既存の正準ScenarioDefinition生成関数から開始する場合
python -m space_idle.dev_cli run --scenario-factory space_idle.content.base_scenario:build_standard_scenario_definition --script /temp/eval.json --output /temp/scenario-run.json
# 任意の実Saveから再開・別のコマンド列を実行し、Saveと選択的な詳細日次ログを出力
python -m space_idle.dev_cli run --from-save /temp/checkpoints/after-two-days.json --script /temp/next.json --save-out /temp/after.json --output /temp/next-result.json --trace-file /temp/trace.ndjson
# 結果比較（開始Content・State fingerprintの同一性も示す）
python -m space_idle.dev_cli compare --left /temp/run-a.json --right /temp/run-b.json --output /temp/compare.json
```

`steps` は `query`（型名とpayload）、`queries`（同一Snapshotの複数Query）、`command`（正準Command）、`advance`（正準1日tickを指定日数進め期間決済を集計）、`state`（所有Domainの実State指標、Node/Resource scope任意）、`checkpoint`（正準Save）で構成する。Command・Queryの型と引数はWeb APIと同じ。`AdvanceTime` は`advance`操作に統一する。`--trace-file`指定時のみ1日ごとの実決済・AllocationをNDJSON保存し、通常は日次ログを保持せず期間の厳密な実績集計とState観測結果を保存する。調整対象の細目へは各Queryや観測scopeで絞り、未観測の因果関係は未知とする。Command失敗時はそのStepと日付を報告し、後続Stepを実行せず、失敗した実験の最終Saveは自動出力しない。

Saveの初期状態識別子が一致しても、違うCommand・Content・期間の結果を公平な攻略順ランキングとして扱わない。実験開始時点の開発配置資産は無償取得した実験条件であり、その前史の取得費用・時間を証明しない。必要なときは配置前Saveから通常Commandで取得・経過を観測する。

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

通常publishのtransportデータは固定32 KiB分割を使わず、単一GitHub tool callの検証済み上限1 MiBに収まる最大の連続部分を各ファイルに保持する。上限を超えるpayloadは複数ファイルとし、GatewayがBase64順次連結で復元する。

通常publishのConnector入力は、ローカルrepoの`.git/space-idle-publish-transaction/`に保持する。`connector-plan`が出力した`execution_index`を固定Launcherへ渡すと、Launcherが共有`develop`上のExecutorを呼び出す。`execution_index`の親ディレクトリ名はpacket件数を、ファイル名はtransaction IDを示し、Executorは原本indexと全packetのパスを登録前に確定できる。ChatGPT Libraryの`/temp/`作成と原本入力の一括登録を同じ操作へ統合し、登録結果のIDで直接読取・原本照合する。登録直後に参照が一時的に不可視の場合だけ、対象transactionのファイルを限定してLibrary参照を再取得し、有限回数の自動再読取を行う。不完全・変造された入力は再試行で通過させず、原本照合に失敗した場合もGitHubへ書き込まない。検証済み入力は削除の成功応答を確認してからGitHubへ書き込む。Library上の削除はゴミ箱への移動である。

通常の成功経路でLibrary一覧や削除後の全件再列挙は行わない。再試行時の既存登録は同じtransactionの決定論的なパスだけ上書きし、登録・読取・削除の応答が失敗または不確定となった場合は、transactionに限定した一覧・回収を行い、回収を確認できなければGitHubへ書き込まない。無関係なLibraryファイルや別transactionのファイルを操作しない。

Executorの登録・読取・削除が完了した後、GitHub transportのtreeを生成する。1実行での`GitHub.create_tree`は最大10回とし、それを超える計画はhelperが事前に検証した複数の実行indexへ分割する。途中区間はGitHubに確定したtree SHAと次区間の`next_execution_index`のみ返し、commitと`publish` ref更新は最終区間で一度だけ実行する。ChatGPTは各区間で同一の固定Launcherを繰り返すだけとし、tree SHAの転記・packet選択・分割手順の作成をしない。Library操作は10回制限に含めず、各区間で原本検証と一時ファイル回収を済ませてからGitHubへ書き込む。中断時は同じ区間のindexから安全に再開する。通常publishの実行者が扱う入力は`execution_index`と固定Launcherのsourceであり、payload規模にかかわらず同じ手順を使う。

### 通常publishの手順

1. 責務単位の関連検証を完了し、ローカル`develop`にcommitする。
2. `python scripts/publish_request.py prepare`でpublish requestを作成する。
3. publish直前にGitHubのheads一覧を1回取得し、観測した`develop`と`publish`のHEADを`connector-plan`に指定する。
4. 返された`execution_index`の絶対パスを`INDEX_PATH`に指定し、`scripts/publish_connector_launch.js`の固定sourceをそのまま`functions.exec`で実行する。結果が`stage: continue`なら返却された`next_execution_index`を次の`INDEX_PATH`として、同じ固定Launcherを実行する。`stage: transport-ref-updated`が返るまで機械的に繰り返す（分割計画・SHAの手動操作は不要）。
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

`functions.exec`では先頭に`const INDEX_PATH = '<execution_index>';`を定義し、その後に`scripts/publish_connector_launch.js`の内容を続けて実行する。区間継続でも`INDEX_PATH`以外は変更しない。Launcherのsourceはローカルrepoから取得し、ExecutorのsourceはLauncherが共有`develop`から取得する。既存の長大なtransactionを新方式へ移行する場合に限り、`python scripts/publish_request.py connector-segments`で保存済み計画から実行indexを生成する。`prepare`やcommitを作り直さない。

### 中断・失敗時の再開

| 到達状態 | 続行手順 |
|---|---|
| `publish` ref更新前 | 未完了区間の`execution_index`で固定Launcherを再実行する。`continue`を受け取った区間のtreeはGitHubに保持されるため、次のindexから続ける。未完了区間の再実行も決定論的なtree作成のみであり、commit・ref更新は最終区間まで行わない。 |
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

全体系バランス調整は通常pytest/Fast CIの合否判定ではなく、`docs/design.md` §22と`docs/architecture.md` §17.1に基づくContent設計作業とする。分析者は地球中心の初期Scenario、登録技術体系と設備・Vehicle・工程・Worldの物理条件を調べ、初期・研究段階後・複数天体進出・中期物流ネットワーク等の**発展構成を調整仮説として**検討する。Facility・Fleet台数、World値、研究日数、初期配置、世代区分はすべて調整候補であり、特定の配置・攻略順・数値を正解として固定しない。発展に必要な研究、製造、投資、輸送、運転と維持の負担を辿り、工学的役割と量的拡張のつながりを吟味した上でContentの追加・統廃合・数量調整を行う。

開発CLIの各Queryは登録Content、必要Recipe、Technology、Research typed Stage、建設・製造の取得負担、拠点条件、運用状態とblockerを通常GameApplicationと同じ契約で取得する。実験ログのInventory決済・Owner移管・活動消費は区別し、期間集計は正準Settlementからのみ作る。日次実行の時間コストが問題になった場合は、必要なscope・期間を絞り、恒久的な別物理計算ではなく正準Simulationの効率化を検討する。登録値自体が不足しているときはContent設計・登録を行う。

Browser E2Eは`playwright/run_suite.py <scenario...>`へ対象Scenarioを明示して実行する。各Scenarioは独立したBrowserContext、GameRuntime、保存用一時ディレクトリ、HTTP serverを使用し、状態を共有しない。

## iPad development server

Windowsでは`start_ipad_server.bat`、macOS/Linuxでは`start_ipad_server.sh`を実行し、同じLAN上のiPadからPCのLAN IPv4とport 8765へ接続する。

```text
http://<PC LAN IPv4>:8765/
```

Playwright WebKitは実機iPad Safariと同一ではない。端末固有のSleep、LAN、Firewall、タッチ操作は実機で検証する。
