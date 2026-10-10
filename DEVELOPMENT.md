# Development

GitHub の `main` をユーザー承認済みの正準ブランチ、`develop` を通常開発中の共有正本とする。実装・検索・リファクタリング・高速検証はローカルrepoで行い、GitHubは共有正本へのpublishと実環境検証に使う。

## Requirements

- Python 3.11+
- pytest
- WebUI受入試験を実行する場合: Playwright 1.57+ / Chromium または WebKit

## Canonical documents

作業開始時に `docs/README.md`、`docs/development-principles.md`、変更に関係する `docs/design.md` と `docs/architecture.md` を読む。現行コード、fixture、既存テスト、暫定Contentは正準仕様ではない。

## Start from develop artifact

通常作業は最新 `develop` の Fast CI が生成した `source-snapshot` artifactから開始する。artifactには次を含める。

- `repository.bundle`: 対象branchの到達可能なGit履歴と対象ref
- `.source-commit`: artifact対象commit
- `.source-tree`: 対象commitのtree
- `.source-branch`: 対象branch
- `.source-publish-commit`: artifact生成時点の `publish` HEAD
- `.source-publish-tree`: その `publish` HEADのtree

`repository.bundle` は対象 `develop` refに加えて `refs/space-idle/publish-base` を含み、通常publishのtransport treeを追加GitHub readなしでローカル再構築できるようにする。

復元例:

```bash
unzip source-snapshot.zip -d source-artifact
branch="$(cat source-artifact/.source-branch)"
git clone -b "$branch" source-artifact/repository.bundle space-idle-local
cd space-idle-local
python scripts/publish_request.py init
```

`init` は復元repoの `origin` が指す `repository.bundle` からsource-snapshot directoryを一意に解決し、通常の `git clone` ではmaterializeされない `refs/space-idle/publish-base` もそのlocal bundleから復元する。source pathはCLIから指定しない。artifactのcommit/treeを復元できない場合は別方式へ読み替えず、artifact生成または取得経路の問題として扱う。

