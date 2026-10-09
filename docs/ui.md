# iPad UI設計

## 1. 役割と対象

本書は、`design.md` が定めるPlayer判断と `architecture.md` が定めるApplication / Domain契約を、iPad上のPresentationとしてどのように構成するかを定める。

正式対応対象は **iPad横画面** とする。Portrait専用Layoutや狭幅Desktop向けLayoutは本書の対象外とする。

UIは内部Domain、DTO、永続Stateの構造をそのまま画面へ露出せず、Playerが「何を判断するか」を単位に構成する。 表示の主軸は数値、単位付きrate、現在/目標の差、時系列、拠点間Resourceフローとする。状態名や制約の説明は測定値の意味と操作不能理由を理解するために付し、活動・投資・物流への改善優先順位や最善手を文章・色・並び順によって暗示しない。情報量を減らすこと自体を目的にせず、判断に必要なstate、requirement、blocker、limiting factor、Resource、Capacity、時間、progress、commitment、候補差を判断地点で確認できることを優先する。

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

単位と時間基準を併記する。 収支の増減とその戦略的価値は同一視しない。注意色は未充足・ブロック・容量超過等の客観的成立差に用い、外部依存や在庫減少の存在だけで警告にしない。

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

Global Attentionはlogや全warning一覧ではなく、Player設定に対して成立しない活動・状態変化・完了イベントを扱う。通知はプレイヤーに取るべき行動を指定しない。

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

### 8.1 共通System Map

「全体」と「輸送」は別の地理を再描画する画面ではなく、同一System Mapを異なるDecision Contextで開く入口とする。Operational Nodeを軸に、Star System・Celestial Body・non-surface Spatial contextとの所属関係を理解できる概略配置を共有する。概略図の画面上の距離を実距離・latency・移動可否と解釈させず、それらはApplication Queryの数値・条件で示す。Surface Cellや未設立Founding targetは通常輸送Nodeへ混入させない。

物理Body・衛星の階層はOperational Nodeの有無に関わらず選択でき、同じInspector Contextから物理環境、Surface Cell登録状況、科学観測、Movement、Foundingの状況と必要条件を確認できる。固体地表のない天体には空の地表Mapを単なる読み込み失敗として表示せず、軌道・科学対象を提示する。未設立のBody/Cell/軌道Contextを通常のCargo配送先やTransport Allocation先の選択肢と混同しない。天体に関する物理値と判定はApplicationの同じWorld/Catalog投影を使い、地図内で再計算しない。

物理天体階層の表示位置とOperational Nodeの表示位置は別レイヤーとし、母天体接続を物流経路の実線として表さない。天体は未運用でも選択でき、地表の有無、代表重力・日射、登録された地域、非地表Contextの有無を区別して表示する。選択BodyのSurveyと非地表Founding候補はそのBodyの範囲で取得し、別Bodyの候補やKnowledgeを無条件に列挙しない。Founding操作は地表／非地表とも同じCommandへ接続し、Vehicle・staging・Recipeごとの準備、輸送、Resource、Fleetとblockerを判断点に提示する。

Mapの位置、拡大率・pan、表示階層、選択Node／OD関係、Resource filterを画面入口で共有する。OverviewではOperational Node、Attention、進行中のResearch・Survey・Exploration・Constructionと主要接続を示し、物流Contextでは実際のTransport Allocation、方向別Current / Target / Available / Used / Spareと選択されたSupply Requirement・Cargo Flowを区別する。Movement候補の成立性はTransportの稼働・配備を意味しないため、未配備候補の全線表示を避けて、選択した関係の候補として示す。

同一ODに複数Allocation／Movement候補があり得る。Map上の集約エッジは表示上の関係でありDomain Stateではない。方向、複数設定、配送済Cargoと未dispatch需要をInspectorまたは一覧で分解し、個別操作へ到達できるようにする。線の直接ヒットを唯一の操作手段とせず、キーボード・タッチ対応の関係一覧を設ける。色とともに線種、ラベル、凡例、数値・単位で意味を示す。

Mapは場所と関係の発見、比較一覧は多拠点の数値・設定と一括確認、Context Inspectorは選択対象の現在値・必要条件・blocker・Draft・Preview・操作を担う。同じ選択ContextをMap・一覧・Inspectorが参照し、どの入口からでも対象を再選択させない。別Canvasへの遷移とperiodic syncでは、対象・スクロール・Draft・pan／zoomを維持する。選択／pan／filterだけでは時間進行を停止せず、基準時点固定が必要なStructured Decisionでのみ既存Planning Modeを使う。

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

### 8.3 Population / 居住と生命維持

Location Overviewでは現在人数、任意の人口目標、Activity拘束人員、Inbound / Outbound、Housingの物理／利用可能／占有数、Life Supportの人数比例需要と実割当、生活Resourceごとの正味消費・現地在庫・補給中量、累積不足・翌日Crew能力、受入blockerを表示する。Earth外部人員供給元には有限残員・日次上限・当日取得可能数を表示する。現在値、次tick配分見込み、到着時点期待人数、将来Forecastを区別する。人口目標設定・解除の位置は固定し、目標を下げても人口消去や自動退去を意味しない。人口目標Previewには人数の出所、既Inbound、輸送時間・座席・質量、必要生活Resource、到着先Housing / Life Support、競合するCapacityを示す。

