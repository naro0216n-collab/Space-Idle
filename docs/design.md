# 宇宙開発Idleゲーム デザイン案 v0.5.0

## 文書ナビゲーション

- §1–4: ゲーム目的、中心ループ、発展像、初期評価範囲
- §5–7: Resource / Inventory / Priority / Facility / Industry
- §8: Spatial / Surface Location / Environment
- §9–10: Movement / Transport / Logistics / Cargo / Vehicle
- §11–14: Scientific Exploration / Research / Knowledge / Survey
- §15–16: Location発展、外部依存、自動進行
- §17–19: LLM、Application / UI、Save / Offline / Test
- §20: World / Scenarioと初期Content
- §21: 全体へ横断適用するゲームデザイン原則
- §22–23: ゲーム性評価範囲とゲーム定義の要約

ゲーム上の意味は担当節を正本とし、§21は詳細メカニクスを再定義しない。Domain責務・State ownership・処理順は `architecture.md` を参照する。

---

## 1. 目的

現代の地球から始まり、探査・実験・研究によって知識生産能力を拡大し、その成果で新技術、新しい生産設備、輸送方式、研究手段を成立させ、最終的に太陽系規模の産業圏へ発展するIdle型宇宙開発シミュレーションを目指す。

着想元の一つとしてCivIdleがあるが、その再現を目的とはしない。宇宙開発固有の「技術的困難さ」「研究手段の世代交代」「距離と輸送」「立地」「現地資源利用」「ロケーション産業自立」を中核に据える。

ゲームの成長軸は契約報酬として資金を稼ぐ経営ループではなく、人工衛星、有人活動、探査機、研究所、実証設備等からResearch Pointを獲得し、それをより高い桁で生産・保持できる研究基盤へ移行することである。産業拡大は高度な研究手段を建設・維持するために必要となり、研究成果はさらに高性能な産業・輸送・研究資産を成立させる。この相互強化をIdleゲームとしての中心ループにする。

プレイヤーの楽しみは、単なる数値増加ではなく、研究・産業・物流ネットワークのボトルネックを発見し、既存資産の高度化と新世代資産への更新を比較しながら、より困難な研究と大規模な宇宙産業を成立させることに置く。

---

## 2. 基本コンセプト

ゲームの基本循環は以下とする。

探査・実験・研究設備を運転する  
→ Research Pointを獲得・蓄積する  
→ 技術を研究する  
→ 新しい設備・製法・輸送能力・研究手段を利用可能にする  
→ 生産、採掘、電力、建設、物流を拡大する  
→ より高コスト・高効率な研究資産を建設・維持できるようになる  
→ 研究点生成量と貯蔵可能量の桁が上がる  
→ より技術的に困難な研究へ進む

この循環の途中で、電力不足、輸送能力不足、特定中間材不足、建設能力不足、維持資材不足、研究点貯蔵不足等のボトルネックが発生する。プレイヤーは既存施設のLevelアップ、新世代設備の新設、産業配置や物流能力の変更を比較して解消する。

Idle要素は「一度構築した仕組みが時間とともに自動で運転し続ける」ことを担当する。時間は通常状態で自動進行し、プレイヤーは速度変更と一時停止を行える。日数を都度選択して進める方式を通常UIの主要操作にはしない。

Idleだからといって、プレイヤーの判断まで自動化しない。研究対象、設備投資、施設Level、新地域への進出、産業構成、拠点間輸送能力、輸送方式、宇宙船の用途配分、電力・建設能力の配分などの主要判断はプレイヤー側に残す。

---

## 3. 進行の基本像

ゲーム開始時点は現代水準とする。ロケットそのものを発明するところからではなく、既に基礎的な宇宙開発能力を持つ組織を運営する。

プレイヤー主体は、初期段階では特定企業・国家機関そのものに固定しない「宇宙開発組織」とする。外部の企業、政府、研究機関等は協力相手、供給者、需要主体、イベント主体として世界側に残すが、契約をこなして資金を稼ぐことをゲーム進行の中心にはしない。

初期のResearch Point源は、地上研究設備、人工衛星による継続観測、有人宇宙活動、近接領域の科学探査等である。これらは比較的低コストで維持できる一方、研究点出力と貯蔵能力は小さい。

産業・輸送能力が拡大すると、より大型の軌道実験設備、無人地表探査、サンプル解析、高度な地上研究設備等を維持できるようになる。さらに月面等へ恒久研究所や大規模実証設備を建設する段階では、建設質量、電力、精密機器、中間材、保守物流等の要求が一段上がる代わりに、研究点出力と貯蔵能力も桁違いに増加する。

この成長段階は地球からの距離そのものではなく、必要な研究設備、実験環境、輸送、電力、精度、継続運転、試作・実証の技術的困難さによって決める。単純な月面観測より高度な地上大型研究設備の方が高いResearch Tierとなることもあり得る。Locationは研究Tierそのものではなく、特定環境や物流条件を提供する。

大まかな世界発展のイメージは以下とする。

現代地球宇宙産業  
→ 人工衛星・有人近接領域研究  
→ 高頻度打上げ・軌道実験  
→ 再使用輸送・軌道上補給  
→ 高度無人探査・地表実験  
→ 恒久的な月面研究・産業拠点  
→ 初期ISRU・現地材料加工  
→ 月面工業化と大型研究設備  
→ 地球圏・月圏の産業統合  
→ 火星・小惑星・外惑星圏  
→ 太陽系規模の研究・産業圏

これは代表的な発展像であり、研究解禁や輸送経路をこの順序へ固定するチェックリストではない。研究は車両、設備、推進、補給等の能力を解禁するが、「特定研究を完了したから特定航路が開く」という直接ゲートにはしない。実際に到達可能かどうかは、機体性能、必要Operation、補給、環境、インフラ等から決める。

---

## 4. 最初のプレイ可能範囲

初期評価では以下までを扱う。

現代地球産業・研究  
→ LEO研究・物流  
→ 月探査  
→ 月面ロボット拠点  
→ 水・酸素等の初期ISRU  
→ 月面構造材生産  
→ 月面建設の部分的現地化  
→ 一部機械部品の現地生産

この時点でも、半導体、精密電子機器、高性能材料、高度制御装置などは地球依存とする。

地球側にも資源採掘・基礎生産を置く。ただし開始時の地球産業は「何でも無限に購入できる市場」ではなく、低効率の採掘・生産設備と有限在庫から始まり、研究と設備投資によって改善する対象とする。

---

## 5. 資源・在庫・能力

### 5.1 資源

元素を過度に細分化せず、産業上意味のあるカテゴリとして扱う。研究施設や高度産業の発展に伴い資源・中間材の種類は増やしてよいが、品目数の増加をそのまま物流設定数の増加へ転嫁しない。

初期候補：

原料
- Regolith / Aggregate Feed
- Metal Ore / Metal Feedstock
- Volatile-bearing Material
- Water

基礎工業品
- Structural Material
- Ceramics / Glass
- Oxygen
- Hydrogen / Fuel
- Propellant

高度工業品
- Machinery
- Electronics
- Precision Components
- Experimental Hardware
- Specialized Materials

知識系（通常貨物Inventoryとは分離する）
- Research Point
- Survey Knowledge
- Operational Experience

Research Pointは組織全体で利用する知識資源として扱い、通常の貨物Inventoryや所在地別在庫とは分離する。Survey Knowledgeは地域・対象ごとの知識、Operational Experienceは実運用から得られる技術・運用系統ごとの経験として、それぞれ別のKnowledge Stateを持つ。

Fundsは組織全体のResource売買決済通貨とする。Research、Construction、Maintenance、Vehicle運用、Player-owned Transport、Facility operation、Technology Unlock等の一般的な活動コストには使用しない。Fundsの増減はExternal Resource MarketにおけるResource ownership transferとScenario初期残高だけから発生し、契約報酬、時間経過による収入、一般External Service料金等の別用途を持たせない。

物理資源は所在地を持つ。地球の水1000t、月面の水1000t、LEOの水1000tは同価値ではない。

### 5.2 在庫・倉庫

各Operational Nodeでは最低限、現在在庫、予約済み在庫、入庫フロー、出庫フロー、輸送待ち、輸送中、到着待機、保管容量を区別する。

通常の物理Resourceは共通の通常Storage Capacityを利用する。Resource種類が増えるたびに一般貨物、バルク、液体、精密部品等の分類とPlayer設定を増殖させない。保管方式そのものが技術・Infrastructure・運用上の独立した判断を生むResourceだけ、Content Definitionが特殊なStorage pool / compatibilityを要求できる。Generic Coreは具体的なStorage分類一覧を固定しない。

ある時点で保持できる量は `Physical Storage Capacity` と、電力・保冷・Facility状態等の成立条件を反映して現在安全に利用できる `Usable Storage Capacity` というStock Capacityとして扱う。保管状態を成立させる条件はUsable Capacityへ反映する。荷役、充填、移送等の一定時間あたり処理量それ自体が有限競合になる場合だけ、目的の明確なService Capacityとして表現する。

通常Inventoryに属する物理Resourceは有限Storage accountingを迂回しない。Research PointやKnowledge等、通常貨物Inventoryとは別Stateで所有するものはこのStorage契約の対象外とする。

輸送中貨物は到着先倉庫容量を事前予約しない。実到着時にInventory Admissionを行い、容量不足分はLogistics側のarrival waitingとして残す。

### 5.3 CapabilityとService Capacity

設備・Vehicle・Infrastructureが「何を実行可能にするか」と、ある時点で保持できる量の上限と、複数用途が競合する時間あたり有限処理能力を分離する。数量概念は `Capability`、`Stock / Pool Capacity`、`Service Capacity` の三種類を混同しない。

`Capability` は、建設、観測、有人運用、Docking、特定Process等を実行できるという資格・機能の存在を表す。Spatial classification、Physical Environment、Installed / Active Capability、Technology、Knowledge threshold等の「成立しているか」を判定する非消費条件はEligibilityとして扱う。

`Service Capacity` は、一定時間あたりに供給・配分できる有限flowを表す。例：発電、採掘、製造、建設、Cargo Handling、Local Distribution、保守、Research execution、Survey / Observation等である。有限Serviceを要求するActivityは、単なるSite可否として確認するのではなく、ResourceやStock admissionと同じExecution allocationへ参加させる。

Service CapacityはOperational Node等へ固定値として付与するのではなく、Facility、Fleet、Infrastructure等から発生させる。Facility / Fleet状態等から得るNominal supplyと、Resource、Power、Maintenance、Fleet、上流Service等の依存を反映したAvailable capacityを区別する。複数用途が同じService Capacityを要求する場合は共通の配分規則で競合させ、各Domainが同じ能力を独立に100%利用できる構造にしない。

Service Capacityは用途に応じたscopeを持てる。Cargo Handling、Construction、Vehicle servicing等はOperational Node scopeを基本とし、Theory研究に用いるResearch executionのように組織全体へ集約して利用すること自体がゲーム上の意味を持つ能力はOrganization scopeを定義できる。Organization scopeへ供給される場合も、provider所在地でPower、Maintenance、Environment等のローカル成立条件を満たしたAvailable supplyだけを集約する。

PowerはOperational NodeごとのService Capacityとして扱う。canonical dayのPhysical snapshot時点の発電設備、Environment、Facility状態等から当日のAvailable Powerを導出し、同日のAllocationで競合利用する。蓄電をPower Capacityへ暗黙に含めない。将来battery等をゲーム上の判断として導入する場合は、Energy Storageを明示Stock Stateとして定義し、充放電executionを介してPower Serviceへ接続する。

