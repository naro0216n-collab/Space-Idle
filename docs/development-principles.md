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

検証は、設計と実装が一致しているかを確認するための証拠収集であり、開発の目的や正準仕様ではない。

設計とDomain契約を先に定め、その契約に必要な検証を後から選ぶ。既存テスト、fixture、CI構成は、その検証対象が変われば更新・統廃合する。

GreenなCIは全体設計の妥当性を保証しない。Redなテストも、直ちに実装が誤っていることを意味しない。失敗した場合は、現在の設計に対して実装・Content・検証方法・環境のどこが不一致なのかを確認する。

テストを増やすこと自体を品質向上とみなさない。長期的に守るDomain invariant、状態遷移、会計、境界、保存復元、決定論等を中心に検証し、開発中の数値や一攻略例を固定する検証は、その実験目的がなくなれば廃棄する。

Gameplay evaluation、性能分析、Domain invariant、Content validation、Browser / Integration validationは目的が異なるため分離する。Gameplayの停止はゲーム上のボトルネックであり得る一方、Simulation計算量の増大は性能問題である。両者を同じScenarioの合否だけで判断しない。

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

認証済みnative Gitを利用できる環境では、記録済みremote HEAD/treeを基点としてlocal target treeを指すcommitを生成し、non-force push後にremote ref/treeを再検証する経路を優先する。

native Git transportが利用できない環境では、記録済みremote commitを親、local target treeをtreeに持つ決定論的commitをGit bundleへ格納し、Publish Gatewayへ渡す。publish直前のChatGPT側確認は対象branch HEADの一度だけとし、それ以外のSHA整合性確認はhelperとGatewayへ移す。bundle payloadはサイズにかかわらず独立Git blobとしてmaterializeし、Connector actionへ渡す実引数bytesを基準に、必要な場合だけ最少数へ自動分割して並列送信する。helperは各blob OIDと、それらを順序付きで参照するpayload root tree OIDを事前計算し、root tree作成packetと最終request packetを同時に生成する。各blob uploadとroot tree作成の返却SHAは後続stepへ渡さず、成功/失敗だけをtransport進行条件とする。payloadをrequest本文へ直接埋め込むinline経路は設けない。

Gatewayはrequestを受けたら、payload root tree OID、各Git blob OID、payload SHA-256、bundle、publish commit、parent/base、target tree、直前remote HEADを機械検証する。すべて一致した場合だけ対象branchへexact commitをnon-force publishし、remote ref/treeを再確認してreceiptを記録し、Fast CIを起動する。不一致時は対象branchを更新しない。ChatGPT側の正常系に個別blob再取得、SHA目視比較、blob/root tree返却SHAの中継、手動commit/ref更新を置かない。ローカルのpublish state更新もreceiptとmanifestを照合して行い、manifestが保持するlocal target commitを正本とする。receipt待ちの間にlocal HEADが進んでも、過去checkpointのSHAを人手で引き渡さない。

`temp` は標準publishの中継やpromotion元にはしない。ユーザー指定時、またはGateway / workflow経路そのものを隔離検証する場合だけ使用する。その検証成果物を通常の `develop` publish入力として再利用しない。

旧transportや既存テストを通すためのcompatibility pathは維持しない。標準経路が成立したら、旧patch方式、手動record fallback、段階的Connector helper等の同責務経路を撤去する。

`main` への統合とゲーム本体version変更はユーザーの明示的承認後のみ行う。
