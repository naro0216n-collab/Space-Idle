# 宇宙開発Idleゲーム デザイン案 v0.5.0

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

資金を扱う場合も、外部調達や外部輸送等の補助的な摩擦を表現する組織レベルの二次状態とし、契約報酬を稼いで次の研究・設備を購入する中心成長通貨にはしない。外部サービスへの支出はプレイヤーが明示的に許可したPolicyの範囲内だけ自動化する。Policy未設定時はexternal serviceの候補が存在していても利用・支出を許可しない。

物理資源は所在地を持つ。地球の水1000t、月面の水1000t、LEOの水1000tは同価値ではない。

### 5.2 在庫・倉庫

各Operational Nodeでは最低限、現在在庫、予約済み在庫、入庫フロー、出庫フロー、輸送待ち、輸送中、到着待機、保管容量を区別する。

保管設備は一般貨物、バルク、液体、極低温、精密部品等のStorage Classへ分けられる。ある時点で保持できる量は `Physical Storage Capacity` と、電力・温調等の成立条件を反映して現在安全に利用できる `Usable Storage Capacity` というStock Capacityとして扱う。荷役や温調処理量のように一定時間あたりの有限処理能力がゲーム上の競合になる場合だけ、Cargo Handling / Conditioning等の別Service Capacityとして表現する。

輸送中貨物は到着先倉庫容量を事前予約しない。実到着時に入庫判定し、容量不足分は物流側の到着待機として残す。

### 5.3 CapabilityとService Capacity

設備・Vehicle・Infrastructureが「何を実行可能にするか」と、ある時点で保持できる量の上限と、複数用途が競合する時間あたり有限処理能力を分離する。数量概念は `Capability`、`Stock / Pool Capacity`、`Service Capacity` の三種類を混同しない。

`Capability` は、建設、観測、有人運用、Docking、特定Process等を実行できるという資格・機能の存在を表す。SiteRequirementやOperation適合判定は原則としてCapabilityを参照する。

`Service Capacity` は、一定時間あたりに供給・配分できる有限flowを表す。例：

- 発電
- 採掘
- 選鉱・精錬・製造
- 建設
- 輸送・軌道投入
- Cargo Handling / Surface Infrastructure / Local Distribution
- Conditioning等の時間あたり保管関連処理
- 保守
- Research execution
- Survey / Observation

Service CapacityはOperational Node等へ固定値として付与するのではなく、Facility、Fleet、Infrastructure等から発生させる。Facility/Fleet状態等から得るNominal supplyと、Resource、Power、Maintenance、上流Service等の依存Allocationによって当tickにenableされるAvailable capacityを区別する。依存関係はPlanningで明示し、Resource / Funds / Fleet / Service等を一つの決定論的allocation graphとして解決する。複数用途が同じService Capacityを要求する場合は共通の配分規則で競合させ、同じ能力を各Domainが独立に100%利用できる構造にしない。

このallocation graphへ当tickのDomain executionやmovementで新たに生産・到着したResourceを戻さない。それらはBoundary settlement後の次tick snapshotから利用可能になる。同tick依存関係に循環を持つContent / DefinitionはValidationでfail-closedとし、Domain固有の実行順や自己供給例外で解決しない。

Research Point生成率のような有限flowと、Research Point貯蔵上限のようなPool Capacityも区別する。前者をService Capacityとして扱う場合でも、後者はある時点で保持できる量の上限でありService Capacityではない。輸送能力もVehicle自体へ固定の`t/day`を持たせず、Vehicle性能、Fleet配分、Route、補給・整備InfrastructureからService Capacityとして導出する。

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

維持資材は特別な税として消去せず通常Resourceとして扱う。当tickの維持消費はResource Claimとして他用途と競合させ、将来の補充必要量はResource DemandとしてInventory / Logisticsへ流す。維持Resource Claimが不足した場合は設備を即時破壊せず、保守充足率を下げ、その設備が供給するService Capacity、生産、研究点生成等を一貫して縮退させる。Capabilityそのものの有無と、現在供給できる量を混同しない。

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

## 8. 空間・Operational Node・天体表面開発

物理的な位置を表すSpatial modelと、Inventory・Facility・Fleet等を所有して経済活動を行うOperational Nodeを分離する。