Research Point生成率のような有限flowと、Research Point貯蔵上限のようなPool Capacityも区別する。生成outputはPool admission可能量を同じexecution settlementへ含め、複数Producerが同じ空き容量を二重利用しない。このallocation graphへ当tickに新たに生産・到着したResourceやCapabilityを戻さず、次tick snapshotから利用可能にする。同tick依存関係に循環を持つContent / DefinitionはValidationでfail-closedとする。

### 5.4 Priorityと活動の優先順位

プレイヤーが複数の活動間で限られたResource、Power、Service Capacity、Research Point、物流能力等を配分する場合、優先度は5段階で指定する。

```text
1  最低
2  低
3  標準
4  高
5  最優先
```

新しい設定の標準値は3とする。Priorityは割合や重みではなく、「どの活動を先に成立させるか」を表す順序尺度とする。同じPriorityに属する活動は、利用可能なResource / Serviceの範囲で公平に充足する。複数日にまたがってStockを確保するProjectは、その蓄積をatomic要求へ任せず、Activity Priorityを持つReservation acquisitionとして在庫を段階的に確保する。停止はPriorityの一段階として表現せず、Pause等の活動状態として扱う。

PriorityはResourceやPower等の個別Requirementへ別々に設定するのではなく、原則としてPlayerが優先したい活動へ設定する。Construction Project、Research Project、Facility operation、Maintenance、Target Stock等の活動がPriorityを持ち、それらを成立させるために同時利用するResource / Service /既存Transport Capacityへその優先度を引き継ぐ。

一方、限られたFleetをどのTransport Allocationへ配備するかは、輸送能力を用意する側の別判断とする。需要側のActivity Priorityと、Fleet配備側のProvisioning Priorityを分離することで、高Priorityの需要が既に用意された輸送能力を優先利用できる一方、別用途のFleetを需要側が暗黙に奪う構造にしない。Transport AllocationのProvisioning Priorityも1〜5、標準値3とする。

### 5.5 FundsとExternal Resource Market

External Resource Marketは、Playerが所有する物理ResourceとFundsを交換する外部境界である。MarketはResearch、Construction、Vehicle運用等を金銭で代替する一般サービスではない。

Market Providerは特定Operational Nodeの `Market Interface` を通じてのみPlayer物流網へ接続する。Market InterfaceはFacilityそのものではなく、Operational Nodeと外部Providerの接続Stateである。別Locationや別恒星系へ市場能力を自動追従させず、そこに市場が存在する場合は別Provider / InterfaceとしてContentで定義する。

Resourceごとにbuy offer / sell offerを持てる。現段階ではoffer価格はContent Definitionが定義する固定条件とし、Market Provider Stateは価格形成の正本を持たない。一方、現在のsupply / demand availabilityは有限のDynamic Stateとし、Content Definitionが定める決定論的なrate / interval等のreplenishment ruleで更新できる。必要ならlead timeを持たせる。Funds Stateは組織全体の残高だけをauthoritativeに所有し、Buy用予約額はBuy Commitmentから導出する。複数Orderが同じ有限availabilityを競合する場合はTrade OrderのActivity Priorityと同順位の決定論的公平性で配分する。内生的な市場価格形成は別の意思決定を導入する場合にのみ独立設計する。

Trade Orderは有限総量を取引する `QUANTITY` と、継続的な目標rateを維持する `RATE` のどちらか一方をauthoritative targetとして持てる。`QUANTITY` は未達量を翌tick以降へ保持する累積目標である。`RATE` は各tickの現在throughput目標であり、あるtickの未達分を翌tickの目標へbacklogとして累積しない。Buyは任意のmaximum buy price、Sellは任意のminimum sell priceをPlayer intentとして持て、現在offerが条件外なら新規commit / settlementを行わない。

Buy OrderはFundsとprovider supplyを `Buy Commitment` として予約する。CommitmentはOrder、Resource、未移転量、commit時buy価格、予約Funds、予約provider supplyをMarket Domainの単一Stateとして所有し、Provider StateやOrder Stateへ同じ予約量を重複保存しない。利用可能Fundsとprovider supplyはこのactive commitmentを控除して導出する。provider lead timeが満了したCommitmentは次のcanonical Boundary以降に受入対象となり、Market Interface所在Operational Nodeで必要なCargo HandlingとInventory Admissionが成立した量だけResource ownershipをMarketからPlayer Inventoryへ移す。そのownership transferと同時に対応Fundsを消費してcommitmentを減らし、入庫不能分は外部側のcommitmentとして保持する。取消可能な未settled commitmentはFundsとprovider supplyを解放する。

Sell Orderは遠隔Resourceのためにprovider demandを先行予約しない。Player所有ResourceをMarket Interface所在Operational Nodeへ通常物流で運び、canonical snapshot時点で取引可能なResourceが実際に提示されている場合だけ、そのResource利用と当日のprovider demand availabilityをSell OrderのActivity Priorityで同時に競合させる。同じInventoryを生産・建設等と売却が二重利用しない。成立量だけownershipをPlayerからMarketへ移し、そのownership transfer時点の有効sell offer価格でFundsを加算する。そのFundsは次tick以降の新規購入に利用できる。Orderは既dispatch / 提示済み量を未手配量から控除して二重dispatchを防ぐ。Orderを変更・取消しても既settlementを遡及変更せず、既にPlayer-owned Cargoとしてdispatch済みのResourceは通常Cargo lifecycleを継続し、到着後は別の有効Sell intentが成立しない限りPlayer Inventoryに残る。

Market取引は通常のCargo、Transport、Cargo Handling、Inventory Admission等の物理契約を迂回しない。Funds支払いだけで任意のOperational NodeへResourceを生成せず、Resource売却だけで遠隔Inventoryから物量を消去しない。

---

## 6. 建築物・建設・維持

### 6.1 建築物の生産とUI

FacilityそのものとProcessを分離する。一つのFacility Definitionが複数の互換Processを持てる場合、同一Facility instanceで通常同時に実行するProcessは一つとし、プレイヤーが選択する。互換Processが一つだけならそのProcessを自明な選択として扱え、冗長なinstance stateを必須にしない。複数候補がある場合はFacility Stateが現在選択中のProcessをauthoritativeに所有し、登録順やID順で暗黙選択しない。

Process変更はPlayer Commandとしてcanonical boundaryから反映し、既に確定したexecutionを遡及変更しない。現在ProcessのRequirementが満たせない場合も別Processへ自動切替せず、その選択を保持したままblocker / limiting factorを示す。

一つのFacilityで複数Processを同時並行に運転すること自体を独立したゲーム上の判断として導入する場合は、能力共有、配分、Power、Maintenance、UIまで含めてその時点で設計を拡張する。現在のProcess選択契約は、一つのactive Processという明確な運転判断を正本とする。

生産設備についてUIは最低限、現在選択Process、選択可能な候補、投入資源と実効消費量/日、産出資源と実効生産量/日、稼働率、limiting factor / blockerを設備単位で表示する。資源画面の地点合計フローだけで済ませず、「どの建築物が何を消費し何を作るか」を設備画面から直接確認できるようにする。

### 6.2 建造投入物

建築物は明示的な実ResourceとConstruction workを消費して建造する。一般Contentでは、物流判断とUI可読性を保つため、簡易設備は2種類、高度設備は3種類程度の主要Resourceへまとめることを基準とする。ただしこれはContent設計上の目安であり、Generic CoreがResource種類数を固定上限として検証しない。

構造・機械・電子等の抽象Componentへ複数の代替材を暗黙にぶら下げず、Construction Recipeが実際に消費するResourceと量を直接定義する。追加Resourceが独立した供給・立地・技術判断を生む場合は、有限個の明示RequirementとしてContentへ定義できる。

建設資材の産地はRecipeの条件にしない。要求Resourceが建設地点Inventoryへ存在すれば、地球産・月産・他拠点産を区別せず利用できる。

```text
採掘
→ 加工
→ 必要ResourceとしてInventoryへ存在
→ 必要なら物流
→ 建設地点Inventory
→ 建設で消費
```

### 6.3 維持コスト

建築物は建造時に投入したResourceの何%かを継続的な維持コストとして要求する。

Content側は設備ごと、または設備群ごとに維持率を持つ。具体的な割合はバランス調整対象とし、構造テストで固定しない。

概念式：

```text
年間維持需要(resource)
= 建造・Upgradeで累積投入した resource × 維持率
```

維持資材は特別な税として消去せず通常Resourceとして扱う。当tickの維持実行は必要Resource / ServiceをExecution Requirement Bundleとして他用途と競合させ、将来の補充必要量はSupply RequirementとしてLogisticsへ流す。維持executionのfulfillmentが不足した場合は設備を即時破壊せず、保守充足率を下げ、その設備が供給するService Capacity、生産、研究点生成等を一貫して縮退させる。Capabilityそのものの有無と、現在供給できる量を混同しない。

通常の手動停止だけで維持費をゼロにしない。将来、長期保管・Mothballを導入する場合はPauseとは別状態とする。

### 6.4 Upgrade

Levelアップは同一世代設備への増設・拡張・改良として扱う。Upgradeも明示ResourceとConstruction workを投入し、その投入分を以後の累積投入Resourceと維持需要へ反映する。Resource種類数はFacility建設と同じくContent設計上は可読な範囲へ保つが、Generic Coreの固定上限にはしない。

### 6.5 Decommission

Facilityは明示的なDecommission Projectによって撤去できる。PauseとDecommissionを同一状態にしない。解体作業が不可逆段階へ入るまではProjectを取消可能とし、不可逆段階へ入ったFacilityは `DECOMMISSIONING` 状態として通常のProcess、Capability、Service Capacity供給を停止する。

DecommissionはConstruction系のwork / Resource allocationを利用してよいが、Facility lifecycleのauthoritative stateはFacility Domainが所有する。不可逆な解体開始後は通常のProcess、Capability、Service Capacity、Storage admission等へ新規Activityを受け入れない。既存stockや開始済みcommitmentを安全にsettleするため解体中にも残す必要がある受動能力だけはContent Definitionで明示し、その保持能力を新規Activityの供給能力として利用しない。

既に開始済みで、そのFacilityの現存を前提に安全にsettleしなければならない不可逆commitmentを破壊する状態遷移は開始できず、Applicationはblockerを示す。一方、将来の反復ProcessやTransport intentがそのFacility能力へ依存するだけなら撤去自体を禁止せず、能力喪失後は通常のblockerとして扱う。

Storage Facilityでは、不可逆解体開始後に通常利用できなくなる容量を除いた残存Physical / Usable Storage Capacityで現在のPlayer-owned stockを安全に保持できない場合、Inventoryを消去・宙づりにせず撤去開始をblockする。この既存在庫保全と、解体後に得られるsalvageの受入余力は別の問題として扱う。

解体でResourceを回収する場合は累積投入ResourceとContent側のrecovery定義から `recovery potential` を導出する。完了settlementでは、全salvage Resourceがcompatible Inventory Admissionを共有する一つの回収executionとして競合し、0..1の共通recoverable fractionを決める。そのfractionを全salvage Resourceへ比例適用し、実際にadmissionできる量だけPlayer-owned Resourceとして生成する。未回収potentialはPlayer Inventoryへ生成した後で消去するのではなく、Resource ownershipを取得しない。

Salvageを全量受け入れられないことだけを理由にFacility removalを永久停止しない。Resource列挙順によって回収構成が変化しないようにし、Applicationは開始前・完了前にrecovery potential、現在条件での見込回収量 / fraction、既存在庫・work・Resource・Service blockerを表示する。完了済みProject等の履歴的状態をFacilityの現存へ依存させない。

---

## 7. 地球初期産業と採掘

