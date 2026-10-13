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

通常の契約テストは`tests/`に集約し、`pytest`の既定収集およびFast CIではこの集合を実行する。バランス調整、設備世代間の量的比較、Content戦略実験、開発用依存Graph診断は`evaluation_tests/`に置き、Content・分析機構の変更や調整作業で明示実行する。評価結果から共通の不変条件が判明した場合は、値や攻略順を固定せず、所有するDomain・Application契約のテストへ組み込む。

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

バランス調整は通常pytest/Fast CIの合否判定ではなく、`docs/design.md` §22と`docs/architecture.md` §17.1の全体系評価として行う。入口は`python scripts/analysis_balance.py --research-id <Technology-ID> --research-include-prerequisites --research-horizons 60 180 360 --summary`等で実登録の技術的到達目標を選ぶ。明示的な設備・稼働・立地・輸送構成も合わせる場合は`python scripts/analysis_balance.py <plan.json> --research-id <Technology-ID> --research-include-prerequisites --summary`、複数構成は`--portfolio <plan.json> ...`を用いる。同じ数量台帳から研究・維持・施工・上流・物流の競合を調べ、調整前後を再比較する。入力Planは任意の感度条件であり、固定の施設数・理想日数・攻略順を目標にしない。Planを伴わない研究全体の目録評価は`--research-generations --summary`で行い、全件完了を必要経路としない。旧来の固定Fixtureプランを正準のバランス指標として維持しない。詳細値は同じコマンドの`--summary`なしの出力に含める。

数量評価はGame State/実Allocationではない。`evaluation_tests/`は台帳の保存則、Definition反映、研究前提、未充足・非二重計上等の汎用契約を検証する。機能上の疑義に対する短い実Application実験は別の検証であり、バランスを定める攻略自動化に転用しない。

Browser E2Eは`playwright/run_suite.py <scenario...>`へ対象Scenarioを明示して実行する。各Scenarioは独立したBrowserContext、GameRuntime、保存用一時ディレクトリ、HTTP serverを使用し、状態を共有しない。

## iPad development server

Windowsでは`start_ipad_server.bat`、macOS/Linuxでは`start_ipad_server.sh`を実行し、同じLAN上のiPadからPCのLAN IPv4とport 8765へ接続する。

```text
http://<PC LAN IPv4>:8765/
```

Playwright WebKitは実機iPad Safariと同一ではない。端末固有のSleep、LAN、Firewall、タッチ操作は実機で検証する。
