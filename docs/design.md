# 宇宙開発Idleゲーム デザイン案 v0.5.0

## 1. 目的

現代の地球から始まり、探査・実験・研究によって知識生産能力を拡大し、その成果で新技術、新しい生産設備、輸送方式、研究手段を成立させ、最終的に太陽系規模の産業圏へ発展するIdle型宇宙開発シミュレーションを目指す。

着想元の一つとしてCivIdleがあるが、その再現を目的とはしない。宇宙開発固有の「技術的困難さ」「研究手段の世代交代」「距離と輸送」「立地」「現地資源利用」「産業自立」を中核に据える。

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

研究・知識系
- Research Point
- Survey Knowledge
- Operational Experience

Research Pointは通常の貨物Inventoryとは分離した知識資源として扱う。Survey Knowledgeは地域・対象ごとの知識、Operational Experienceは技術・運用系統ごとの経験として別状態を持つ。

資金が残る場合も、外部調達や外部輸送等の補助的な摩擦を表現する二次資源とし、契約報酬を稼いで次の研究・設備を購入する中心成長通貨にはしない。

物理資源は所在地を持つ。地球の水1000t、月面の水1000t、LEOの水1000tは同価値ではない。

### 5.2 在庫・倉庫

各地点では最低限、現在在庫、予約済み在庫、入庫フロー、出庫フロー、輸送待ち、輸送中、到着待機、保管容量を区別する。

保管設備は一般貨物、バルク、液体、極低温、精密部品等のStorage Classへ分けられる。物理容量と、温調・保冷等を含む現在利用可能な保管サービス能力は必要に応じて分離する。

輸送中貨物は到着先倉庫容量を事前予約しない。実到着時に入庫判定し、容量不足分は物流側の到着待機として残す。

### 5.3 能力

在庫よりもフロー能力を重視する。

- 発電
- 採掘
- 選鉱・精錬
- 製造
- 建設
- 輸送・軌道投入
- 保管サービス
- 通信
- Surface Infrastructure / Local Distribution
- 保守
- 研究点生成
- 研究点貯蔵

能力はLocationへ固定値として付与するより、施設・資産から発生するフローとして扱う。「設備が存在すること」と「現在実際に供給可能な能力」を分離する。輸送能力も同様に、Vehicle自体へ固定のt/dayを持たせず、Vehicle性能、Fleet配分、Route、補給・整備Infrastructureから定常運用として導出する。

---

## 6. 建築物・建設・維持

### 6.1 建築物の生産とUI

FacilityそのものとProcessを分離する。一つのFacilityが複数工程を持てる場合、プレイヤーは工程を選択できる。

生産設備についてUIは最低限、以下を設備単位で表示する。

- 現在選択されているProcess
- 投入資源と実効消費量/日
- 産出資源と実効生産量/日
- 稼働率
- limiting factor / blocker

資源画面の地点合計フローだけで済ませず、「どの建築物が何を消費し何を作るか」を設備画面から直接確認できるようにする。

### 6.2 建造投入物

建築物は原則として2〜3種類の明示的な実Resourceを消費して建造する。

簡易設備は2種類、高度設備は3種類程度を基本とする。構造・機械・電子等の抽象Componentへ複数の代替材をぶら下げる方式は採用しない。Construction Recipeが実際に消費するResourceと量を直接定義する。

建設資材の産地はRecipeの条件にしない。要求Resourceが建設地点Inventoryへ存在すれば、地球産・月産・他拠点産を区別せず利用できる。

したがって建造時の「現地代替」「現地材比率」「代替材選択」は廃止する。現地生産の価値は通常の採掘・加工・Inventory・物流だけで表現する。

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

維持資材は特別な税として消去せず、通常のResource Demandとして在庫・物流系へ流す。維持資材が不足した場合は設備を即時破壊せず、保守充足率を下げ、その設備のAvailable Capability、生産、研究点生成等を一貫して縮退させる。

通常の手動停止だけで維持費をゼロにしない。将来、長期保管・Mothballを導入する場合はPauseとは別状態とする。

### 6.4 Upgrade

Levelアップは同一世代設備への増設・拡張・改良として扱う。Upgradeにも2〜3種類の実Resourceを投入し、その投入分も以後の維持需要へ反映する。

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

同一Location内の採掘Facilityが供給するNominal Extraction Capacityを合算し、開発済みSurface Cell群から得られるEffective Resource Opportunityに対して単調増加・限界収益逓減となる関係で実効採掘量を求める。設備を追加して総採掘量が通常減少する式にはせず、同じ地域へ過度に集中するほど追加投資1単位あたりの増産量が低下する構造とする。