初期地球には低効率の資源採掘建造物を用意する。地球を「必要資材が自動で無限供給される背景市場」とせず、プレイヤーが初期産業を拡張・更新する対象にする。

初期候補：

- Surface Aggregate Quarry / Open-Pit Material Mine
- Metal Ore Mine
- Industrial Water Intake / Processing Facility
- Basic Structural Material Plant
- Basic Machinery Works

地表資源は有限埋蔵量を消費する方式ではなく、地域ごとの `Resource Potential` と、そこへ投入した採掘設備能力の組み合わせから継続的な採掘Throughputを得る。Resource Potentialは「残量」や「建設可能鉱山数」ではなく、その地域が追加採掘投資をどの程度高い限界生産性で受け入れられるかを表す地質的機会とする。

同一Location内の採掘Facilityが供給するNominal Extraction Capacityを合算し、開発済みSurface Cell群から得られるEffective Resource Opportunityに対して、Generic Core共通の単調増加・限界収益逓減responseから実効採掘量を導出する。設備を追加して総採掘量が通常減少する式にはせず、同じOpportunityへ過度に集中するほど追加投資1単位あたりの増産量が低下する構造とする。

```text
Developed Surface Cells
→ Resource Potential / Effective Opportunity

Extraction Facilities
→ Nominal Extraction Capacity

Opportunity + Capacity
→ common diminishing-return response
→ Actual Extraction Throughput
```

ResourceやLocationごとに任意の採掘関数をContentへ持たせず、方式差が必要な場合も共通response modelへ入力するOpportunity、Facility性能、Environment / accessibility等の物理parameterとして表現する。採掘設備数にハード上限を設けない。プレイヤーは、既存拠点へ設備を追加するか、Potentialの高い隣接地域を開発するか、別Locationを設立するかを限界収益で比較する。

Surface Infrastructure不足はResource Opportunityを書き換えず、採掘executionが必要とするLocal Distribution等のService Capacity Requirementとして一度だけ競合させる。同じ地理的負荷をOpportunity係数とService Capacityの双方へ重複適用しない。

研究完了だけで既存採掘FacilityのThroughputを直接上昇させない。研究はより高性能なFacility Definition、Process、Construction / Modernization手段を解禁し、実際の建設・更新投資が完了して初めてInstalled Capacityが変化する。

地球の一般鉱物等は開始時から高いSurvey Knowledgeを持たせてよい。これはEarthという固有Location IDへのCore特例ではなく、Surface Cellごとの初期Knowledge差として表現する。初期設備は低効率・高維持比率・大規模という性格を持たせ、後に高効率設備や宇宙資源利用へ置換する理由を作る。

## 8. 空間・Operational Node・天体表面開発

物理的な位置を表すSpatial modelと、Inventory・Facility・Fleet等を所有して経済活動を行うOperational Nodeを分離する。

- Star System：複数のCelestial Body / Spatial contextを含む恒星系上位context。
- Celestial Body：Star System内の天体そのもの。
- Surface Cell：地表の物理・地理・資源・環境・Surveyの単位。
- non-surface Spatial Node：軌道、Lagrange領域、深宇宙上の運用地点等の物理的context。
- Operational Node：Inventory、Facility、Fleet、Storage、Power等を所有し、産業・研究・物流活動の端点となる運用拠点。
- Surface Location：Surface Cell上にプレイヤーが設立・拡張するOperational Nodeであり、連結した開発領域を追加で持つ。

すべてのSpatial NodeがOperational Nodeである必要はない。単なる軌道上の位置や未開発Surface Cellは物理的targetにはなれても、Inventoryや通常物流のNodeにはならない。一方、軌道研究所・Depot・Service Station等が存在する地点はnon-surface Spatial contextに結び付いたOperational Nodeとして扱える。

地表をSurface Cellへ分割し、資源・地形・環境・Survey・開発領域の正準単位とする。UIではヘックス主体の天体マップとして表現してよいが、球面を完全な六角形だけで覆うことや、全Cellが同面積・常に6隣接であることをCore仕様にはしない。天体ごとにSurface Cell数を変えてよく、各Cellは面積、隣接関係、天体上の位置を持つ。

```text
Star System
└ Celestial Body
   └ Surface Cell graph
      ├ static geology / resource potential
      ├ terrain / area / adjacency
      ├ dynamic environment
      ├ survey knowledge
      └ derived development affiliation
```

Surface CellはFacility配置スロットでもOperational Nodeでもない。通常Facilityを建設するたびにCellを選択させず、地理的開発と産業設備投資を別判断として扱う。

### 8.1 プレイヤーによるLocation設立

地表LocationはContent側が候補地点を固定列挙する方式を基本とせず、プレイヤーがSurvey結果と地形・資源・環境条件を比較してSurface Cell上の任意地点へ設立する。標準の月面開発では、開始時からプレイヤー運営の月面Locationを与えず、月周回等の既存non-surface Operational Nodeから広域Surveyを行い、その結果を比較して最初の月面Locationを選ぶ。既設Surface Locationを持つScenarioも同じ一般契約で定義できる。

新しい運用拠点を成立させる一回限りの処理は `Operational Node Founding` の共通lifecycleとして扱う。Foundingは既存Operational Nodeをstaging originとし、まだ通常Inventory / Logistics Nodeではないphysical targetへ必要Resource、Fleet、preparation workを実際にcommitしてMovementし、成功時に新しいOperational Node Stateへ一度だけsettleする。

Founding targetは少なくとも地表Locationとnon-surface Operational Nodeを型として区別する。Surface Location Foundingはtarget Surface Cellと生成するcore cellを持ち、non-surface Foundingは既存のnon-surface Spatial contextをtargetとする。両者はcommitment、Movement、settlement、保存則を共有するが、Surface Cell領域や地表Site条件をnon-surface拠点へ持ち込まない。

Location設立前のSurface CellはInventoryや通常物流のNodeではない。Surface FoundingではContentが必要Resource、展開Facility / Fleet、輸送・着陸能力、準備作業、所要時間、物理Site条件をDeployment Recipeとして定義する。Resource Survey Knowledgeを成立条件にする場合は「Survey済み」というbooleanではなく、対象Cell / Resource等とminimum Knowledge Levelを明示するKnowledge Requirementを定義する。

Deployment開始時にprepared Resource / Fleetをsource側の物理Stateからone-shot Movement payload / commitmentへ移し、成功時だけRecipeに従って初期Storage、Facility、Inventory、必要なFleet等へ変換する。Definitionだけを根拠にtarget側へResource、Fleet、Facilityを無償生成しない。失敗・取消可能境界・帰還dispositionもMovement / commitment契約で明示する。

Surface Locationは一点座標ではなく、Operational Nodeとしての経済・産業・物流機能と、連続して開発したSurface Cell群の双方を持つ。設立Cellは `core cell` として領域の成立起点・連結性のanchorになるが、Location全体の代表Environment、代表Movement endpoint、無料Surface Infrastructure endpoint、Resource Opportunity特権にはならない。

```text
Surface Location
├ Operational Node state
│  ├ Inventory / Storage
│  ├ Facilities / Power / Service Capacity
│  └ Fleet / logistics connections
├ core cell: founding / territory-connectivity anchor
└ contiguous developed cells
```

新たな開発Cellは既存領域へ隣接することを基本とし、離れた地域を同一Locationの飛び地として無償取得しない。遠隔地域を利用したい場合は領域を連続的に拡張するか、別Locationを設立する。同一Surface Cellは原則として一つのLocationの開発圏へ所属し、Resource Opportunityを複数Locationへ複製しない。

### 8.2 Location拡大と複数拠点化

Location拡大は隣接Surface CellをDevelopment Projectとして取り込むことで表現する。Cell数に固定のハード上限は置かず、必要なSurvey Knowledge、建設資源、Construction Service Capacity、時間、地形・環境、Surface Infrastructure等の負担を通じてsoft constraintを作る。必要Knowledge LevelはDevelopment Contentが明示し、すべてのCell開発へ一律のSurvey段階をCoreで固定しない。

Location内部で個別ResourceをCell単位にroutingしない。一方、領域が巨大化しても共通Inventoryによって内部物流が無償・無限になる構造にはしない。Surface Cargo Gateway、Distribution Hub、access point等の位置依存InfrastructureはSurface Cell上の明示的な `access anchor` を形成できる。

Local Distribution / Surface Infrastructure demandは、実際にLocation内の地理的広がりを利用するActivityからService Capacity Requirementとして発生させる。Coreはdeveloped Cell、利用可能anchor、Surface geometry、Activityが利用するResource OpportunityやMovement endpointから一貫した共通負荷モデルで必要量を導出する。負荷は利用距離・spreadやActivity量の増加に対して不自然に減少せず、有効anchor追加だけで悪化せず、停止したanchorへ暗黙fallbackしない。同じ地理的負荷をResource Opportunity等へ別係数として重複適用しない。

どのanchorを使うかを毎回PlayerへCell-routing操作として要求せず、Playerが建設・維持している有効anchor集合の範囲でCoreが実行可能な組合せを導出する。Playerの戦略判断はanchorの建設・配置・増強とLocation境界に置く。

Core Cellであること自体は内部物流コストを免除しない。設立直後にcore cell上へGatewayやDistribution Hubが存在すれば結果として近距離になるだけであり、Infrastructureを撤去・停止すればそのanchor能力も失われる。必要anchorが存在しない活動はblockerを持ち、core cellへ暗黙fallbackしない。

近接・隣接地域へ別Locationを設立すること自体は禁止しない。新Locationには独立したFounding、Storage、Power、Construction、access / Gateway、物流接続等の投資が必要となり、Inventoryも別Operational Nodeとして分離される。したがってプレイヤーは、一つのLocationを拡大して内部Infrastructure負荷を引き受けるか、複数Locationへ分散して設立・拠点間物流の固定費を負担するかを比較する。Location分割によって同じSurface CellのResource OpportunityやService Capacityを複製してはならない。

これにより惑星開発を、建物配置パズルではなく、調査済み地域をどこまで一つの産業圏へ統合し、どこから別拠点網として接続するかという地理的・経済的判断として表現する。

### 8.3 FacilityとSurface Cell

通常FacilityはOperational Nodeへ所属し、地表Location上であっても個別Cell配置を要求しない。採掘FacilityもSurface Location全体へNominal Extraction Service Capacityを供給し、開発済みCell群のEffective Resource Opportunityと組み合わせて採掘量を決める。軌道研究所やDepot等も、non-surface Operational Nodeへ同じFacilityモデルで所属できる。

一方、Landing Site、Surface Cargo Gateway、Mass Driver、局所日照を利用する発電設備、局所環境を直接利用・改変する設備等、物理的位置そのものが性能・接続・環境効果へ本質的に影響するFacilityだけはSurface Cellへ配置する。同じOperational Node内でFacilityを別Cellへ置き換えたときに、局所Physical Environment、Movement接続、性能、効果のいずれも変化しないFacilityはOPERATIONAL_NODEを基本とし、Cell選択を要求しない。これらも通常Facilityと同じ建設・維持・Power・Capability / Service Capacityモデルを使う。

「地表である」「軌道である」等のSpatial classificationと、温度・日照・大気・放射線等のPhysical Environment Requirementを同一Facetで代用しない。Operational Node-scope FacilityのEligibilityは、そのNodeのSpatial classification、Celestial Body global Physical Environment、およびInfrastructureが供給するInstalled / Active Capability等から判定する。Powerや有限Service Capacityが必要な運転は通常Allocationで実行量を決める。Surface Cell localなPhysical Environmentが必要なFacilityはCell placementを要求して、その配置CellのPhysical Environmentを評価する。

