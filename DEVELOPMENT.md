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

復元例:

```bash
unzip source-snapshot.zip -d source-artifact
branch="$(cat source-artifact/.source-branch)"
git clone -b "$branch" source-artifact/repository.bundle space-idle-local
cd space-idle-local
python scripts/publish_request.py init
```

`init` は復元repoの `origin` が指す `repository.bundle` からsource-snapshot directoryを一意に解決する。source pathはCLIから指定しない。artifactのcommit/treeを復元できない場合は別方式へ読み替えず、artifact生成または取得経路の問題として扱う。

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

高速に再現できる検証はローカルで実行する。

```bash
pytest -q --ignore=tests/test_gameplay_mechanics.py
git diff --check
```

実ブラウザ、clean install、OS差などローカル環境で十分再現できない検証は、対応するテストも変更単位に含めてGitHub CIで実行する。

Publish Gateway、publish helper、CI/E2E harnessなど開発環境そのものの契約テストは `development_tests/` に物理分離し、ゲーム本体の `tests/` と通常suiteには含めない。開発基盤を変更した場合は `pytest -q development_tests`、publish経路だけを変更した場合は `pytest -q development_tests/test_publish_request.py` で専用検証する。実ブラウザの受入シナリオは `playwright/` に置き、この開発基盤テストとも分離する。

## Publish procedure

GitHub反映の入口は差分種別で決める。

- `.github/workflows/**` を含まない通常変更は `scripts/publish_request.py` を使用する。
- `.github/workflows/**` だけを変更する場合は後述の Workflow maintenance procedure を使用する。
- `.github/workflows/publish-gateway.yml` は、先に Publish control maintenance で固定 `publish` branchへ同一blobを反映済みの場合に限り、通常publishへ同梱できる。Gatewayがcontrol blobとの一致を機械検証する。
- 上記以外のworkflowと通常変更が混在する場合は、責務ごとにcommitを分け、通常変更を先にpublishする。

`publish` branchはPublish Gateway専用のtransport branchであり、通常開発や統合には使用しない。

### Normal develop publish

通常publishは次の順序で実行する。

1. 変更を責務としてまとまったlocal commitにする。
2. `prepare`を実行して、現在の `HEAD` をpublish対象として固定する。
3. remote `develop` HEADを1回、transport基点となる remote `publish` HEAD/treeを1回取得し、`connector-plan` に渡す。
4. helperが生成したtree headerとtree element filesから1つの `GitHub.create_tree` actionを構成して実行する。長いpayloadはhandoff上複数の `content` elementへ分けるが、Connector call全体が144 KiB以内なら送信は1回である。
5. 返却tree SHAを `connector-tree` に渡す。hard ceiling上1回に収まらない場合だけhelperが次の `create_tree` packetを生成し、収まる場合は直ちにcommit packetを生成する。複数tree callになってもbranchはまだ更新しない。
6. 最終tree後に生成されたcommit packetを実行し、返却commit SHAを `connector-update` に渡す。生成されたnon-force ref packetを1回だけ実行し、この1回の `publish` branch更新でpayload part、index、request triggerを同時に可視化してGatewayを起動する。
7. Gateway成功後、requestに対応するreceiptを取得して `record` に渡す。
8. Fast CIは結果が次の判断に必要になった時点で確認する。

```bash
python scripts/publish_request.py prepare
```

remote `develop` HEADとremote `publish` HEAD/treeをそれぞれ1回取得した後、その観測値を渡す。

```bash
python scripts/publish_request.py connector-plan \
  --target-remote-head <current-develop-head> \
  --publish-remote-head <current-publish-head> \
  --publish-remote-tree <current-publish-tree>
```

`connector-plan` が生成したtree headerとtree element filesを、順序を変えず1つの `GitHub.create_tree` callへ組み立てる。個々の `content` elementはlocal handoff用に小さく保つが、Connector call全体が144 KiB以内なら分割送信しない。tree生成に成功したら返却tree SHAを渡す。

```bash
python scripts/publish_request.py connector-tree \
  --tree-sha <create-tree-result-sha>
```

