# 宇宙開発Idleゲーム 開発原則

## 1. 目的

本書は、`docs/design.md` と `docs/architecture.md` で定めたゲームとシステムを、開発中の局所実装へ引きずられず継続的に実現するための変更・実装方針を定める。

本プロジェクトはゲーム性評価段階にある。現行コード、既存テスト、fixture、暫定Content、過去の実装コストは、それ自体を将来設計の前提とはしない。変更時には、現在あるものへ最小差分を足すことより、変更後の全体が一貫した責務・状態モデル・ゲームループになることを優先する。

`design.md` はゲームとして何を成立させるか、`architecture.md` はそれをどの責務境界で表現するかを定める。本書は、それらを変更・実装する際の判断順序を定める。

---

## 2. 開発の基本原則

変更要求は、既存実装へ追加する差分ではなく、現在のシステム全体を再評価する入力として扱う。

まず「変更後にどのようなゲーム上の意思決定とDomain状態が成立すべきか」を定義し、その結果から必要な責務境界、状態所有、処理順、Application契約、Persistence、UI表示、Content構造を導出する。

現行構造が新しい目的に適さない場合は、既存モジュール、API、State、Content、テストを維持するための互換層を積み上げず、より妥当な構造へ正面から更新する。局所的には大きな変更でも、将来の変更点が予測可能になり、責務が単純になるならその方を選ぶ。

一つの不具合や一つの失敗ケースだけを解消することを完了条件にしない。修正後に、同じ原因が別Domainや別状態遷移へ残っていないか、変更によって新しい重複責務・特殊分岐・暗黙依存を作っていないかまで確認する。

---

## 3. 変更時の判断順序

### 3.1 目的と不変条件を定める

実装前に、今回成立させるゲーム上の結果と、変更後も守る一般則を整理する。

例：

- 何をプレイヤー判断として残すか
- どのStateがどのDomainに所有されるか
- どのResource / Capability / Operationが共通モデルで扱われるか
- 何が保存対象で、何が派生状態か
- どのblockerをApplicationが説明すべきか
- 同順位処理や同一条件で決定論をどう保つか

暫定的な施設名、数値、攻略順は、設計目的そのものと区別する。

### 3.2 影響範囲を全体から確認する

変更対象ファイルだけでなく、少なくとも以下の関係を確認する。

- Domain間の責務境界
- Definition / State分離
- Simulation Orchestratorの処理順
- Resource / Capability / Inventory会計
- Application Command / Query
- Persistence / Validation
- Content Definition
- UI / HTTP境界
- Offline Progress
- 将来のLocation、Vehicle、Facility、Research等の追加方法

既存の境界が変更後も妥当かを先に判断し、既存構造を所与として修正箇所を探さない。

### 3.3 変更後の全体像を決める

複数箇所に個別対応を足す前に、共通モデルで問題を一度だけ表現できるかを検討する。

特定Location、特定Vehicle、特定Facility、特定fixtureだけに必要な条件が現れた場合は、まず一般モデルの不足か、Contentで表現すべき差か、Domain境界の誤りかを調べる。

既存概念が新設計と重複・矛盾する場合は、旧概念を残したまま新概念を並設せず、State、Command、Query、Persistence、UIを含めて旧経路を撤去する。

### 3.4 縦方向に実装する

Domainだけ、UIだけ、Saveだけを局所的に完成扱いせず、変更した責務が必要とする層を一貫して更新する。

```text
Domain model
→ Simulation / orchestration
→ Application Command / Query
→ Persistence / Validation
→ Content
→ UI / HTTP
```

各層で同じルールを再実装せず、判断は所有Domainへ集約し、外側は契約を利用する。

### 3.5 実装後に広域監査する

機能が動作した時点で終えず、変更範囲の周辺を含めて監査する。

確認対象：

- 同じ概念を複数Domainが所有していないか
- 旧概念・互換wrapper・一時的な変換層が残っていないか
- 登録順、呼出順、ID名、Location名への隠れた依存がないか
- Queryと実行系が同じ判定を使っているか
- Save / Loadで派生状態を二重管理していないか
- UIがDomainロジックを再計算していないか
- 一件の修正のために一般モデルが不自然に複雑化していないか
- 将来同種Contentを追加するときにCore変更を要求する構造になっていないか

この監査で構造上の問題が見つかった場合は、当初の変更範囲外でも原因が同じなら合わせて正す。

---

## 4. 局所最適を全体改善とみなさない

あるScenarioが進む、ある画面が動く、あるテストが通る、ある処理が高速になる、という局所結果だけでは設計の妥当性を証明しない。

変更を採用するには、少なくとも次を確認する。