人工的な与圧、温調、放射線遮蔽等はPhysical Environmentを書き換えない。Infrastructureは `pressurized workspace`、`thermal control`、`radiation shelter` 等のCapability / Service Capacityを供給し、それを必要とする活動が有限能力として利用する。

### 8.4 環境変化と将来のテラフォーミング

Surface Cellは静的な地質・地形と、将来変化し得るPhysical Environment Stateを分離する。

```text
Static
  geology / resource potential
  terrain / elevation / area

Dynamic physical environment
  temperature
  atmospheric pressure / composition
  radiation
  water / volatile state
  illumination and other local conditions
```

Physical Environmentの各fieldは、天体全体で共通に評価する値、Surface Cell localでのみ評価する値、天体global値へCell local overlayを合成する値のいずれかとして定義する。Celestial Body全体に共通する環境変化とSurface Cell localな変化を、そのfieldのscope / composition規則に従って合成して現在のPhysical Environmentを得る。Surface Locationそのものには代表Cell由来の単一Environment値を持たせず、Cell-local値を必要とする活動は明示Surface Cellを要求する。UIがLocation概要を表示する場合は、developed cellsの範囲、extrema、分布、core cell値等を説明用summaryとして提示できるが、そのsummaryをSimulation判定の正本にはしない。

テラフォーミングや自然変化はPhysical Environmentを更新し、Facility、Resource Opportunity、Movement、Construction等へ一般則として作用する。人工的な建屋内環境や保護InfrastructureはPhysical EnvironmentではなくCapability / Service Capacityとして扱う。

地表以外の軌道・宇宙空間NodeはSurface Cellを要求しない。LEO、月周回等はそれぞれの物理・運用構造に適したSpatial Nodeとして扱い、Inventory・Facility・Fleet等を持つ場合だけOperational Nodeとして経済活動へ参加させる。

## 9. 輸送と物流

本作の物流は、任意の成立済みOperational Nodeから任意の成立済みOperational NodeへResourceを輸送できる一般モデルとする。地球、惑星、衛星、小惑星、軌道拠点、深宇宙拠点、将来の別恒星系は同じSpatial / Movement / Transport / Logistics契約を利用する。

責務を次のように分離する。

```text
Spatial
  位置と二地点間の空間的関係を表す

Movement
  二地点間で必要となるOperationと移動特性を導出する

Transport
  Vehicle / FleetとInfrastructureから反復可能な輸送能力を供給する

Logistics
  Resourceをどこからどこへ、どの需要のために運ぶかを計画する
```

通常物流の二地点関係をOperational Node IDごとの静的な航路一覧として正本化しない。各EndpointのSpatial context、利用可能なaccess / Gateway、二地点間のtransport geometry、Movement Operation、Vehicle性能、InfrastructureからMovement PlanとTransport Serviceを導出する。新しいCelestial BodyやLocationを追加するときに、既存全地点とのOD別Route Definitionを追加することを要求しない。

### 9.1 Spatial relationとMovement

同一Surface上では実際のSurface geometryとGateway / access pointを利用する。宇宙空間では各Spatial contextが持つ安定したtransport geometryから二地点間のcharacteristicな空間関係を導出する。別恒星系についても同じ考え方を一段上の空間関係へ適用する。

Movementは少なくとも次の要素へ分解できる。

```text
origin-side operation
+
space / surface movement
+
destination-side operation
```

Powered Ascent、Spaceflight、Landing、Atmospheric Entry、Surface Transport等はMovement Operationとして表現する。同じSpatial relationでも利用するVehicle、推進方式、Infrastructureによって所要時間、Payload、Resource消費、Endurance要求は変化する。Spatial側のgeometryをそのまま輸送日数や単一の万能性能値へ読み替えず、Movement OperationとVehicle性能の組み合わせから運用結果を導出する。

Surface Cell自体はInventory Nodeや通常物流Nodeにはしない。成立前のSurface CellはFounding / Deployment等の一回限りの物理targetにはなれるが、通常物流は成立済みOperational Nodeをorigin / destinationとする。Surface Locationでは実際に利用するGateway / access Surface CellをEndpoint条件へ反映する。

### 9.2 通常輸送の抽象化とFleet配分

通常物流では個別のVehicle便を主要な管理対象とせず、Fleetの反復運用から方向別の定常Transport Capacityを導出する。Transport Serviceは少なくともPayload / Transport Capacity、Cargo latency、往復・回収を含むcycle、Propellantやservicing等の運用要求を持つ。

長距離輸送の戦略性は、有限Fleet、有限capacity、大きなlatency、運用Resource、Storage、Cargo Handling、先行備蓄から生じる。Playerの主要判断は個々の出発時刻ではなく、どのVehicleをどの拠点間輸送へ投入するか、どの程度のcapacityを用意するか、どのResourceやProjectを優先するか、どこへ在庫を前置きするか、中継・補給・積替えInfrastructureを整備するかに置く。

Transport Allocationのauthoritative targetはforward / reverseを区別する方向別定常Capacityとする。必要Fleet数はVehicle性能と成立するMovement / Service Planから導出する。UIはFleet unit数を判断材料や入力補助として利用でき、その入力はApplication境界で方向別Target Capacityへ変換する。Domain Stateは方向別Target Capacityだけをauthoritativeに保持する。

反復Serviceへ利用できるMovement候補が複数ある場合、通常はCoreがlatency、Propellant等の運用Resource負担、handoff / service構成等を含む正準評価で決定論的に選択する。Playerが特定Gateway、Movement Plan、Service構成等を戦略的に固定する必要がある場合だけhard constraintを設定できる。通常経路選択はPlayer設定ではなくCoreの正準評価として扱い、経路を戦略的に固定したい場合だけhard constraintをPlayer intentとして保持する。

Transport AllocationのProvisioning Priorityは1〜5、標準値3とする。これはfree Fleetを複数Transport Allocationへ配備するときの優先順位であり、Cargo需要のActivity Priorityとは別の判断とする。Priority変更だけで既に別Activityへ排他的にcommitされたFleetを奪わない。

Transport以外のScientific ExplorationやFleet-backed ProviderもFleetを利用する場合は同じFleet Domainの排他的commitmentを利用する。ただし、それらへTransportの自動Provisioning Priority semanticsを一律に適用しない。one-shot Scientific ExplorationはCampaign自身が必要unitをcommitし、継続能力を供給するFleet-backed Research / Survey ProviderはProvider AssignmentがFleet commitmentを参照する。Provider Assignmentと、その能力を消費するResearch / Survey Activityを同じStateへ混在させない。

Transport AllocationのCapacityは「どれだけ輸送能力を用意するか」を表し、物流需要からFleetを無条件に増員しない。Fleet不足、推進剤不足、整備能力不足、Infrastructure不足等は別々のlimiting factorとして示す。

Transport Capacityは少なくともTarget、Nominal、Available、Used、Spareを区別する。推進剤・整備等の運用需要はFleetを割り当てただけで最大量を常時消費させず、実際のService利用率から発生させる。

### 9.3 Supply Requirementと先行物流

Facility、Construction、Maintenance、Industry、Research等のDomainは、自分の成立条件から現在必要なResourceだけでなく、既に決定済みのProject進行等から予測できる将来必要量をSupply RequirementとしてLogisticsへ提示できる。通常運転・Project成立に必要な補給はこのRequirementから自動Planningされ、PlayerがResourceごとのTarget Stockを設定することを前提にしない。

PlayerはOperational NodeごとにTarget Stockを設定できる。Target Stockは通常需要を超えて意図的に追加備蓄したい量を表すPlanning intentであり、Inventory Reservationではない。Target Stockを満たしている在庫も通常Inventoryの一部として他Activityから利用でき、不足すれば追加Supply Requirementとして通常物流と競合する。

物流計画は少なくとも、現在必要量、予測される将来必要量・継続消費率・予測必要時期、Target Stock、現地Inventory / Reservation、Inbound Cargo、end-to-end latency、利用可能Transport Capacity、Activity Priority、必要ならPlayerが設定したrouting hard constraintを扱う。現地在庫やInboundを複数Requirementが重複して充足済みと数えないよう、同一destination / ResourceのPlanning creditは共通に配分する。

将来必要量は、その時点でResourceを消費・予約するものではない。Logisticsは予測必要時期、継続消費率、輸送lead time、現在在庫、Inbound量、利用可能capacityから、現在発送を開始する必要がある量・rateを判断する。将来まで十分な余裕がある高Priority Requirementが、現在必要な低Priority活動のResourceやTransport Capacityを直ちに先取りしない。

通常routingでは、Playerが成立させたInventoryとTransport Networkの範囲でCoreがsourceとend-to-end pathを決定論的に選択する。Playerが自動選択を制限したい場合だけ、対象需要へsource、via Operational Node、Transport Service / Allocation等のhard constraintを設定できる。constraintが成立しない場合は戦略上異なる候補へ勝手にfallbackせずblockerを返す。constraintが存在しないことは、成立済みNetwork内の通常auto-routingを許可する状態である。

Routingは既存Transport Serviceの利用方法を決めるものであり、Transport Allocation target、Fleet配備、Trade Order、Facility、Target Stockを暗黙変更・生成しない。External Resource Marketで購入したResourceも、Market InterfaceでPlayer ownershipへ移った後のInventoryだけを通常source候補として扱う。

Routing constraint変更は未dispatchの将来Planningへ作用し、既dispatch Cargo、開始済みhandoff、Movement条件を遡及変更しない。sourceから発送するResourceは現地用途と同じResource allocationへ参加し、Logisticsだけがsource Inventoryを先取りしない。

### 9.4 Cargo lifecycleとhandoff

Resourceはsource Inventoryからdispatchされた時点でLogistics上の輸送中Cargoとなる。通常物流では大量の個別便を生成せず、同じsource、destination、Resource、Transport Service、latency、dispatch rate等の条件が続く期間をCargo Flowとしてまとめて扱う。

別Fleetへ直接積み替えられる場合は、Cargo Handling等の必要条件を満たした上でStorageへ一旦入庫せず次のTransport Serviceへhandoffできる。一旦中継Operational Nodeへ荷卸しする場合は、その時点で物理Resourceのauthoritative ownershipをInventoryへ戻してStorage Capacityを使用し、次Legへ確保する必要があれば通常のReservation / commitmentを利用する。

最終目的地でも同じInventory admission契約を利用する。到着時に荷役・Storage条件が成立していないCargoはarrival waitingとなり、輸送完了前の物理量としてLogistics側へ残る。arrival waitingはCargo Handling / arrival holdingと反復利用可能Transport Capacityへbackpressureを発生させ、無制限の無料Storageとして機能しない。

輸送中Cargoは目的地Storageを事前予約しない。既に同じSupply Requirementへ割り当て済み・輸送中のCargoは未充足見込みから控除し、重複発送を防ぐ。

### 9.5 End-to-End輸送

PlayerまたはSupply Planningは最終destinationとResource需要を提示し、Logisticsは現在成立しているMovement / Transport ServiceとOperational Nodeからend-to-end pathを導出する。中継Nodeごとの再発送Commandを通常操作として要求しない。

hard routing constraintがある場合は、そのconstraintを満たす候補だけを利用する。constraintがない場合は、latency、Propellant等の運用Resource負担、handoff負担、利用可能Transport Capacity等の実際の物流特性を一つの正準評価として比較し、同じphysical stateから同じpathを決定論的に選択する。評価上同値の候補だけstable keyでtie-breakする。

本作は本格的な軌道位相計算やlaunch window等の時間変動するroute optimizationを扱わない。通常経路はCoreの正準評価で選択し、静的な候補間に存在する所要時間、推進剤等の運用Resource負担、handoff負担のtrade-offを評価へ含める。