```text
Developed Surface Cells
→ Resource Potential / Effective Opportunity

Extraction Facilities
→ Nominal Extraction Capacity

Opportunity × Capacity
→ diminishing returns
→ Actual Extraction Throughput
```

採掘設備数にハード上限を設けない。プレイヤーは、既存拠点へ設備を追加するか、資源Potentialの高い隣接地域を新たに開発するか、別地点へ新Locationを設立するかを限界収益で比較する。

研究完了だけで既存採掘FacilityのThroughputを直接上昇させない。研究はより高性能なFacility Definition、Process、Construction / Modernization手段を解禁し、実際の建設・更新投資が完了して初めてInstalled Capacityが変化する。

地球の一般鉱物等は開始時から高いSurvey Knowledgeを持たせてよい。これはEarthという固有Location IDへのCore特例ではなく、Surface Cellごとの初期Knowledge差として表現する。初期設備は低効率・高維持比率・大規模という性格を持たせ、後に高効率設備や宇宙資源利用へ置換する理由を作る。

## 8. 天体表面・Location・惑星開発

Celestial Body、物理的な地表、プレイヤーが運営するLocationを分離する。

地表をSurface Cellへ分割し、資源・地形・環境・Survey・開発領域の正準単位とする。UIではヘックス主体の天体マップとして表現してよいが、球面を完全な六角形だけで覆うことや、全Cellが同面積・常に6隣接であることをCore仕様にはしない。天体ごとにSurface Cell数を変えてよく、各Cellは面積、隣接関係、天体上の位置を持つ。

```text
Celestial Body
└ Surface Cell graph
   ├ static geology / resource potential
   ├ terrain / area / adjacency
   ├ dynamic environment
   ├ survey knowledge
   └ derived development affiliation
```

Surface CellはFacility配置スロットではない。通常Facilityを建設するたびにCellを選択させず、地理的開発と産業設備投資を別判断として扱う。

### 8.1 プレイヤーによるLocation設立

地表LocationはContent側が「月南極高地」「表側海地域」等の候補をあらかじめ列挙する方式を基本とせず、プレイヤーがSurvey結果と地形・資源・環境条件を見てSurface Cell上の任意地点へ設立する。

Locationは一点座標ではなく、プレイヤーが運営する経済・産業・物流上の拠点である。設立時のCore Cellと、そこから連続して開発したSurface Cell群を持つ。

```text
Location
├ core cell
├ contiguous developed cells
├ Inventory
├ Facilities
└ logistics connections
```

新たな開発Cellは既存領域へ隣接することを基本とし、離れた地域を同一Locationの飛び地として無償取得しない。遠隔地域を利用したい場合は領域を連続的に拡張するか、別Locationを設立する。

同一Surface Cellの資源Potentialを複数Locationへコピーしない。開発Cellは原則として一つのLocationの開発圏へ所属し、近接地点へLocationを大量設立して同じ資源Opportunityを重複利用する抜け道を作らない。

### 8.2 Location拡大

Location拡大は隣接Surface CellをDevelopment Projectとして取り込むことで表現する。Cell数に固定のハード上限は置かず、Survey、建設資源、Construction Capacity、時間、地形・環境、Surface Infrastructure等の負担を通じてsoft constraintを作る。

Location内部で個別ResourceをCell単位にroutingしない。一方、領域が巨大化しても共通Inventoryによって内部物流が無償・無限になる構造にはしない。開発領域の規模、広がり、利用する遠隔Cell、Gatewayとの接続等から集約的なSurface Infrastructure / Local Distribution負荷を生じさせ、能力不足時は遠隔資源Opportunityの利用、Gatewayとの荷役・分配、Location運用のAvailable Capacityを縮退させる。

これにより惑星開発を、建物配置パズルではなく、調査済み地域をどこまで産業圏へ統合するかという地理的・経済的判断として表現する。

### 8.3 FacilityとSurface Cell

通常FacilityはLocationへ所属し、個別Cell配置を要求しない。採掘FacilityもLocation全体へNominal Extraction Capacityを供給し、開発済みCell群のResource Opportunityと組み合わせて採掘量を決める。

一方、Landing Site、Surface Cargo Gateway、Mass Driver、局所環境を直接利用・改変する設備等、物理的位置そのものが性能・接続・環境効果へ本質的に影響するFacilityだけはSurface Cellへ配置できる。これらも別Domainにはせず通常Facilityと同じ建設・維持・電力・Capabilityモデルを使い、位置依存Facilityの建設操作はCell IDをリストから選ばせず天体マップ上で行う。

