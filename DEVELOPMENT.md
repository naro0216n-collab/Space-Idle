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

通常の実装はローカルGitで完結させ、GitHubへの転送だけを固定 `publish` branch上のPublish Gatewayへ委ねる。`publish` はゲーム開発branchではなく、Connector制約下でnative `git push`を代替するtransport control planeである。

通常publishは次の順序に固定する。

1. ローカル変更を整合した単位としてcommitし、working treeをcleanにする。
2. `scripts/publish_request.py`で、前回publish済みtreeから現在HEAD treeまでのbinary diffをgzip+Base64化し、ChatGPTのtool間搬送を含むConnector経路で完全性を保って転送できる上限サイズの少数chunkと小さなmanifestへ生成する。標準chunk上限は8 KiBで、差分サイズに応じてchunk数だけが増減する。`prepare`は生成直後にchunk/diff digestと一時Git indexでのtarget tree再現を自己検証し、完全なrequestだけを成功として返す。
3. publish直前にremote対象branch HEADを一度だけ確認し、manifestの `base-sha` と一致することを確認する。不一致ならrequestを送らず差分を調査する。
4. GitHub Connectorでは `publish_request.py connector-plan` が生成する最少call計画を使う。標準8 KiB chunkはGateway側の検証・再送単位として維持するが、Connector送信はchunk数で固定分割しない。`publish` branchのbase commit/treeを計画時に一度だけ与え、全chunk本文とmanifestを `.publish/chunks/*` / `.publish/request.patch` として既存publish treeへ直接接続する単一 `create_tree(content=...)` requestをまず生成する。call予算判定は計画packet全体ではなく、実際にConnectorへ渡す `action_args` のcompact JSON bytesで行う。標準96 KiB内ならこの1回でtransport root treeを完成させる。超過時だけ最少数の独立upload groupへ自動分割して並列materializeし、最終root tree作成時にローカル算出済みblob OIDを直接参照する。独立したchunks-tree assembly callは通常工程に置かない。GitHub object lookupとPublish Gatewayがchunks tree OID、各chunk SHA-256、payload SHA-256、bundle commit/tree/parentを検証するため、upload返却SHAの転記・個別照合callも行わない。root tree作成後はtransport commitを1回作成し、`publish` refを1回だけnon-force更新してGatewayを起動する。Contents APIはGit Data APIが利用不能な場合だけfallbackとする。
5. Publish Gatewayはchunks subtreeのGit OID、各chunk digest、request digest、remote base SHA、patch適用後のGit tree SHAを検証し、すべて一致した場合だけ通常のnon-force pushで対象branchを更新する。push直後にもremote refとremote commit treeを再取得し、published commit SHAとmanifest target treeへ一致することをGateway自身が確認する。
6. Gatewayは検証済みのrequest ID、base commit、target tree、chunks tree OID、published commit/treeを小さなreceiptとして `publish` branchへ記録する。ローカルではそのreceiptとmanifestを `publish_request.py record` に渡し、全SHA関係を機械検証した場合だけ次回publish stateを更新する。SHA文字列を人手で見比べない。
7. Gatewayは対象branch更新後にFast CIを `workflow_dispatch` し、実ブラウザ・clean install・次回用Git bundle artifactを検証する。

複数の未publish commitがある場合は、まずtransport planを確認する。これはローカル履歴を書き換えず、全体を1 requestにまとめた場合と各local checkpointを順次publishした場合の転送量を比較する。

```bash
python scripts/publish_request.py plan --target-ref HEAD
```

通常は責務として成立しているlocal commit境界をそのまま順次publishする。小さい連続commitを1 requestへまとめることもできるが、transport都合でrebase/reset/squashして履歴を作り直さない。

request生成例:

```bash
python scripts/publish_request.py prepare \
  --target-branch develop \
  --target-ref HEAD \
  --output /tmp/space-idle-publish.patch
```

`prepare`は通常自動検証する。転送前の生成物を改めて診断する場合は同じ検証を独立実行できる。

```bash
python scripts/publish_request.py verify \
  --manifest /tmp/space-idle-publish.patch
```

Connector向け送信packetは次で生成する。`publish` branchのbase commit/treeを与える通常経路では、全payloadがcall予算内なら `transport-root-tree.json` が全chunk本文とmanifestを含む唯一の大容量 `create_tree` callとなる。超過時だけ `upload-group-*.json` が生成され、互いに独立しているため並列送信できる。group uploadはblob objectをmaterializeするためだけに使い、その返却tree SHAは次工程へ渡さない。最後の `transport-root-tree.json` はローカル算出済みblob OIDを参照し、chunks subtreeとmanifestをpublish treeへ直接接続する。

