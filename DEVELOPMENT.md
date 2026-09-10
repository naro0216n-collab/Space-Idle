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
2. `scripts/publish_request.py`で、前回publish済みtreeから現在HEAD treeまでのbinary diffを固定長chunkと小さなmanifestへ生成する。
3. publish直前にremote対象branch HEADを一度だけ確認し、manifestの `base-sha` と一致することを確認する。不一致ならrequestを送らず差分を調査する。
4. GitHub Connectorで `publish` branchの `.publish/chunks/` に必要chunkを更新し、最後に `.publish/request.patch` manifestを更新する。chunk更新だけではGatewayを起動しない。
5. Publish Gatewayは各chunk digest、request digest、remote base SHA、patch適用後のGit tree SHAを検証し、すべて一致した場合だけ通常のnon-force pushで対象branchを更新する。
6. Gateway成功後は対象branchのremote commit/treeを確認し、ローカルpublish stateへ記録する。
7. Gatewayは対象branch更新後にFast CIを `workflow_dispatch` し、実ブラウザ・clean install・次回用Git bundle artifactを検証する。

request生成例:

```bash
python scripts/publish_request.py prepare \
  --target-branch develop \
  --target-ref HEAD \
  --output /tmp/space-idle-publish.patch
```

複数の整合したローカルcommitが未publishでも、`--target-ref`で古いcommitから順番にpublishし、対応する`--local-ref`でrecordする。publish都合でrebase/resetして履歴を組み直さない。

Gateway成功後:

```bash
python scripts/publish_request.py record \
  --remote-commit <published-remote-commit> \
  --remote-tree <published-tree> \
  --local-ref HEAD
```

manifestにはtarget branch、remote base commit SHA、最終Git tree SHA、diff全体と各chunkのSHA-256、commit messageを含める。gzip+Base64化したbinary diff本体は固定長chunkへ分離する。manifestを最後に更新することで、不完全なchunk転送では対象branchを更新しない。

変更ファイル全文、個別blob登録、個別blob SHA照合は通常publishでは行わない。Git tree SHA一致を最終内容の同一性判定とする。

### Publish failure handling

- remote HEAD不一致: publishしない。remote変更を調査し、必要なら新しいartifactから再同期する。
- chunkまたはrequest SHA不一致: Gatewayは適用前に失敗する。該当chunkだけ再転送し、manifestのrequest-idを更新して再検証する。
- patch適用失敗: base不一致またはrequest破損として扱い、ゲーム実装を転送都合へ合わせて変更しない。
- target tree不一致: Gatewayはcommit前に失敗する。ローカルrequest生成または転送破損を調査する。
- target branch push競合: forceしない。remote HEADを再確認する。
- Gateway自体の変更: 通常publishと分離して `temp` で検証し、固定 `publish` branchへ反映する。

native `git push` が利用できる実行環境では、それを第一選択としPublish Gatewayを経由しない。GraphQL等で同等のexact-tree・expected-head付き原子的publishがConnectorへ将来露出した場合は、Gatewayより単純なら置き換える。

`create_tree(content=...)` はGatewayが利用不能な場合のfallbackとする。個別 `create_blob`、Contents APIによる実装ファイルの逐次commitは通常工程にしない。

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