通常Facilityの設置・運転環境はLocation Coreと拠点Infrastructureが提供する運用環境を基準とし、位置依存Facilityは設置Cellの現在Environmentを参照する。

### 8.4 環境変化と将来のテラフォーミング

Surface Cellは静的な地質・地形と、将来変化し得るEnvironment Stateを分離する。

```text
Static
  geology / resource potential
  terrain / elevation / area

Dynamic
  temperature
  atmospheric pressure / composition
  radiation
  water / volatile state
  other environmental conditions
```

将来のテラフォーミングや大規模環境変化はDynamic Environmentを更新し、FacilityのOperating Environment、Resource Opportunity、輸送・建設条件等へ一般則として作用できるようにする。研究完了やテラフォーミングによって地質的Resource Potentialそのものを無条件に増加させない。

地表以外の軌道・宇宙空間NodeはSurface Cellを要求しない。LEO、月周回等はそれぞれの物理・運用構造に適したSpatial Nodeとして扱う。

## 9. 輸送と物流

本作では、地表から軌道へ質量を投入するPowered Ascentと、軌道投入後のSpaceflight、Landing、Atmospheric Entry等を異なるOperationとして扱う。ただしLaunch Vehicle / Spacecraftという名称を排他的な可否ラベルにはしない。

輸送可否と輸送性能は、機体のDry Mass、Payload、Propellant、推進性能、Operation Capability、Endurance、Atmospheric / Landing Capability、Docking / Refueling Compatibility、整備要求と、Route側のOperation要件・端点条件から決める。Vehicle自体に固定の輸送能力t/dayを持たせず、実際の輸送能力は使用Routeと運用条件から導出する。

研究は新しい機体・推進・補給方式を解禁するが、航路そのものを技術IDで直接アンロックしない。

Locationは物流上の経済Nodeだが、地表Locationを代表座標一点として距離計算しない。位置が意味を持つ地表輸送では、実際に接続に使用するGateway / access pointのSurface Cell間から距離・所要時間・必要Operationを導出する。Location拡大によって二つの開発圏が接近した場合、旧Core Cell間距離を理由に長距離輸送扱いを固定しない。

Surface Cell自体はInventory Nodeや物流Lane Nodeにはしない。Location内移動は集約Surface Infrastructureとして扱い、Location間Routeだけを物流Networkへ公開する。これにより惑星表面のCell解像度を物流Node数へ直接転嫁しない。

### 9.1 Fleet配分と輸送能力

プレイヤー保有Vehicleは通常物流では同型機・所在地点ごとのFleetとして扱い、輸送、Scientific Exploration、再配置等へ用途配分する。通常物流の主要判断は個々の便を発進させることではなく、どのVehicle Fleetをどの拠点間輸送へどれだけ投入するかとする。

Fleetを輸送へ割り当てると、Route、Vehicle性能、往復・回収経路、Turnaround、補給・整備条件から反復可能なTransport Serviceを自動構成し、方向別の定常輸送能力を生成する。Transport Service / Corridor自体をプレイヤーが別途作成・管理する対象にはしない。

Fleet Allocationは、次のどちらか一方を目標として設定できる。

- Units：投入するFleet隻数を指定し、その隻数から輸送能力を導出する。
- Capacity：必要な定常輸送能力を方向別に指定し、Vehicle性能と通常運用条件から必要隻数を導出する。

Transport AllocationではVehicle type、拠点間関係、経路・運用Policyを明示する。性能・所要時間・推進剤消費等が実質的に異なる複数のTransport Service Planが成立する場合は候補を提示し、Coreが戦略上重要な方式を暗黙に最適化・切替しない。

UnitsとCapacityを同時に正本とはしない。Capacity指定時の必要隻数はNominalな1隻当たり能力から決め、推進剤不足や整備不足等の一時的低下を埋めるためにFleetを自動増員しない。Fleet不足で目標隻数を満たせない場合は不足を表示し、新造・探査終了等で利用可能になったFleetを既存目標まで自動投入できる。

限られたFleetを複数Transport Allocationが要求する場合はAllocation priorityで配分する。これはLane priorityとは分離し、前者はVehicle用途配分、後者は輸送能力の貨物需要への配分を表す。

輸送能力は少なくとも以下を区別して表示する。

- Target：Capacity指定時のプレイヤー目標
- Nominal：Fleet数とTransport Serviceの通常運用から得られる能力
- Available：現在の推進剤、整備、荷役、Infrastructure等を反映した利用可能能力
- Used：物流Laneが実際に利用している能力
- Spare：AvailableからUsedを引いた余剰能力