- Celestial Body：天体そのもの。
- Surface Cell：地表の物理・地理・資源・環境・Surveyの単位。
- non-surface Spatial Node：軌道、Lagrange領域、深宇宙上の運用地点等の物理的context。
- Operational Node：Inventory、Facility、Fleet、Storage、Power等を所有し、産業・研究・物流活動の端点となる運用拠点。
- Surface Location：Surface Cell上にプレイヤーが設立・拡張するOperational Nodeであり、連結した開発領域を追加で持つ。

すべてのSpatial NodeがOperational Nodeである必要はない。単なる軌道上の位置や未開発Surface Cellは物理的targetにはなれても、Inventoryや通常物流のNodeにはならない。一方、軌道研究所・Depot・Service Station等が存在する地点はnon-surface Spatial contextに結び付いたOperational Nodeとして扱える。

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

Surface CellはFacility配置スロットでもOperational Nodeでもない。通常Facilityを建設するたびにCellを選択させず、地理的開発と産業設備投資を別判断として扱う。

### 8.1 プレイヤーによるLocation設立

地表LocationはContent側が「月南極高地」「表側海地域」等の候補をあらかじめ列挙する方式を基本とせず、プレイヤーがSurvey結果と地形・資源・環境条件を見てSurface Cell上の任意地点へ設立する。標準の月面開発では、開始時からプレイヤー運営の月面Locationを与えず、月周回等の既存non-surface Operational Nodeから広域Surveyを行い、その結果を比較して最初の月面Locationを選ぶ。既設Surface LocationをContentとして持たせるのは、シナリオの前提として既存拠点が明示される場合に限る。

Location設立前のSurface CellはInventoryや通常物流LaneのNodeではない。最初の拠点は、既存のOperational Nodeをstaging originとして、Survey済みCellへFounding / Deployment Operationを実施することで成立させる。設立処理は「まだ存在しないDestination Inventoryへ通常Construction資材を配送する」方式にはしない。必要Resource、展開Facility / Fleet、輸送・着陸能力、準備作業、所要時間、SiteRequirementsを一つの設立Projectとして満たし、成功時にSurface LocationとそのOperational Node状態を生成する。

Founding PackageはContentで定義し、設立直後に通常の建設・物流へ移行するための最小運用基盤を与えられるようにする。何を含めるかは固定のCore特例にせず、初期Storage、Surface access / cargo handling、電力、Survey、Construction等のFacility、必要なら初期Fleet、InventoryからPackageを構成する。これにより「Locationを作るにはLocation側の倉庫やGatewayが既に必要」という循環依存を作らない。

Surface Locationは一点座標ではなく、Operational Nodeとしての経済・産業・物流機能と、設立時のCore Cellから連続して開発したSurface Cell群の双方を持つ。

```text
Surface Location
├ Operational Node state
│  ├ Inventory / Storage
│  ├ Facilities / Power / Service Capacity
│  └ Fleet / logistics connections
├ core cell
└ contiguous developed cells
```

新たな開発Cellは既存領域へ隣接することを基本とし、離れた地域を同一Locationの飛び地として無償取得しない。遠隔地域を利用したい場合は領域を連続的に拡張するか、別Locationを設立する。

同一Surface CellのResource Potentialを複数Locationへコピーしない。開発Cellは原則として一つのLocationの開発圏へ所属し、近接地点へLocationを大量設立して同じResource Opportunityを重複利用する抜け道を作らない。

### 8.2 Location拡大と複数拠点化

Location拡大は隣接Surface CellをDevelopment Projectとして取り込むことで表現する。Cell数に固定のハード上限は置かず、Survey、建設資源、Construction Service Capacity、時間、地形・環境、Surface Infrastructure等の負担を通じてsoft constraintを作る。

Location内部で個別ResourceをCell単位にroutingしない。一方、領域が巨大化しても共通Inventoryによって内部物流が無償・無限になる構造にはしない。開発領域の規模、広がり、利用する遠隔Cell、Gatewayとの接続等から集約的なSurface Infrastructure / Local Distribution負荷を生じさせ、Service Capacity不足時は遠隔Resource Opportunityの利用、Gatewayとの荷役・分配、Location運用を縮退させる。

近接・隣接地域へ別Locationを設立すること自体は禁止しない。新Locationには独立したFounding、Storage、Power、Construction、access / Gateway、物流接続等の投資が必要となり、Inventoryも別Operational Nodeとして分離される。したがってプレイヤーは、一つのLocationを拡大して内部Infrastructure負荷を引き受けるか、複数Locationへ分散して設立・拠点間物流の固定費を負担するかを比較する。Location分割によって同じSurface CellのResource OpportunityやService Capacityを複製してはならない。

