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
python scripts/publish_request.py init ../source-artifact
```

artifactのcommit/treeを復元できない場合は別方式へ読み替えず、artifact生成または取得経路の問題として扱う。

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

GitHub反映の入口は差分種別で一意に決める。作業者がtransport都合で選択しない。

- `.github/workflows/**` を含まない通常変更: `scripts/publish_request.py` だけを使用する。
- `.github/workflows/**` だけのworkflow変更: `scripts/workflow_maintenance.py` だけを使用する。
- workflowとそれ以外が混在するcommit: 反映しない。通常変更を先に独立checkpointとしてpublishし、その後workflow-only commitを作る。

通常の実装はローカルGitで完結させ、GitHubへの転送だけを固定 `publish` branch上のPublish Gatewayへ委ねる。`publish` はゲーム開発branchではなく、Connector制約下でnative `git push`を代替するtransport control planeである。`temp` は通常publishの中継には使わず、ユーザー指定時またはGateway / workflow自体の隔離検証時だけ使用する。

通常publishは次の順序に固定する。

1. ローカル変更を責務としてまとまったcommitにする。publish対象は `prepare` 実行時の現在 `HEAD` に固定され、working treeの未commit差分は対象にしない。別requestを並行開始せず、active transactionをreceipt記録まで完了させる。
2. `scripts/publish_request.py prepare` で、記録済みremote commitを親、local target treeをtreeに持つ決定論的publish commitを作り、Git bundleへ格納する。生成物はv6 JSON requestで、bundle Base64、payload SHA-256、base commit、target tree、publish commit、local target commitを保持し、生成時にbundle/parent/treeを自己検証する。`.github/workflows/**` の差分を含むtargetはここでworkflow maintenance対象として分離し、通常Gateway requestを生成しない。
3. publish直前に対象branch HEADを一度だけ取得する。`connector-plan`へ渡し、manifestの `base_sha` と一致しない場合は送信せず原因を調査する。
4. `connector-plan` は固定Connector profileを使い、bundle Base64を独立Git blobへmaterializeするための `upload-part-*.json` だけを生成する。call budgetはhelper内部のtransport設定であり、CLIやmanifestから変更しない。必要な場合だけ実action引数bytesから最少数へ自動分割する。各uploadは独立しており並列実行できる。
5. 全uploadが成功した後に `connector-root` を実行し、事前計算blob OIDを順序付きで参照する `assemble-payload-root.json` を初めて生成する。`GitHub.create_tree` が成功することで、期待blob群がGitHub object storeにmaterializeされていることを確認する。
6. root作成結果のtree SHAを `connector-submit --root-tree-sha` へ渡す。helperは事前計算root OIDとの一致を機械検証し、一致した場合だけ `submit-request.json` を生成する。返却SHAをpayload sourceへ採用するのではなく、事前計算OIDの成立確認にだけ使用する。request packetはこのstage以前には存在しない。
7. `submit-request.json` の `GitHub.create_file` を1回実行する。Publish Gatewayはrequest作成commitを契機に自動実行し、payload root tree、各blob OID、payload長、payload SHA-256、Git bundle、publish commit、parent/base、target tree、直前remote HEADを検証する。すべて一致した場合だけexact publish commitを対象branchへnon-force pushし、remote ref/treeを再確認する。
8. Gatewayは成功receiptを `.publish/receipts/<request-id>.json` へ自動記録し、Fast CIをdispatchする。ローカルではreceiptを取得して `publish_request.py record` に渡す。`record` はmanifest内の `local_target_commit` を自動的に使用し、現在のlocal HEADが次作業へ進んでいてもrequest、receipt、当該local target tree、published commit objectの関係を機械検証した場合だけ次回publish stateを更新する。

Connector transportはstageを `uploads-planned -> root-packet-ready -> submit-ready` としてrepo-local active transactionへ記録する。manifestやplan directoryはhelperが `.git` 配下へ固定生成し、CLIから指定しない。既にactive transactionがある場合は再計画せず、そのstageで生成済みpacketを使って続行する。payload uploadの失敗は該当packetを再送する。root作成が失敗した場合は、期待blobがmaterializeされていないtransport integrity failureとしてrequest生成前に停止し、upload packetの忠実な再送またはconnector実装自体の修正を行う。任意budgetへの縮小、payloadの手動分割、Base64再構成、inline requestへの切替は標準経路に含めない。

標準実行例。`prepare` は現在 `HEAD` を自動検証してrepo-local active transactionを作成する。

```bash
python scripts/publish_request.py prepare
```

対象branch `develop` HEADを一度だけ取得した後、そのSHAをupload stageへ渡す。

```bash
python scripts/publish_request.py connector-plan \
  --target-remote-head <current-develop-head>
```

出力された全 `upload-part-*.json` の `GitHub.create_blob` が成功したらroot stageへ進む。packet pathはhelper出力だけを使用し、別manifestやplan directoryを指定しない。

```bash
python scripts/publish_request.py connector-root
```

`assemble-payload-root.json` の `GitHub.create_tree` 成功後、その返却tree SHAを機械検証して最終request packetを生成する。

```bash
python scripts/publish_request.py connector-submit \
  --root-tree-sha <create-tree-result-sha>
```

Gateway成功後はrequest IDに対応するreceiptを取得し、次回基点を更新する。

```bash
python scripts/publish_request.py record \
  --receipt /tmp/publish-receipt.json
```

標準Connector経路はGit bundle request v6だけを扱う。旧patch transport、段階的旧helper、manual record fallback、任意call-budget調整は維持しない。


### Workflow maintenance procedure

workflow更新は通常Publish Gatewayへ流さない。`scripts/workflow_maintenance.py` は `.github/workflows/**` だけが変更されたcommitted targetを受け付け、他パスが一件でも含まれれば開始前に拒否する。対象branchは `develop` に固定し、`main` や通常source publishへ兼用しない。

入口は次の1つだけとする。対象は現在 `HEAD` に固定され、manifestやplan directoryはrepo-local transaction領域へ自動生成する。

```bash
python scripts/workflow_maintenance.py prepare
```

`prepare` 後に `develop` HEADを一度だけ取得し、記録済みbaseと一致する場合だけConnector stageへ進む。

```bash
python scripts/workflow_maintenance.py connector-plan \
  --target-remote-head <current-develop-head>
```

`connector-plan` は変更後workflow fileの `GitHub.create_blob` packetだけを生成する。call budgetは通常publishと同じ固定96 KiB profileであり、CLIから変更しない。1 workflow fileのblob action自体がprofile上限を超える場合は自動細分化せず停止する。workflow fileは1 Git blobであるため、分割transportへ読み替えない。

全blob upload後にtree packetを生成する。削除workflowはtarget tree entryを `sha: null` として扱い、追加・変更workflowはlocal target commitの事前計算blob OIDを参照する。Connector返却blob SHAを後続入力へ採用しない。

```bash
python scripts/workflow_maintenance.py connector-tree
```

`GitHub.create_tree` 成功後、その返却tree SHAがlocal target treeと一致した場合だけcommit packetを生成する。

```bash
python scripts/workflow_maintenance.py connector-commit \
  --tree-sha <create-tree-result-sha>
```

commit packetはrecorded `develop` HEADを唯一のparent、検証済みtarget treeをtreeとして `GitHub.create_commit` を実行する。commit作成後、その返却SHAからnon-force ref update packetを生成する。

```bash
python scripts/workflow_maintenance.py connector-update \
  --commit-sha <create-commit-result-sha>
```

`advance-workflow-ref.json` の `GitHub.update_ref(force=false)` 実行後、`develop` を一度取得してremote HEAD/treeを検証する。

```bash
python scripts/workflow_maintenance.py verify-remote \
  --remote-head <develop-head-after-update> \
  --remote-tree <develop-tree-after-update>
```

workflow maintenanceは通常publish stateへ動的に生成されたGitHub commit objectを擬似記録しない。`verify-remote` 成功時に旧ローカルrepoへrehydration-required markerを記録し、`publish_request.py` は以後の通常操作を拒否する。maintenance後は更新後 `develop` のFast CIが生成した `source-snapshot` からrepoを復元し、`publish_request.py init` を実行してから通常開発へ戻る。これによりworkflow maintenanceのcommit SHAを手作業で通常publish stateへ中継しない。

`temp` はworkflow経路そのものの隔離検証に使用できるが、標準workflow maintenanceの中継・promotion元にはしない。`temp` で得たcommitを `develop` 入力へ再利用せず、`develop` 更新は常にlocal committed targetから独立して作成する。

### Publish failure handling

- target HEAD不一致: requestを作成しない。remote変更を調査し、必要なら最新source-snapshotから再同期する。
- blob upload失敗: 失敗した生成済みupload packetだけを再送する。
- root tree作成失敗: request packetはまだ存在しない。upload transportの忠実性またはconnector実装を修正し、期待blob群をmaterializeしてから同じroot packetを再実行する。
- root tree SHA不一致: `connector-submit` が停止する。返却SHAをrequestへ流用せず、root作成経路を調査する。
- blob OID、payload長、payload SHA-256、bundle、parent、target tree不一致: Gatewayが失敗し、対象branchは更新されない。
- target branch push競合: forceしない。Gatewayの直前base再確認またはnon-force pushで停止する。
- `.github/workflows/**` の変更: 通常Gatewayではrequestを生成しない。workflow更新権限を持つ分離されたmaintenance経路を使用し、必要なら `temp` でworkflow自体を隔離検証する。

通常helperにはnative Git、temp publish、任意commit message、repository切替、plan directory切替などの代替mutation入口を置かない。これらは一見便利でも、標準Gateway・workflow maintenanceとの取り違えでremote更新経路を分岐させるためである。将来、認証済みnative Git環境を正式採用する場合は、既存helperへサブコマンドを再追加せず、その実行環境でtransportを一意に選択する専用入口として設計し、同一環境でGatewayとの選択を作業者へ委ねない。

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