helperが次のtree packetを返した場合だけ同じ操作を繰り返す。commit packetを返したらそれを実行し、返却commit SHAを渡す。

```bash
python scripts/publish_request.py connector-update \
  --commit-sha <create-commit-result-sha>
```

生成されたref packetを `GitHub.update_ref` で実行する。`force` は常にfalseであり、partごとのbranch更新や `create_file` は通常publish経路に置かない。

Gateway成功後、receiptを取得して記録する。

```bash
python scripts/publish_request.py record \
  --receipt /tmp/publish-receipt.json
```

active transactionが存在する場合は、そのtransactionの現在段階から続行する。新しいpublishを開始する判断はhelperに任せ、作業者は既存transactionの生成済みpacketを実行する。prepared targetを公開する前にそのcheckpoint自体を取り消す必要が生じた場合は、remote `develop` HEADと `publish` treeを一度観測し、両方がtransaction開始時から内容上不変である場合だけ `cancel` で閉じる。transaction directoryを手動削除しない。

```bash
python scripts/publish_request.py cancel \
  --target-remote-head <current-develop-head> \
  --publish-remote-tree <current-publish-tree>
```

Connector handoffが失敗した、ref update結果が不明確だった、またはGatewayがpayload検証で停止した場合だけ、後述の Publish recovery に進む。

### Workflow maintenance procedure

`.github/workflows/**` だけを変更したcommitは `scripts/workflow_maintenance.py` で `develop` へ反映する。

1. workflow-only commitを現在の `HEAD` として `prepare` する。
2. remote `develop` HEADを1回取得し、そのSHAを `connector-plan` に渡す。
3. helperが生成したworkflow blob packetの `action_args` をコピペで対応するConnector callへ渡し、生成順に実行する。
4. `connector-tree` が生成したtree packetを実行し、返却tree SHAを `connector-commit` に渡す。
5. commit packetを実行する。生成commitを1回取得し、そのcommit SHA・tree SHA・parent SHAを `connector-update` に渡す。
6. ref update packetを実行する。更新後の `develop` HEADとtreeを1回取得し、`verify-remote` に渡す。
7. 成功後は新しい `develop` のFast CIが生成した `source-snapshot` からrepoを復元し、`publish_request.py init` で通常開発へ戻る。

```bash
python scripts/workflow_maintenance.py prepare
python scripts/workflow_maintenance.py connector-plan \
  --target-remote-head <current-develop-head>
python scripts/workflow_maintenance.py connector-tree
python scripts/workflow_maintenance.py connector-commit \
  --tree-sha <create-tree-result-sha>
python scripts/workflow_maintenance.py connector-update \
  --commit-sha <create-commit-result-sha> \
  --commit-tree-sha <fetched-commit-tree-sha> \
  --commit-parent-sha <fetched-commit-parent-sha>
python scripts/workflow_maintenance.py verify-remote \
  --remote-head <develop-head-after-update> \
  --remote-tree <develop-tree-after-update>
```

各stageではhelperが生成したpacketと、直前stageが要求する観測値だけを次へ渡す。

### Publish control maintenance procedure

Publish Gateway の control plane (`.github/workflows/publish-gateway.yml` と Gateway validator scripts) は `scripts/publish_control_maintenance.py` で固定 `publish` branchへ反映する。通常のgame/source publishや `develop` workflow maintenanceとは混在させない。

1. control plane変更をcommitし、clean worktreeで `prepare` する。
2. remote `publish` HEADとtreeを1回取得し、`connector-plan` に渡す。
3. helperが生成したblob packetの `action_args` をコピペで `GitHub.create_blob` へ渡す。返却blob SHAは本文を確認せず `connector-tree` へ渡し、helperが正準blob OIDとの一致を機械判定する。
4. helperが生成したtree、commit、non-force ref update packetを順に実行する。
5. 更新後の `publish` HEADとtreeを1回取得し、`verify-remote` に渡してtransactionを閉じる。`develop` は変更されないためsource-snapshot再構築は不要。

