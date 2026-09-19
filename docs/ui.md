# iPad UI設計

## 1. 役割と対象

本書は、`design.md` が定めるPlayer判断と `architecture.md` が定めるApplication / Domain契約を、iPad上のPresentationとしてどのように構成するかを定める。

正式対応対象は **iPad横画面** とする。Portrait専用Layoutや狭幅Desktop向けLayoutは本書の対象外とする。

UIは内部Domain、DTO、永続Stateの構造をそのまま画面へ露出せず、Playerが「何を判断するか」を単位に構成する。情報量を減らすこと自体を目的にせず、判断に必要なstate、requirement、blocker、limiting factor、Resource、Capacity、時間、progress、commitment、候補差を判断地点で確認できることを優先する。

本ゲームは輸送計画そのものを主目的としない。研究、産業、拠点開発、建設、探査、物流、Fleet運用、経済を一つの宇宙開発ゲームとして接続し、特定Domainの操作様式を全体へ一般化しない。

---

## 2. 画面構成

### 2.1 3領域Layout

画面は次の3領域を基本とする。

- **Navigation**: 作業領域を切り替える。
- **Decision Canvas**: ゲーム世界、対象、関係、候補を表示し、主要操作を行う。
- **Context Inspector**: Canvas上の主作業を中断せず、選択対象の状態、理由、条件、結果を確認する。

```text
Navigation | Decision Canvas | Context Inspector
```

Navigationは狭く安定した幅、Decision Canvasは主領域、Context Inspectorは通常幅と拡張幅程度の段階的な幅を基本とする。ページ全体を横スクロールさせない。

### 2.2 Global Bar

全作業領域を跨いで必要なGlobal Stateだけを上部へ固定表示する。

- canonical game day
- pause / speed
- Research Point現在量 / capacity
- Player判断が必要なAttentionへの入口
- Save / Load等のSystem操作への入口

FundsはExternal Resource Market専用の決済Stateであり、Global KPIとして常時強調しない。Location固有Inventory、個別Facility値、Transport詳細等もGlobal Barへ置かない。

### 2.3 Top-level Navigation

Top-level Navigationは次の6領域とする。

- 全体
- 拠点
- 研究
- 探査
- 輸送
- 経済

「全体」はカードDashboardではなく、全体MapとAttention / active activityへの入口とする。

Facility、Construction、Inventory、Location dependency等は選択Locationを保持した「拠点」Context内で扱う。Fleetは用途横断資産であるため独立したTop-level Navigationへ分離せず、全体・拠点から参照でき、研究・探査・輸送の各Decision Contextから関連commitmentを確認・操作できるようにする。

---

## 3. Interaction原則

### 3.1 Player判断中心

画面やDialogは内部Command / StateではなくPlayer intentを単位にする。

代表的な判断は次のように扱う。

- ボトルネックを発見し、改善対象を選ぶ。
- Facilityが低稼働な理由を確認し、Process、Priority、供給側等を調整する。
- 建設候補を比較し、必要条件と準備時期を確認して開始する。
- Research候補と現在Stageの条件を確認し、必要なExecution Contextを選ぶ。
- Survey対象をMapで選択し、戦略差がある場合だけProvider差を比較する。
- 新Location候補をMapで比較し、Founding blockerを解消する。
- 輸送不足を発見し、必要なTransport Capacity等だけを調整する。
- Fleetを研究、Survey、Exploration、Transport等の用途へどう配分するか判断する。
- Market Interfaceで買う / 売るResourceと条件を判断する。

内部State lifecycleをそのまま複数のPlayer操作へ分解しない。

### 3.2 Context保持

別の情報を参照するためにNavigationやInspectorを操作しても、現在のDecision Contextを失わない。

少なくとも次を必要に応じて保持する。

- Location / Operational Node
- Surface Cell
- Resource
- Facility / Project
- Research / Survey対象
- Fleet用途
- origin / destination
- 比較候補
- blocker / limiting factor
- Structured Decision中のDraft

Playerに別画面の数値や対象を記憶させて、元の画面へ戻って入力させない。

### 3.3 Context付き遷移