需要側routingは既存Serviceを選択する責務であり、特定Transport AllocationがどのVehicleとMovement Operationで反復Serviceを供給するかという供給側構成を暗黙変更しない。

同一Vehicle / Transport Serviceが途中でCargoを保持したまま運行を継続できる場合、Movement上に複数Operationが存在していても一つの物流Legとして扱える。実在するOperational Nodeで別Fleet / Transport ServiceへCargoを引き渡す地点だけが物流上のhandoff pointとなる。Spatial hierarchy上の中間contextそれ自体はhandoff pointではない。

LEOや月周回軌道等は有力な補給・積替え・整備Nodeになり得るが必須進行ゲートではない。有限・状況依存のFounding、Fleet relocation、Scientific Exploration等は一回限りのMovementとして同じMovement評価契約を利用し、通常物流を個体Missionの反復へ戻さない。

## 10. ロケット・宇宙船の建造と保有

ロケットや宇宙船は外部サービスだけでなく、プレイヤーが建造・保有できる物理資産とする。通常運用では同型機と所在Operational NodeごとのFleet数量として管理し、個体識別そのものを主要なゲーム操作にはしない。

Vehicle Definitionは固定の`t/day`能力ではなく、任意のMovement Planについて適合性、Payload、latency、運用Resource、反復cycleを導出できる性能を持つ。Dry Mass / Payload、Propellant、Operation Capability、Endurance、Docking / Refueling Interface、turnaround / maintenance、Production Requirement等を必要に応じて定義する。

Spatial relationのcharacteristic geometryやOperation要件をVehicle性能と組み合わせ、Movement可否、1cycle当たりPayload、所要時間、推進剤需要、整備需要を導出し、Fleet投入数から定常Transport Capacityへ変換する。Delta-v等は適用可能なOperationの評価指標として利用できるが、すべてのMovementを一つの性能尺度へ固定しない。用途名や機種名へ物流能力を直接結び付けない。

Vehicle Assembly等へ建造を指示すると、製造Capability / Service、Resource、時間を消費してProduction状態へ入り、完了後に建造Operational Nodeの該当Fleetへunitを追加する。地球外を含む任意Operational Nodeで同じProduction requirementを満たせば建造できる。

通常の同型Vehicleは `Vehicle Definition × Operational Node × commitment state × quantity` で管理する。Fleet Domainは総unit数と排他的Fleet Commitmentをauthoritativeに所有する。Commitmentはowner activity reference、vehicle definition、所在またはMovement state、quantity、必要ならcompletion dispositionを持ち、Transport、Scientific Exploration、Fleet-backed Survey / Research Provider、Relocation、Release、Retirement等が同じunitを二重所有しないようにする。

Transport Allocationだけは、free Fleetを複数Allocationへ自動配備する継続IntentとしてProvisioning Priorityを持つ。他のFleet利用Activityへ同じ自動Provisioning semanticsを一律適用せず、各Activityの開始・割当Command等から必要unitをcommitする。

Fleet relocationは一回限りのMovementとして実際の所要時間を持つ。出発したFleetはsource側free Fleetから除かれ、Movement完了後にdestination側Fleetへ加わる。Transport AllocationをPause /解除する場合も運用中Fleetを瞬時にfree Fleetへ戻さず、必要な回収・release時間を経て解放する。

不要になったVehicleはFleet Retirementとして退役できる。退役対象は所在Operational Nodeでfreeなunitから排他的にcommitし、通常のService Capacity / Resource requirementとして表現される解体workを経てFleet総数を減らす。salvageはVehicle Definitionのrecovery定義からrecovery potentialを導出し、Facility Decommissionと同じく全salvage Resourceへ共通recoverable fractionを適用して、実際にInventory Admissionできる量だけPlayer-owned Resourceとして生成する。salvageを全量受け入れられないことだけを理由にRetirement完了を永久停止しない。

個体ごとの耐久・改修・履歴が主要な意思決定にならない限り恒久Vehicle Entityを導入せず、必要な差は可能な範囲でcohortとして集約する。

UIでは所在Operational Node、総数、free数量、owner activity別commitment、再配置・release・Retirement状態を確認できるようにする。Transport UIは方向別Capacity target、Provisioning Priority、必要・投入隻数、Nominal / Available / Used / Spare Capacity、運用Resource需要、blocker / limiting factorを表示する。

打上げヴィークル、軌道間輸送船、着陸船、統合型宇宙船等を用途名称だけで使用制限しない。実性能がMovement Operation要件を満たすかで判定する。

## 11. 科学探査とResearch Point

資源Surveyとは別にScientific Exploration Campaignを導入する。

Scientific Explorationは必要性能を満たすFleet unitをFleet Domainへ排他的にcommitし、往路・科学活動・必要な帰還を含むCampaignを進行させて有限量のResearch Pointを得るシステムとする。物流とScientific Explorationは同じFleet資産を競合するため、輸送capacityを維持するか研究獲得へ回すかが明示的な資産配分判断になる。

Campaignは必要に応じて、探査対象・科学目的、必要Operation / Endurance / Payload、必要環境・Infrastructure / Capability、所要期間、有限Research Point総量と生成率、消耗Resource、完了後Fleet dispositionを持つ。

科学活動中に生成するResearch Pointは共有Knowledge Poolのadmissionと同じexecution settlementへ接続する。Research Point貯蔵余力が不足している量についてCampaignのproductive science progressだけを進めて有限報酬を消失させず、RP admission不足をlimiting factorとして表示する。移動progressは科学活動progressと分離し、開始済みMovementをRP容量不足で物理的に停止させない。

CampaignをPauseした場合は新たな科学executionを進めないが、開始済みMovement等の物理obligationは通常どおりsettleする。CampaignにcommitされたFleetはPauseだけで他用途へ二重利用可能にせず、解放・中止・帰還が必要ならCampaign lifecycleの明示transitionを通す。

同じ科学探査を無期限に繰り返すだけで無限Research Pointを得る構造は避ける。基本は有限Campaignとし、継続観測型を導入する場合も有限budget、逓減、上限、運用コスト等から無限無料生成にならない条件を明示する。

これにより、Fleetを建造する → 輸送能力へ投入するか探査へ割り当てるか選ぶ → 探査でResearch Pointを得る → 新技術を研究する → より高性能なFleet・研究設備・探査手段を成立させる、という資産配分のループを作る。

## 12. 研究システム

研究は本作の中心的な成長システムとする。

Research Point源は、地上研究設備、人工衛星、有人実験、軌道研究設備、Scientific Exploration、地表研究所、実証設備等である。研究源ごとに「この研究にしか使えないRP」という適用範囲は原則設けず、生成したResearch Pointは組織全体の共有Knowledge Poolへ蓄積する。

研究資産の世代差はTierで表現し、Tierが上がるとResearch Point生成効率と貯蔵能力を明確に向上させる。技術的に高度な研究は必要Research Pointも大きく増えるため、初期研究源だけで後期研究を進めることは理論上可能でも極めて遅くなる。

研究施設・研究資産はLevelを持てる。

- Tier：研究手段そのものの世代差・基礎効率差
- Level：既存設備への増設、拡張、改良、運用成熟

ここでいうResearch ProviderのTierは研究設備・研究手段の世代差であり、§13.1の研究段階区分とは別概念とする。研究項目の表示段階が上がったことだけを理由にResearch ProviderのTierを自動更新しない。

一世代前の高Level資産と新世代の低Level資産が一定範囲で競合できる一方、十分な規模では新Tierが効率面で優位になるよう調整する。

Research Pointの貯蔵上限は研究基盤の規模を表す。容量低下で既獲得点を消滅させず、新規生成を停止または制限する。Facility、Fleet、Scientific Exploration等によるRP生成は、同じResearch Point Pool headroomを有限capacityとして競合し、出力先容量を二重利用しない。

Facility-backed Research ProviderはFacilityのPower、Maintenance、Environment等の成立条件からRP generation / Research execution供給量を導出する。Fleet-backed Research Providerは、どのFleetを継続的な研究供給へ用いるかを `Research Provider Assignment` として明示し、そのAssignmentがFleet Domainの排他的commitmentを参照する。Assignmentは所在Operational Node、対象Vehicle、Activity Priority、Pause状態、Fleet Commitment参照を所有し、割当unit数量そのものはFleet Domainだけがauthoritativeに所有する。

PlayerはResearch Provider用途へFleetを何unit配分するかを指定する。Applicationは希望quantityを受けてResearch Provider AssignmentとFleet Commitmentを原子的に作成・resize・releaseし、必要差分をfree Fleetから確保できなければStateを変更せずblockerを返す。

commitされたunitがProvider運用条件を満たす場合だけRP generation / Research executionを供給し、Transport、Survey、Scientific Exploration等へ同時配分しない。Activity PriorityはRP generation / Pool admission等の実際の競合へ作用する。AssignmentをPauseしても研究供給だけを停止してFleet commitmentは保持し、Fleetを他用途へ戻す操作はreleaseとして分離する。

Research Projectは複数を並行して進められる。並行性は固定queue数ではなく、Research Point、必要Facility / Capability、Research execution Service Capacity、Prototype Resource、Demonstration条件等の実際のボトルネックによって制約する。共有Research Pointを複数Projectが必要とする場合はActivity Priorityに従って配分し、Project処理順の先着消費にしない。ProjectをPauseしてもStage progressと明示的に取得済みのResource Reservationは保持し、Reservationを解放して計画自体を戻す操作はCancel / releaseとして分離する。

Theoryに用いるResearch executionはOrganization scopeのService Capacityとし、所在地の異なる有効な研究providerから供給されたAvailable capacityを組織全体で競合利用できる。各providerは所在地でPower、Maintenance、Environment等のローカル条件を満たさなければOrganization poolへ能力を供給しない。研究施設をRP generatorだけに縮退させず、RP生成とResearch execution供給を独立した能力として持たせる。

---

## 13. 研究進行

研究開始・完了条件はResearch Pointだけに統一しない。Research Definitionは、研究内容に応じてTheory、Prototype、Demonstration、Operational Experienceという意味の異なるtyped Stage Specを必要な組み合わせ・順序で持てる。各Stage種別のRequirement、progress、completionの意味はCore契約として明示する。

- Theory：Organization scopeのResearch PointとResearch execution能力を使って理論・設計を成立させる。
- Prototype：明示Execution Siteで試作Resource、Facility / Capability、有限Service Capacity等を使って試作を進める。
- Demonstration：明示Execution Siteと指定条件の下で一定期間・work量等の実証を進める。
- Operational Experience：実Domain activityから蓄積されたKnowledge Stateが必要値へ到達することを要求する。

Research Definitionは一つ以上のtyped Stage Specをordered listとして定義する。各Stage instanceはResearch Definition内で一意な `stage_id` を持ち、技術内容上別の試作・実証・理論検討等を順次要求する必要がある場合は、同じStage種別を異なる `stage_id` で複数回配置できる。Project Stateは現在の `stage_id`、Activity Priority、必要なExecution Site / Reservation / commitment参照をauthoritativeに所有し、Theory / Prototype / Demonstration等で実行量を蓄積するStageだけstage-local progressを保持する。Operational ExperienceはKnowledge Stateの値をcompletion conditionとして参照し、同じ経験量をProject progressへ複製しない。Stage progressはAllocation済みRequirementの範囲だけで進行し、Stage completionはcanonical boundaryでDefinition上の次Stageへsettleする。最終Stage完了時だけTechnology StateへUnlockを記録する。