```bash
python scripts/publish_control_maintenance.py prepare
python scripts/publish_control_maintenance.py connector-plan \
  --target-remote-head <current-publish-head> \
  --target-remote-tree <current-publish-tree>
python scripts/publish_control_maintenance.py connector-tree \
  --blob '<control-path>=<create-blob-result-sha>' \
  --blob '<control-path>=<create-blob-result-sha>'
python scripts/publish_control_maintenance.py connector-commit \
  --tree-sha <create-tree-result-sha>
python scripts/publish_control_maintenance.py connector-update \
  --commit-sha <create-commit-result-sha> \
  --commit-tree-sha <fetched-commit-tree-sha> \
  --commit-parent-sha <fetched-commit-parent-sha>
python scripts/publish_control_maintenance.py verify-remote \
  --remote-head <publish-head-after-update> \
  --remote-tree <publish-tree-after-update>
```

control planeの実装は独立した小さなtracked fileへ分け、巨大なworkflow本文をConnector callへ再構成しない。blob本文の成立判定はGit blob OIDで行い、tree/commit/refはhelperが生成するGit data packetだけを使用する。

### Publish recovery

通常publishでpayload handoffが失敗、不明確、ref update結果が不明確、またはGatewayのpayload検証で停止した場合も、active transactionを正本として復旧する。remote payloadの個別取得やSHA転記は行わない。

repair開始時だけremote `publish` HEAD/treeを1回取得し、その観測値を渡す。

```bash
python scripts/publish_request.py connector-repair \
  --publish-remote-head <current-publish-head> \
  --publish-remote-tree <current-publish-tree>
```

helperは観測された `publish` 基点が、直前世代をまだbranchへ反映していない基点、または直前世代を原子的に反映したcommit/treeのいずれかであることを機械検証する。Gatewayが既にreceiptを記録した後の別commit等であればrepairせず停止する。

次世代も144 KiB hard ceilingをConnector call全体へ適用する。会話表示やlocal packet読出しで本文を複数sliceに分ける必要がある場合、helperはそれらを同一 `GitHub.create_tree` call内の複数 `content` elementとして扱う。call全体がhard ceiling以内なら送信は1回であり、handoff field数をtool call数へ伝播させない。hard ceilingを超える場合だけ、helperがtree elementsを必要最少数の連続 `create_tree` callへpackingする。blob返却SHAの中継や本文SHAの手動確認は行わない。

その後は通常系と同じく、tree packet → `connector-tree` → 必要なら次tree packet → commit packet → `connector-update` → non-force ref packetの順で実行する。`publish` branch更新は世代ごとに1回だけであり、handoff fieldやtree batchをbranchへ個別公開しない。再度payload検証で停止した場合は同じhard ceiling契約のまま `connector-repair` で次世代へ進む。request ID、base、target tree、publish commitはactive transactionのものを維持する。

remote `develop` HEAD、publish parent、target treeなどpublish対象そのものの整合性が崩れている場合はtransport recoveryではない。transactionを進めず、remote同期または実装状態の問題として調査する。

Workflow maintenanceで問題が発生した場合も、各helper stageが生成したpacketと検証結果を正本として同じ原則で処理する。

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

Browser E2Eの起動方式は実測したrunner特性に合わせる。macOS Full ValidationのようにscenarioごとのPython/Playwright cold startが支配的なjobでは、workflow jobに列挙されたscenario commandを実行時の正本として `playwright/run_suite.py` へ集約し、後続entrypointは完了markerを重いgame import前に検証して終了する。scenario集合をハーネスへ別途ハードコードせず、追加・削除・並べ替えはworkflow側の宣言へ自動追従させる。coalesced jobへ追加するscenarioは既存scenarioと同じgeneric entrypoint contractを使用し、未対応の先頭scenarioや不整合はfail-closedとする。同一jobの重いPython/game bootstrapだけを共有し、各シナリオはPlaywright/browser process、BrowserContext、GameRuntime、save用temp directory、HTTP serverをすべて作り直す。従来のbrowser process隔離まで維持したまま、重複したPython cold startだけを除去する。Fast CIのようにprocess集約自体が実測で遅くなる経路は独立scenario実行を維持する。runnerはbootstrap、browser起動、各scenario、全体の実時間をCI logへ出力し、長期化時にsetup・browser起動・scenario本体を切り分けられる状態を維持する。

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