これにより惑星開発を、建物配置パズルではなく、調査済み地域をどこまで一つの産業圏へ統合し、どこから別拠点網として接続するかという地理的・経済的判断として表現する。

### 8.3 FacilityとSurface Cell

通常FacilityはOperational Nodeへ所属し、地表Location上であっても個別Cell配置を要求しない。採掘FacilityもSurface Location全体へNominal Extraction Service Capacityを供給し、開発済みCell群のResource Opportunityと組み合わせて採掘量を決める。軌道研究所やDepot等も、non-surface Operational Nodeへ同じFacilityモデルで所属できる。

一方、Landing Site、Surface Cargo Gateway、Mass Driver、局所環境を直接利用・改変する設備等、物理的位置そのものが性能・接続・環境効果へ本質的に影響するFacilityだけはSurface Cellへ配置できる。これらも別Domainにはせず通常Facilityと同じ建設・維持・電力・Capability / Service Capacityモデルを使い、位置依存Facilityの建設操作はCell IDをリストから選ばせず天体マップ上で行う。

通常Facilityの設置・運転環境は所属Operational NodeのSpatial contextとInfrastructureが提供する運用環境を基準とし、位置依存Facilityは所属Surface Location内の配置Cellの現在Environmentを参照する。

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

地表以外の軌道・宇宙空間NodeはSurface Cellを要求しない。LEO、月周回等はそれぞれの物理・運用構造に適したSpatial Nodeとして扱い、Inventory・Facility・Fleet等を持つ場合だけOperational Nodeとして経済活動へ参加させる。

## 9. 輸送と物流

本作では、地表から軌道へ質量を投入するPowered Ascentと、軌道投入後のSpaceflight、Landing、Atmospheric Entry等を異なるOperationとして扱う。ただしLaunch Vehicle / Spacecraftという名称を排他的な可否ラベルにはしない。

輸送可否と輸送性能は、機体のDry Mass、Payload、Propellant、推進性能、Operation Capability、Endurance、Atmospheric / Landing Capability、Docking / Refueling Compatibility、整備要求と、Route側のOperation要件・端点条件から決める。Vehicle自体に固定の輸送能力t/dayを持たせず、実際の輸送能力は使用Routeと運用条件から導出する。

研究は新しい機体・推進・補給方式を解禁するが、航路そのものを技術IDで直接アンロックしない。

Operational Nodeは物流上の経済Nodeであり、地表Locationもその一種とする。ただし地表Locationを代表座標一点として距離計算しない。位置が意味を持つ地表輸送では、実際に接続に使用するGateway / access pointのSurface Cell間から距離・所要時間・必要Operationを導出する。Location拡大によって二つの開発圏が接近した場合、旧Core Cell間距離を理由に長距離輸送扱いを固定しない。

Surface Cell自体はInventory Nodeや物流Lane Nodeにはしない。Location内移動は集約Surface Infrastructureとして扱い、成立済みOperational Node間のRouteだけを通常物流Networkへ公開する。Location設立前のCellはFounding / Deployment Operationの物理targetにはなれるが、通常Cargo Flowのdestination Inventoryにはならない。設立完了後はSurface Locationのaccess / Gatewayと他Operational Nodeとの物理関係から利用可能Routeを導出し、将来生成されるLocation IDを静的Route一覧へ事前列挙しない。これにより惑星表面のCell解像度を物流Node数へ直接転嫁しない。

### 9.1 Fleet配分と輸送能力

プレイヤー保有Vehicleは通常物流では同型機・所在Operational NodeごとのFleetとして扱い、輸送、Scientific Exploration、再配置等へ用途配分する。通常物流の主要判断は個々の便を発進させることではなく、どのVehicle Fleetをどの拠点間輸送へどれだけ投入するかとする。

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

### 9.2 拠点間物流LaneとResource Demand

定常物流でプレイヤーが主に設計する対象は、品目ごとの補充ルールではなくOperational Node間の物流需要と、その需要を支える共有輸送能力とする。

```text
Transport Capacity
Earth Base → LEO          30 t/day
LEO → Lunar Base A         8 t/day

Lane Demand
Earth Base → Lunar Base A  6 t/day
```