推進剤・整備等の運用需要はFleetを割り当てただけで常に最大量を消費させず、実際のTransport Service利用率から発生させる。能力不足時はFleet不足、推進剤不足、整備能力不足、Infrastructure不足等のlimiting factorを区別して示す。

### 9.2 拠点間物流Lane

定常物流でプレイヤーが主に設計する対象は、品目ごとの補充ルールではなく拠点間の物流需要と、その需要を支える共有輸送能力とする。

```text
Transport Capacity
Earth Base → LEO          30 t/day
LEO → Lunar Base A           8 t/day

Lane Demand
Earth Base → Lunar Base A    6 t/day
```

施設・建設案件・維持需要・産業は必要資源からResource Demandを生成する。物流システムはLaneの要求量とpriorityに従って、Fleet Allocationや外部Transport Serviceから生じた共有Transport Capacityへ貨物を自動割当する。

Transport AllocationのCapacityは「どれだけ輸送能力を用意するか」、Laneのrequested capacityは「その能力を物流需要へどれだけ利用するか」を表す。Lane需要からFleetを無条件に増員せず、輸送能力をどこまで増強するかはプレイヤー判断として残す。

### 9.3 Transport Serviceと往復運用

定常輸送能力を生成するTransport Serviceは、Cargoを目的地へ運ぶだけでなく、Fleet資産が同じ運用を反復可能な状態へ戻れることを要件とする。

軌道間輸送船のようにVehicle自体が目的地へ移る場合は、逆方向Routeや回送を含めた往復cycleを自動構成する。再使用打上げ系のようにCargoの到着先とVehicleの回収先が異なる運用も、Vehicle固有のOperation / recovery性能から表現する。Powered Ascent等のOperation名そのものへ固定の帰還規則は持たせない。

往復Serviceでは同一Fleetが往路・復路を担当するため、方向別Capacityを単純加算してFleet必要量を求めない。復路Cargoがない場合は空荷回送を含む定常運用とし、帰り荷がある場合は既存の復路能力を利用できる。

Fleet Allocationを減らした場合、運用中Fleetを即座に別地点へ戻さず、必要な回収・再配置時間を経てFleet Poolへ戻す。地点間の恒久再配置もaggregateなFleet relocationとして時間を要する。

### 9.4 End-to-End輸送とCargo Flow

プレイヤーは出発地と最終目的地を指定でき、中継ノードごとの再発送操作を要求しない。

```text
Earth Base → Lunar Base A
Earth Base → LEO → Lunar Base A
Earth Base → LEO → Lunar Orbit → Lunar Base A
```

Fleet Allocationや外部Serviceが生成した方向別Transport Capacityをネットワークとして扱い、End-to-End能力は経路上の共有capacityから決まる。同じVehicleが途中NodeでCargoを引き渡さず連続運行できる場合は一つのTransport Serviceとして扱え、別Fleetへ引き渡す地点だけが物流上のhandoffになる。

通常物流では個々のVehicle Missionを反復生成せず、利用した定常capacityに応じてCargo Flowを発生させる。ただし輸送時間は保持し、出発したCargoはRoute / Serviceのlatencyを経て目的地へ到着する。

LEOや月周回軌道は有力な補給・積替え・整備ノードだが、必須ゲートではない。

到着先倉庫が満杯の場合、Cargoは物流側のarrival waitingに残る。輸送中から目的地倉庫を予約しない。

---

## 10. ロケット・宇宙船の建造と保有

ロケットや宇宙船は外部サービスだけでなく、プレイヤーが建造・保有できる物理資産とする。通常運用では同型機と所在地点ごとのFleet数量として管理し、個体識別そのものを主要なゲーム操作にはしない。

Vehicle Definitionは固定のt/day能力ではなく、RouteとTransport Serviceに応じた輸送・探査適合性と運用効率を決める性能を持つ。必要に応じて以下を含む。

- Dry Mass / Payload Capacity
- Propellant種類・容量・消費モデル
- Operation Capabilityと環境適合範囲
- 移動性能・Endurance
- Docking / Refueling等のInterface
- 最小Turnaroundと整備work / 維持・交換資材
- Production Capability
- 建造期間
- 2〜3種類程度の実Resource投入量

同じ性能要因からRoute可否、1cycle当たりPayload、所要時間、推進剤需要、整備需要を導出し、Fleet投入数から定常Transport Capacityへ変換する。用途名や機種名へ物流能力を直接結び付けない。

Vehicle Assembly Facility等へ建造を指示すると、製造Capabilityと資源を消費してProduction状態へ入り、完了後に建造地点の該当Fleetへ1隻追加される。

