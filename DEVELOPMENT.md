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
git bundle verify ../source-artifact/repository.bundle

test "$(git branch --show-current)" = "$branch"
test "$(git rev-parse HEAD)" = "$(cat ../source-artifact/.source-commit)"
test "$(git rev-parse 'HEAD^{tree}')" = "$(cat ../source-artifact/.source-tree)"
python scripts/publish_request.py init \
  --remote-commit "$(cat ../source-artifact/.source-commit)" \
  --remote-tree "$(cat ../source-artifact/.source-tree)"
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
pytest -q -m "not development" --ignore=tests/test_gameplay_mechanics.py
git diff --check
```

実ブラウザ、clean install、OS差などローカル環境で十分再現できない検証は、対応するテストも変更単位に含めてGitHub CIで実行する。

Publish Gatewayやpublish helperなど開発環境そのもののテストは `development` markerへ分離し、通常のゲーム本体suiteには含めない。関連機構を変更した場合だけ `pytest -q -m development tests/test_publish_request.py` で専用検証する。

## Publish procedure

通常の実装はローカルGitで完結させ、GitHubへの転送だけを固定 `publish` branch上のPublish Gatewayへ委ねる。`publish` はゲーム開発branchではなく、Connector制約下でnative `git push`を代替するtransport control planeである。`temp` は通常publishの中継には使わず、ユーザー指定時またはGateway / workflow自体の隔離検証時だけ使用する。

通常publishは次の順序に固定する。

1. ローカル変更を責務としてまとまったcommitにする。publish対象は明示したcommitted `target-ref` のtreeであり、その後にworking treeへ別の未commit作業があっても対象へ混入させない。
2. `scripts/publish_request.py prepare` で、記録済みremote commitを親、local target treeをtreeに持つ決定論的publish commitを作り、Git bundleへ格納する。生成物はv6 JSON requestで、bundle Base64、payload SHA-256、base commit、target tree、publish commit、local target commitを保持し、生成時にbundle/parent/treeを自己検証する。
3. publish直前に対象branch HEADを一度だけ取得する。`connector-plan`へ渡し、manifestの `base_sha` と一致しない場合は送信せず原因を調査する。
4. Connector経路では `connector-plan` がbundle Base64を必ず独立Git blobとしてmaterializeする。実際のaction引数をcompact JSONへシリアライズしたbytesでcall容量を判定し、必要な場合だけcall予算から逆算した最少数のpartへ自動分割する。各partは独立した `GitHub.create_blob` として並列送信する。execution bridgeが生成済みpacketを忠実に引き渡せない場合は、remote requestを送る前に `--connector-call-budget-bytes` を下げて `connector-plan` を再実行し、helperにより小さいpacketへ再計画させる。ChatGPT側でpayload境界やBase64を作り直さない。payloadをrequest本文へ直接埋め込むinline経路は使わない。
5. helperは各partのGit blob OIDと、それらを順序付きで参照するpayload root tree OIDを事前計算し、root tree作成packetと小さい最終request packetを同時に生成する。全part送信後、事前計算blob OIDだけを使う `GitHub.create_tree` を1回実行し、成功したら事前生成済み `GitHub.create_file` request packetを実行する。materializationとroot bindingを分離することで、Connectorへ渡したcontentが変化して別blobが生成された場合は期待blob OIDが存在せずroot作成が失敗し、request送信前に停止する。`create_blob` と `create_tree` の返却SHAは後続入力にせず、内容の正確性を返却SHAの手動比較に依存させない。Gatewayは成立済みrootからOID整合性を最終検証する。
6. Publish Gatewayはrequest作成commitを契機に自動実行する。payload root treeを取得し、root tree OID、各blob OID、payload長、payload SHA-256、Git bundle、publish commit、parent/base、target treeを検証する。すべて一致し、対象branch HEADがbaseのままである場合だけexact publish commitを対象branchへnon-force pushし、直後にremote commit/treeを再検証する。SHA不整合時は対象branchを更新しない。
7. Gatewayは成功receiptを `.publish/receipts/<request-id>.json` へ自動記録し、Fast CIをdispatchする。ローカルではreceiptを取得して `publish_request.py record` に渡す。`record` はmanifest内の `local_target_commit` を自動的に使用し、現在のlocal HEADが次作業へ進んでいても、request、receipt、当該local target tree、published commit objectの関係を機械検証した場合だけ次回publish stateを更新する。local target SHAを手動で引き渡さない。

Connector経路でChatGPT側が必要とするGitHub callは、Gateway実行前では対象branch HEAD取得1回、1個以上のblob upload、payload root tree作成1回、最終request作成1回である。Gateway成功後にreceiptを1回取得する。Gateway内部のbase再確認、payload tree/blob OID検証、target push、remote tree確認、receipt作成、CI dispatchはworkflowが自動実行する。正常系でpublish branch HEAD/tree、blob/root tree返却SHA、transport commit SHA、ref SHAをチャット側が中継・目視比較しない。

複数の未publish commitがある場合だけ、必要に応じてtransport量を比較する。

```bash
python scripts/publish_request.py plan --target-ref HEAD
```

request生成例:

```bash
python scripts/publish_request.py prepare \
  --target-branch develop \
  --target-ref HEAD \
  --output /tmp/space-idle-publish.json
