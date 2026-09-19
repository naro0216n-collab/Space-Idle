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

実ブラウザ、clean install、OS差などローカル環境で十分再現できない検証は、対応するテストも変更単位に含めてGitHub CIで実行する。ローカルで実行できないことを理由に、正準契約上必要な検証自体を省略しない。

Publish Gateway、publish helper、CI/E2E harnessなど開発環境そのものの契約テストは `development_tests/` に物理分離し、ゲーム本体の `tests/` と通常suiteには含めない。開発基盤を変更した場合は `pytest -q development_tests` を基準とし、変更責務が明確に限定される場合は現在のsuite構成から関連targetだけを選んでよい。特定test file名を開発手順上の恒久契約にはしない。実ブラウザの受入シナリオは `playwright/` に置き、この開発基盤テストとも分離する。

## Publish procedure

GitHub反映の入口は差分種別で決める。

- `.github/workflows/**` を含まない通常変更は `scripts/publish_request.py` を使用する。
- `.github/workflows/**` だけを変更する場合は後述の Workflow maintenance procedure を使用する。
- `.github/workflows/publish-gateway.yml` は、先に Publish control maintenance で固定 `publish` branchへ同一blobを反映済みの場合に限り、通常publishへ同梱できる。Gatewayがcontrol blobとの一致を機械検証する。
- 上記以外のworkflowと通常変更が混在する場合は、責務ごとにcommitを分け、通常変更を先にpublishする。

`publish` branchはPublish Gateway専用のtransport branchであり、通常開発や統合には使用しない。

### Normal develop publish

通常publishは次の一本道で実行する。

1. 変更を責務としてまとまったlocal commitにする。
2. `prepare`で現在の `HEAD` をpublish対象として固定する。
3. GitHubのheads一覧を1回取得し、`develop` HEADと`publish` HEADを同じ観測から `connector-plan` へ渡す。`publish` treeはsource-snapshotに保持した正準baseを使うため再取得しない。
4. `connector-plan` が16 KiB logical chunkを `content` として含む `GitHub.create_tree` packet群を、1 callあたり144 KiB未満になるよう複数batchへ分割して生成する。各packetにはlocal Gitで事前計算した `expected_tree` が含まれる。
5. tree packetを順番どおり実行する。各返却tree SHAはpacketの `expected_tree` とその場で比較し、一致時だけ次packetへ進む。helperへ返却SHAを戻して次packetを生成し直さない。
6. 全tree batch成立後、`connector-plan` が同時に生成済みの `GitHub.create_commit` packetを実行する。commitは最終 `expected_tree` と観測済み `publish` HEADを親に持つ。
7. `GitHub.create_commit` の返却commit SHAをそのまま1回のnon-force `GitHub.update_ref` に渡して固定 `publish` branchを進める。commit SHAをhelperへ戻す中間stageは置かない。これがGatewayを起動する唯一のbranch更新である。
8. 当該transport commitのPublish Gateway runが `completed / success` になったことを1回のrun観測で確認し、そのrun ID・conclusion・transport commitを `record` へ渡す。
9. Fast CIは結果が次の判断に必要になった時点で確認する。

```bash
python scripts/publish_request.py prepare
python scripts/publish_request.py connector-plan \
  --develop-head <current-develop-head> \
  --publish-head <current-publish-head>
# generated tree packet群を順番に実行し、各返却SHA == packet.expected_tree を確認
# generated create_commit packetを実行
# create_commit返却SHAをそのまま GitHub.update_ref(branch=publish, force=false) へ渡す
python scripts/publish_request.py record \
  --gateway-transport-commit <publish-transport-commit> \
  --gateway-run-id <publish-gateway-run-id> \
  --gateway-conclusion success
```

transportは `.publish/transport/<target>/0000.b64` から始まる固定slotを使用する。bundleのBase64表現を16 KiB固定logical chunkへ分割するが、chunkごとの `create_blob` は行わない。`connector-plan` は各chunk本文を `create_tree` entryの `content` として直接指定し、Connectorの1 call上限144 KiB未満に収まるよう複数tree batchへpackする。transport全体は最大256 partまで扱い、144 KiBはtransport全体の上限ではなく単一Connector callの上限とする。