UIでは建造候補に加えて、保有Fleetについて所在、総数、輸送配分、Scientific Exploration拘束、再配置・回収中、未配分数を確認できるようにする。Transport Allocationでは目標mode、目標値、必要隻数、実際の投入隻数、Nominal / Available / Used / Spare Capacity、運用資源需要、blocker / limiting factorを表示する。

打上げヴィークル、軌道間輸送船、着陸船、統合型宇宙船等を用途名称だけで使用制限しない。実性能がOperation要件を満たすかで判定する。

---

## 11. 科学探査とResearch Point

資源Surveyとは別にScientific Exploration Campaignを導入する。

Scientific Explorationは必要性能を満たすFleet unitを一定数割り当て、一定期間の科学観測、近接探査、有人活動等を行うことでResearch Pointを得るシステムとする。

Campaignは必要に応じて以下を持つ。

- 探査対象・科学目的
- 必要Operation / Delta-v / Endurance / Payload
- 必要環境・Infrastructure / Capability
- 所要期間
- Research Point総量または生成率と上限
- 消耗資源

探査へ拘束されたFleet unitは輸送能力や別Campaignへ同時に割り当てられない。適合判定は「探査船」タグではなくVehicle性能から行う。物流とScientific Explorationは同じFleet資産を競合するため、輸送capacityを維持するか研究獲得へ回すかが明示的な資産配分判断になる。

同じ科学探査を無期限に繰り返すだけで無限Research Pointを得る構造は避ける。基本は有限Campaignとし、継続観測型は明示的な逓減・上限・運用コストを持たせる。

これにより、

宇宙船Fleetを建造する
→ 輸送能力へ投入するか探査へ割り当てるか選ぶ
→ 探査でResearch Pointを得る  
→ 新技術を研究する  
→ より高性能なFleet・研究設備・探査手段を成立させる

という資産配分のループを作る。

---

## 12. 研究システム

研究は本作の中心的な成長システムとする。

Research Point源は、地上研究設備、人工衛星、有人実験、軌道研究設備、Scientific Exploration、地表研究所、実証設備等である。研究源ごとに「この研究にしか使えないRP」という適用範囲は原則設けない。

研究資産の世代差はTierで表現し、Tierが上がるとResearch Point生成効率と貯蔵能力を明確に向上させる。技術的に高度な研究は必要Research Pointも大きく増えるため、初期研究源だけで後期研究を進めることは理論上可能でも極めて遅くなる。

研究施設・研究資産はLevelを持てる。

- Tier：研究手段そのものの世代差・基礎効率差
- Level：既存設備への増設、拡張、改良、運用成熟

一世代前の高Level資産と新世代の低Level資産が一定範囲で競合できる一方、十分な規模では新Tierが効率面で優位になるよう調整する。

Research Pointの貯蔵上限は研究基盤の規模を表す。容量低下で既獲得点を消滅させず、新規生成を停止または制限する。

---

## 13. 研究進行

研究開始・完了条件はResearch Pointだけに統一しない。研究ごとに以下を組み合わせる。

- Theory：蓄積Research Pointを消費する
- Prototype：実際の試作資材、設備、環境を要求する
- Demonstration：指定条件を満たした状態で一定期間の実証を要求する
- Operational Experience：実運用から経験を蓄積する

実証場所は特定Location IDで固定せず、必要環境とCapabilityから判定する。

研究項目は単純な「生産量+10%」より、新しい施設、製法、推進方式、輸送方式、探査方法、建設方法、運用方法を開放することを優先する。研究完了で既存設備を自動更新しない。

技術名称は「月面○○」のような地域名だけの抽象名称を避け、具体的な原理、装置、工程、運用技術として表現する。

主要分野：

- Launch & Propulsion
- Spacecraft & Logistics
- Orbital Construction
- Power & Thermal
- Survey & Planetary Science
- ISRU & Chemical Processing
- Materials & Metallurgy
- Manufacturing & Construction
- Robotics & Automation
- Communications, Navigation & Computing
- Human Spaceflight

一本道にはせず、発電方式、物流方式、研究資産更新、有人・無人開発等で複数の合理的経路を持たせる。

---

## 14. 資源Survey

資源SurveyはResearch Point獲得用のScientific Explorationとは別状態とする。

Survey対象は固定Locationではなく、Surface Cell × Resourceを基本とする。有限埋蔵量を探索するのではなく、その地域に資源が存在する可能性と、継続的な採掘投資を支えられるResource Potentialを段階的に明らかにする。