Facility、Construction、Maintenance、Industry、Research等のDomainは、自分の成立条件からdestination、resource、必要量または目標量、urgency / priorityを持つResource Demandを生成する。Resource Demandは原則として特定の調達元を決めない。特定sourceがゲーム上の条件である場合だけsource constraintを与える。既に同じDemandへ割り当て済み・輸送中のCargoは未充足量から控除し、同じ将来需要への重複発送を防ぐ。ただし輸送中Cargoをdestination InventoryやStorage予約へ読み替えない。

Logisticsはプレイヤーが設定したsourcing / route Policyの範囲で利用可能sourceと経路を選び、Laneの要求量とpriorityに従って、Fleet Allocationや許可済みExternal Transport Serviceから生じた共有Transport Capacityへ貨物を割り当てる。sourceから発送するResourceは現地用途と同じResource Claim allocationへ参加し、Logisticsだけがsource Inventoryを先取りしない。Domainが物流経路を直接所有せず、LogisticsがDomainの戦略条件を勝手に変更しない。

Transport AllocationのCapacityは「どれだけ輸送能力を用意するか」、Laneのrequested capacityは「その能力を物流需要へどれだけ利用するか」を表す。Lane需要からFleetを無条件に増員せず、輸送能力をどこまで増強するかはプレイヤー判断として残す。

外部輸送・外部調達を自動利用できるのは、プレイヤーが当該Laneや調達Policyで明示的に許可した場合だけとする。利用可否、支出上限、最低保持資金等のPolicyを設定でき、Simulationはその範囲内の反復判断だけを自動化する。物理Resourceの外部調達も通常のdelivery latency、到着、Storage契約を通り、資金支払いだけで目的地Inventoryへ即時生成しない。

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

ロケットや宇宙船は外部サービスだけでなく、プレイヤーが建造・保有できる物理資産とする。通常運用では同型機と所在Operational NodeごとのFleet数量として管理し、個体識別そのものを主要なゲーム操作にはしない。

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

Vehicle Assembly Facility等へ建造を指示すると、製造Capabilityと資源を消費してProduction状態へ入り、完了後に建造Operational Nodeの該当Fleetへ1隻追加される。

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

Research Point源は、地上研究設備、人工衛星、有人実験、軌道研究設備、Scientific Exploration、地表研究所、実証設備等である。研究源ごとに「この研究にしか使えないRP」という適用範囲は原則設けず、生成したResearch Pointは組織全体の共有Knowledge Poolへ蓄積する。

研究資産の世代差はTierで表現し、Tierが上がるとResearch Point生成効率と貯蔵能力を明確に向上させる。技術的に高度な研究は必要Research Pointも大きく増えるため、初期研究源だけで後期研究を進めることは理論上可能でも極めて遅くなる。

研究施設・研究資産はLevelを持てる。

- Tier：研究手段そのものの世代差・基礎効率差
- Level：既存設備への増設、拡張、改良、運用成熟

一世代前の高Level資産と新世代の低Level資産が一定範囲で競合できる一方、十分な規模では新Tierが効率面で優位になるよう調整する。

Research Pointの貯蔵上限は研究基盤の規模を表す。容量低下で既獲得点を消滅させず、新規生成を停止または制限する。

Research Projectは複数を並行して進められる。並行性は固定queue数ではなく、Research Point、必要Facility / Capability、Research execution Service Capacity、Prototype Resource、Demonstration条件等の実際のボトルネックによって制約する。共有Research Pointを複数Projectが必要とする場合はResearch priorityに従って配分し、Project処理順の先着消費にしない。研究施設をRP generatorだけに縮退させず、必要な研究実行能力にも意味を持たせる。

---

## 13. 研究進行

研究開始・完了条件はResearch Pointだけに統一しない。Research Definitionは、研究内容に応じて以下の段階を必要な組み合わせ・順序で持てる。すべての研究を固定4段階へ強制しない。

- Theory：蓄積Research PointとResearch execution能力を使って理論・設計を成立させる。
- Prototype：実際の試作Resource、Facility、Environment、Service Capacityを要求する。
- Demonstration：指定条件を満たした状態で一定期間の実証を要求する。
- Operational Experience：実際の運用から蓄積されたKnowledge Stateを要求する。

Prototype / Demonstrationの実施場所は特定Location IDで固定せず、必要Environment、Capability、Service Capacityから判定する。試作資材は通常のResource Claim / Resource Demand、物流、Inventoryを通して確保し、Researchだけが別会計で資材を消費しない。