helperはsource-snapshot由来の `publish` base tree、各chunk本文、削除対象pathから各batch後の期待root tree SHAをlocal Gitで事前計算する。第2batch以降は直前batchの期待treeをbaseとする。返却SHAが期待値と異なる場合は、そのcallに使用した転記情報を正しい入力の候補として保持せず、次batchへ進まない。正常系ではGitのcontent-addressed object identityを利用し、tree write間にhelper round-tripを挟まない。

初回移行時に旧 `.publish` transport artifactが残っている場合も、固定slot以外の旧artifactを同じunreferenced tree組立の中で削除し、部分的なremote状態を作らない。

Gatewayはtransport commitをcheckoutした後、そのworking treeにある固定slotだけを読む。GitHub Contents / Blob APIでpayloadを再取得せず、連番partを連結してbundleを検証し、bundleからpublish commit、base、target treeを導出する。checkout済み `origin/<target>` がbundle parentと一致することをローカル確認した後、exact publish commitをnon-force pushする。成功したpush後の `ls-remote` /再fetch、receipt書込み、Fast CI pending status書込みは行わない。Fast CIの明示dispatchは `GITHUB_TOKEN` pushから別workflowが自動起動しないため維持する。

#### Transaction continuation and cancellation

active transactionが存在する場合は、その記録済みexecution planから続行する。prepared targetを `publish` refへ出す前に取り消す場合だけ、heads一覧を1回観測し、`develop` と`publish` の両HEADがtransaction開始時から不変であることをhelperへ渡して `cancel` する。tree/commit objectの作成だけでrefが未更新なら、生成済みobjectはunreferenced objectとして扱いcancel可能である。transaction directoryを手動削除しない。

```bash
python scripts/publish_request.py cancel \
  --develop-head <current-develop-head> \
  --publish-head <current-publish-head>
```

#### Pre-ref packet retry

各 `create_tree` packetの返却SHAをpacket内の `expected_tree` と比較する。一致しない場合は、そのpacketから先へ進まず、そのcallに使った手動転記を再利用対象から外す。clipboard、scratch text、手元に保持した引数や部分文字列も破棄し、失敗callから得た情報は「現在の転記を再利用できない」という事実だけとする。

再試行はactive transactionに記録済みのgenerated packet fileを正本として開き直すところから始める。packet全体を先頭から新しく転記してtool callを組み立て、`expected_tree`、logical chunkのpath・本文・16 KiB境界、batch順序は正本packetのまま使用する。返却SHAが `expected_tree` と一致した場合だけ次packetへ進む。新規転記でも不一致なら、そのcallの転記情報も同様に破棄し、generated packetからもう一度新しく組み立てる。remote tree / blobの内容比較や失敗転記の部分修正はこのretry経路の入力にしない。正本packetからの新規転記を繰り返しても継続的に成立しない場合だけ、Connector / helper経路の開発基盤障害として扱い、active transactionを保持したまま開発基盤側のrecoveryへ移る。

正常系のための `connector-blob` / `connector-tree` / `connector-commit` のような返却SHA中継stageは置かない。返却tree SHAとの比較は生成済みpacket自身の `expected_tree` で完結し、commit返却SHAはそのままnon-force ref updateへ渡す。

ref更新後の一時的なGateway障害では、同じtransport commitのworkflow rerunを用いる。target移動やcontrol不一致など意味のあるGateway failureは原因を解消してから次のpublish判断を行う。

### Workflow maintenance procedure

`.github/workflows/**` だけを変更したcommitは `scripts/workflow_maintenance.py` で `develop` へ反映する。

1. workflow-only commitを現在の `HEAD` として `prepare` する。
2. remote `develop` HEADを1回取得し、そのSHAを `connector-plan` に渡す。
3. helperが変更本文を `content` として持つ `create_tree` packet群、最終 `create_commit` packet、non-force ref updateの実行条件を一度に生成する。144 KiBを超える変更は複数tree batchへ分割する。
4. tree packet群を順番に実行し、各返却SHAをpacketの `expected_tree` と比較する。不一致時は `Pre-ref packet retry` に従って保持中の転記情報を破棄し、generated packetから新規転記する。成立後に生成済みcommit packetを実行し、その返却SHAを直接non-force `develop` ref updateへ渡す。中間helper round-tripやcommit再fetchは行わない。
5. ref update成功後、同じcommit SHAを `record-update --result success` へ渡す。追加のremote HEAD/tree再取得は行わない。
6. 成功後は新しい `develop` のFast CIが生成した `source-snapshot` からrepoを復元し、`publish_request.py init` で通常開発へ戻る。