```text
Unknown
→ Presence Probability
→ Estimated Resource Potential
→ Measured Resource Potential
```

初期の広域観測では粗い地域差を示し、より詳細なSurveyによって候補CellのPotential推定幅を狭められる。Surveyは基地設立・領域拡張・新鉱業拠点投資の意思決定情報を提供する。

完了Campaignは能力配分対象から自動的に外し、余剰Survey能力を未完了対象へ再配分する。地球の一般鉱物等、開始時点で既知とする資源はSurface Cellごとの初期Knowledgeを高い状態で定義してよい。

地質的Knowledgeと現在Environmentの観測は将来分離可能にする。地質的Resource PotentialのKnowledgeは基本的に恒久知識だが、温度・大気・水相等の可変Environmentはテラフォーミングや世界変化によって更新され得る。

## 15. 月面開発と産業自立

月面は以下のように発展する。

1. 軌道から広域Surveyを行う
2. 有望Surface Cellを比較する
3. 任意地点へ初期Locationを設立する
4. 隣接CellをSurvey・開発して産業圏を拡大する
5. Resource PotentialとInstalled Extraction Capacityを組み合わせて初期ISRUを成立させる
6. 基礎工業・Surface Infrastructure・物流Gatewayを増強する
7. 遠隔有望地域へ第二Locationを設立し、Location間Surface Logisticsを形成する
8. 複数拠点の産業・研究・物流を統合し重工業化する

月に到達すること、基地を作ること、地域を開発圏へ取り込むこと、資源を採掘すること、加工すること、研究所を維持すること、設備を現地製造すること、産業を自己拡張可能にすることは別段階として扱う。

同じ高Potential地点へ採掘設備を追加し続けるほど限界収益は低下するため、既存Locationの高密度化、隣接地域への拡張、別Locationの設立と物流投資を比較する。資源枯渇を強制移住の主因にはしない。

自給度は単一値にせず、Mass、Energy、Propellant、Machinery、Electronics、Food、Replacement Parts等のDependencyを個別に見られるようにする。

発展した拠点をPrestige等で操作不能にしない。新技術は古い拠点のFacility更新、Surface Infrastructure増強、これまで利用効率の低かった地域の再開発理由にもする。

## 16. 自動進行と自動化

ゲーム時間は通常状態で自動進行する。プレイヤーは一時停止と複数段階の速度変更を行う。

自動化対象：

- 定常生産・採掘
- 維持Resource Demandの生成
- Research Point生成
- 設定済み研究・Survey・Scientific Explorationの進行
- Transport Allocation目標に対する利用可能Fleetの投入
- 物流Lane上の共有Transport Capacityへの貨物割当
- 建設進行
- 保守
- Offline Progress

プレイヤー判断として残すもの：

- 研究対象と研究順序
- 旧研究資産のLevelアップと新Tier資産建設の比較
- 新規産業配置
- 拠点間物流能力の増強
- Vehicle建造とFleet用途配分
- Transport AllocationのUnits / Capacity目標とpriority
- 輸送方式・輸送資産・経路Policyの選択
- 新地域への進出
- 発電方式
- 技術経路
- 大規模再開発

施設、建設案件、研究、Survey、Scientific Exploration、物流Lane等は必要に応じて停止・再開できる。停止は取消と区別し、設定と進捗を保持する。

---

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
- Location設立・隣接Surface Cell開発
- 建設計画・停止・再開・取消
- 設備停止・再開・Levelアップ
- Process選択・電力優先度
- Vehicle建造・Fleet再配置
- Transport Allocation設定・停止・再開
- Logistics Lane設定
- 手動Cargo / 特殊Transport Mission
- Research開始・停止・再開
- Scientific Exploration開始・停止・Fleet unit割当
- Resource Survey開始・停止・配分
- 位置依存FacilityのSurface Cell配置

主要Query例：

- 世界・天体Surface Map・Location概要
- Surface CellのSurvey / Resource Potential / Environment / 開発状態
- 在庫・フロー・保管
- Facility / Level / 維持充足率 / 配置種別
- Process投入・産出・稼働率・limiting factor
- 建設候補・案件
- Vehicle建造候補・必要資材・blocker
- Fleet / Transport Allocation / Transport Capacity / Cargo Flow / Logistics Lane
- Research Point生成量・保有量・上限
- Research / Scientific Exploration / Survey
- Location領域、Surface Infrastructure負荷、Gateway / access point候補
- Bottleneck / blocker

UIは建設可否、維持率、機体適合、研究条件等を独自再計算しない。Core/Applicationが判断材料と停止理由を返す。