- 状態所有が明確になったか
- 責務重複が減ったか、増えていないか
- 別Domainとの会計・状態遷移が整合しているか
- 同じ問題へ別の例外を追加する必要が生じないか
- 将来のContent追加で同じCore修正を繰り返さずに済むか
- プレイヤーの意思決定をCoreが暗黙に代行していないか
- ボトルネックを消すのではなく、正しく発生・観測・操作できる構造になっているか

局所改善が全体の複雑性を増す場合は、局所改善を採用せず設計を再検討する。

---

## 5. 開発中Contentの扱い

施設、Vehicle、Research、Recipe、初期在庫・Fleet配分、生産率、Route所要日数、暫定Transport / Lane設定等は、ゲーム性評価中は変更される実験変数である。

これらを用いたGameplay結果から一般的な欠陥が見つかることはあるが、現在の数値や一つの攻略経路を成立させるためにCoreを最適化しない。

例えば特定Scenarioで資材不足が起きた場合、直ちに供給量を増やすのではなく、次を区別する。

- 意図されたゲーム上のボトルネック
- blockerやQueryが不足して判断不能なUX問題
- Resource会計や状態遷移の不整合
- Route探索や配分処理の一般的欠陥
- 単なる暫定Contentバランス

一般的欠陥だけをCore修正へ昇格させ、バランス問題はContent評価として扱う。

---

## 6. 検証・テスト・CIの位置づけ

### 6.1 テストが表すもの

テストは、現在の正準仕様から導出される契約を実行可能な形で検証するためのものとする。過去の実装手順、修正履歴、削除済み設計、ある時点の内部構造を保存する記録にはしない。

恒久テストを置くかどうかは、「このテストが失敗したとき、現在の `design.md` / `architecture.md` が要求する不変条件、状態遷移、Domain境界、Application契約のどれが破られたと言えるか」で判断する。対応する現行契約を説明できない検証は、恒久suiteへ残す根拠を持たない。

バグ修正や移行作業を契機に検証を追加する場合も、個別の事故や旧実装の不存在そのものではなく、その事故が示した一般的な契約へ検証対象を引き上げる。例えば旧class名の不存在ではなくState ownership、旧call pathの不存在ではなくApplication境界、特定順序で偶然成立したScenarioではなく登録順非依存を検証する。

### 6.2 優先して検証する契約

テストsuiteは、現在のゲームとArchitectureを長期的に守る契約へ集中させる。特に次を優先する。

- Domain invariantと状態遷移
- State ownershipとDomain間境界
- Resource / Funds / Cargo等の保存と二重計上防止
- Allocation、Service Capacity、Inventory、Logistics等のDomain間整合性
- Save / Loadでauthoritative Stateが保存され、派生Stateが正しく再導出されること
- Offline Progressと通常Simulationの意味論的一致
- Entity登録順、Domain登録順、同順位処理順に依存しない決定論
- Application Command / QueryがDomain契約を正しく公開し、UIの意思決定に必要なstate、blocker、必要条件、limiting factorを返すこと
- Content追加がGeneric Coreの特定ID例外を要求しないこと

Gameplay検証は実Application APIと実際の状態遷移を使い、複数Domainを通した契約が成立することを確認する。ただし一つの攻略順、特定Facility数、暫定初期在庫、特定の成功日数等を正準仕様へ昇格させない。

### 6.3 仕様変更時のテスト再構成

仕様・Architectureが変わった場合は、既存テストを新仕様へ機械的に追従させるのではなく、各テストが現在も有効な契約を表しているかを再評価する。

変更後の契約に対して、既存テストは次のいずれかとして扱う。

- 現在も同じ契約を検証するなら維持する。
- 契約の表現が変わったなら、新しいpublic / Domain契約へ書き換える。
- より上位の不変条件テストへ包含できるなら統合する。
- 契約自体が廃止された、暫定Content値だけを固定する、旧API・旧class・旧fixture形状だけを保存する場合は削除する。

「過去に一度壊れたから」という理由だけで個別回帰テストを永久に積み上げない。過去の不具合が恒久的な設計契約を示している場合だけ、その契約を最小限のテストで保持する。

テスト削除は品質低下とはみなさない。不要なテストを残して現行設計と矛盾する契約を固定する方が回帰リスクになる。削除・統合時は、そのテストが表していた現行契約が別の検証で十分に覆われているか、または契約自体が廃止済みであることを確認する。

### 6.4 重複と実装詳細への依存を避ける

同じDomain ruleを複数layerで同じ内容のまま繰り返し検証しない。各layerではそのlayer固有の契約を確認する。

- Domain test: invariant、state transition、allocation、保存則等のルール
- Architecture test: dependency方向、State ownership、Domain越境を含む境界契約
- Application / integration test: Command / Queryと複数Domain接続
- Gameplay / browser test: 実際の意思決定に必要な状態が一連の操作で利用可能か
- Development infrastructure test: publish、CI、package、launcher等の開発基盤契約