Prototype / DemonstrationのExecution SiteはOperational Nodeを基本とし、研究内容がSurface Cell localなPhysical Environmentや位置そのものを必要とするときだけSurface Cell contextを追加指定する。実施場所は特定Location IDで固定せず、Spatial classification、Environment、Capability、Knowledge等のEligibilityと、実行時に競合するResource / Service Requirementから候補を判定する。有限Research executionやConstruction work等をSite可否だけで消費済みにせず、通常Allocationへ接続する。

Operational ExperienceはResearch Project自身が時間経過だけで生成するpointではない。輸送、採掘、製造、有人運用等の実Domain activityが対応するexperience categoryへ知識を蓄積し、Researchはその状態をrequirementとして参照する。

研究完了によるTechnology Unlockは一つのauthoritativeなTechnology Stateへ記録する。Facility、Process、Vehicle等の各Domainは解禁状態を重複保存せず、この状態を参照する。研究完了で既存設備を自動更新しない。

研究項目は単純な「生産量+10%」より、独立した技術的制約の克服、新しい原理・装置・工程・運用方法の成立、後続研究へ意味のある前提を提供することを優先する。研究項目数を段階または区分ごとに固定せず、必要な技術課題を分解した結果として研究数を決める。

### 13.1 研究段階区分とTechnology DAG

研究の発展段階は、Technology DAGの成熟度とゲーム世界における宇宙活動の変化をプレイヤーへ可視化する表示metadataとする。研究開始可否とTechnology Unlockは各Research Definitionが持つ具体的なprerequisiteから個別に決まり、表示段階は研究項目を束ねる一括gateとして扱わない。

表示名は、宇宙活動の技術的成熟と運用形態の変化を表す基準名として次のように定義する。第9段階以降も、同じ原則でTechnology DAGへより高い成熟段階を追加できる。

| 段階 | 表示上の基準名 | 発展の目安 |
|---|---|---|
| 1 | 軌道活動・近傍天体探査 | 地球近傍での継続的宇宙活動と初期の近傍天体探査 |
| 2 | 長期無人域外活動 | 月面・惑星表面等での長期間の無人探査・作業 |
| 3 | 長期有人域外活動 | 地球近傍を越えた有人探査と長期間有人運用 |
| 4 | 恒久的域外活動 | 継続補給・保守・建設を伴う恒久的な域外活動 |
| 5 | 域外産業化 | 探査・拠点維持から継続的な資源処理・製造・産業運用への発展 |
| 6 | 惑星間産業ネットワーク | 複数地域の産業・物流・研究が相互依存する惑星間ネットワーク |
| 7 | 外惑星・極端環境活動 | 長距離、高放射線、低日射等の極端環境での持続的活動 |
| 8 | 太陽系規模インフラ | 太陽系内の複数圏域を結ぶ長期的・分散的インフラ運用 |

研究の専門区分はTechnology DAGを表示・探索しやすくする分類metadataとする。推進、電力、熱、材料、通信、計算、航法、自律制御、観測、資源、建設、生命維持、生命科学、食料、居住、保守等を基礎区分とし、実際の技術課題の粒度に応じて細分化・統合する。各区分の研究数は、その分野に存在する独立した技術課題と他技術への因果関係から決める。

各技術系列は、同じ技術課題が成熟していく過程を段階を越えて追える縦方向の連続性を持つ。典型的な発展方向は、基礎現象の理解・計測、基本機構の成立、長時間・高負荷条件への適応、劣化・故障の理解、反復利用・閉ループ化、自律・統合運用である。系列ごとの必要段数は技術内容から決まり、成熟した系列は産業化、自律運用、物質循環、惑星間ネットワーク、極端環境活動など、より高い段階の技術課題へ接続する。

Technology DAGは、系列内の成熟関係と、技術成立に必要な区分横断prerequisiteの双方を表す。例えば推進は材料・熱制御・計算・計測へ、生命維持は電力・熱・微生物学・計測へ依存し得る。区分横断edgeは実際の技術的因果関係に基づいて設定し、複数の合理的な技術経路から発展方針を選べる構造を保つ。

### 13.2 研究項目の設定原則

研究項目は、複数の応用へ一般化可能な科学・工学上の技術課題を単位とする。各項目は、何を理解し、計測し、制御し、製造し、または運用できるようになるのかを名称と内容から具体的に識別できるようにする。名称に用いる条件語は、対象となる物理領域、負荷条件、時間尺度、制御対象など、研究内容そのものを特定する情報として機能させる。

研究項目を独立させる目安は、少なくとも次のいずれかを満たすことである。

- 独立した技術的制約・科学的不確実性を克服する
- 後続研究に意味のあるprerequisiteを与える
- 複数の応用先で再利用可能な知識・工程・制御能力を成立させる
- ゲーム上区別する価値のある新しい運用可能性または効率変化を生む

製品、Facility、Vehicle、特定Locationでの活動は、それ自体を研究単位とするのではなく、成立に必要な一般化可能な技術課題へ分解してTechnology DAGへ配置する。研究粒度は、独立したプレイヤー判断、後続技術への因果関係、または再利用可能な能力が一つの項目として認識できる範囲に保つ。より細かな差異で独立した技術判断を生まないものは、関連するContentの性能差として表現する。

具体的な研究項目名、各項目の表示段階、専門区分、prerequisiteはContent Definitionとして構成する。Technology DAGはacyclicとし、同一系列の縦方向の成熟と区分横断依存を同じdirect prerequisite graphで表現する。推進・発電・自律化・有人／無人運用等には複数の合理的な研究経路を構成でき、プレイヤーが選択した技術体系に応じて未取得系列が残る状態もTechnology DAG上の通常状態として扱う。

有人運用は、crew-ratedなVehicle / Facility特性、Habitation / Life Support等のCapability・Service Capacity、消耗ResourceのExecution Requirement / Supply Requirementとして表現する。Crew個人・人口の配置、成長、リスクが独立したプレイヤー判断を構成する設計へ発展した場合は、そのState ownershipを独立Domainとして定義する。

## 14. 資源Survey

資源Surveyは、地表資源を無条件で完全可視化せず、観測・探査能力への投資によって知識を段階的に得るための仕組みとする。Scientific Explorationが有限Research Pointを得る科学Campaignであるのに対し、Resource Surveyは `Surface Cell × Resource` ごとのKnowledgeを更新する。

Knowledge Levelは以下を基本とする。

```text
UNKNOWN
→ PRESENCE_PROBABILITY
→ ESTIMATED_RESOURCE_POTENTIAL
→ MEASURED_RESOURCE_POTENTIAL
```

各Levelは公開可能な情報を段階的に増やす。Presenceでは存在確率、Estimatedでは推定Potentialとuncertainty、Measuredでは投資判断に用いる測定済みPotentialを示す。Survey KnowledgeとStatic Resource Potential自体は分離し、Knowledge進展が地質量そのものを書き換えない。

Survey ProviderはFacilityまたはFleetから有限なSurvey / Observation Service Capacityを供給できる。Provider / Observation Modeはsurvey rate、coverage / reach、max Knowledge Level、precision、必要Operation / Infrastructure / Capability、minimum source units等の物理差をContent Definitionとして持てる。軌道Remote Survey等は対象天体にSurface Locationが存在しなくても成立し得る。

Fleet-backed Survey ProviderはProvider AssignmentがFleet Domainの排他的Fleet Commitmentを参照し、Fleet quantity自体はFleet Domainだけがauthoritativeに所有する。Playerは対象Provider用途へFleetを何unit配分するかを指定し、Survey CampaignはそのProvider能力をService Capacityとして利用する。Campaign自身へFleet Commitmentを複製しない。

PlayerはSurvey Campaignへ単一Cell × ResourceのJobを一件ずつ登録するのではなく、調査対象となるSurface Cell集合、Resource集合、goal Knowledge Levelを指定する。UI上の地域選択は最終的に対象Cell集合へ解決し、別の永続Region Entityを必須にしない。Campaignは指定scope内のKnowledge Stateから未完了targetを導出し、利用可能Survey Capacityを配分する。完了targetはactive allocationから外し、同じscopeの未完了targetへ余剰能力を再配分できるが、未指定Cell / Resourceを勝手に追加せず、goal Knowledge Levelを越えて自動Surveyしない。

通常は、Campaignのscopeとgoalを満たすProvider / Observation Mode候補をCoreがEligibilityと実際の能力から解決する。候補が一意、またはゲーム上同等ならPlayerへ冗長な選択を要求せず決定論的に選択してよい。一方、必要Fleet拘束量、Resource消費、Reach、所要時間、Infrastructure Requirement、到達可能Knowledge Level等に戦略的な差がある場合は、Applicationが候補差を返し、PlayerがProvider / Observation Modeをhard constraintとして指定できる。登録順やID順だけで戦略的に異なる候補を暗黙選択しない。

Survey CampaignはActivity PriorityとPause / Resumeを持てる。PauseはCampaignの観測需要を停止するがProvider Assignmentを変更しない。Founding、Development、Extraction等はSurvey内部progressを直接参照せず、対象subjectとminimum Knowledge Levelを明示するKnowledge Requirementを通じて利用する。

## 15. Location開発とロケーション産業自立

Locationの発展は「到達したか」「基地が存在するか」という一段階ではなく、Survey、Founding、領域開発、資源利用、加工、研究維持、現地製造、自己拡張能力を段階的に成立させる過程として扱う。

典型的には、既存Operational Nodeから未開発地域をSurveyし、有望Surface Cellを比較し、Founding / Deploymentで新Locationを設立し、通常物流・建設へ接続し、Resource PotentialとExtraction Service Capacityを組み合わせて現地資源利用を成立させる。その後、基礎工業・Surface Infrastructure・Gateway・研究設備を増強し、同一Location拡張と別Location設立を比較しながら複数Operational Nodeの産業・研究・物流を統合する。

初期Contentでは月面開発がこの進行を代表するが、Coreで扱う概念はロケーション産業自立であり、特定天体名へ結び付けない。火星、小惑星、軌道拠点その他の地域でも同じOperational Nodeモデルを利用する。

ロケーション産業自立はbinaryな達成状態や単一の自給率ではなく、選択したOperational Node集合について外部依存構造を示すderived analyticsとする。Resource単位を正本とし、Contentは表示・分析用Resource Groupを定義できる。Mass、Energy、Propellant、Machinery等の固定カテゴリをGeneric Coreへ埋め込まない。

分析は少なくとも二つの時間基準を区別する。

- `CURRENT`：現在のproduction、consumption / demand、imports、exports、unmet demandからsnapshot時点の依存構造を示す。
- `FORECAST`：active Project、Supply Requirement、Target Stock等が持つforecast requirement time / consumption rateから、既に計画へ現れている将来dependency / critical resourceを示す。固定の将来日数をStateとして持たず、UIが期間を絞る場合はQuery filterとして扱う。

Resource flowとPower等のService dependencyを一つの「Energy」値へ混在させない。Service Capacity依存を分析する場合はResource dependencyとは別のprojectionとして扱う。

同じ高Potential地点へ採掘設備を追加し続けるほど限界収益は低下するため、既存Locationの高密度化、隣接地域への拡張、別Locationの設立と物流投資を比較する。資源枯渇を強制移住の主因にはしない。発展した拠点をPrestige等で操作不能にせず、新技術は既存Facility更新、Surface Infrastructure増強、再開発理由にもする。

## 16. 自動進行と自動化

ゲーム時間は通常状態で自動進行する。プレイヤーは一時停止と複数段階の速度変更を行う。

Simulationは1 game dayをcanonicalな状態更新単位とする。一日の開始時点で利用可能なInventory、Reservation、Facility、Fleet、Environment、Capability、Service Capacity等をPhysical snapshotとして固定し、その日のPlanning / Allocationを決める。その日に新たに生産・到着・完了したResourceやCapabilityは、次の日のsnapshotから新しいAllocationへ利用する。

