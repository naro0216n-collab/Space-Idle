# Development

GitHub の `main` ブランチを開発上の正準ソースとする。配布用 zip はスナップショットであり、以後の変更元にはしない。

## Requirements

- Python 3.11+
- pytest
- WebUI受入試験を実行する場合: Playwright 1.57+ / Chromium

## Local setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -U pip pytest
```

E2Eを実行する場合:

```bash
python -m pip install 'playwright>=1.57,<2'
python -m playwright install chromium
```

## Validation

```bash
pytest -q
python playwright/acceptance.py
```

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