private helper、内部call順、現在のmodule分割、temporary adapter等は、それ自体がArchitecture契約でない限りテストの正本にしない。内部構造を変更しただけで大量のテスト修正が必要になる場合は、テストがpublic / Domain契約ではなく実装を写していないかを先に確認する。

新しいテストを追加する前に、同じ不変条件を既存テストが既に検証していないかを確認する。既存テストへ自然に統合できる場合は、個別ケースを別ファイル・別testとして増やすより契約中心に統合する。

### 6.5 Fixture・Content・Scenario

fixtureは検証したい状態を構築する入力であり、それ自体を仕様としない。テストの意味に不要な初期Scenario全体、暫定Content、ID一覧、登録数、balance値を複製しない。

数値そのものが正準契約でない場合は、特定値より関係を検証する。例えば「施設が3個ある」よりState ownership、「100日で完成する」より必要Resourceとworkに応じて進行すること、「Moonだけ到達可能」よりSpatial / Vehicle requirementから可否が導出されることを検証する。

Content固有のvalidationが必要な場合は、Generic Coreの不変条件と分離してContent validationとして扱う。Gameplay ScenarioもContent評価とCore契約検証を混同しない。

### 6.6 一時的な移行確認

大規模移行では、旧経路が残っていないこと、旧schemaが参照されていないこと、特定migrationが完了したことを一時的に確認してよい。ただしこれは移行作業の完了確認であり、そのまま恒久suiteの仕様にはしない。

移行完了後に長期的に守るべき内容がある場合は、「旧symbolが存在しない」という履歴依存の形ではなく、現在のArchitecture境界やauthoritative Stateが一意であることを検証する形へ置き換える。

### 6.7 CIと検証範囲

GreenなCIは設計妥当性の証明ではなく、選択された検証が通ったという証拠である。Redなテストも直ちに実装誤りとは限らず、正準仕様の変更に対してテスト契約が古くなっていないかを含めて原因を確認する。

変更単位では、その責務に直接関係する最小の検証から開始し、Domain横断、Persistence、Offline、Application等の影響範囲に応じて必要な検証を広げる。変更と無関係な長時間検証を毎回機械的に実行することを品質基準にはしない一方、ローカル実行不能を理由に必要な実環境検証を変更単位から除外しない。

実ブラウザ、clean package install、OS差等はGitHub CIで検証し、高速に再現できるDomain / architecture / integration検証はローカルで優先する。Gameplay evaluation、性能分析、Domain invariant、Content validation、Browser / Integration validationは目的を分け、それぞれの結果を別の契約の証明として流用しない。

テストsuiteは現在の正準仕様を効率よく検証する構成として継続的に統廃合する。テスト数、ファイル数、過去ケースの保存量そのものを品質指標にしない。

---

## 7. 完了判定

変更は、依頼された局所動作が成立しただけでは完了としない。

少なくとも以下を満たした時点で、検証可能な実装単位として扱う。

- 変更後のDomain責務とState所有が明確である
- 旧設計との重複経路・不要な互換層が整理されている
- Simulation、Application、Persistence、Content、UIが同じ契約で接続されている
- 一般モデルに特定Content由来の特殊分岐を持ち込んでいない
- 変更後のボトルネックと状態遷移をApplicationから説明できる
- Save / Load、Offline、決定論等の関連不変条件が維持される
- 周辺Domainを含む広域監査で同根の未修正箇所や新たな責務重複がない
- 現在の設計から導出された必要な検証で問題が確認されない

CI通過や特定Gameplay Scenarioの完走だけを完了判定には使わない。

---

## 8. GitHubへの反映

独立作業は原則ローカルで行い、全体整合性を確認した差分を検証可能な単位で `develop` へ反映する。

`develop` への反映単位は「テストが通ったファイル群」ではなく、「一つの責務変更がDomainから外部境界まで一貫して成立した変更」とする。複数の成立済みlocal commitが未反映でも、publish都合でrebase・reset・squashして作り直さず、責務境界ごとに順次反映してよい。

GitHubへのtransport方式はゲーム実装の構造やcommit境界を決める根拠にしない。publish対象はcommitted target treeであり、その後にworking treeで別作業を続けていても対象commitへ未commit内容を混入させない。

publish transportは実行環境ごとに一意にする。認証済みnative Gitを正式なtransportとして採用する環境では、その環境の単一publish入口が記録済みremote HEAD/treeを基点としてlocal target treeを指すcommitを生成し、non-force push後にremote ref/treeを再検証する。通常helperへnative Gitを並列サブコマンドとして露出し、Gatewayとの選択を作業者へ委ねない。