Blockerや不足から別作業領域へ移る場合は、画面だけでなく原因Contextを引き継ぐ。

たとえばOxygen不足の原因がTransport Capacityである場合、「輸送を見る」はdestination、Resource、該当Supply Requirement、関係Transport Allocation、問題Capacityを選択済みの輸送Contextへ移る。

Facility blockerからPower、Maintenance、Inventory、Construction等へ移る場合も同じ原則を用いる。

### 3.4 基本操作フロー

各Domainの主要導線は次を基本形とする。

1. Map、Location、Attention、Project等から問題または機会を発見する。
2. 対象を選択する。
3. Inspectorで原因、必要条件、current stateを確認する。
4. 必要ならContext付きで関連Canvasへ移る。
5. 主要ControlでPlayer intentを変更する。
6. Current / Target / Previewまたは実行結果を確認する。
7. 元の対象へ戻ってもSelectionを保持する。

---

## 4. 操作種別

Player操作は次の4種に分類する。

### 4.1 View

状態参照、選択、Map移動、Filter、Layer切替、Inspector切替等。

- Simulation継続
- Preview不要
- Commit不要

### 4.2 Direct Action

単一・可逆・低波及で、Applicationが即時に妥当性を判定できる操作。

例:

- Activity Priority変更
- Process選択
- Pause / Resume
- 単一Provider Assignment数量変更
- 比較を必要としない単純Target変更
- 明確な候補選択

原則としてSimulationを停止せず即時Commandとして処理する。

### 4.3 Structured Decision

複数条件の比較、複数値の同時調整、複数Domainへの波及、確定前比較等を必要とする操作。

例:

- 複数Fleet用途の再配分
- 大規模なTransport Capacity再構成
- 複数hard constraintの同時変更
- 複数Resource / Serviceへ広く波及するPlayer intent変更

必要な場合だけPlanning Modeを用いる。

### 4.4 Forecast

時間発展を伴う高コスト予測。

- 将来Inventory推移
- downstream dependencyへの波及
- multi-hop物流全体影響
- long-term steady state
- Location dependencyの将来変化

通常操作やSlider eventごとには実行しない。

---

## 5. Direct Manipulation

### 5.1 Control選択

主要操作は次を優先する。

- Slider
- Stepper
- Segmented Control
- Button / Preset
- Chip / Card selection
- Map上の直接選択
- Network上のNode / Edge選択
- 必要な場合のDrag

数値手入力は精密値入力、大幅変更、キーボード利用、アクセシビリティ上の代替として残し、値表示tapからのPopover等を基本とする。

### 5.2 Player intentとControl

ControlはDomain上のauthoritative Player intentと一致させる。

- TransportはDirectional Capacity targetを主要Controlとする。Required Fleet Unitsは派生結果として表示する。Fleet unit数を入力補助に使う場合もApplication境界でCapacity targetへ変換する。
- Research / Survey ProviderでFleet quantityがPlayer intentなら数量Controlを使用できる。
- Target Stockはtarget quantityがPlayer intentであり、days-of-supply等はApplicationがtarget quantityへ換算する補助Presetとする。
- 通常Cargo dispatch量はLogisticsが自動解決するため、一般物流UIでPlayerの恒常的なquantity入力にしない。Manual Cargo / special one-shot Movementだけ個別quantityを持てる。
- Priorityは1〜5の固定Segmented Controlとし、3を「標準」と表示する。

### 5.3 Meaningful breakpoint

連続ControlではApplicationが返す意味のある候補値をSnap / Presetとして利用できる。

- current
- minimum viable
- meet current demand
- next bottleneck
- practical max
- physical max

UIはこれらをDomain ruleから独自計算しない。

---

## 6. 情報表示

### 6.1 情報階層

判断との距離に応じて情報を階層化する。

常時またはPrimary Context:

- 選択対象
- current state
- primary action
- blocker / limiting factor
- progress

同じInspector内:

- requirement / fulfillment
- commitment
- input / output
- Resource / Capacity
- 候補差

展開表示:

- 詳細breakdown
- 履歴
- 全候補
- Detailed Forecast
- 内訳