Operational ExperienceはResearch Project自身が時間経過だけで生成するpointではない。輸送、採掘、製造、有人運用等の実Domain activityが対応するexperience categoryへ知識を蓄積し、Researchはその状態をrequirementとして参照する。

研究完了によるTechnology Unlockは一つのauthoritativeなTechnology Stateへ記録する。Facility、Process、Vehicle等の各Domainは解禁状態を重複保存せず、この状態を参照する。研究完了で既存設備を自動更新しない。

研究項目は単純な「生産量+10%」より、新しいFacility、Process、推進方式、輸送方式、探査方法、建設方法、運用方法を開放することを優先する。

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

現段階ではCrew個人を独立Entityとして管理するDomainは導入しない。有人運用はcrew-ratedなVehicle / Facility特性、Habitation / Life Support等のCapability・Service Capacity、消耗ResourceのResource Claim / Resource Demandとして表現する。将来Crewそのものが主要な意思決定対象になる場合にだけ、個体・人口Stateを独立Domainへ昇格する。

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

初期の広域観測では粗い地域差を示し、より詳細なSurveyによって候補CellのPotential推定幅を狭められる。Survey手段は観測位置・方式ごとに到達範囲と到達可能なKnowledge深度を持つ。軌道Remote SurveyはSurface Locationが存在しなくても対象天体の広域Cellを観測でき、最初のLocation候補比較に必要な粗いKnowledgeを与える。地表Surveyや近接観測は既設Location、展開Facility / Fleet、到達可能範囲等を必要とする代わりに、より高いKnowledge Levelまで精査できる。Surveyは基地設立・領域拡張・新鉱業拠点投資の意思決定情報を提供する。

Survey開始条件を単なる「providerとtargetが同一天体」に縮退させない。ProviderのObservation / Sensor Capability、providerのSpatial context、target coverage、必要Operation、到達可能Knowledge Levelから可否と進行を決める。広域軌道SurveyはSurface物流Routeを要求せず、Surface Surveyは通常物流や現地運用条件と接続できる。

完了Campaignは能力配分対象から自動的に外し、余剰Survey能力を未完了対象へ再配分する。地球の一般鉱物等、開始時点で既知とする資源はSurface Cellごとの初期Knowledgeを高い状態で定義してよい。

地質的Knowledgeと現在Environmentの観測は将来分離可能にする。地質的Resource PotentialのKnowledgeは基本的に恒久知識だが、温度・大気・水相等の可変Environmentはテラフォーミングや世界変化によって更新され得る。

## 15. Location開発とロケーション産業自立

Locationの発展は「到達したか」「基地が存在するか」という一段階ではなく、Survey、Founding、領域開発、資源利用、加工、研究維持、現地製造、自己拡張能力を段階的に成立させる過程として扱う。

典型的には、次の判断が繰り返される。

1. 既存Operational Nodeから未開発地域をSurveyする
2. 有望Surface Cellを比較する
3. Founding / Deployment Operationで新Locationを設立する
4. 最小運用基盤から通常物流・建設へ接続する
5. Resource PotentialとExtraction Service Capacityを組み合わせて現地資源利用を成立させる
6. 基礎工業・Surface Infrastructure・Gateway・研究設備を増強する
7. 同一Locationを拡張するか、別Locationを設立して拠点網を形成するか比較する
8. 複数Operational Nodeの産業・研究・物流を統合する

初期Contentでは月面開発がこの進行を代表するが、Coreで扱う概念はロケーション産業自立であり、特定天体名へ結び付けない。火星、小惑星、軌道拠点その他の地域でも同じLocation / Operational Nodeモデルを利用する。

ロケーション産業自立はbinaryな達成状態や単一の自給率ではなく、選択したLocationまたはOperational Node集合について、外部依存構造を示すderived analyticsとする。ここでいうロケーションは分析scopeを指し、Entity型としてのSurface Locationだけに限定しない。既存のProduction、Consumption、Resource Demand、Import / Export、Unmet Demandから、ResourceまたはContent定義のResource Group単位で少なくとも以下を確認できるようにする。

- local production
- local consumption / demand
- imports / exports
- unmet demand
- external inflow / dependency
- critical dependency / limiting resource

Mass、Energy、Propellant、Machinery等の特定カテゴリをGeneric Coreへ固定しない。Contentは表示・分析用Resource Groupを定義できるが、実際のResource flowを正本とする。

