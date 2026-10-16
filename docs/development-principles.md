# 宇宙開発Idleゲーム 開発原則

## 1. 目的

本書は、`docs/design.md` と `docs/architecture.md` で定めたゲームとシステムを、開発中の局所実装へ引きずられず継続的に実現するための変更・実装方針を定める。

本プロジェクトはゲーム性評価段階にある。現行コード、既存テスト、fixture、暫定Content、過去の実装コストは、それ自体を将来設計の前提とはしない。変更時には、現在あるものへ最小差分を足すことより、変更後の全体が一貫した責務・状態モデル・ゲームループになることを優先する。

`design.md` はゲームとして何を成立させるか、`architecture.md` はそれをどの責務境界で表現するかを定める。本書は、それらを変更・実装する際の判断順序を定める。

---

## 2. 開発の基本原則

変更要求は、既存実装へ追加する差分ではなく、現在のシステム全体を再評価する入力として扱う。

まず「変更後にどのような宇宙開発活動、量的成長、長期自動運転、技術的成果、Player判断、Domain状態が成立すべきか」を定義し、その結果から必要な責務境界、状態所有、処理順、Application契約、Persistence、UI表示、Content構造を導出する。新しい判断操作の有無を設備・技術の価値の唯一の尺度にせず、設備規模・処理量・負担・継続運転の増大も評価する。

現行構造が新しい目的に適さない場合は、既存モジュール、API、State、Content、テストを維持するための互換層を積み上げず、より妥当な構造へ正面から更新する。局所的には大きな変更でも、将来の変更点が予測可能になり、責務が単純になるならその方を選ぶ。

一つの不具合や一つの失敗ケースだけを解消することを完了条件にしない。修正後に、同じ原因が別Domainや別状態遷移へ残っていないか、変更によって新しい重複責務・特殊分岐・暗黙依存を作っていないかまで確認する。

---

## 3. 変更時の判断順序

### 3.1 目的と不変条件を定める

実装前に、今回成立させるゲーム上の結果と、変更後も守る一般則を整理する。

例：

- 何をプレイヤー判断として残すか
- 何が自動で反復され、設備世代・投資・物流の拡張によって日次物量や能力がどの程度変わるか
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

既存概念が新設計と重複・矛盾する場合は、変更後の責務を一つのState、Command、Query、Persistence、UI経路へ統合し、同じ責務を持つ複数経路を残さない。

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

### 3.5 計算量と導出範囲をArchitecture契約として扱う

Generic Coreが将来増加するEntityや関係を扱う場合、正しさだけでなく、どの集合に対して何回導出するかを実装前に確認する。Operational Node、Movement Plan、Facility、Resource、Project等の件数が増えたとき、局所Queryや1回のtickが無関係な全世界集合の再列挙へ暗黙に拡大しない構造を選ぶ。

特に、同じauthoritative Stateから同一の派生結果を複数箇所が参照する場合は、一度導出して索引・snapshotとして再利用する。個別ID参照やorigin / destination等で範囲が指定されたQueryは、その要求範囲に応じた導出を使い、各行の評価から全候補生成を繰り返さない。派生索引のinvalidationは、その入力となるauthoritative Stateを変更する責務側で行い、read Queryが安全確認のために毎回破棄する構造へしない。

この再利用は派生状態の保存正本化を意味しない。索引・cache・projectionはSave対象にせず、入力State変更後に再導出可能であることを保つ。性能問題への対処として、wall-clockとgame timeの対応、canonical tick、Domain invariant、Queryの意味論を変更して処理コストを見えなくすることは行わない。まず重複導出、探索範囲、責務境界、データアクセス経路を修正する。

検証は不安定な実時間閾値だけに依存せず、「同一physical stateで全候補導出が一度だけである」「絞り込みQueryが全世界候補を要求しない」等、計算量増大の原因となる契約を直接確認する。

### 3.6 実装後に広域監査する

機能が動作した時点で終えず、変更範囲の周辺を含めて監査する。

確認対象：

- 同じ概念を複数Domainが所有していないか
- 同じ責務を持つ複数経路・変換層が残っていないか
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

Contentの追加・統廃合とTechnologyの独立性評価は相互依存する。先に登録済みTechnologyの出口やPlayer選択数を数えて研究の要否を決めず、産業・研究・輸送の工学的体系、長期的な量的拡大、複数世代の設備と工程を実際に接続したうえで研究体系を見直す。複数のアプローチから選定してよく、工学的必要性や生産規模そのものも採用根拠となる。研究の未接続は現行Contentの状態であって、単独では削除理由にならない。