通常速度、高速進行、Offline Progressはいずれも同じ日次Simulation semanticsを利用する。複数日を一括して計算できる区間は実装上まとめてよいが、同じ期間を日次Simulationで進めた結果と同じStateへ到達することを契約とする。

自動化対象は、定常生産・採掘、Execution / Supply Requirement生成、通常需要とTarget Stock不足からの発送必要量算出、設定済みPriorityによるResource / Service / admission配分、成立済みTransport Network内での通常source / end-to-end path選択、Research Point生成、設定済み研究・Survey・Scientific Explorationの進行、Survey scope内の未完了targetへの能力配分、Transport Allocation目標へのFleet投入、Cargo allocation / arrival、Trade Order反復充足、建設、保守、Offline Progressとする。

プレイヤー判断として、研究対象、設備投資、Activity Priority、拠点間物流能力、Vehicle建造とFleet用途配分、Transport Allocationの方向別Capacity targetとProvisioning Priority、通常需要を超えるTarget Stock、必要時のrouting hard constraint、External Resource Market Order、新地域への進出、発電方式、技術経路、Survey scope / goal、Asset廃止等を残す。Coreは通常運用の自動化によって新しいFacility、Vehicle、Transport Allocation、Trade Order、Target Stockを生成しない。

施設、建設案件、研究、Survey、Scientific Exploration、Transport Allocation等は必要に応じて停止・再開できる。PauseはCancelと区別し、設定と成立済みprogressを保持し、開始済みMovement、dispatch済みCargo、Market Commitment等の物理obligationを巻き戻さない。一方、Pause中もすべての排他的Asset commitmentを永久保持するという共通ルールにはしない。継続能力を供給するResearch / Survey Provider AssignmentではActivity PauseとFleet releaseを分離し、one-shot CampaignやTransportでは各Domainが物理obligationに沿ったrelease / completion transitionを明示する。

Transport AllocationのPauseはtargetと明示hard constraintを保持しつつ新規dispatch / provisioningを止め、既に運用中のFleetは必要なrecovery / releaseを経てfree poolへ戻す。再開時は保持したtargetに対して再度Provisioningする。Scientific Explorationのような一回限りCampaignは、PauseだけでCampaign Fleetを別用途へ解放せず、必要ならAbort / Return / Cancel等の明示transitionを利用する。

## 17. LLM利用方針

LLMはプレイヤーの主要判断を代行させない。

「LLMによってプレイヤーが考える対象が増えるなら利用する。プレイヤーが考える必要を減らす用途には原則利用しない。」

候補用途：

- 外部組織の要求・提案
- 特殊イベント
- 組織間交渉
- 科学的不確実性
- 研究上の問題
- 状況依存Mission
- 世界側の反応やニュース

通常SimulationとLLMは分離し、LLM応答待ちでゲーム進行を止めない。

---

## 18. Simulation Core / Application / UI

ゲームルールはUI、HTTP、LLMから独立させる。UIはSimulation内部を直接操作せず、Application LayerのCommand / Query境界を利用する。

主要Command例：

- 時間一時停止・再開・速度変更
- Operational Node Founding Deployment・Surface Location隣接Cell開発
- 建設計画・停止・再開・取消
- Facility停止・再開・Levelアップ・Process選択・Decommission計画/取消
- Activity Priorityを1〜5で設定
- Vehicle建造・Fleet再配置・Fleet Retirement計画/取消
- Transport Allocation設定・停止・再開・解除・方向別Capacity目標・Provisioning Priority・必要時のMovement hard constraint設定
- 通常需要を超えるTarget Stock設定
- 必要時のsource / via / Transport Service等のrouting hard constraint設定
- External Resource Market Buy / Sell Order作成・変更・取消
- 手動Cargo / 特殊Movement
- Research開始・停止・再開・Activity Priority・current `stage_id` のPrototype / Demonstration Execution Context設定
- Fleet-backed Research ProviderへのFleet数量配分・Priority・Pause / Resume・release
- Fleet-backed Survey ProviderへのFleet数量配分・release
- Scientific Exploration開始・停止・再開・Fleet unit割当・Abort / Return / completion disposition設定
- Resource Survey開始・停止・再開・Surface Cell / Resource scope・goal Knowledge Level・必要時のprovider / observation mode hard constraint設定
- 位置依存FacilityのSurface Cell配置

主要Query例：

- 世界・天体Surface Map・Operational Node / Location概要
- Surface CellごとのSurvey Knowledge Level、presence probability、estimated range、measured Resource Potential、Environment、開発状態
- Inventory・Reservation・Inbound / outbound flow・Storage / over-capacity状態
- Facility / Level / 維持充足率 / 配置種別 / 現在Process / Process候補
- Capability / Service CapacityのNominal / Available / Allocated / Spare
- Activity Priority / Execution Requirement Bundle / requested execution / fulfillment / limiting factor
- Process投入・産出・稼働率・limiting factor
- 建設候補・案件・将来Supply Requirement・Projected Material Readiness
- Operational Node Founding候補・Knowledge / Site / Movement / manifest blocker
- Vehicle建造候補・必要資材・blocker
- Fleet総数 / free / owner activity別commitment、Transport Allocation / Provisioning Priority / Target・Nominal・Available・Used・Spare Capacity / Required Fleet Units / Retirement状態
- end-to-end Movement / Transport Service候補・latency・運用Resource負担・選択済みroute・hard constraint
- Cargo Flow / handoff / arrival waiting / transport capacity shortfall
- Target Stock / current stock / inbound amount / 通常需要と追加備蓄需要
- Funds / Market Provider / Market Interface / buy-sell offer / Trade Order / committed-settled量
- Research Point生成量・保有量・上限 / Technology Unlock / Operational Experience
- Research Provider / Fleet-backed Assignment / Fleet commitment / RP generation・Research execution供給量
- Research Projectのcurrent typed Stage、progress、Execution Context、Requirement、Reservation、blocker
- Scientific Explorationのphase / science progress / RP budget / Fleet commitment / disposition
- Resource Surveyのscope、goal Knowledge Level、completed / remaining target、resolved provider / observation mode、戦略差のある候補、Survey Provider Assignment / Fleet commitment
- Facility Decommission / Fleet Retirementのwork、不可逆状態、existing-stock blocker、recovery potential、見込recoverable fraction / amount
- Location領域、developed-cell Environment summary、Surface Infrastructure負荷、Gateway / access anchor候補
- Operational Node集合のCURRENT / FORECAST Resource dependencyと必要ならService dependency
- Bottleneck / blocker

通常routingやSurvey provider選択を自動化しても、その結果と理由、limiting factor、明示hard constraintをUIから確認可能にする。情報を隠すことで操作を簡略化せず、操作対象となる概念自体を戦略判断へ絞る。

UIは建設可否、維持率、機体適合、Movement、研究条件、資源・能力配分、routing、Survey推定値等を独自再計算しない。Core/Applicationが判断材料、Priority、Allocation結果、予測準備時期、停止理由、候補差を返す。操作不能な状態でも必要条件、現在設定、progress、commitment、候補とblockerを隠さない。Priority UIは5段階の固定選択として表示し、標準値3を「標準」として提示する。

UIはiPad横画面を正式対応対象とし、Playerの判断対象を中心に構成する。別画面の数値や対象を記憶して戻って入力することを要求せず、blocker、必要条件、Current / Target / Preview、関連対象を判断地点で確認できるようにする。主要なPresentation構造、Navigation、直接操作、Attention、Planning Mode、各Domainの主要動線は `ui.md` を正本とする。

## 19. Save / Load / Offline / テスト

Saveはversion付きSnapshotを基本とし、静的World / Content DefinitionはContentから再構築し、可変authoritative Stateだけを復元する。Snapshotはdomain-owned state sectionを保ち、Facility lifecycle / Process selection、Project / Activity control、FleetPool / Fleet Commitment、Transport Allocationの方向別Capacity target / Provisioning Priority / optional hard constraint、Inventory / Reservation / Cargo、Target Stock、必要なrouting hard constraint、Market State、Research Provider Assignment / Research Project current Stage、Exploration、Survey Knowledge / Survey Provider Assignment / Survey Campaign scope、Dynamic Environment等を各所有Domainの境界に沿って保存する。中央Save schemaへDomain内部fieldを無秩序に平坦化しない。

Movement Plan、Transport Service Plan、auto-selected source / path、Required Fleet Units、current Capacity、auto-selected Survey provider / observation mode、Survey Campaignから展開した未完了target集合、salvage回収見込、Analytics、Projected Material Readiness等のderived / transient stateは保存せず再導出する。Saveは `world_definition_id` と `scenario_id` をmetadataとして保持し、Load時にScenario初期化を再実行しない。

Offline Progressは通常Simulationと別ルールにせず、実時間をゲーム時間へ変換した上で同じ日次時間進行経路を利用する。通常進行、高速進行、Offlineで同じgame timeを進めた場合は同じSimulation Stateへ到達することを不変条件とする。複数日をまとめるfast-forwardは、この同値性を保つ実装最適化としてのみ利用する。

テストは暫定バランス数値や過去の内部構造を固定せず、少なくとも次の構造的不変条件を優先する。

- Resource / Cargo / Funds / Fleetが負にならず、authoritative ownershipを二重保存しない。
- 通常物理ResourceがStorage accountingを迂回せず、特殊保管が必要なResourceだけcompatible poolを要求する。
- Inventory / Reservation / Logistics-owned Cargo / Market Commitmentの保存とatomic settlementが成立する。
- Execution Requirement Bundleが複数Resource / Service / output admissionを同じexecution fulfillmentでsettleする。
- Eligibility判定だけで有限Serviceを消費済みにせず、Allocationで競合させる。
- PriorityLevelが1〜5の順序尺度として機能し、同順位結果が登録順へ依存しない。
- 通常Supply RequirementはTarget Stock未設定でも自動補給され、Target Stockは追加備蓄需要だけを作りInventoryを予約しない。
- routing hard constraintがない同一physical stateからsource / pathが決定論的に導出され、hard constraintが成立しない場合は別戦略へfallbackしない。
- Auto-routingがTransport Allocation target、Fleet、Trade Order等を暗黙変更しない。
- Transport Allocationのauthoritative targetが方向別Capacityで、Required Fleet Unitsが派生し、Provisioning Priorityが別Activityへcommit済みFleetをpreemptしない。
- Pause / Resumeが設定・progressを保持し、開始済み物理obligationを巻き戻さず、Transportはsafe releaseを行う。
- Operational Node Foundingがprepared Resource / FleetをMovement payloadへ移し、target typeに応じたStateへ一度だけsettleする。
- Founding / Development Knowledge Requirementが対象subjectとminimum levelを明示し、無関係なSurvey結果で満たされない。
- Scientific ExplorationがRP Pool容量不足時に有限RPを消失させず、science progress / RP settlementを整合させる。
- Research Projectのtyped ordered Stageとcurrent stageが一致し、最終Stage完了時だけTechnology Stateを更新する。
- Facility Processが複数候補時にPlayer選択を要求し、登録順で暗黙決定しない。
- Facility Build / Upgrade Recipeが有限個の明示Resourceを消費し、Resource種類数をGeneric Core固定上限にしない。
- 維持需要が累積投入Resourceとmaintenance fractionから決定論的に導出される。
- Extraction responseがCapacityに対して単調非減少・限界収益逓減で、Content固有任意関数へ分岐しない。
- Surface LocationのEnvironment / Movement / Surface Infrastructureをcore cellへ暗黙縮退させない。
- Survey Campaignが指定scope外を更新せず、goal Knowledge Levelを越えず、Provider / Observation Modeの物理制約を守る。戦略的に異なる候補を登録順で暗黙選択しない。
- Fleet-backed Research / Survey Provider AssignmentとFleet CommitmentがFleet数量を二重所有しない。
- Facility Decommission / Fleet Retirementが既存在庫を消去せず、salvage回収が全Resourceへ共通fractionで適用され、Resource列挙順に依存しない。salvage全量を受け入れられなくてもAsset removal自体は完了できる。
- CURRENT / FORECAST external-dependency Analyticsをauthoritative Stateとして保存しない。
- Save / Load後の将来進行、通常速度・高速進行・Offlineの同game time進行が一致する。
- Location固有ID、Vehicle用途名、暫定Content値によるGeneric Core分岐が存在しない。

