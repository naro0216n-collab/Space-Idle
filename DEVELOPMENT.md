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
git clone source-artifact/repository.bundle space-idle-local
cd space-idle-local
git checkout develop

test "$(git rev-parse HEAD)" = "$(cat ../source-artifact/.source-commit)"
test "$(git rev-parse 'HEAD^{tree}')" = "$(cat ../source-artifact/.source-tree)"
python scripts/publish_manifest.py init \
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

## Deterministic publish procedure

GitHub Connectorを使用する場合は、GitHub上で実装を再構成せず、ローカルで成立した最終Git treeを転送する。通常publishは次の順序に固定する。

1. ローカル変更を整合した単位としてcommitし、working treeをcleanにする。
2. `python scripts/publish_manifest.py prepare` を実行する。
3. publish直前にremote `develop` HEADを一度だけ確認し、manifestの `base_remote_commit` と一致することを確認する。不一致ならforceせず調査する。
4. manifestの変更対象だけを転送する。
   - `M` / `A`: ローカルblob内容をGitHub blobとして登録する。
   - `D`: 新treeで対象pathを削除する。
5. GitHubが返したblob SHAをmanifestの `blob_sha` と比較する。不一致のファイルが1つでもあればtreeを作らずpublishを中断する。正常ファイルを再取得して全文照合しない。
6. remote base treeを基に1つのtreeを作る。GitHub tree SHAがmanifestの `target_tree` と一致しなければcommitを作らず調査する。
7. そのtreeから1つのcommitを作り、確認済みremote HEADをparentにする。
8. `develop` refを `force=false` で1回だけ更新する。
9. ref更新成功後、remote commitとtreeをローカルpublish stateへ記録する。

```bash
python scripts/publish_manifest.py record \
  --remote-commit <published-remote-commit> \
  --remote-tree <published-tree>
```

このpublish stateにより、Connectorが作るremote commit SHAとローカルcommit SHAが異なっても、次回publishでは前回publish済みtreeから現在のローカルtreeまでの変更だけを抽出できる。

### Publish failure handling

- remote HEAD不一致: `force`しない。予期しないremote変更として差分を調査する。
- blob SHA不一致: そのファイルだけ転送を再試行する。tree/commit/refへ進まない。
- tree SHA不一致: path、file mode、削除、blob SHAを確認する。commitへ進まない。
- commit作成後にref更新失敗: orphan commitは放置可能。remote HEADを再確認し、競合原因を調査する。
- 大きなファイルの転送失敗を理由にゲームコードやモジュール境界を変更しない。publish transportの問題として扱う。

`update_file` / `create_file` / `delete_file` によるファイルごとの逐次commit、patch自己適用workflow、転送専用branch、追加worktreeは通常publishに使わない。

native `git push` が利用できる実行環境では、それを第一選択としてよい。現在の制約環境でGitHub Connectorを使う場合は上記手順をfallbackとして使用する。

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
- 上記以外のbranchは作らない。
- ゲーム本体version変更と `develop` → `main` 統合はユーザー承認後だけ行う。

## iPad development server

Windowsでは `start_ipad_server.bat`、macOS/Linuxでは `start_ipad_server.sh` を利用する。同一LAN上の通常サイズiPadから、PCのLAN IPv4とport 8765へSafariで接続する。

```text
http://<PC LAN IPv4>:8765/
```

Playwright WebKitは物理iPad Safariそのものではないため、iPadのスリープ、実LAN、Windows Firewall、実タッチ性能などの端末固有事項は実機試験で確認する。