同じ集計を単一Locationだけでなく、任意のOperational Node集合へ適用できるようにする。これにより、ある天体上の複数Location、地球圏・月圏等の地域経済、Player全体についても同じ仕組みで依存構造を比較できる。

同じ高Potential地点へ採掘設備を追加し続けるほど限界収益は低下するため、既存Locationの高密度化、隣接地域への拡張、別Locationの設立と物流投資を比較する。資源枯渇を強制移住の主因にはしない。

発展した拠点をPrestige等で操作不能にしない。新技術は古い拠点のFacility更新、Surface Infrastructure増強、これまで利用効率の低かった地域の再開発理由にもする。


## 16. 自動進行と自動化

ゲーム時間は通常状態で自動進行する。プレイヤーは一時停止と複数段階の速度変更を行う。

自動化対象：

- 定常生産・採掘
- 各DomainからのResource Claim / Resource Demand生成
- 設定済みpriorityに基づくResource / Service Capacity配分
- Research Point生成
- 設定済み研究・Survey・Scientific Explorationの進行
- Transport Allocation目標に対する利用可能Fleetの投入
- 物流Lane上の共有Transport Capacityへの貨物割当
- Playerが許可したsourcing / external service Policy内での反復調達
- 建設進行
- 保守
- Offline Progress

プレイヤー判断として残すもの：

- 研究対象と研究優先度
- 旧研究資産のLevelアップと新Tier資産建設の比較
- 新規産業配置
- Resource / Service Capacityのpriority Policy
- 拠点間物流能力の増強
- Vehicle建造とFleet用途配分
- Transport AllocationのUnits / Capacity目標とpriority
- sourcing / route / external service Policyと支出上限
- 輸送方式・輸送資産の選択
- 新地域への進出、Location拡張と別Location設立の比較
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
- 軌道Survey結果からのLocation設立Deployment・隣接Surface Cell開発
- 建設計画・停止・再開・取消
- Facility停止・再開・Levelアップ
- Process選択・Power / Resource / Service Capacity priority
- Vehicle建造・Fleet再配置
- Transport Allocation設定・停止・再開
- Logistics Lane / sourcing / route Policy設定
- External transport / procurement許可・支出Policy設定
- 手動Cargo / 特殊Transport Mission
- Research開始・停止・再開・priority設定
- Scientific Exploration開始・停止・Fleet unit割当
- Resource Survey開始・停止・配分
- 位置依存FacilityのSurface Cell配置

主要Query例：

- 世界・天体Surface Map・Operational Node / Location概要
- Surface CellのSurvey / Resource Potential / Environment / 開発状態
- Inventory・Flow・Storage
- Facility / Level / 維持充足率 / 配置種別
- Capability / Service CapacityのNominal / Available / Allocated / Spare
- Resource Claim / allocation / unmet amount / priority
- Process投入・産出・稼働率・limiting factor
- 建設候補・案件
- Vehicle建造候補・必要資材・blocker
- Fleet / Transport Allocation / Transport Capacity / Cargo Flow / Logistics Lane
- Research Point生成量・保有量・上限 / Technology Unlock / Operational Experience
- Research / Scientific Exploration / Survey
- Location領域、Surface Infrastructure負荷、Gateway / access point候補
- LocationまたはOperational Node集合のロケーション産業自立・外部依存分析
- Bottleneck / blocker

UIは建設可否、維持率、機体適合、研究条件、資源・能力配分等を独自再計算しない。Core/Applicationが判断材料、priority、allocation結果、停止理由を返す。

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
- Technology Unlockが単一のauthoritative stateとして保持される
- Operational Experienceが実Domain activityから蓄積され、Research時間経過だけで生成されない
- 同じInventory Resourceを複数Domainが登録順依存で二重消費せず、Resource Claim allocationで競合する
- 同じService Capacityを複数用途が二重利用せず、priorityと同順位配分が決定論的である
- External transport / procurementが未許可Policyで資金を自動消費しない
- Route可否が技術名や用途ラベルではなく実能力から決まる
- Surface Cell数や隣接数を天体間で固定しない
- Locationの開発領域が同一天体上で連結し、同一Cellを複数Locationが重複利用しない
- Resource Potentialが採掘で枯渇せず、Installed Capacity増加に対して総採掘量が単調増加かつ限界収益逓減となる
- 研究完了だけでは既存Facilityの採掘能力が変化しない
- Surface Cellが物流Nodeへ自動昇格せず、地表Route距離が実Gateway / access pointから導出される
- Surface Locationとnon-surface Operational Nodeが共通のInventory / Facility / Fleet所有契約で扱える
- 通常Facilityに不要なCell指定を要求せず、位置依存Facilityだけが有効な開発Cellへ配置される
- Dynamic Environment変化が静的地質Potentialを無条件に書き換えない
- Save/Load後の決定論
- Offline進行との同値性
- 登録順や固有Location IDに依存しない