## 20. World / Scenarioと初期Content

静的な宇宙・天体・Surface Cell topology、Resource Potential、基準Physical Environment等を `World Definition` とし、ゲーム開始時のPlayer所有・運用状態を `Scenario Definition` として分離する。

Scenario Definitionは少なくとも、開始時Operational Node / Surface Location、Facility、Fleet、Inventory、Knowledge / Technology、Funds、Market Provider State / Market Interface等のPlayer Stateを構成する。戦略的なsource / via固定がScenario自体の意味として必要な場合だけ初期routing hard constraintを持てる。開始時の具体的数量・価格・Facility数はContent balanceであり、Core仕様として固定しない。

標準Scenarioでは、地球側に基礎産業・研究・打上げ・Vehicle建造を開始できる運用基盤、Resource売買に利用できる地球側Market Interface、成立済みTransport Network内で初期の反復物流を自動進行できる能力、地球周辺から月をRemote Surveyして候補を比較し、通常のResource / Fleet / Founding契約だけで最初の月面Locationを設立できる軌道・Fleet能力を持たせる。一方、開始時からプレイヤー所有の月面Surface Locationや完全な月面Resource Knowledgeは与えない。これらは開始時Facility数、Fleet数、Funds額等の固定値ではなく、標準Scenarioが成立させるゲームループ上の能力として扱う。月面進出はRemote Survey → 候補比較 → Founding Deploymentという通常ゲームループを使う。

初期Content候補：

### 地球初期Location

- General Research Laboratory
- Surface Aggregate Quarry
- Metal Ore Mine
- Industrial Water Processing Facility
- Basic Structural Material Plant
- Basic Machinery Works
- High-Energy Propulsion Test Stand
- Vacuum Materials Laboratory
- Launch Vehicle Factory / Vehicle Assembly Facility
- Launch Complex
- Launch Vehicle Refurbishment Facility
- Satellite Factory
- Mission Control

### 軌道・近接領域

- Earth Observation Satellite
- Microgravity Experiment Platform
- Crewed Orbital Laboratory
- Orbital Service Station
- Propellant Depot
- Assembly Platform
- Maintenance Dock
- Cargo Terminal

### 月周回・深宇宙

- Multispectral Survey Orbiter
- Neutron Spectrometry Orbiter
- Cislunar Relay Constellation
- Sample Return Vehicle
- Deep-Space Experiment Platform

### 月面

- Robotic Geology Station
- Cargo Depot
- Surface Solar Power Grid
- Regolith Harvester
- Volatile Extractor
- Water Extraction / Electrolysis
- Regolith Sintering
- Ore Processing
- Metallurgy
- Fabrication Workshop
- Machine Shop
- Heavy Equipment Assembly
- Sample Analysis Laboratory
- Vacuum Regolith Process Laboratory

### 初期Vehicle候補

- Reusable Launch Vehicle
- Reusable Orbital Cargo Tug
- Reusable Surface Cargo Lander
- Survey / Experiment Spacecraft

名称は用途を説明するために利用できるが、Operation可否を名称だけで固定しない。

## 21. 横断的なデザイン原則

この節は各メカニクスの詳細を再掲せず、ゲーム全体で維持する判断軸だけを示す。具体的な仕様は対応節を正本とする。

1. **研究と産業を相互強化させる。** Research Point → Technology → 産業・物流・研究手段 → より大きなResearch Pointという中心ループを維持し、距離や資金だけを進行軸にしない。§1–4、§11–13参照。
2. **実際のボトルネックをPlayer判断にする。** Resource、Power、Service Capacity、Fleet、Storage、輸送latency等から制約を発生させ、Activity Priorityは5段階・標準3で「どの活動を先に成立させるか」を表す。§5–6、§9、§16参照。
3. **技術は新しい手段を成立させる。** Research完了だけで既存Assetを一律強化せず、Facility、Process、Vehicle、推進、建設・運用方法等を解禁して投資判断を生む。§6–7、§10、§12–13参照。
4. **空間を経済状態から分離しつつ、距離と立地を意味のある制約にする。** Surface Cell、Operational Node、Surface Locationを役割分離し、任意の成立済みNode間Movementを一般則で評価する。§8–10参照。
5. **宇宙物流は個別便ではなくnetwork capacityとして設計する。** PlayerはFleet配備、Transport Capacity、中継Infrastructure、Target Stock、必要なrouting hard constraint等のNetwork構造を決める。成立済みNetwork内の通常source / path選択はCoreが決定論的に運用し、auto-routingが新しいAssetやCapacityを暗黙生成しない。§9–10、§16参照。
6. **現地産業化の価値を通常Resource flowから生む。** 建設材の産地特例や有限鉱床による強制移住ではなく、Resource Potential、加工、Maintenance、Storage、物流負担からLocation発展を成立させる。§6–9、§15参照。
7. **Location開発を地理的・産業的な選択にする。** 一つのLocation拡張と複数拠点化、Gateway、Surface Infrastructure、Resource Potentialのtrade-offを保ち、必要な情報を判断地点で提示する。§8、§15、§18参照。
8. **Idle自動化はPlayerが成立させた仕組みの反復運用を担う。** Research対象・Execution Site、Priority、Fleet用途配分、Transport Capacity、Target Stock、必要なrouting hard constraint、Resource売買、新地域進出、Survey scope / goal、Asset廃止等の戦略判断はPlayerに残す。通常補給、成立済みNetwork内のrouting、Survey scope内の能力配分等は自動化し、blockerを理由に別戦略や新Assetを暗黙生成しない。§10、§13–16、§18参照。
9. **日次Simulationを共通時間軸にする。** 1 game dayをcanonical state-update単位とし、通常進行・高速進行・Offlineで同じgame timeの結果を一致させる。§16、§19参照。
10. **同じ意味のContent追加をCore例外へ変えない。** 既存契約で表現できる新しい天体、Vehicle、Facility、Research、ResourceはContent追加として扱う。一方、新しいゲーム上の意味やState ownershipが必要な機能は、その時点で正準設計とCore契約を拡張する。全節および `architecture.md` 参照。

---

## 22. ゲーム性評価段階

現在の評価では、最終仕様や全コンテンツを固定するのではなく、本作の中心的な判断構造が成立する程度までメカニクスを実装して比較する。

優先評価対象：

- 自動時間進行、速度変更、一時停止、日次canonical Simulation、Offline同値性
- Research Point生成・貯蔵・消費とPool admission競合
- Scientific ExplorationによるFleet unit拘束、有限RP budget、Pool admission、Movement disposition
- Research Tier / Level
- 複数Research Project、Activity Priority、Theory / Prototype / Demonstration / Operational Experienceのtyped ordered Stage
- Technology Unlock / Operational Experienceの単一状態所有
- 明示Resourceを使うConstruction Recipe（一般Contentでは2〜3主要Resourceを目安とするがCore上限にはしない）
- 建築物の維持Execution Requirement / Supply Requirement
- Execution Requirement BundleによるDomain横断の複合Resource / Service競合
- 5段階Activity Priorityと同順位fair allocation
- Stock / Pool admissionを含む出力側capacity競合
- Capability / Service Capacity分離と共有capacity競合
- Process入出力とUI可視化
- 地球初期採掘・基礎産業
- Vehicle建造とFleet数量管理
- Transport Allocationの方向別Capacity targetとProvisioning Priority、Required Fleet Unitsの派生
- 成立済みNetwork内の通常auto-routingと必要時だけのhard routing constraint
- 通常需要の自動補給と、追加備蓄としてのTarget Stock
- Survey scope / goal指定とProvider / Observation Modeの条件付き自動解決
- Decommission / Retirementの比例salvage回収と既存在庫保全
- Transport AllocationからのTransport Capacity自動生成
- Nominal / Available / Used / Spare Capacityとlimiting factor
- 発電・配電・部分稼働
- 在庫・倉庫・Physical / Usable Storage Capacity・必要な有限荷役Service
- Celestial Bodyごとに可変数のSurface Cellを持つ天体マップ
- Surface拠点なしの軌道SurveyからKnowledge Requirementを満たし、typed Founding targetとDeployment Recipe manifestで任意地点へ最初のLocationを設立し、隣接Cellを開発する一連の進行
- Resource Potential / soft saturation採掘
- Surface Infrastructureによる大規模Locationの集約内部物流負荷
- Operational NodeとSurface Location / non-surface Spatial contextの分離
- 任意Operational Node間のSpatial Relation / Movement Plan導出
- 通常物流のaggregate Transport CapacityとCargo Flow
- direct handoff / Storage経由handoff / arrival waiting
- Supply Requirement、Target Stock、future-aware sourcing / dispatch、auto-routing結果とrouting hard constraint
- 長距離latency下でのProjected Material ReadinessとTransport shortfall表示
- External Resource Marketの有限buy / sell availability、Funds決済、通常Cargo lifecycle / Storage契約
- Facility Decommission / Fleet Retirementと比例salvage settlement
- 推進剤の実資源化
- 複数Surface Cell / Resourceを束ねるResource Survey、Knowledge Level / uncertainty表示、Fleet-backed Survey commitment
- 初期月面ContentでのISRU・現地加工
- Location / Operational Node集合のロケーション産業自立・外部依存分析
- Process選択、routing hard constraint、Fleet commitment、Research stage、Survey Knowledgeを含むSave/Load / Offline Progress
- Bottleneck表示

FundsはResource売買決済だけに用い、一般的な活動コストや報酬ループを進行軸にしない。

複数戦略を比較し、低Tier研究資産を長く育てる戦略と新Tierへ早期更新する戦略、輸送力増強と現地生産、Vehicleを物流へ使うか探査へ使うか、地球産業を拡張するか宇宙資源利用へ早期移行するか等に合理的なトレードオフが生まれることを確認する。

---

## 23. ゲーム定義の要約

本作は、

「探査・実験・研究設備からResearch PointとOperational Experienceを獲得し、その研究成果で産業・輸送・研究基盤を拡大し、Surface Locationと軌道等のOperational Nodeを産業・物流Networkとして発展させながら、5段階Activity PriorityによるResource / Service Capacity配分、建設・維持・資源利用、将来需要を見越した物流、Fleet配分・Transport Capacityのボトルネックを解消し、ロケーション産業自立を高めつつ、より高い桁の知識生産と技術的に困難な宇宙開発へ進むIdle型宇宙産業シミュレーション」

と定義する。

ゲームの成長感は、契約を繰り返して資金残高を増やすことではなく、

「地球の低効率産業と人工衛星・地上研究設備で基礎知識を得る段階」
から
「自前のロケット・宇宙船Fleetを建造し、任意拠点間の定常輸送能力と科学探査へ配分する段階」
へ、
さらに
「恒久研究所を遠隔地へ建設し、大量の電力・物資・維持物流を投入して高効率研究を行う段階」
へ、
さらに
「現地産業が建設資材と維持資材を供給し、複数地域の研究・産業圏が相互に強化される段階」
へ移行することで表現する。