重要情報を別画面へ退避して記憶を要求しない。

### 6.2 数値の意味

同じResourceやCapacityについて次を区別する。

- Stock
- Flow / rate
- Target
- Requirement
- Reserved / committed
- Nominal Capacity
- Available Capacity
- Used / Allocated Capacity
- Spare Capacity
- Forecast
- Draft / Preview

単位と時間基準を併記する。

### 6.3 Current / Target / Preview

変更前後を比較する操作ではCurrent、Target / Draft、Preview resultを視覚的に分離する。Preview resultをCurrent stateとして表示しない。

### 6.4 Blocker / limiting factor

Blockerは単なるerror textにせず、少なくとも次を示す。

- 何が不足 / 不成立か
- current
- required
- affected action
- related entity
- 解決対象へのContext navigation

複数blockerがある場合は現在の操作を直接止めるものと、次に支配的になるものを区別する。

稼働率やCapacityが100%未満なら、値だけでなくlimiting factorを同時に示す。

### 6.5 自動化結果

Coreが自動選択するものはPlayerに毎回選ばせない一方、結果と理由を確認できるようにする。

- auto-selected source
- end-to-end path
- Survey provider / observation mode
- normal logistics dispatch
- Fleet provisioning result

Player hard constraintがある場合は自動選択結果と明示constraintを区別する。

---

## 7. Attention

Global Attentionはlogや全warning一覧ではなく、Player判断が必要な事象を扱う。

主対象:

- Player判断がなければ進まないblocker
- active Project / Research / Survey等の停止
- significant unmet demand
- Capacity / Storage / Cargo arrival等の継続的な詰まり
- Fleet不足によるtarget未達
- Market Orderの成立条件不一致
- Founding / Construction等の準備完了
- 新しい戦略候補の解禁

通常自動処理で解決中の一時変動を過剰通知しない。Attention選択時は対象と原因Contextを保持して該当Canvasへ移る。

---

## 8. 全体Map / Location

### 8.1 全体Map

「全体」はStar System / Operational Node / Locationの空間関係と主要状態を把握する入口とする。

Map上で少なくとも次を識別できるようにする。

- Operational Node / Surface Location
- active founding / development
- 主要Movement / logistics connection
- Attentionを持つLocation
- Research / Survey / Exploration等の主要active activity

詳細数値をMapへ過密表示せず、選択した対象をInspectorへ展開する。

### 8.2 Location Overview

Location Inspectorは次の固定カテゴリから、そのLocationで意味のある状態を示す。

- 主要blocker
- Resource不足 / excess
- Service Capacity不足
- active Project
- Storage / Cargo問題
- Facility低稼働
- external dependency

カテゴリ位置を安定させ、条件によって別の操作へ置換しない。Inventory全品目は一操作で展開できるが、初期表示を単なる全品目表にしない。

Locationを開いた後は設備、建設、Inventory、依存関係等を同じLocation Context内で切り替えられるようにする。

---

## 9. Facility

Facility一覧は比較用途として、各Facilityの次の状態を短く表示する。

- lifecycle / pause
- selected Process / primary function
- utilization
- primary output / Capability / Service
- maintenance fulfillment
- Activity Priority
- main blocker / limiting factor

Facility Inspectorでは次を安定配置する。

- Process inputs / outputs
- current Process / candidates
- requested execution / fulfillment
- Resource requirement
- Service Capacity requirement
- maintenance demand / fulfillment
- output admission / Storage constraint
- Activity Priority
- blocker / limiting factor
- Upgrade / Pause / Resume / Decommission

Facility低稼働の主要原因を別画面へ移らないと判断できない構成にしない。

Process候補に戦略差がある場合だけ、primary input / output、Capability requirement、Resource burden、Service burden、blockerを比較する。

---

## 10. Construction / Upgrade / disposal

### 10.1 Construction

建設候補はPlayer-facingな用途 / Capabilityで整理する。表示分類はContent / Presentation情報でありGeneric Coreの固定カテゴリにしない。

基本動線:

1. Locationで建設を開く。
2. 用途 / Capabilityで候補を絞る。
3. 候補を選択する。
4. Inspectorで結果、必要Resource、Service、placement requirement、Projected Material Readiness、blockerを確認する。
5. Surface Cell指定が必要なFacilityだけMap上で配置する。
6. 開始する。

候補では「何を可能にするか」、主要input / outputまたはCapability、Build Resource、必要Service / placement condition、current availability、Inboundを含む準備状況、Projected Material Readiness、blockerを確認できるようにする。

### 10.2 Upgrade

Current LevelとUpgrade後の主要差を同じInspectorで示し、変化しない詳細値より差分を優先する。

### 10.3 Decommission / Retirement

不可逆操作、existing-stock blocker、current commitment、recovery potential、expected recoverable amount、release / completion conditionを表示する。recovery potentialと実際の見込回収量を混同しない。

---

## 11. Research

ResearchはDAG / Treeを主要Canvasとする。

Node上ではunavailable、available、active、blocked、completed、current stage、progress、primary blockerを簡潔に区別し、Requirement全文はInspectorへ置く。

Research Inspectorは次を優先する。

- 何を解禁するか
- prerequisite
- RP requirement / available RP
- current typed Stage
- stage progress
- current Stage Execution Requirement
- Execution Context
- provider supply
- blocker
- strategic candidate差

Provider / Execution Context候補が一意またはゲーム上同等ならPlayer選択を要求しない。戦略差がある場合だけFleet拘束、Resource消費、Service requirement、Location、所要時間 /供給能力、blockerを比較する。

active Researchでは完了済みStage詳細より、次に必要なStage条件とcurrent progressを優先する。

---

## 12. Survey / Scientific Exploration

### 12.1 Resource Survey

Surface Mapを主要Canvasとし、Cellまたは地域scope、Resource scope、goal Knowledge Levelを直接指定する。

Applicationがresolved provider / observation modeを提示し、戦略差のある候補が複数ある場合だけ比較とhard constraint操作を提示する。

Map LayerはEnvironment、Knowledge、Resource Potential、Location territory、Movement accessibility等を切り替え、全情報を常時重ねない。選択Cell Inspectorでは判断情報を統合する。

Presence probability、Estimated Potential + uncertainty、Measured Potential、goal Knowledge Level、current Knowledge Levelを区別し、Knowledge進展をResource量の増減のように表現しない。

Survey Inspectorではselected scope、Resource scope、goal、completed / remaining target、resolved provider / observation mode、Fleet commitment、estimated completion、blocker、strategic alternativesを確認できるようにする。

### 12.2 Scientific Exploration

同じContextでtarget / mission、phase、science progress、RP budget / admission、Fleet commitment、Movement / return、Pause / Abort / Return / completion dispositionを確認する。Fleet数量だけの設定画面にしない。

---

## 13. Founding / Surface Development

Surface Locationが存在しない天体でもRemote SurveyからFoundingまで同じMap文脈で追えるようにする。

基本動線:

1. 天体Mapを開く。
2. Survey Knowledge / Environment / Resource Potential Layerを確認する。
3. 候補Cellを比較する。
4. InspectorでKnowledge / Site / Movement / manifest blockerを確認する。
5. staging node / Founding target / Deployment Recipeを確認する。
6. 条件成立後にFoundingを開始する。

既存Surface Locationではdeveloped territoryと隣接候補をMap上で区別し、候補CellについてEnvironment、known Resource Potential、Knowledge sufficiency、development requirement、Surface Infrastructure負荷への影響、blockerを示す。

---

## 14. Fleet

FleetはVehicle inventory一覧ではなく、どこに何が拘束されているかを判断できるようにする。

- Operational Node
- total
- free
- Research commitment
- Survey commitment
- Scientific Exploration commitment
- Transport provisioning / operating use
- relocation / releasing
- retirement commitment

全Fleetを一本の割合Sliderへまとめない。free、committed、releasingを区別する。

Research / Survey等でFleet quantityが直接Player intentならStepper等を用いる。TransportではCapacity targetがPlayer intentであり、Required / Assigned Unitsは結果表示とする。