Facilityの追加・改称・性能調整は単体比較で確定しない。実際の選定は工学的役割、Resource入出力、既存・将来の全FacilityとVehicleの需要、建設・維持・物流・研究・人口等の競合を踏まえた全体系から行う。目録上の用途数は実消費量でなく、Scenarioごとの資産数・稼働とPlayerの計画によって需要が決まる。上流だけ増産して共通の建設・Vehicle製造材に接続しない場合、さらに上位の名目設備を積むのでなく、産業と需要の物理的な接続を再設計する。名称の「連続」「大型」や単なる高能力倍率を、独立した工学的機能の説明や調整根拠としない。

研究と産業のContent調整は、プレイヤーの最適行動の発見や、所与の施設数・研究日数・立地に対する効率ランキングではない。地球中心の初期産業から、研究段階ごとの施設・Vehicleの種類と規模、別天体の拠点成立、広域物流、次世代の工業化を**設計仮説**として組み立てる。その構成自体が技術的役割、時間、物量、取得負担、World条件、他の活動との需要競合に照らして妥当かを調べ、必要なら技術分類・Facility・Vehicle・Recipe・Resource・World・初期Scenarioまで変更する。表示世代全研究の完了、理想日数、特定設備数、特定地点は正解としない。

LLMに委任する調整は、全期間の発展構造とそれを構成する複数Domainの結合KPIを判断単位とする。詳細数値は採用する方針の根拠に限り、個別数値の改善や部分評価を全体の達成として報告しない。

調整に必要な手段は目的から選ぶ。目録や簡潔な関係整理で判断できる事項に診断機能を増やさず、調整判断に必要な数量だけを登録Definitionと所有Domain契約から取得する。差分比較や多段階Plan・個別Scenario・感度スイープを作ること自体は成果でない。評価目的が説明できない既存機能やテストは、必要な契約を通常Domainへ戻したうえで撤去する。Contentに不足がある場合は、評価器の網羅性を増やす前に、Contentの構成・工程・技術的役割を見直す。ゲーム本体の状態推移を評価ツールへ複製しない。

全体系バランス調整では`balance-principles.md`のLLMによる6工程を使う。単一CLIの数量出力は設計判断を支援する根拠であり、Content適正値や実到達Stateの証明ではない。変更したContent群と前後段階への影響、調整根拠、未確認条件を簡潔に残すが、CLIに履歴管理や自動探索を持たせない。数量集計テストはState出典・保存整合・段階継承・条件付き数量の区別を守り、暫定目標を正準Core契約にしない。

これらを用いたGameplay結果から一般的な欠陥が見つかることはあるが、現在の数値や一つの攻略経路を成立させるためにCoreを最適化しない。

例えば特定Scenarioで資材不足が起きた場合、直ちに供給量を増やすのではなく、次を区別する。

- 意図されたゲーム上のボトルネック
- blockerやQueryが不足して判断不能なUX問題
- Resource会計や状態遷移の不整合
- Route探索や配分処理の一般的欠陥
- 単なる暫定Contentバランス

一般的欠陥だけをCore修正へ昇格させ、バランス問題はContent評価として扱う。

GUIと開発CLIが同じ数量・状態を必要とする場合、各利用者がprivate Domainを個別探索する経路を設けず、所有DomainのApplication公開Projectionを共通化する。新しいContent要素やQuantity Requirementで必要な契約が増える場合は、GUI・CLIとその間のQuery投影が同時に追従するかを確認し、参照漏れのない一つの経路に統合する。

---

## 6. 検証・テスト・CIの位置づけ

### 6.1 テストが表すもの

テストは、現在の正準仕様から導出される契約を実行可能な形で検証するためのものとする。過去の実装手順、修正履歴、削除済み設計、ある時点の内部構造を保存する記録にはしない。

恒久テストを置くかどうかは、「このテストが失敗したとき、現在の `design.md` / `architecture.md` が要求する不変条件、状態遷移、Domain境界、Application契約のどれが破られたと言えるか」で判断する。対応する現行契約を説明できない検証は、恒久suiteへ残す根拠を持たない。

不具合修正や構造変更を契機に検証を追加する場合も、個別事象の再現形状ではなく、その事象が示した一般的な契約へ検証対象を引き上げる。State ownership、Application境界、登録順非依存、保存則など、現在の設計から説明できる契約を直接検証する。

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
- 現在の契約を表さず、暫定Content値や特定の内部表現だけを固定する場合は削除する。

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

### 6.6 CIと検証範囲