---

## 19. Save / Load / Offline / テスト

Saveはversion付きSnapshotを基本とし、静的Definitionは現在のContentから再構築し、可変Stateだけを復元する。Fleet数量、Transport Allocation目標、再配置・回収中Fleet、Cargo Flow等は可変状態として保持し、Transport Service Planや現在のTransport Capacityは保存済み正本と重複させず再導出する。ゲーム性評価段階では旧仕様・旧Saveとの後方互換を目的化しない。

Offline Progressは通常Simulationと別ルールにせず、実時間をゲーム時間へ変換した上で通常の時間進行経路を利用する。

テストは暫定バランス数値を固定せず、以下の構造的不変条件を優先する。

- 資源が負にならない
- 在庫・予約・Cargo質量が整合する
- 輸送中Cargoが目的地倉庫を事前予約しない
- 建設Recipeが明示Resourceを消費する
- 建設資材の産地による代替特例が存在しない
- 維持需要が建造投入量から決定論的に導出される
- 維持不足が一貫してFacility能力へ反映される
- Vehicle建造がCapability・資源・時間を消費する
- Fleet総数と輸送・Scientific Exploration・再配置等の排他的配分が整合する
- Transport AllocationのUnits / Capacity目標が二重正本にならない
- Capacity指定時のFleet必要数が一時的な推進剤・整備不足で自動膨張しない
- Nominal / Available / Used Transport Capacityが同じService Planから一貫して導出される
- 共有Transport Capacityを複数Laneが利用しても能力を二重消費しない
- Cargo Flowが輸送latencyと資源量を保存する
- Research Pointの生成・貯蔵上限が整合する
- Route可否が技術名や用途ラベルではなく実能力から決まる
- Surface Cell数や隣接数を天体間で固定しない
- Locationの開発領域が同一天体上で連結し、同一Cellを複数Locationが重複利用しない
- Resource Potentialが採掘で枯渇せず、Installed Capacity増加に対して総採掘量が単調増加かつ限界収益逓減となる
- 研究完了だけでは既存Facilityの採掘能力が変化しない
- Surface Cellが物流Nodeへ自動昇格せず、地表Route距離が実Gateway / access pointから導出される
- 通常Facilityに不要なCell指定を要求せず、位置依存Facilityだけが有効な開発Cellへ配置される
- Dynamic Environment変化が静的地質Potentialを無条件に書き換えない
- Save/Load後の決定論
- Offline進行との同値性
- 登録順や固有Location IDに依存しない

---

## 20. 初期施設・資産候補

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

---

## 21. 基本的なデザイン原則

1. ゲームの中心成長ループは、Research Point獲得 → 技術 → 産業・物流拡大 → 高度研究手段 → より大きなResearch Point獲得とする。
2. Research Point源の世代差はTier、同一世代の拡張はLevelで表現する。
3. 一世代前の高Level資産と新世代の低Level資産が比較対象になり、旧資産が即座に無価値にならないようにする。
4. 研究難易度は距離ではなく技術的困難さを中心に決める。
5. 技術研究は航路を直接解除せず、実際のVehicle・設備能力を成立させる。
6. 建築物は2〜3種類の実Resourceを投入して建造する。
7. 建造時の現地代替レイヤーは持たず、産地差はInventoryと物流だけで表現する。
8. Facility維持は建造・Upgrade投入資源の一定割合を通常Resource Demandとして要求する。
9. Facilityの生産物・投入物・稼働率・律速要因をUIから直接確認可能にする。
10. 地球初期産業にも低効率採掘・基礎生産を置き、無限背景市場にしない。
11. ロケット・宇宙船はCapability・資源・時間を使って建造可能な物理資産とし、通常運用では所在地点ごとのFleetとして用途配分する。
12. Fleetを拠点間輸送へ配分すると、Vehicle性能・Route・補給・整備条件から定常Transport Capacityが自動生成される。
13. Fleet AllocationはUnits指定とCapacity指定を選択できるが、同時に二つを正本としない。
14. 宇宙船FleetをScientific Explorationへ割り当ててResearch Pointを得られるようにする。
15. Scientific ExplorationとResource Surveyを別状態として扱う。
16. 資源・中間材の種類は増やしてよいが、物流設定数の爆発を避ける。
17. 定常物流では品目別補充より拠点間輸送能力、Fleet配分、方式、優先度を主要判断とする。
18. 通常物流は個体Vehicle Missionの反復ではなく共有Transport CapacityとCargo Flowとして扱い、輸送latencyは保持する。
19. 地表Locationは固定候補から選ぶのではなく、天体Surface Cell上へ設立し、隣接地域を開発して拡大できる。
20. Surface Cellは物理地理・資源・環境・開発領域の単位とし、通常Facility配置スロットや物流Nodeとして扱わない。
21. 地表資源は有限ReserveではなくResource Potentialと採掘設備能力のsoft saturationで表現し、採掘設備数へハード上限を置かない。
22. 新技術は高性能Facilityや工法を解禁し、既存設備を研究完了だけで自動強化しない。
23. Location拡大による内部移動負荷は集約Surface Infrastructureで扱い、個別貨物のCell routingへ展開しない。
24. 位置が本質的なFacilityだけSurface Cellへ配置し、それ以外のFacilityへ不要なCell選択を要求しない。
25. 地表Location間の物理距離はLocation代表点ではなく実Gateway / access pointから導出する。
26. Surface Cellの静的地質と可変Environmentを分離し、将来のテラフォーミング・環境変化を同じ空間モデル上で扱えるようにする。
27. Idle自動化は反復処理を担当し、戦略判断を奪わない。
28. Celestial Body、Surface Cell、Location、軌道等の非地表Spatial Nodeを分離する。
29. 打上げと宇宙輸送を異なるOperationとして扱うが、Vehicle名称だけで可否を固定しない。
30. 輸送中貨物は目的地倉庫容量を事前予約しない。
31. LLMは世界側の問題や主体を増やすために使い、プレイヤー判断を代行させない。
32. Simulation CoreをUIから独立させ、決定論的に再現・テスト可能にする。
33. ゲーム性評価段階では後方互換や暫定バランス数値の固定を優先しない。