---

## 20. 初期Content候補

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
2. Research Point源の世代差はTier、同一世代の拡張はLevelで表現し、複数Research Projectは実際のResource / Service Capacityによって並行性を制約する。
3. 一世代前の高Level資産と新世代の低Level資産が比較対象になり、旧資産が即座に無価値にならないようにする。
4. 研究難易度は距離ではなく技術的困難さを中心に決める。
5. 技術研究は航路を直接解除せず、単一のTechnology Stateを通して実際のVehicle・Facility・Process等を解禁する。
6. Theory / Prototype / Demonstration / Operational Experienceは研究ごとに必要な組み合わせで使い、Operational Experienceは実運用から得る。
7. 建築物は2〜3種類の実Resourceを投入して建造し、建造時の現地代替レイヤーを持たない。
8. Facility維持は建造・Upgrade投入Resourceの一定割合を通常Resource requirementとして要求し、当tick消費はResource Claim、補充はResource Demandとして扱う。
9. Capabilityという資格と、複数用途が競合する有限Service Capacityを分離する。
10. 同じResourceやService Capacityを複数Domainが必要とする場合、Domain処理順ではなく明示的priorityと共通allocationで競合を解決する。
11. Facilityの生産物・投入物・稼働率・allocation・律速要因をUIから直接確認可能にする。
12. 地球初期産業にも低効率採掘・基礎生産を置き、無限背景市場にしない。
13. Celestial Body、Surface Cell、Spatial Node、Operational Node、Surface Locationを分離する。
14. Inventory、Facility、Fleet、Storage、Power等の一般的な所有先はOperational Nodeとし、Surface LocationだけがSurface Cell領域を追加で持つ。
15. ロケット・宇宙船はCapability・Service Capacity・Resource・時間を使って建造可能な物理資産とし、通常運用ではOperational NodeごとのFleetとして用途配分する。
16. Fleetを拠点間輸送へ配分すると、Vehicle性能・Route・補給・整備条件から定常Transport Capacityが自動生成される。
17. Fleet AllocationはUnits指定とCapacity指定を選択できるが、同時に二つを正本としない。
18. 宇宙船FleetをScientific Explorationへ割り当ててResearch Pointを得られるようにし、Scientific ExplorationとResource Surveyを別状態として扱う。
19. 資源・中間材の種類は増やしてよいが、物流設定数の爆発を避ける。
20. DomainはResource Demandで必要量とpriorityを表し、調達元・経路はPlayer Policyの範囲でLogisticsが選択する。
21. 外部調達・外部輸送はPlayerが明示的に許可したPolicy内だけ自動利用し、戦略的支出判断をSimulationが暗黙代行しない。
22. 通常物流は個体Vehicle Missionの反復ではなく共有Transport CapacityとCargo Flowとして扱い、輸送latencyは保持する。
23. 地表Locationは固定候補から選ぶのではなく、Surface拠点を前提としない軌道Surveyで候補を比較し、天体Surface Cell上へ最初の拠点をDeploymentしてから隣接地域を開発して拡大できる。
24. Surface Cellは物理地理・資源・環境・開発領域の単位とし、通常Facility配置スロットや物流Nodeとして扱わない。
25. 地表資源は有限ReserveではなくResource Potentialと採掘Service Capacityのsoft saturationで表現し、採掘設備数へハード上限を置かない。
26. 新技術は高性能Facilityや工法を解禁し、既存設備を研究完了だけで自動強化しない。
27. Location拡大による内部移動負荷は集約Surface Infrastructure Service Capacityで扱い、個別貨物のCell routingへ展開しない。
28. 近接地域への別Location設立を禁止せず、単一Location拡張と複数拠点化をFounding・Infrastructure・物流コストのtrade-offにする。
29. 位置が本質的なFacilityだけSurface Cellへ配置し、それ以外のFacilityへ不要なCell選択を要求しない。
30. 地表Location間の物理距離はLocation代表点ではなく実Gateway / access pointから導出する。
31. Surface Cellの静的地質と可変Environmentを分離し、将来のテラフォーミング・環境変化を同じ空間モデル上で扱えるようにする。
32. ロケーション産業自立は特定天体固有の状態ではなく、任意のLocation / Operational Node集合の実Resource flowから導出する外部依存分析とする。
33. Idle自動化は反復処理を担当し、研究・Resource priority・物流方式・外部支出等の戦略判断を奪わない。
34. 有人運用は当面Capability、Service Capacity、Resource Claim / Resource Demand、crew-rated特性で表現し、必要性が生じるまでCrew個体Domainを導入しない。
35. 打上げと宇宙輸送を異なるOperationとして扱うが、Vehicle名称だけで可否を固定しない。
36. 輸送中貨物は目的地倉庫容量を事前予約しない。
37. LLMは世界側の問題や主体を増やすために使い、プレイヤー判断を代行させない。
38. Simulation CoreをUIから独立させ、明示的なphase contractに基づいて決定論的に再現・テスト可能にする。
39. ゲーム性評価段階では後方互換や暫定バランス数値の固定を優先しない。