```

`prepare` は自動検証する。生成物の診断を独立実行する場合だけ `verify` を使う。

```bash
python scripts/publish_request.py verify \
  --manifest /tmp/space-idle-publish.json
```

対象branch HEADを一度取得した後、Connector packetを生成する。

```bash
python scripts/publish_request.py connector-plan \
  --manifest /tmp/space-idle-publish.json \
  --github-repository naro0216n-collab/Space-Idle \
  --target-remote-head <current-target-head>

# blobs-root-tree-then-request-file:
#   upload-part-*.json の GitHub.create_blob を並列実行後、
#   assemble-payload-root.json の GitHub.create_tree を実行する。
#   成功したら事前生成済み submit-request.json の GitHub.create_file を1回実行する。
# payloadサイズにかかわらずこの経路を使い、blob/tree返却SHAは後続stepへ渡さない。
```

Gateway成功後はrequest IDに対応するreceiptを取得し、次回基点を更新する。対象local commitはmanifestから自動解決されるため、receipt待ちの間に次のlocal作業へ進んでも `--local-ref` 等のSHA指定は不要である。

```bash
python scripts/publish_request.py record \
  --manifest /tmp/space-idle-publish.json \
  --receipt /tmp/publish-receipt.json
```

標準Connector経路はGit bundle request v6だけを扱う。旧patch transport、段階的 `connector-publish-step`、remote chunks-treeの個別verify、manual `record --remote-commit/--remote-tree` は通常経路にも互換経路にも残さない。障害時は生成済みrequestとGatewayログから原因を確認し、正常系へ診断stepを追加しない。

### Publish failure handling

- target HEAD不一致: requestを作成しない。remote変更を調査し、必要なら最新source-snapshotから再同期する。
- payload transport失敗: `create_blob` 自体が失敗した場合はそのcallを再送する。packet転送の忠実性に問題がある場合は、最終requestを送信する前に `connector-plan --connector-call-budget-bytes <smaller-budget>` でhelperに再分割させる。root tree作成失敗時も最終requestは送信せず、生成済みupload packetを再実行するか、必要なら同じ方法で再計画してからroot作成を再試行する。blob/tree返却SHAは比較・中継せず、payloadの手動分割・Base64再構成も行わない。Gatewayがrequest記載の事前計算OIDと実在objectを機械照合する。
- blob OID、payload長、payload SHA-256、bundle、parent、target tree不一致: Gatewayが失敗し、対象branchは更新されない。
- target branch push競合: forceしない。Gatewayの直前base再確認またはnon-force pushで停止する。
- Gateway自体の変更: まずローカルで構文・契約を検証し、固定 `publish` branchのcontrol planeへ候補Gatewayを反映した後、明示的に `temp` をtargetとするrequestで実動作を隔離検証する。成功後に同じsource変更を通常の `develop` publish対象へ含める。`temp` のcommit・tree・request・payload等を `develop` publish入力として再利用しない。

認証済みnative `git push` が利用できる実行環境では、それを第一選択としPublish Gatewayを経由しない。native Git経路も記録済みremote HEAD/treeとの一致を確認し、local target treeを親remote HEAD上へcommitしてnon-force pushし、remote ref/tree一致を確認する。

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

Browser E2Eの起動方式は実測したrunner特性に合わせる。macOS Full ValidationのようにscenarioごとのPython/Playwright cold startが支配的なjobでは、最初のentrypointがjobのscenario集合を `playwright/run_suite.py` へ集約し、後続entrypointは完了markerを重いgame import前に検証して終了する。同一jobではPlaywrightとbrowser processを1回だけ起動し、各シナリオは独立したBrowserContext、GameRuntime、save用temp directory、HTTP serverを作り直す。browser process起動コストだけを共有し、cookie・storage・page・ゲーム状態等の検証状態は共有しない。Fast CIのように共有化が実測で遅くなる経路は独立scenario実行を維持する。runnerはbootstrap、browser起動、各scenario、全体の実時間をCI logへ出力し、長期化時にsetup・browser起動・scenario本体を切り分けられる状態を維持する。

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