## Local setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -U pip pytest
python -m pip install -e .
```

E2Eを実行する場合:

```bash
python -m pip install -e '.[e2e]'
python -m playwright install chromium
```

## Local development

通常作業はローカル `develop` 作業コピー上で連続して行う。追加branchやworktreeを通常工程には使わない。

変更はテストファイル単位ではなく、DomainからApplication・Persistence・UI等まで責務が一貫する単位で実装し、ローカルcommitする。CI完了を次のローカル作業開始条件にしない。

### Test maintenance

検証対象は `docs/design.md` / `docs/architecture.md` の現在の契約から選ぶ。テストsuiteは実装履歴の保存場所ではなく、現在の正準仕様を効率よく検証する構成として維持する。詳細な選定・統廃合基準は `docs/development-principles.md` §6 を正本とする。

変更時は、関連する既存テストについても契約を再評価する。新しい実装に合わせて期待値だけを書き換えるのではなく、現在の契約を表すなら更新し、上位の不変条件へ統合できるなら統合し、旧仕様・暫定Content・private実装・過去の移行状態だけを固定するなら削除する。

バグ修正や旧経路撤去のたびに恒久テストを1件ずつ追加する運用にはしない。旧symbolや旧APIの不存在確認が必要な場合は移行完了確認として扱い、長期的に守る内容があるならState ownership、Domain境界、保存則等の現行契約へ検証を置き換える。

新規テストを追加する前に、同じ契約を既存テストが覆っていないか確認する。同じruleをDomain、integration、gameplayの各層で重複して検証せず、それぞれのlayer固有の契約だけを持たせる。

### Local validation

高速に再現できるDomain invariant、architecture、integration等の検証はローカルで行う。変更checkpointでは、変更した責務に直接関係する検証をまず実行し、State ownership、Resource保存、Save / Load、Offline、Application契約等への影響に応じて範囲を広げる。

テストファイル名や現在のsuite分割を開発手順の恒久契約にはしない。必要なtest targetは変更内容と現在のtest構成から選択する。コード・文書差分の基本確認には少なくとも次を利用できる。

```bash
git diff --check
```

ローカルpytestの実行入口は、短い外部コマンド呼出し期限の有無にかかわらず `scripts/local_test_run.py` に統一する。引数はpytestのオプション・テスト対象のみを受け付ける。テストプロセスのログ・実際の終了コード・最終状態を `.git/local-test-runs/` に保存する。`start` や呼出しツールのタイムアウトは検証結果ではない。`running`、`interrupted` は未判定、`error` はテスト実行基盤のエラーとし、pytestが実際に終了した場合だけ `passed` / `failed` と `result.exit_code` を記録する。実行結果は `status` にrun IDを指定して再取得する。CIのジョブtimeout・終了結果はGitHub Actionsが別途管理するため、CI内の直接pytest実行は維持する。

```bash
python scripts/local_test_run.py start -- -q --durations=20
python scripts/local_test_run.py status <startで返されたrun_id>
```

実ブラウザ、clean install、OS差などローカル環境で十分再現できない検証は、対応するテストも変更単位に含めてGitHub CIで実行する。ローカルで実行できないことを理由に、正準契約上必要な検証自体を省略しない。

Publish Gateway、publish helper、CI/E2E harnessなど開発環境そのものの契約テストは `development_tests/` に物理分離し、ゲーム本体の `tests/` と通常suiteには含めない。開発基盤を変更した場合は `scripts/local_test_run.py start -- -q development_tests` を基準とし、変更責務が明確に限定される場合は現在のsuite構成から関連targetだけを選んでよい。特定test file名を開発手順上の恒久契約にはしない。実ブラウザの受入シナリオは `playwright/` に置き、この開発基盤テストとも分離する。

## Publish procedure

GitHub反映は変更内容に応じて次のhelperを使用する。`publish` branchはPublish Gatewayのtransport専用とする。

- 通常のゲーム・開発基盤変更：`scripts/publish_request.py`
- `.github/workflows/**` だけの変更：`scripts/workflow_maintenance.py`
- Publish Gateway control planeの変更：`scripts/publish_control_maintenance.py`

`.github/workflows/publish-gateway.yml` を通常publishに含める場合は、Publish control maintenanceで固定`publish`側を先に更新する。それ以外のworkflow変更と通常変更は、責務ごとにcommitを分けて通常変更から反映する。

### Normal develop publish

1. ローカルで責務単位の変更を検証し、commitする。
2. `prepare`を実行する。GitHubのheads一覧から`develop`と`publish`のHEADを同時に取得し、`connector-plan`へ渡す。
3. 出力された`execution_index`のパスを`INDEX_PATH`に指定し、固定`scripts/publish_connector_launch.js`を1回の`functions.exec`で実行する。Launcherは共有`develop`の`scripts/publish_connector_executor.js`を取得する。
4. Executorは原本packetを一時Libraryへ登録・取得し、内容とtransactionの整合性を自動検証する。全登録の削除確認後、packet順に`create_tree`、期待SHA照合、`create_commit`、non-forceの`publish` `update_ref`を実行する。ファイル数・transaction規模にかかわらず同じ入口を使用する。Libraryでの削除はゴミ箱移動である。
5. 該当transport commitのPublish Gatewayが`completed / success`になったら、返却されたtransport SHA・run ID・conclusionを`record`へ渡す。run未完了の間はtransactionを保持し、ほかのローカル開発を進めてよい。
6. 次のpublishの前に直前Fast CIの結果を確認する。失敗した場合は原因に応じた修正を先に行う。

```bash
python scripts/publish_request.py prepare
python scripts/publish_request.py connector-plan \
  --develop-head <current-develop-head> \
  --publish-head <current-publish-head>
# connector-plan が返した execution_index を INDEX_PATH に指定し、
# scripts/publish_connector_launch.js を functions.exec で実行する。
python scripts/publish_request.py record \
  --gateway-transport-commit <transport-commit> \
  --gateway-run-id <gateway-run-id> \
  --gateway-conclusion success
```

`connector-plan`はsource-snapshot由来の`publish` base treeとローカルcommitから正規packetを構築する。transportは`.publish/transport/<target>/`の連番固定slotを使用し、各`create_tree` callはConnectorの入力上限内に収める。packet内容・入力整合性・期待treeはhelperとExecutorが検証する。Gatewayはbundle内のexact commitを正規のnon-force経路で`develop`へ反映し、Fast CIを起動する。

### Transaction continuation

- **ref更新前**：保持されているtransactionの`execution_index`から固定Launcherを実行する。原本packetの検証・期待tree照合が成立しない場合は、そのtransactionを保持して原因を解決する。
- **ref更新後**：transport commitに紐づくGateway結果を取得し、成功なら`record`する。一時的なGateway障害には同じrunの再実行を使う。
- **record済み**：次のpublishに進める。直前Fast CIの結果は次のpublish判断時に確認する。

ref更新前のtransactionを取り消す場合は、現在の`develop` / `publish` HEADを取得し、helperの`cancel`へ渡す。helperが両HEADとtransactionの一致を検証する。

```bash
python scripts/publish_request.py cancel \
  --develop-head <current-develop-head> \
  --publish-head <current-publish-head>
```

### Workflow maintenance procedure

`.github/workflows/**`だけを変更したcommitは`scripts/workflow_maintenance.py`で`develop`へ反映する。

1. `prepare`し、取得したremote`develop` HEADを`connector-plan`へ渡す。
2. helper生成の`create_tree` packetを順番に実行して期待tree SHAを照合し、最終`create_commit`の返却SHAで`develop`をnon-force更新する。
3. 更新に用いたcommit SHAを`record-update`へ渡す。成功後は最新Fast CIの`source-snapshot`からローカルrepoを復元し、`publish_request.py init`する。

```bash
python scripts/workflow_maintenance.py prepare
python scripts/workflow_maintenance.py connector-plan \
  --develop-head <current-develop-head>
python scripts/workflow_maintenance.py record-update \
  --commit-sha <create-commit-result-sha> \
  --result success
```

### Publish control maintenance procedure

Publish Gatewayのcontrol planeは`scripts/publish_control_maintenance.py`で固定`publish`へ反映する。

1. control plane変更をcommitして`prepare`し、取得したremote`publish` HEADを`connector-plan`へ渡す。
2. helper生成の`create_tree` packetを順番に実行して期待tree SHAを照合し、最終`create_commit`の返却SHAで`publish`をnon-force更新する。
3. 更新に用いたcommit SHAを`record-update`へ渡す。helperが次の通常publishに使うcontrol baseを更新する。

```bash
python scripts/publish_control_maintenance.py prepare
python scripts/publish_control_maintenance.py connector-plan \
  --publish-head <current-publish-head>
python scripts/publish_control_maintenance.py record-update \
  --commit-sha <create-commit-result-sha> \
  --result success
```

Workflow / control maintenanceでpacket照合が成立しない場合は、保持中の正規packetと返却値を確認して該当transactionを再実行する。意味のあるref競合・Gateway検証失敗は原因を解消してから次の更新を判断する。

## CI

### Fast CI

`develop` への通常publishで実行する。

- Unit / architecture
- clean package install
- Chromium direct HTTP smoke
- 次回ローカルrepo構築用Git bundle artifact

Fast CIは小変更ごとの承認ゲートではない。run生成を確認した後はローカル作業を継続し、同一runを継続pollしない。次のpublish判断または結果が必要になった時点で確認する。

`develop` CIが失敗している場合、その失敗に依存する追加publishの前に原因を修正する。CIで初めて判明する実ブラウザ・clean install・OS差の失敗は正常な開発フィードバックとして扱う。

### Full Validation

次の場合に実行する。

- `main`反映候補
- ユーザー要求
- Persistence schema変更
- Simulation Orchestrator処理順変更
- package / server / launcher変更
- Fast CIで扱わないOS・ブラウザ検証

Gameplay、Windows、WebKitを通常Fast CIへ常設しない。

Browser E2Eのscenario集合はworkflowが `playwright/run_suite.py <scenario...>` へ明示的に渡す。workflow YAMLをruntimeで再解析したり、完了markerやsecondary entrypointで重複実行を回避する制御は置かない。runnerは1つのPlaywright / Browser processを所有し、同じbrowser engineのscenario moduleを同一Python process内で順次実行する。各scenarioは独立したBrowserContext / Page、GameRuntime、save用temp directory、HTTP serverを新規作成・終了し、Cookie、Storage、DOM、ゲーム状態を共有しない。Browser processは各scenarioの結果判定やGameRuntime Stateの所有者ではない。process自体の障害隔離を検証する場合は通常suiteとは目的を分ける。Fast CIのChromium smokeは短時間で再現できる主要browser wiringを検証し、WebKit等のOS・engine差はFull Validationで検証する。runnerはbootstrap、各scenario、全体の実時間をCI logへ出力し、長期化時にsetupとscenario本体を切り分けられる状態を維持する。

Chromium scenarioはrunner imageに実browserが存在すればそれを優先して全シナリオで共通使用し、存在しない場合はPlaywright Chromiumを使用する。シナリオごとに異なるChromium binaryを偶発的に使い分けない。

## Branch policy

- `main`: ユーザー承認済み正準状態。明示的承認なしに更新しない。
- `develop`: 通常開発中の共有正本。
- `temp`: ユーザー指定時、またはGitHub workflow自体を隔離検証するときだけ使う。
- `publish`: Publish Gateway専用の固定transport control branch。ゲーム実装の開発・統合には使わない。
- 上記以外のbranchは作らない。
- ゲーム本体version変更と `develop` → `main` 統合はユーザー承認後だけ行う。

## iPad development server

Windowsでは `start_ipad_server.bat`、macOS/Linuxでは `start_ipad_server.sh` を利用する。同一LAN上の通常サイズiPadから、PCのLAN IPv4とport 8765へSafariで接続する。

```text
http://<PC LAN IPv4>:8765/
```

Playwright WebKitは物理iPad Safariそのものではないため、iPadのスリープ、実LAN、Windows Firewall、実タッチ性能などの端末固有事項は実機試験で確認する。