現在のConnector実行環境では、publish対象を現在の `HEAD` commitへ固定し、記録済み `develop` commitを親、local target treeをtreeに持つ決定論的commitをGit bundleへ格納してPublish Gatewayへ渡す。source-snapshotは `develop` commit/treeだけでなく生成時点の `publish` commit/treeとそのGit objectを保持し、通常publishのtransport baseを追加network readなしでローカル再構築できる状態にする。repo-localな単一active transactionを正本とし、active transaction中に別requestを開始しない。

通常transportは `.publish/transport/<target>` の固定slotだけを使用する。payloadをBase64 ASCIIの16 KiB固定logical chunkへ分割して連番partとして表現し、各chunkを独立したGit blobとしてConnectorへ転送する。helperはローカルGitで事前計算した期待blob OIDと返却OIDを機械比較し、通常系では生成packetをそのまま順番に送る。成功したchunkは確定済みとして再送しない。

返却OIDが不一致となったchunkだけはlogical chunkを変更せず、転記単位を1/2ずつ細分化する。最初のretryは8 KiBずつ、継続失敗時は4 KiB、2 KiB、1 KiB…と同一本文を連続区間で読み出し、順番どおり連結して同じ16 KiB chunkとして再送する。細分化するのはLLMの転記単位だけであり、transport path、本文、期待OID、logical chunk境界は変えない。helperが一致を確認したら直ちに次chunkへ進む。旧 `.publish` transport artifactは固定slotへ移行するtreeで削除し、同責務の新旧経路を併存させない。

全chunkのblob OIDが一致した後だけ、helperは確定したblob SHAを `create_tree` の各entryへ指定する。tree組立時に本文を再転記せず、Git object IDを参照させる。helperはsource-snapshot由来の `publish` base treeと確定blob OIDから期待root tree SHAをローカルGitで事前計算し、`create_tree` 返却SHAも機械比較する。通常運用はhelperが提示するpacketとConnectorの返却SHAだけを順に受け渡し、一致後に次stageへ進む。

期待tree成立後だけ `create_commit` → non-force `update_ref` を行い、`publish` branchは1回だけ進める。Gatewayはcheckout済み固定slotを直接読み、連番partを連結してbundleを検証し、bundle自身からpublish commit、parent/base、target treeを導出する。GitHub Contents / Blob APIでpayloadを再取得せず、checkout済み `origin/<target>` とbundle parentをローカル比較する。成立後はexact publish commitをnon-force pushし、成功push後の `ls-remote` /再fetch、receipt書込み、pending commit status書込みを重ねない。Fast CIは `GITHUB_TOKEN` によるpushから別workflowが起動しないため明示dispatchする。

Gateway成功の記録は、そのtransport commitをheadに持つPublish Gateway workflow runの `completed / success` を観測してactive transactionへ記録する。receipt専用GitHub objectは作らない。ref更新後の一時的Gateway障害は同じworkflow run/transport commitをrerunし、retry generationとしてtransportを再公開しない。target移動やcontrol不一致等の意味のあるfailureは再送で隠さず原因を解消する。

通常publish前のremote観測はGitHub heads一覧1回から `develop` と `publish` の両HEADを得る。`publish` treeはlocal source stateを使う。prepared targetのcancelも同じ二つのHEADが未変化であることを機械確認して行い、transaction directoryの手動削除を標準手順にしない。

通常Publish Gatewayの権限境界はgame/source publishを基本とし、`.github/workflows/**` を含むtargetはrequest生成前に識別する。一般のworkflow変更はworkflow maintenance経路へ分離する。Publish Gateway自身の `.github/workflows/publish-gateway.yml` だけは、先に固定 `publish` branchのcontrol maintenanceで同一blobが成立済みの場合に限り通常publishへの同梱を許可し、Gatewayがpublish targetのblob OIDと現在のcontrol branch blob OIDの一致をpush前に機械検証する。

`publish` branch上のcontrol plane更新は独立したcontrol maintenance責務とする。対象pathをGateway workflowと現在使用するvalidatorへ固定し、各control fileを `GitHub.create_blob` して返却OIDをlocal正準OIDと照合する。その後の `create_tree` もlocal期待tree SHAと照合してから `create_commit` → non-force `update_ref` へ進む。source-snapshotに保持したpublish base treeを利用するため通常時にremote treeを再取得せず、ref update成功後も再readせずlocal publish stateを更新する。廃止したcontrol componentは同じcontrol treeから削除し、互換経路を残さない。

`temp` は標準publishの中継やpromotion元にはしない。ユーザー指定時、またはGateway / workflow経路そのものを隔離検証する場合だけ使用する。その検証成果物を通常の `develop` publish入力として再利用しない。

旧transportや既存テストを通すためのcompatibility pathは維持しない。標準経路が成立したら、旧patch方式、手動record fallback、段階的Connector helper等の同責務経路を撤去する。

`main` への統合とゲーム本体version変更はユーザーの明示的承認後のみ行う。