Location OverviewとTransportの双方で、任意のorigin / destinationと正の整数人数を指定する一回限りの旅客移送を独立操作として提供する。未設定の人口目標やMission作成を要求しない。Transport Serviceの便とfree Fleetによる専用便を選択候補として並べ、所要日数、使用Fleet・Service、出発確定人数、未出発待機人数、共通Cargo Capacityへの影響、必要Resource、到着先受入余力、出発元の人口目標への影響、blockerをApplication Previewから表示する。Order一覧には要求／未出発／Transit／到着受入済み／取消済み人数を示し、未発送人数の取消操作を固定位置に置く。明示した輸送方法が使えなくなれば別の方法へ無断切替しない。

Facility InspectorはHousing人数容量、Life Support Providerの人日/日供給、正味Resource・Power負荷、Pause・Decommissionの人員影響を表示する。Fleet / Transport Inspectorは共通Mass Capacity・seatと貨物／旅客の使用内訳、船内Resource、専用便によるfree Fleet拘束を表示する。Mission Inspectorでは必要Crew、拘束済み人数、Transit中乗員、船内Resource、帰還条件を表示する。操作可否と不足理由はApplication DTOを正本とし、UIで別の人口・輸送可否ルールを組み立てない。

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

ResearchはDAG / Treeを主要Canvasとする。DAG全体を保ちながら名称・分類で検索し、選択Nodeへのジャンプ、direct prerequisiteと後続関係の強調を提供する。検索で一致がなくても選択とスクロールを破棄しない。研究からLocationやFleetへ遷移した場合は同じ研究Nodeへ戻れる。

Node上ではunavailable、available、active、blocked、completed、current stage、progress、primary blockerを簡潔に区別し、Requirement全文はInspectorへ置く。

RPの貯蔵表示は `stored < capacity`、`stored == capacity`、`stored > capacity` の実値を区別し、満杯だけでAttentionにしない。受入値がゼロなら「受入余力あり」と表示しない。Stage別所要時間は現在の供給・条件に基づく参考値と明示し、全Stageの確定完了日とはしない。

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

Surface MapとSurveyのCell選択は共通の地理的概略配置を使う。緯度・経度の表示点に可変サイズの操作カードを直接重ねるのではなく、各Cellの操作領域が重複しない配置を導出し、隣接関係を示す。表示の間隔・画面上の距離は実際の距離や移動所要時間を意味しない。Cellが増加した場合も隣の操作領域を覆わせず、Canvas内のスクロールと全Cellに到達できる選択一覧を提供する。選択一覧とMapは同一のCell選択／調査scopeを操作し、別の正本を持たない。地表の再描画や同期で選択、フォーカス、マップ内スクロール、調査Draftを失わない。

Applicationがresolved provider / observation modeを提示し、戦略差のある候補が複数ある場合だけ比較とhard constraint操作を提示する。

Map LayerはEnvironment、Knowledge、Resource Potential、Location territory、Movement accessibility等を切り替え、全情報を常時重ねない。選択Cell Inspectorでは判断情報を統合する。

Presence probability、Estimated Potential + uncertainty、Measured Potential、goal Knowledge Level、current Knowledge Levelを区別し、Knowledge進展をResource量の増減のように表現しない。

Survey Inspectorではselected scope、Resource scope、goal、completed / remaining target、resolved provider / observation mode、Fleet commitment、estimated completion、blocker、strategic alternativesを確認できるようにする。

### 12.2 Scientific Exploration

同じContextでtarget / mission、phase、science progress、RP budget / admission、Fleet commitment、Movement / return、Pause / Abort / Return / completion dispositionを確認する。Fleet数量だけの設定画面にしない。

未開発のBody/Cell/軌道Contextも対象候補として提示し、観測対象とFleetが訪れる物理endpointを明示する。Outbound・観測中・帰還中の実Fleet所在、往復の推進剤・所要日数、帰還可否とblocker、出発元での補給量をApplication projectionから示す。未運用地点でのFleet滞在は通常FleetPoolや物流ノードとして表示しない。

---

## 13. Founding / Surface Development

Surface Locationが存在しない天体でもRemote SurveyからFoundingまで同じMap文脈で追えるようにする。

共通System MapではCelestial Bodyを物理的な対象として選択し、その天体のSurface Map／Surveyへ直接降りられるようにする。未設立天体をOperational Nodeへ昇格させず、地表の表示対象と、Fleet・Inventory・Founding準備を所有するstaging Operational Nodeを別の選択Contextとして保持する。同一の天体へ戻った場合は地表Cellの選択とMap表示位置を復元し、別天体へ切り替える場合は旧天体のCell選択や地表Projectionを新天体の状態として表示しない。対象天体の地表情報はその判断領域で取得し、他の画面の通常同期に含めない。

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

