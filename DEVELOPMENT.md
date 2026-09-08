# Development

GitHub の `main` ブランチを開発上の正準ソースとする。配布用 zip はスナップショットであり、以後の変更元にはしない。

## Requirements

- Python 3.11+
- pytest
- WebUI受入試験を実行する場合: Playwright 1.57+ / Chromium または WebKit

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

## Validation

```bash
pytest -q
SPACE_IDLE_BROWSER=chromium SPACE_IDLE_E2E_TRANSPORT=direct python playwright/acceptance.py
```

通常環境では受入試験を `direct` で実行し、ブラウザから実際のHTTP Serverへ接続する。localhostアクセスが制限される特殊な実行環境だけ `SPACE_IDLE_E2E_TRANSPORT=bridge` を使用する。`bridge` は製品経路ではなく、制約環境でUIロジックを検証するための代替経路である。

## iPad development server

Windowsでは `start_ipad_server.bat`、macOS/Linuxでは `start_ipad_server.sh` を利用する。
同一LAN上の通常サイズiPadから、PCのLAN IPv4とport 8765へSafariで接続する。

```text
http://<PC LAN IPv4>:8765/
```

WebUIは通常サイズiPadの横持ちを基準とし、iPad mini向け最適化は行わない。縦持ちでは横持ち用レイアウトを維持する。

## Git workflow

- `main`: 統合済み・テスト通過状態
- 変更は目的別ブランチで行い、可能な限りPRで`main`へ統合する
- ゲーム性評価段階では旧仕様・旧Save互換を目的化しない
- テストは暫定バランス値より不変条件・状態遷移・境界整合性を優先する

## GitHub validation

GitHub Actionsを、チャット実行環境固有のネットワーク・ブラウザ制約から独立した再現可能な外部検証環境として使用する。`main`とPRでは以下を並列実行する。

- Ubuntu / Python 3.11: unit・architecture tests
- Ubuntu clean install: repository外からimportと`space-idle-api` entry pointを検証
- Windows: 同梱`start_ipad_server.bat`を実起動し、`0.0.0.0:8765`待受、WebUI、API、非loopback IPv4経由の到達性を確認
- Chromium: browser → HTTP Server → API → SimulationをbridgeなしでE2E検証
- macOS WebKit: 同じdirect HTTP経路をiPad風touch/viewport/UAで検証

public repositoryの標準GitHub-hosted runnerを使用し、large runnerは使用しない。Actions artifactとcacheは通常CIでは常用せず、GitHub側のstorage quotaに開発フローを依存させない。E2E結果は標準出力にもJSONで記録される。

Playwright WebKitは物理iPad Safariそのものではないため、iPadのスリープ、実LAN、Windows Firewall、実タッチ性能などの端末固有事項は実機試験で確認する。