---

## 22. ゲーム性評価段階

現在の評価では、最終仕様や全コンテンツを固定するのではなく、本作の中心的な判断構造が成立する程度までメカニクスを実装して比較する。

優先評価対象：

- 自動時間進行、速度変更、一時停止
- Research Point生成・貯蔵・消費
- Scientific ExplorationによるFleet unit拘束とResearch Point獲得
- Research Tier / Level
- Theory / Prototype / Demonstration / Operational Experience
- 建築物の2〜3資源建造Recipe
- 建築物の維持Resource Demand
- Process入出力とUI可視化
- 地球初期採掘・基礎産業
- Vehicle建造とFleet数量管理
- Fleet AllocationのUnits / Capacity共存
- Fleet AllocationからのTransport Capacity自動生成
- Nominal / Available / Used / Spare Capacityとlimiting factor
- 発電・配電・部分稼働
- 在庫・倉庫・保管サービス
- Celestial Bodyごとに可変数のSurface Cellを持つ天体マップ
- 任意地点へのLocation設立と隣接Cell開発
- Resource Potential / soft saturation採掘
- Surface Infrastructureによる大規模Locationの集約内部物流負荷
- Spatial Node
- Transport Operation
- Logistics Laneと共有Transport Capacity
- Cargo Flowと輸送latency
- 貨物需要の自動割当
- 推進剤の実資源化
- Surface Cell単位のResource Survey
- 月面ISRU・現地加工
- Save/Load / Offline Progress
- Bottleneck表示

契約報酬と受託判断を中心とする資金獲得ループは評価対象から外す。

複数戦略を比較し、低Tier研究資産を長く育てる戦略と新Tierへ早期更新する戦略、輸送力増強と現地生産、Vehicleを物流へ使うか探査へ使うか、地球産業を拡張するか宇宙資源利用へ早期移行するか等に合理的なトレードオフが生まれることを確認する。

---

## 23. 現時点でのゲーム定義

本作は、

「探査・実験・研究設備からResearch Pointを獲得し、その研究成果で産業・輸送・研究基盤を拡大し、天体表面の有望地域へLocationを設立・拡張しながら、建設・維持・資源利用・物流・Fleet配分とTransport Capacityのボトルネックを解消し、より高い桁の知識生産と技術的に困難な宇宙開発へ進むIdle型宇宙産業シミュレーション」

と定義する。

ゲームの成長感は、契約を繰り返して資金残高を増やすことではなく、

「地球の低効率産業と人工衛星・地上研究設備で基礎知識を得る段階」
から
「自前のロケット・宇宙船Fleetを建造し、定常輸送能力と科学探査へ配分する段階」
へ、
さらに
「恒久研究所を遠隔地へ建設し、大量の電力・物資・維持物流を投入して高効率研究を行う段階」
へ、
さらに
「現地産業が建設資材と維持資材を供給し、複数地域の研究・産業圏が相互に強化される段階」
へ移行することで表現する。
