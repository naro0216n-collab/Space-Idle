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
- workflowと通常変更が混在する場合は、責務ごとにcommitを分け、通常変更を先にpublishする。

`publish` branchはPublish Gateway専用のtransport branchであり、通常開発や統合には使用しない。

### Normal develop publish

通常publishは次の順序で実行する。

1. 変更を責務としてまとまったlocal commitにする。
2. `prepare`を実行して、現在の `HEAD` をpublish対象として固定する。
3. remote `develop` HEADを1回取得し、そのSHAを `connector-plan` に渡す。
4. helperが生成したpacketを生成順に実行する。各packetは `action` と `action_args` が完全なConnector呼び出しであり、**1 packetを1 Connector callとしてそのまま実行する**。
5. Gateway成功後、requestに対応するreceiptを取得して `record` に渡す。
6. Fast CIは結果が次の判断に必要になった時点で確認する。

```bash
python scripts/publish_request.py prepare
```

remote `develop` HEADを取得した後、そのSHAを渡す。

```bash
python scripts/publish_request.py connector-plan \
  --target-remote-head <current-develop-head>
```

`connector-plan` が生成したpacketを生成順に実行する。packetの内容は作業者が再設計する入力ではなく、そのcall自体の実行仕様である。

Gateway成功後、receiptを取得して記録する。

```bash
python scripts/publish_request.py record \
  --receipt /tmp/publish-receipt.json
```

active transactionが存在する場合は、そのtransactionの現在段階から続行する。新しいpublishを開始する判断はhelperに任せ、作業者は既存transactionの生成済みpacketを実行する。

Connector callが失敗した、結果が不明確だった、またはGatewayがpayload検証で停止した場合だけ、後述の Publish recovery に進む。

### Workflow maintenance procedure

`.github/workflows/**` だけを変更したcommitは `scripts/workflow_maintenance.py` で `develop` へ反映する。

1. workflow-only commitを現在の `HEAD` として `prepare` する。
2. remote `develop` HEADを1回取得し、そのSHAを `connector-plan` に渡す。
3. helperが生成したworkflow blob packetを、通常publishと同じく1 packetずつそのまま実行する。
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

### Publish recovery

通常publishで問題が発生した場合も、active transactionを正本として復旧する。

- payload uploadが明確に失敗し、remote fileが作成されていない場合は、そのupload packetをもう一度実行する。
- upload結果が不明確な場合、またはGatewayがpayload blob不一致を報告した場合は、対象remote pathを1回取得する。remote blobが期待値と異なる場合は、観測したblob SHAを `connector-repair` に渡す。

```bash
python scripts/publish_request.py connector-repair \
  --part-index <mismatched-part-index> \
  --remote-blob-sha <observed-remote-blob-sha>
```

helperが生成したrepair packetを、通常packetと同じく **1 packet = 1 Connector call** として実行する。実行後は対象pathを1回取得し、helperが示す期待blob OIDと一致したことを確認して既存transactionを続行する。

request送信前なら既存のsubmit packetへ進む。Gateway送信後にpayload検証で停止した場合は、payload修復後に同じ失敗Gateway jobをrerunする。

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