```bash
python scripts/publish_request.py connector-plan \
  --manifest /tmp/space-idle-publish.patch \
  --github-repository naro0216n-collab/Space-Idle \
  --publish-base-commit <current-publish-head> \
  --publish-base-tree <current-publish-tree> \
  --target-remote-head <current-target-head>

# single-create-tree-publish: transport-root-tree.json を1回実行する。
# parallel-upload-then-create-tree-publish: upload-group-*.json を並列実行後、
#   transport-root-tree.json を1回実行する。
# 正常系ではchunks-tree assembly、upload返却SHAの受け渡し、個別verify callを行わない。
```

`connector-plan` に現在の `publish` branch commit/treeと、直前に取得したtarget branch HEADを与える。helperはtarget HEADがmanifestの `base-sha` と一致することを機械確認してから、通常publishに必要な大容量送信を `transport-root-tree.json` へ集約する。全payloadが収まる場合、GitHub callは target branch HEAD確認1回、publish branch HEAD/tree取得1回、root tree作成、transport commit作成、publish ref更新の計5回となる。返されたroot tree SHAをtransport commitへ、そのcommit SHAをref更新へ渡す2つの依存だけが残り、chunk/tree SHAをチャット側で中継しない。計画生成のために段階ごと `connector-publish-step` を呼び直す必要もない。

複数の整合したローカルcommitが未publishでも、`--target-ref`で古いcommitから順番にpublishし、対応する`--local-ref`でrecordする。publish都合でrebase/resetして履歴を組み直さない。

Gateway成功後は `.publish/receipts/<request-id>.json` を取得し、そのreceiptを使って次回基点を記録する。

```bash
python scripts/publish_request.py record \
  --manifest /tmp/space-idle-publish.patch \
  --receipt /tmp/publish-receipt.json \
  --local-ref HEAD
```

manifestにはtarget branch、remote base commit SHA、最終Git tree SHA、diff全体と各chunkのSHA-256、chunks subtreeの期待Git OID、commit message、転送サイズ情報を含める。chunkファイルはBase64本文そのものを正準bytesとし、末尾改行や空白を付加しない。generator、chunk blob OID、最終chunks tree OID、Gateway digest検証は同一bytesを扱い、transport途中の改行正規化に依存しない。gzip+Base64化したbinary diffまたはGit bundle本体は標準8 KiB chunkへ分離するが、これはConnector call数を決める単位ではない。`connector-plan` は実際にGitHub actionへ渡す `action_args` だけをcompact JSONへシリアライズしてbytesを測定し、標準96 KiBの `--connector-call-budget-bytes` 内へ可能な限りpayloadを集約する。全chunkとmanifestがpublish root作成callへ収まれば1 call、超過時だけ最少数の独立groupへ自動分割する。chunk sizeはGateway側の検証・再送単位、call budgetはConnector 1呼出し全体の実測上限として別々に扱う。gzip/bundleは決定論的に生成し、同じbase/tree/messageから再prepareした場合にpayload chunkが変化しないようにする。

変更ファイル全文の再取得や個別blob SHAの目視照合は通常publishでは行わない。prepareがchunks subtree Git OIDを算出し、Gatewayがremote subtree OIDと各SHA-256を検証するため、transport完全性は機械検証する。最終内容の同一性はtarget Git tree SHAで判定する。

### Publish failure handling

- remote HEAD不一致: publishしない。remote変更を調査し、必要なら新しいartifactから再同期する。
- chunk blob、chunk subtree、chunkまたはrequest SHA不一致: 期待OIDを参照するGitHub tree作成またはGatewayが失敗し、target branchは更新されない。まず `publish_request.py verify` でローカル生成物を再検証する。正常系では返却SHAを目視比較せず、失敗したupload groupだけを再送する。
- patch適用失敗: base不一致またはrequest破損として扱い、ゲーム実装を転送都合へ合わせて変更しない。
- target tree不一致: Gatewayはcommit前に失敗する。ローカルrequest生成または転送破損を調査する。
- target branch push競合: forceしない。remote HEADを再確認する。
- Gateway自体の変更: 通常publishと分離して `temp` で検証し、固定 `publish` branchへ反映する。

native `git push` が利用できる実行環境では、それを第一選択としPublish Gatewayを経由しない。GraphQL等で同等のexact-tree・expected-head付き原子的publishがConnectorへ将来露出した場合は、Gatewayより単純なら置き換える。

ゲーム実装ファイルを直接逐次反映する `create_tree(content=...)` はGatewayが利用不能な場合のfallbackとする。通常Gateway transportの `create_tree(content=...)` は圧縮済みchunkだけをまとめてGit object化するために使い、ゲーム実装ファイルを直接逐次更新する用途とは区別する。Contents APIによる実装ファイルの逐次commitは通常工程にしない。

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
