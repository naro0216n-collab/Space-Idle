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
pytest -q --ignore=tests/test_gameplay_mechanics.py
git diff --check
```

実ブラウザ、clean install、OS差などローカル環境で十分再現できない検証は、対応するテストも変更単位に含めてGitHub CIで実行する。

## Publish procedure

通常の実装はローカルGitで完結させ、GitHubへの転送だけを固定 `publish` branch上のPublish Gatewayへ委ねる。`publish` はゲーム開発branchではなく、Connector制約下でnative `git push`を代替するtransport control planeである。`temp` は通常publishの中継には使わず、ユーザー指定時またはGateway / workflow自体の隔離検証時だけ使用する。

Connector経路の正常入口は `gateway-begin` に一本化する。`prepare`、`connector-plan`、`verify`、低水準 `record` を個別に組み合わせる手順は公開しない。helperがrequest生成、自己検証、call容量判定、packet生成、active session管理までまとめて行う。

通常publishは次の順序に固定する。

1. ローカル変更を責務としてまとまったcommitにする。publish対象は明示したcommitted `target-ref` のtreeであり、その後にworking treeへ別の未commit作業があっても対象へ混入させない。
2. publish直前に対象branch HEADを一度だけ取得する。これはChatGPT側が正常系で取得する唯一のpublish整合性入力である。
3. 取得したHEADとpublish対象commitを `gateway-begin` へ渡す。`develop`では取得HEADが記録済みpublish基点と一致することをhelperが検証する。隔離検証用`temp`では取得した`temp` HEADそのものをそのsessionのbaseとし、developのpublish stateとは独立に扱う。その上でhelperは決定論的publish commit、Git bundle、v5 request、payload SHA-256、Connector packet、active sessionを一括生成する。GitHub repository、固定 `publish` branch、Connector call容量、manifest/packet出力先はhelper所有であり、publishごとに指定しない。
4. `gateway-begin` はConnector本来のcall容量を上限として、payloadを最小数の `GitHub.create_blob` actionへ分ける。ChatGPT側bridgeの経験的な固定上限は設けない。helperが出力する`connector_namespace` / `connector_function`を実行入口とし、別のConnector write actionへ読み替えない。action名・part境界・初回分割数は判断対象ではない。現在のhelper packet自体をexecution bridgeが忠実に引き渡せない場合は、欠損した内容を送信したり固定サイズを推測したりせず、remote write前に`gateway-refine`を実行する。helperが最大の未確認partを一段だけ二分して新packetを生成し、part選択・境界はhelper所有のままとする。
5. 各 `GitHub.create_blob` が返したSHAを、helperが事前計算したGit blob OIDと照合する。全文再取得・全文比較は正常系で行わない。`gateway-submit --uploaded-blob-sha ...` へ現在のupload action順で返却SHAを渡し、一致したpartは確定する。不一致partがあればhelperはそのpartだけを二分し、新しい `create_blob` actionを返す。成功済みpartは再送しない。この照合・再分割を必要なpartだけ反復するため、より小さい固定上限を事前推測したりChatGPTがBase64境界を作り直したりしない。全partのOIDが一致した場合に限って小さい最終 `GitHub.create_file` request actionを生成する。
6. `gateway-submit` が生成した最終actionをそのまま実行する。長いBase64 payloadを `create_file` 引数へ直接転記する正常経路は持たない。
7. Gatewayはpayload、Git object、bundle、publish commit、parent/base、target tree、対象branch HEADを検証し、すべて一致した場合だけexact commitを対象branchへnon-force publishする。成功時はreceiptを記録しFast CIを起動する。
8. Gateway処理後に対象branch HEADを一度取得し、`gateway-complete --target-remote-head <head>`へ渡す。helperはそのHEADが事前計算したpublish commitと完全一致する場合だけsessionを閉じる。`develop` requestだけが通常publish stateを更新する。隔離検証用`temp` requestは観測したtemp HEADを独立baseとして使用し、成功してもdevelop基点を変更しない。receiptはGateway側監査記録であり、通常完了入力にはしない。

active Gateway sessionは一つだけ存在できる。未完了sessionがある状態で別の `gateway-begin` は開始できない。状態確認には `gateway-status` を使う。`gateway-abort` はrequestが未送信である、または既存requestが再びpublishし得ないことを確認した障害時だけ使用し、正常手順には含めない。

通常サイズの開始例:

```bash
# 1. GitHubで develop HEADを一度取得する。
# 2. helperへその値と責務checkpointを渡す。
python scripts/publish_request.py gateway-begin \
  --target-ref <committed-checkpoint> \
  --target-remote-head <current-develop-head>
```

`gateway-begin` は常に `phase: upload-payload-parts` を返す。現在表示されているupload actionを実行し、その返却SHAをaction順で次へ渡す。

helper packetそのものを現在のexecution bridgeが忠実に転送できない場合は、送信前に次を実行する。これはGitHubへ何も書き込まず、最大の未確認partをhelper内部で一段だけ二分する。必要なら繰り返すが、固定のbridge上限を設けるためには使わない。

```bash
python scripts/publish_request.py gateway-refine
```

```bash
python scripts/publish_request.py gateway-submit --uploaded-blob-sha <sha> [--uploaded-blob-sha <sha> ...]
```

SHA不一致partがあれば `gateway-submit` は `phase: upload-payload-parts` のまま再分割したupload actionだけを返す。そのactionを実行して再度 `gateway-submit` する。全part一致時だけ単一request actionが返る。request actionをupload検証より先に生成・送信する手順は存在しない。

Gateway処理後に対象branch HEADを一度取得して完了する。

```bash
python scripts/publish_request.py gateway-complete \
  --target-remote-head <observed-target-head>
```

receipt照合が必要な監査・復旧時だけ `gateway-record` を使用する。通常系ではreceipt JSONをローカルへ転記しない。

現在状態の確認:

```bash
python scripts/publish_request.py gateway-status
```

複数の未publish commitがある場合にtransport量やcheckpoint候補を確認したいときだけ `plan` を使う。`plan` はpublish実行入口ではない。

```bash
python scripts/publish_request.py plan --target-ref HEAD
```

正常系でChatGPTが手作業するのは、責務checkpointの選択、開始時の対象branch HEAD取得、helperが指定した`connector_namespace` / `connector_function`へのaction args転送、Connectorが返した短いblob SHAのhelperへの受け渡し、Gateway後の対象branch HEAD確認だけである。Connector function自体を推測・代替しない。Base64、Git blob OID、part境界、call予算、manifest path、packet順序、publish branch、receipt JSONを人手で再構成しない。

### Publish failure handling

- `gateway-begin`でtarget HEAD不一致: Connector actionは生成しない。remote変更を調査し、必要なら最新source-snapshotから再同期する。
- `GitHub.create_blob`失敗: requestはまだ生成されない。該当actionだけ再実行する。返却SHA不一致: helperが不一致partだけを二分して再発行する。全文照合や手動part編集は行わず、全partがhelper計算OIDと一致した後だけ最終requestを生成する。
- blob OID、payload長、payload SHA-256、bundle、parent、target tree不一致: Gatewayが失敗し、対象branchは更新されない。
- target branch push競合: forceしない。Gatewayの直前base再確認またはnon-force pushで停止する。
- helper/Connector/Gateway経路そのものを変更した場合: ローカル契約テスト後、必要に応じて `temp` をtargetとする隔離検証を行う。`temp` の成果物を `develop` publish入力として再利用しない。

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