---

## 15. Transport / Logistics

Transport UIは輸送計画作成そのものを主ゲームプレイにしない。Playerが成立させたNetworkについてdemand、Target Stock、Transport Capacity、Fleet provisioning、Cargo Flow、auto-selected routing、bottleneckを確認し、必要な箇所だけ調整する。

Attentionまたは選択Contextがある場合は関係する需要、Allocation、path、bottleneckを強調したNetworkを初期表示し、Contextがない場合だけNetwork overviewを表示する。

代表的な動線:

1. LocationまたはAttentionでResource不足を発見する。
2. local production / consumption / inboundを確認する。
3. 主因が物流ならContext付きでTransportへ移る。
4. relevant allocation / route / demandを選択済みで表示する。
5. Directional Capacity target、Provisioning Priority、Target Stock、必要なhard constraintのうち原因に関係する項目だけ調整する。
6. Capacity、Required Fleet Units、operational Resource demand、coverage等を確認する。

Transport Allocationではorigin / destination、selected Movement / Service、Directional Capacity target、Provisioning Priority、Required Fleet Units、Assigned / available units、Nominal / Available / Used / Spare Capacity、latency、operational Resource demand、blocker / limiting factorを表示する。

Resource需要ではlocal stock、normal demand、Target Stock追加需要、inbound、active shipping demand、unmet demandを区別する。

通常routingはselected source、selected path、latency、主要operational Resource burden、handoff、limiting factorを表示し、hard constraintはPlayerが自動選択を戦略的に制限する場合だけNode / Edgeから設定する。

通常Cargo dispatch量をPlayerの恒常的な手入力項目にしない。Cargo Flowはsource、destination / next handoff、dispatch rate、latency、arrival waiting、capacity shortfallを可視化する。Manual Cargo / special one-shot Movementだけ個別quantity入力を許可する。

---

## 16. Market

FundsはExternal Resource Market専用の決済Stateとして扱う。

Market InterfaceではFunds / available Funds、Market Interface Location、buy / sell offer、availability、Trade Order target、committed amount、settled amount、price condition、logistics blockerを表示する。

QUANTITYとRATEを同時に主targetとして見せず、選択control modeのtargetだけを主要Controlとする。

Buyではreserved Funds / provider supplyを、SellではInterfaceへ実際に到達しているResourceとprovider demandを確認できるようにする。Marketへ未到達の遠隔Resourceを即売却できるように表現しない。

---

## 17. Location dependency

選択Operational Node集合についてCURRENTとFORECASTを切り替えて外部依存を確認できるようにする。Resource dependencyとService dependencyは別projectionとして表示し、単一の「自給率」へ圧縮しない。

主要表示:

- local production
- local consumption / demand
- imports
- exports
- unmet demand
- critical external Resource
- forecast requirement

該当Resource、Facility、Construction、TransportへContext付きで移動できるようにする。

---

## 18. Planning Mode / Preview

### 18.1 Planning Mode

Planning Modeは通常操作方式ではなく、基準stateを固定して複数値や候補を比較する必要があるStructured Decisionだけに用いる。

対象画面を開いただけでは停止しない。編集を開始し、基準固定が必要になった時だけ自動停止する。

自動停止前のspeedを保持し、Commit / Cancel後、自動停止だった場合だけ元speedへ戻す。Planning中にPlayerがTime Controlを明示操作した場合は自動復帰しない。

### 18.2 Fast Preview

Slider等のpointer move中はControl値を即時追従させるがDomain Previewを毎event実行しない。必要なStructured Decisionでは操作停止後100〜200ms程度を初期目安にdebounceし、pointer up等で最終Fast Previewを取得する。

Fast Previewは実行可否、Targetから導出されるCapacity / required units、Resource demand、fulfillment / coverage、blocker、limiting factor、next bottleneck、shortage等、現在の判断に直接必要な派生結果へ限定する。

古いrequest sequence / revisionの結果をUIへ適用せず、可能なら不要処理をcancelする。

### 18.3 Detailed Forecast