Transport UIは輸送計画作成そのものを主ゲームプレイにしない。共通System Mapの物流Contextと、需要・Allocation・Fleet・Target Stock・Cargo・制約の比較一覧／Inspectorを併用する。Mapで対象ODやNodeを選ぶと関連一覧も選択状態となり、一覧から選ぶとMapの対象を強調する。既存の比較・編集機能はMapへ吸収して消さない。未配備Movement候補と実際に稼働するTransport Serviceは表示を区別する。

Attentionまたは選択Contextがある場合は関係する需要、Allocation、path、bottleneckを強調し、Contextがない場合だけ物流overviewを表示する。通常source/path選択とCargo dispatchの自動化を維持し、必要なhard constraintのみPlayerが編集する。
代表的な動線:

1. LocationまたはAttentionでResource不足を発見する。
2. local production / consumption / inboundを確認する。
3. 主因が物流ならContext付きでTransportへ移る。
4. relevant allocation / route / demandを選択済みで表示する。
5. Directional Capacity target、Provisioning Priority、Target Stock、必要なhard constraintのうち原因に関係する項目だけ調整する。
6. Capacity、Required Fleet Units、operational Resource demand、coverage等を確認する。

Transport Allocationではorigin / destination、selected Movement / Service、Directional Capacity target、Provisioning Priority、Required Fleet Units、Assigned / available units、Nominal / Available / Used / Spare Capacity、latency、operational Resource demand、blocker / limiting factorを表示する。

Resource需要ではlocal stock、normal demand、Target Stock追加需要、inbound、active shipping demand、unmet demandを区別する。 輸送中Cargoは最終destinationとLeg chainから到着時点の最短見込み・Segment最後の見込みを示し、handoff待機・入庫制約があるときの見込みは確定到着として表示しない。runwayは現地在庫のみからの計算であることを明示する。

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
- external Resource dependency quantity / rate (unmet demandとは区別)
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

future Inventory、downstream impact、multi-hop logistics impact、Location dependency forecast等はFast Previewから分離する。期間末日時点の生産・消費・入出荷収支は数値で表し、期間末日の収支符号のみから長期均衡・枯渇の成否を断定しない。 期間中の在庫変化は、拠点・Resource単位で最小利用可能量とその時点も表示できるようにする。複数拠点の残高を合計することで各拠点固有の制約を打ち消さない。利用可能在庫が0になった事実だけをResource需要の未充足と同一視せず、それぞれ別の指標として扱う。

期間中の実行配分未達、期限到来Supply Requirementの未発送、中継／入庫arrival waitingを別系列にし、対象拠点・Resourceごとの初回観測日、最大未達量・発生日、到着待機の期間末残量を表示する。実行配分未達はResource以外のRequirement制約も含み得るため、現地Resource在庫不足と同一視しない。依存分析では現地生産差とscope内発送・輸送中量を分離し、外部供給に依存するだけで警告表示にしない。

UIは固定日数を正準仕様として持たず、必要に応じて短期 / 中期 / 長期等の期間を選び、実期間はApplication Query filterとして扱う。

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

| 内部概念 | Player-facing名称 | 通常UIでの扱い |
|---|---|---|
| Movement Plan | 移動経路 / 移動候補 | 経路候補として表示する。内部IDは表示しない。 |
| Transport Allocation | 輸送能力設定 | origin / destinationと方向別Capacity targetを中心に表示する。内部Allocation IDは表示しない。 |
| Supply Requirement | 補給需要 | 発生元、Resource、必要量、必要時期、供給状態として表示し、内部Requirement IDは表示しない。 |
| Target Stock | 追加備蓄目標 | 通常需要とは別のPlayer intentとして表示する。 |
| Provisioning Priority | 配備優先度 | 5段階Controlとして表示する。 |
| hard constraint | 固定条件 | 自動選択をPlayerが意図的に制限する場合だけ表示・操作する。 |
| Execution Requirement Bundle | 稼働要件 | Bundle名そのものは通常表示せず、Resource / Service /受入条件とfulfillmentを判断地点で示す。 |
| commitment | 割当済み / 使用中 / 回収中 | 所有Domainの意味に合わせて具体状態を表示し、genericな`commitment`だけをPlayerへ見せない。 |
| admission | 受入条件 / 受入余力 | Storage、RP Pool等の具体的な受入先と残余Capacityとして表示する。 |
| Projected Material Readiness | 資材準備見込み | 建設・Projectの開始判断地点で見込み時期として表示する。 |
| Transport Capacity | 輸送能力 | Target / Nominal / Available / Used / Spareを区別して表示する。 |
| Cargo Flow | 輸送中貨物 / 貨物流れ | 通常dispatchをPlayer入力にせず、量、rate、latency、arrival waitingを可視化する。 |

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
- 全体・輸送で共通System MapのNode位置・pan／zoom・選択が一致し、実AllocationとMovement候補を区別できる。
- Mapと輸送一覧が同じNode／OD／Allocationを相互参照し、複数Allocationを集約した表示からも個別設定へ進める。
- Research検索・前後関係の確認と復帰、RP上限状態の実値表示、Scientific Explorationのphaseとpauseを混同しない。
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
