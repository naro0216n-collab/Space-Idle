# Development

## 作業の前提

- `main`：ユーザー承認済みの正準branch。明示的な承認なしに更新しない。
- `develop`：通常開発の共有正本。検証済みの責務単位をpublishする。
- `publish`：Publish Gateway専用のtransport control branch。ゲーム開発には使わない。
- `temp`：ユーザー指定時、またはworkflow・publish経路自体を隔離検証するときだけ使う。

通常の実装・検索・テスト・commitはローカルrepoの`develop`で行う。通常開発で追加branch・worktreeを作らず、publishのために成立済みcommitをrebase・resetしない。ゲーム本体version変更および`develop`から`main`への統合は、ユーザー承認後だけ行う。

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

`init`がartifactの基点を記録し、repo-local Git identityとpublish基点を設定する。復元に失敗したら別の取得・復元方式に切り替えず、source-snapshotの生成・取得経路を解決する。最新のローカル環境が構築済みなら継続利用する。

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

DomainからApplication、Persistence、Content、UIまで、変更した責務に必要な層を接続して検証する。テストの選定・改廃は`docs/development-principles.md` §6に従い、現在の不変条件・状態遷移・保存則を優先する。個別修正ごとにテストやpublishを細分化しない。

```bash
git diff --check
python scripts/local_test_run.py start -- -q --durations=20
python scripts/local_test_run.py status <startで返されたrun_id>
```

ローカルpytestは`scripts/local_test_run.py`から実行する。`start`や実行ツールのtimeoutをpytestの終了結果と解釈しない。`status`で実際の終了コードと判定結果を確認する。対象を絞る場合は`start --`以降へpytestのtargetを指定する。

Publish Gateway、helper、CI/E2E harnessの変更はゲームの通常テストと分離した`development_tests/`で検証する。ブラウザ受入Scenarioは`playwright/`に置く。実ブラウザ、clean install、OS差等はGitHub CIで検証し、ローカル実行不可を理由に必要な検証を除外しない。

## `develop`へのpublish

### 使用する経路

| 変更内容 | 標準helper | 反映先 |
|---|---|---|
| 通常のゲーム・開発基盤変更 | `scripts/publish_request.py` | Publish Gateway経由で`develop` |
| `.github/workflows/**`だけの変更 | `scripts/workflow_maintenance.py` | `develop` |
| Publish Gateway control planeの変更 | `scripts/publish_control_maintenance.py` | `publish` |

Publish Gateway workflow自体を変更するときは、control planeの更新を先に完了する。その他のworkflow変更と通常変更は責務ごとにcommitを分けて反映する。helperが出力する手順とpacketを記載順に使い、独自の操作順変更・代替transport・手動照合を追加しない。

### 一時ファイルの配置

**通常publishのConnector受け渡しに使用する一時ファイルは、必ずChatGPT Libraryの`/temp/`フォルダで扱う。** ローカルrepo内の`temp`ディレクトリやGitの`temp` branchとは異なる。

固定Launcherが呼び出すExecutorが、必要な`/temp/`フォルダの作成、原本packetの一時登録・読取、登録ファイルの削除（Libraryのゴミ箱への移動）を自動実行する。**一時ファイルはGitHub更新前に削除される。** 実行者がLibraryへ手動登録したり、別フォルダへ中継したり、手動転記・ハッシュ照合したりしない。登録・読取・削除のいずれかが失敗した場合は、GitHub更新を進めず、保持したtransactionを規定の手順で再開する。

ローカルのartifact、Git bundle、`.git/`内に保持するtransaction記録は、このLibrary一時ファイルとは別の作業データである。

### 通常publishの手順

1. 責務単位の関連検証を完了し、ローカル`develop`へcommitする。
2. `python scripts/publish_request.py prepare`を実行する。
3. **publish直前に**GitHubのheads一覧を1回取得し、その時点の`develop`と`publish`のHEADを`connector-plan`へ渡す。
4. `connector-plan`が返す`execution_index`の絶対パスを`INDEX_PATH`へ指定し、`scripts/publish_connector_launch.js`の固定sourceを**改変せず1回の`functions.exec`で実行**する。Libraryの一時ファイル管理とGitHub transportはLauncher/Executorに委ねる。
5. 返却されたtransport commitに紐づくPublish Gatewayの`completed / success`を確認し、transport commit SHA、run ID、結論を`record`へ渡す。Gateway未完了の間はtransactionを保持し、独立したローカル作業は進めてよい。
6. **次のpublish直前に**前回Fast CIの結果を確認する。失敗している場合は原因を修正してから次のpublishを行う。

```bash
python scripts/publish_request.py prepare
python scripts/publish_request.py connector-plan \
  --develop-head <current-develop-head> \
  --publish-head <current-publish-head>
# connector-planのexecution_indexをINDEX_PATHへ渡し、
# scripts/publish_connector_launch.jsをfunctions.execで1回実行
python scripts/publish_request.py record \
  --gateway-transport-commit <transport-commit> \
  --gateway-run-id <gateway-run-id> \
  --gateway-conclusion success
```

`functions.exec`では、`const INDEX_PATH = '<execution_index>';`を先に定義してから、`scripts/publish_connector_launch.js`の内容をそのまま実行する。入力sourceやpacketの内容を手動展開・修正・再構築しない。ファイル数やtransaction規模で手順を変えない。

### 中断・失敗時の再開

| 状態 | 対応 |
|---|---|
| `publish` ref更新前に中断 | 保存済みtransactionの`execution_index`で固定Launcherを再実行する。検証不成立なら原因を解消し、同じtransactionを保持する。 |
| `publish` ref更新済み | 該当transport commitのGateway結果を確認する。成功なら`record`する。Gatewayの一時的障害は同じrunの再実行で扱う。 |
| `record`済み | 次のpublishへ進める。直前Fast CIの結果は次のpublish判断時に確認する。 |

ref更新前のtransactionを取り消す場合だけ、最新の`develop`・`publish` HEADを取得して`cancel`へ渡す。helperが取消を拒否した場合は、独自のref更新や履歴の作り直しで迂回しない。

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

Maintenanceのpacket実行・照合が失敗した場合は、そのtransactionの規定手順で再実行する。ref競合やGateway検証失敗では、原因を解消するまで次の更新を行わない。

## CI

- **Fast CI**：`develop`へのpublish後、Unit / architecture、clean package install、Chromium direct HTTP smoke、次回復元用`source-snapshot`を検証する。Fast CIは承認ゲートではない。同一runを継続pollせず、次のpublish判断に必要なときに結果を見る。
- **Full Validation**：`main`反映候補、ユーザー要求、Persistence schema変更、Simulation Orchestrator処理順変更、package / server / launcher変更、Fast CIで扱わないOS・ブラウザ検証に使用する。Gameplay、Windows、WebKitを通常Fast CIへ常設しない。

Browser E2Eは`playwright/run_suite.py <scenario...>`へ対象Scenarioを明示して実行する。各Scenarioは独立したBrowserContext、GameRuntime、保存用一時ディレクトリ、HTTP serverを使用し、状態を共有しない。

## iPad development server

Windowsでは`start_ipad_server.bat`、macOS/Linuxでは`start_ipad_server.sh`を実行し、同じLAN上のiPadからPCのLAN IPv4とport 8765へ接続する。

```text
http://<PC LAN IPv4>:8765/
```

Playwright WebKitは実機iPad Safariと同一ではない。端末固有のSleep、LAN、Firewall、タッチ操作は実機で検証する。