```bash
python scripts/workflow_maintenance.py prepare
python scripts/workflow_maintenance.py connector-plan \
  --develop-head <current-develop-head>
# generated tree packet群 → create_commit → non-force develop ref update を順番に実行
python scripts/workflow_maintenance.py record-update \
  --commit-sha <create-commit-result-sha> \
  --result success
```

### Publish control maintenance procedure

Publish Gateway control plane (`.github/workflows/publish-gateway.yml` とvalidator) は `scripts/publish_control_maintenance.py` で固定 `publish` branchへ反映する。通常game/source publishとは混在させない。

1. control plane変更をcommitし、clean worktreeで `prepare` する。
2. remote `publish` HEADを1回観測して `connector-plan` へ渡す。base treeはsource-snapshot由来のlocal publish stateを使うため再取得しない。
3. helperがcontrol file本文を `content` として持つ `create_tree` packet群と最終 `create_commit` packetを一度に生成する。各batchの期待tree SHAはlocal Gitで事前計算する。
4. tree packet群を順番に実行し、各返却SHAをpacketの `expected_tree` と比較する。不一致時は `Pre-ref packet retry` に従って保持中の転記情報を破棄し、generated packetから新規転記する。成立後にcommit packetを実行し、返却commit SHAを直接non-force `publish` ref updateへ渡す。中間helper round-tripやcommit object再fetchは行わない。
5. `update_ref` 成功後は同じcommit SHAを `record-update --result success` へ渡す。追加のremote HEAD/tree再取得は行わず、helperがnormal publish stateの `publish` baseを更新する。

```bash
python scripts/publish_control_maintenance.py prepare
python scripts/publish_control_maintenance.py connector-plan \
  --publish-head <current-publish-head>
# generated tree packet群 → create_commit → non-force publish ref update を順番に実行
python scripts/publish_control_maintenance.py record-update \
  --commit-sha <create-commit-result-sha> \
  --result success
```

control planeでも正常系のための個別 `create_blob` と返却OID中継stageを設けない。content-addressed tree identityで転送内容を検証し、廃止したcontrol componentは同じcontrol treeから削除して新旧control経路を併存させない。

### Publish recovery

pre-refの `create_tree` 期待SHA不一致は `Pre-ref packet retry` に従い、失敗した転記情報を破棄してgenerated packetから新規転記する。pre-ref recoveryの入力は正本packetと返却SHAの一致判定に限定し、正本packetの新規転記を繰り返しても成立しない場合だけConnector / helper経路の開発基盤障害として扱う。ref更新後にGateway runが一時的理由で失敗した場合は、同じtransport commitのGitHub Actions rerunを使用する。別のrequest/generationを書き足して復旧しない。

Gatewayがtarget branch移動、trusted workflow不一致、bundle不整合等の意味のある条件で停止した場合は、active transactionと該当runを証拠として原因を調査する。remote target状態やpublish対象そのものが変わった場合はtransport recoveryではなく、新しいsource stateから次のpublishを判断する。

Workflow maintenanceで問題が発生した場合も、helper stageが生成したpacketと検証結果を正本として処理する。

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

Browser E2Eのscenario集合はworkflowが `playwright/run_suite.py <scenario...>` へ明示的に渡す。workflow YAMLをruntimeで再解析したり、完了markerやsecondary entrypointで重複実行を回避する制御は置かない。runnerは同一Python processでscenario moduleを順に読み込むが、各scenarioはPlaywright/browser process、BrowserContext、GameRuntime、save用temp directory、HTTP serverをそれぞれ新規作成し、browser固有状態を共有しない。Fast CIのChromium smokeは短時間で再現できる主要browser wiringを検証し、WebKit等のOS・engine差はFull Validationで検証する。runnerはbootstrap、各scenario、全体の実時間をCI logへ出力し、長期化時にsetupとscenario本体を切り分けられる状態を維持する。

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