future Inventory、downstream impact、multi-hop logistics impact、long-term steady state、Location dependency forecast等はFast Previewから分離する。

UIは固定日数を正準仕様として持たず、必要に応じて短期 / 中期 / steady-state等の意味的horizonを選び、実期間はApplication Query filterとして扱う。

### 18.4 Draft

DraftはStructured Decisionで必要な場合だけ使用する。active Draftは原則1つとし、Inspector drill-down、Map移動、関連対象参照、Comparisonでは保持する。別のStructured Decision開始時だけ適用、破棄、元のDecisionへ戻る選択を提示する。

---

## 19. Comparison

Comparisonは戦略的に異なる複数候補が存在するときだけ用いる。

代表対象:

- Founding候補Cell
- Process候補
- Research Execution Context
- Survey provider / observation mode
- Movement候補
- Construction候補

共通Componentは2〜4候補のPin、共通比較軸、差分強調、blocker表示、Inspector展開を提供できる。候補が一意またはゲーム上同等ならComparisonを要求せず、Coreの決定論的選択を利用する。

全Domainを一つの巨大Generic Tableへ統合しない。

---

## 20. Context Inspector

Inspector内NavigationはMain Contextと1段階Detailまでを基本とする。それ以上はContext付きで適切なDecision Canvasへ移る。

Inspector最上部は次の順を基本とする。

1. 対象名 / 状態
2. 最重要current valueまたはprogress
3. blocker / limiting factor
4. primary action
5. requirements / commitments / details

詳細breakdownをprimary actionより上へ積み上げない。

---

## 21. Player-facing terminology

UI実装は、内部概念をPlayer-facing名称へ正面から対応付けるterminology tableを持つ。

少なくとも次を整理対象とする。

- Movement Plan
- Transport Allocation
- Supply Requirement
- Execution Requirement Bundle
- Provisioning Priority
- hard constraint
- commitment
- admission
- Projected Material Readiness

内部概念を無条件に隠すのではなく、Playerが戦略判断に使う概念だけを理解可能な名称で露出する。

---

## 22. Applicationとの境界

UIはeligibility、blocker、limiting factor、Capacity、Resource requirement、Vehicle compatibility、Movement / route feasibility、Survey estimate、provider selection、Research condition、construction feasibility、Projected Material Readiness、external dependencyを独自計算しない。

ApplicationはUIが文字列解析をしなくてよい構造化stateを返す。Blockerは少なくともkind、subject、current、required、unit、severity、affected action、related entity、必要ならContext navigation targetを表現できる。

戦略差のある候補については、ApplicationがPlayer判断に必要な比較軸を返し、UIが独自rankingやDomain優劣を計算しない。

Periodic authoritative syncでは編集中Control、focus、selection、scroll、Decision Contextをauthoritative stateが実際に変化していない限り失わせない。authoritative stateが変化した場合はCurrent stateを優先し、古いDraft / PreviewをCurrentとして表示しない。

---

## 23. UI検証契約

UIは見た目だけでなく、少なくとも次の契約を検証する。

- blockerから原因と解決対象へ数値暗記なしで到達できる。
- 関連Canvasへ移っても選択Contextが保持される。
- Current / Target / Previewを誤認しない。
- Stock / Flow / Capacity / Commitmentを区別できる。
- disabled actionでも必要条件とblockerを確認できる。
- auto-selected resultとPlayer hard constraintを確認できる。
- Research / Survey等で戦略差がない候補選択をPlayerへ強制しない。
- TransportでCapacity targetとRequired Fleet Unitsの意味を混同しない。
- 通常Cargoを手動dispatch UIへ変えない。
- Facility低稼働の主要原因をFacility Contextから確認できる。
- ConstructionでProjected Material Readinessとblockerを候補選択地点で確認できる。
- Founding候補比較に必要なSurvey / Site / Movement / manifest情報を同じDecision Contextで確認できる。
- authoritative syncで編集中Controlを不必要に失わない。
- Global Attentionが自動解消可能な一時変動で埋まらない。
- Fleet free / committed / releasingを誤認しない。
- Fundsを一般活動コストのように見せない。