GreenなCIは設計妥当性の証明ではなく、選択された検証が通ったという証拠である。Redなテストも直ちに実装誤りとは限らず、正準仕様の変更に対してテスト契約が古くなっていないかを含めて原因を確認する。

変更単位では、その責務に直接関係する最小の検証から開始し、Domain横断、Persistence、Offline、Application等の影響範囲に応じて必要な検証を広げる。変更と無関係な長時間検証を毎回機械的に実行することを品質基準にはしない一方、ローカル実行不能を理由に必要な実環境検証を変更単位から除外しない。

実ブラウザ、clean package install、OS差等はGitHub CIで検証し、高速に再現できるDomain / architecture / integration検証はローカルで優先する。Gameplay evaluation、性能分析、Domain invariant、Content validation、Browser / Integration validationは目的を分け、それぞれの結果を別の契約の証明として流用しない。

全体系Content調整の実作業は、**時間目標と発展像を入力した専用バランスCLIの全体系レポート**を根拠にする。研究費用、施設・Vehicle性能、取得資材、産業の生産/消費、初期条件、World、活動規模、時間目標は全て変更候補であり、既存数値を所与として不足箇所を自動補修する作業にはしない。CLIに適正値の自動決定、汎用Command/Query実験Script、Checkpoint、局所差分比較を復活させない。評価条件の設計目標、登録Contentから取得した現状係数、根拠を持つ任意仮定、実GameApplicationで確認した数量を区別する。生産目標を利用可能な独立Resource供給と扱わず、段階末の能力を区間全体の稼働能力とみなさない。

通常テストは正準Domainの不変条件、状態遷移、Application契約、Save/Load、Offline、CLIの数量契約と非干渉性を検証する。Contentバランスの妥当性はテスト通過や特定の攻略順では証明されない。実効稼働や到達時間を判断する必要がある場合は、正準GameApplicationで通常操作と状態遷移を用いて確認し、その結果を独立した数量Simulationや一時的なテスト代用で置き換えない。設計に必要な数量が不足する場合は所有Domainの副作用のない読取契約を見直すが、不要な詳細観測機能や診断器は追加しない。

テストsuiteは現在の正準仕様を効率よく検証する構成として継続的に統廃合する。テスト数、ファイル数、過去ケースの保存量そのものを品質指標にしない。

---

## 7. 完了判定

変更は、依頼された局所動作が成立しただけでは完了としない。

少なくとも以下を満たした時点で、検証可能な実装単位として扱う。

- 変更後のDomain責務とState所有が明確である
- 同じ責務を持つ重複経路や不要な変換層が存在しない
- Simulation、Application、Persistence、Content、UIが同じ契約で接続されている
- 一般モデルに特定Content由来の特殊分岐を持ち込んでいない
- 変更後のボトルネックと状態遷移をApplicationから説明できる
- Save / Load、Offline、決定論等の関連不変条件が維持される
- 周辺Domainを含む広域監査で同根の未修正箇所や新たな責務重複がない
- 現在の設計から導出された必要な検証で問題が確認されない

CI通過や特定Gameplay Scenarioの完走だけを完了判定には使わない。

---

## 8. GitHubへの反映

独立作業はローカルrepoで行い、責務としてまとまり、その時点で既知の不整合がないcheckpointを `develop` へ反映する。反映単位はファイル数やテスト実行単位ではなく、Domainから必要なApplication・Persistence・Content・UI境界まで一貫して成立した責務変更とする。

publish対象はcommit済みtarget treeとし、publish transportの都合をゲーム実装の構造、commit境界、State ownershipへ持ち込まない。成立済みlocal commitは履歴整理やtransport都合で作り直さず、責務境界に沿ったcheckpointとして保持する。

通常publishの操作手順、Publish Gatewayのtransport protocol、source-snapshotの復元方法、workflow maintenance、失敗時のrecoveryは `DEVELOPMENT.md` と各helperの生成手順を唯一の運用正本とする。実行者はそこに記載された操作と生成済みpacketだけを記載順に実行し、独自の確認・中継・代替・追加検証・操作順変更を行わない。手順が実行できない場合も独自の迂回は作らず、`DEVELOPMENT.md` の指定されたrecoveryを使用する。

branchの役割は次の通りとする。

- `develop`: 通常開発中の共有正本。検証済みcheckpointを通常publishで反映する。
- `publish`: Publish Gateway専用のtransport control branch。game/sourceの開発履歴とは分離する。
- `temp`: ユーザー指定、またはworkflow・publish経路そのものを隔離検証する場合に使用する。
- `main`: ユーザー承認済みの正準branch。`develop` からの統合とゲーム本体version変更はユーザーの明示的承認後に行う。