---

## 22. ゲーム性評価段階

現在の評価では、最終仕様や全コンテンツを固定するのではなく、本作の中心的な判断構造が成立する程度までメカニクスを実装して比較する。

優先評価対象：

- 自動時間進行、速度変更、一時停止
- Research Point生成・貯蔵・消費
- Scientific ExplorationによるFleet unit拘束とResearch Point獲得
- Research Tier / Level
- 複数Research Project、Research Point priority allocation、Theory / Prototype / Demonstration / Operational Experience
- Technology Unlock / Operational Experienceの単一状態所有
- 建築物の2〜3資源建造Recipe
- 建築物の維持Resource Claim / Resource Demand
- Resource ClaimによるDomain横断の在庫競合とpriority allocation
- Capability / Service Capacity分離と共有capacity競合
- Process入出力とUI可視化
- 地球初期採掘・基礎産業
- Vehicle建造とFleet数量管理
- Fleet AllocationのUnits / Capacity共存
- Fleet AllocationからのTransport Capacity自動生成
- Nominal / Available / Used / Spare Capacityとlimiting factor
- 発電・配電・部分稼働
- 在庫・倉庫・Usable Storage Capacity・荷役 / Conditioning Service
- Celestial Bodyごとに可変数のSurface Cellを持つ天体マップ
- Surface拠点なしの軌道Surveyから任意地点へ最初のLocationを設立し、隣接Cellを開発する一連の進行
- Resource Potential / soft saturation採掘
- Surface Infrastructureによる大規模Locationの集約内部物流負荷
- Operational NodeとSurface Location / non-surface Spatial contextの分離
- Transport Operation
- Logistics Laneと共有Transport Capacity
- Cargo Flowと輸送latency
- Resource Demand、sourcing Policy、source側Resource Claim、貨物需要の自動割当
- 明示Policy内のExternal Transport / Procurement、資金摩擦、通常のdelivery latency / Storage契約
- 推進剤の実資源化
- Surface Cell単位のResource Survey
- 初期月面ContentでのISRU・現地加工
- Location / Operational Node集合のロケーション産業自立・外部依存分析
- Save/Load / Offline Progress
- Bottleneck表示

契約報酬と受託判断を中心とする資金獲得ループは評価対象から外す。

複数戦略を比較し、低Tier研究資産を長く育てる戦略と新Tierへ早期更新する戦略、輸送力増強と現地生産、Vehicleを物流へ使うか探査へ使うか、地球産業を拡張するか宇宙資源利用へ早期移行するか等に合理的なトレードオフが生まれることを確認する。

---

## 23. 現時点でのゲーム定義

本作は、

「探査・実験・研究設備からResearch PointとOperational Experienceを獲得し、その研究成果で産業・輸送・研究基盤を拡大し、Surface Locationと軌道等のOperational Nodeを産業・物流Networkとして発展させながら、Resource / Service Capacity配分、建設・維持・資源利用・Fleet配分・Transport Capacityのボトルネックを解消し、ロケーション産業自立を高めつつ、より高い桁の知識生産と技術的に困難な宇宙開発へ進むIdle型宇宙産業シミュレーション」

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
