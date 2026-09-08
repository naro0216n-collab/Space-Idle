# 宇宙開発Idleゲーム デザイン案 v0.3.0

## 1. 目的

現代の地球から始まり、探査・実験・研究によって知識生産能力を拡大し、その成果で新技術、新しい生産設備、輸送方式、研究手段を成立させ、最終的に太陽系規模の産業圏へ発展するIdle型宇宙開発シミュレーションを目指す。

着想元の一つとしてCivIdleがあるが、その再現を目的とはしない。宇宙開発固有の「技術的困難さ」「研究手段の世代交代」「距離と輸送」「立地」「現地資源利用」「産業自立」を中核に据える。

ゲームの成長軸は契約報酬として資金を稼ぐ経営ループではなく、人工衛星、有人活動、探査機、研究所、実証設備等から継続的にResearch Pointを生み出し、それをより高い桁で生産・保持できる研究基盤へ移行することである。産業拡大は高度な研究手段を建設・運用するために必要となり、研究成果はさらに高性能な産業・輸送・研究資産を成立させる。この相互強化をIdleゲームとしての中心ループにする。

プレイヤーの楽しみは、単なる数値増加ではなく、研究・産業・物流ネットワークのボトルネックを発見し、既存資産の高度化と新世代資産への更新を比較しながら、より困難な研究と大規模な宇宙産業を成立させることに置く。

---

## 2. 基本コンセプト

ゲームの基本循環は以下とする。

探査・実験・研究設備を運転する  
→ Research Pointを生産・蓄積する  
→ 技術を研究する  
→ 新しい設備・製法・輸送能力・研究手段を利用可能にする  
→ 生産、電力、建設、物流を拡大する  
→ より高コスト・高効率な研究資産を建設・維持できるようになる  
→ 研究点生産量と貯蔵可能量の桁が上がる  
→ より技術的に困難な研究へ進む

この循環の途中で、電力不足、輸送能力不足、特定中間材不足、建設能力不足、研究点貯蔵不足等のボトルネックが発生する。プレイヤーは既存施設のレベルアップ、新世代設備の新設、産業配置や物流能力の変更を比較して解消する。

Idle要素は「一度構築した仕組みが時間とともに自動で運転し続ける」ことを担当する。時間は通常状態で自動進行し、プレイヤーは速度変更と一時停止を行える。日数を都度選択して進める方式を主要操作にはしない。

Idleだからといって、プレイヤーの判断まで自動化しない。研究対象、設備投資、施設レベルアップ、新地域への進出、産業構成、拠点間輸送能力、輸送方式、電力・建設能力の配分などの主要判断はプレイヤー側に残す。

---

## 3. 進行の基本像

ゲーム開始時点は現代水準とする。ロケットそのものを発明するところからではなく、既に基礎的な宇宙開発能力を持つ組織を運営する。

プレイヤー主体は、初期段階では特定企業・国家機関そのものに固定しない「宇宙開発組織」とする。外部の企業、政府、研究機関等は協力相手、供給者、需要主体、イベント主体として世界側に残すが、契約をこなして資金を稼ぐことをゲーム進行の中心にはしない。

初期のResearch Point源は、地上研究設備、人工衛星による継続観測、有人宇宙活動、近接領域の探査等である。これらは比較的低コストで維持できる一方、研究点出力と貯蔵能力は小さい。

産業・輸送能力が拡大すると、より大型の軌道実験設備、無人地表探査、サンプル解析、高度な地上研究設備等を維持できるようになる。さらに月面等へ恒久研究所や大規模実証設備を建設する段階では、建設質量、電力、精密機器、中間材、保守物流等の要求が一段上がる代わりに、研究点出力と貯蔵能力も桁違いに増加する。

この成長段階は地球からの距離そのものではなく、必要な研究設備、実験環境、輸送、電力、精度、継続運転、試作・実証の技術的困難さによって決める。単純な月面観測より高度な地上大型研究設備の方が高い研究Tierとなることもあり得る。Locationは研究Tierそのものではなく、特定環境や物流条件を提供する。

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

月に到達すること、月面基地を作ること、資源を採掘すること、資源を加工すること、研究所を維持すること、設備を現地製造すること、産業を自己拡張可能にすることは、それぞれ別の段階として扱う。

---

## 4. 最初のプレイ可能範囲

初期プロトタイプでは以下までを扱う。

現代宇宙産業  
→ LEO産業化  
→ 月探査  
→ 月面ロボット拠点  
→ 水・酸素等の初期ISRU  
→ 月面構造材生産  
→ 月面建設の一部現地化  
→ 一部機械部品の現地生産

この時点でも、半導体、精密電子機器、高性能材料、高度制御装置などは地球依存とする。

したがって、この段階は「月経済圏完成」ではなく、「月面産業が自らの一部を支え始めた状態」とする。

---

## 5. 中核ゲームシステム

### 5.1 資源

元素を過度に細分化せず、産業上意味のあるカテゴリとして扱う。研究施設や高度産業の発展に伴い資源・中間材の種類は増やしてよいが、品目数の増加をそのまま物流設定数の増加へ転嫁しない。

初期候補：

原料
- Regolith
- Metal Ore
- Volatile-bearing Material
- Water

基礎工業品
- Structural Metal
- Ceramics / Glass
- Oxygen
- Fuel
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

Research Pointは通常の貨物Inventoryとは分離した知識資源として扱う。研究施設・探査資産等から生成され、研究基盤が供給する研究点貯蔵能力まで蓄積できる。Survey Knowledgeは地域・対象ごとの知識、Operational Experienceは技術・運用系統ごとの経験として別状態を持つ。

資金が残る場合も、外部調達や外部輸送等の補助的な摩擦を表現する二次資源とし、契約報酬を稼いで次の研究・設備を購入する中心成長通貨にはしない。

物理資源は所在地を持つ。地球の水1000t、月面の水1000t、LEOの水1000tは同価値ではない。

推進剤は輸送コストへ吸収した抽象値だけではなく、少なくとも宇宙圏輸送では実資源として扱う。月面ISRUによる水・酸素・水素・推進剤生産が、輸送能力や地球依存度を実際に変える構造とする。

### 5.2 在庫・倉庫

本作はフロー能力を中心に扱うが、在庫と保管能力も明示的に管理する。

各地点では最低限、以下を区別する。

- 現在在庫
- 予約済み在庫
- 入庫フロー
- 出庫フロー
- 輸送待ち
- 輸送中
- 到着待機
- 保管容量

保管設備は資源カテゴリに応じて分けられる。

例：

- 一般貨物倉庫
- バルク原料置場
- 水タンク
- 酸素タンク
- 極低温推進剤タンク
- 精密部品倉庫

レゴリスや鉱石等のバルク原料は、一般倉庫と同等の高コスト管理を要求せず、安価な屋外ストックパイル等として大容量化しやすくする。

物理的な保管容積と、温調・保冷等を含む現在利用可能な保管サービス能力は必要に応じて分離する。極低温保管のように継続的な設備稼働を必要とする場合、設備を停止しても容器そのものは消えないが、保管サービスには電力等の維持条件が必要となる。

輸送中貨物は到着先倉庫容量を事前予約しない。実際に到着した時点で入庫判定を行い、容量不足分は倉庫在庫ではなく物流側の到着待機として残す。長距離輸送そのものが目的地倉庫を事前に圧迫する設計にはしない。

### 5.3 能力値

在庫よりもフロー能力を重視する。

例：

- 発電能力
- 採掘能力
- 選鉱能力
- 精錬能力
- 製造能力
- 建設能力
- 輸送能力
- 軌道投入能力
- 保管サービス能力
- 通信能力
- 保守能力
- 研究点生成能力
- 研究点貯蔵能力

建設能力等をLocationに与えられた固定値として扱わず、建設ヤード、建設ロボット、重機、施工設備等の施設・資産から発生するフローとして扱う。建設機械そのものは生産・所有・輸送可能な資産とし、配置された設備から実際の建設能力が発生する構造を基本とする。

能力については、「設備としてその機能が存在すること」と「現在実際に稼働して供給可能な能力」を区別する。研究実証等で現在の稼働能力を要求する場合、設備が存在するだけでは条件を満たさず、環境条件、停止状態、給電等を含めて実際に利用可能であることを要求する。

プレイヤーはフロー全体を見てボトルネックを判断する。ボトルネックの原因自体はゲーム側が可視化するが、最適な解決策までは自動提示しない。

---

## 6. 地点と経済ノード

ゲーム世界は、天体そのものと、実際に在庫・施設・物流状態を持つ経済ノードを分離して管理する。

天体は `CelestialBody` として、地表・軌道等のSpatial Nodeを束ねる親概念とする。InventoryやFacilityを「地球」「月」という天体全体へ直接置くのではなく、実際に存在する地表地域・軌道等のノードへ配置する。

想定構造：

```text
WorldState
- Time
- Celestial Bodies
- Spatial Nodes / Locations
- Transport Network
- Research
- Projects
- Organizations
- Contracts

CelestialBody
- Physical Parameters
- Surface Nodes
- Orbital Nodes

Location / Spatial Node
- Inventory
- Facilities
- Environment
- Power Network
- Local Resources
- Survey Knowledge
- Transport Connections
```

初期構造例：

```text
Earth
├ 地球地表
└ LEO

Moon
├ 月周回軌道
├ 月面南極地域
├ 月面表側地域
└ 必要に応じて追加月面地域
```

将来はMEO、GEO、複数の火星周回軌道、複数地表地域等を同じ構造で追加できる。各天体を必ず「地表1ノード＋軌道1ノード」に固定するものではない。

地球地表とLEO、月面と月周回軌道は別Inventory Nodeである。例えば地球地表に100 tの機械が存在しても、打上げを行うまではLEO在庫として利用できない。

月面は単一ノードにせず、日照、資源、地形、通信条件などに差を持たせる。ただし初期段階ではHexマップ等の細密地表表現は行わない。

施設定義や建設レシピは、原則として「月面だから建設可能」「LEOだから建設可能」といった特定Location IDへの直接依存を持たせない。施設は必要な重力、大気、圧力、温度、日照、地表・軌道条件、資源、通信、インフラCapability等を要求し、Location側の環境・設備状態との組み合わせで建設可否や稼働可否を決定する。

また、「その場所へ設置できる条件」と「設置後に正常運転できる条件」は分離可能にする。これにより、将来の環境変化を見越した先行建設や、テラフォーミング等によって環境条件そのものが変化する場合にも、Location固有の例外分岐を追加せず同じモデルで扱えるようにする。

---

## 7. 輸送

輸送はサプライチェーンの中核とするが、資源種類の増加を「資源ごとに補充ルールを大量設定する物流パズル」へ変換しない。

本作では、地表から軌道へ質量を投入する打上げと、軌道投入後の機体が軌道間・天体間・地表との間を移動する宇宙輸送を、運用上異なる概念として扱う。ただし `Launch Vehicle` と `Spacecraft` を排他的な用途ラベルとして扱わず、実際の輸送可否は機体性能と各移動Operationの要求から決める。

主なOperation例：

- Powered Ascent：地表から離昇し軌道へ投入する
- Spaceflight：軌道間・天体間を航行する
- Landing：地表へ着陸する
- Atmospheric Entry：大気圏へ進入・帰還する

輸送手段の適合判定には、Dry Mass、Payload Capacity、Propellant Capacity、Available Delta-v、Thrust、Specific Impulse、Mission Duration、Entry/Landing Capability、Docking/Refueling Compatibility、Turnaround Requirement等を利用する。Route側は端点、必要Operation、必要Delta-v、基準所要時間、環境、端点インフラ等を定義する。

研究は新しい推進方式、再使用機体、補給設備、着陸能力等を解禁できるが、航路そのものを技術IDで直接アンロックしない。現在保有する機体・サービス・インフラがRouteの物理的・運用的要求を満たせば利用可能とする。

### 7.1 拠点間物流能力

定常物流でプレイヤーが主に設計する対象は、個別品目の補充プランではなく拠点間の輸送能力とする。

例：

```text
地球地表 → LEO        30 t/day
LEO → 月面南極地域      8 t/day
```

プレイヤーは、どの拠点を接続するか、どの輸送方式・保有資産・外部サービスを利用するか、どの程度の輸送能力を割り当てるか、能力不足時にどの拠点や用途を優先するかを決める。

各施設・建設案件・産業は必要資源と目標状態から貨物需要を生成する。物流システムは有効な物流レーンの空き能力へ貨物を自動で積載し、品目ごとのバッチサイズや定期便設定をプレイヤーに要求しない。資源は内部では個別Inventoryとして保持し、供給不足、輸送待ち、到着待機、充足率を追跡する。

物流判断の中心は、Precision Componentsを何tずつ送るかではなく、「この研究拠点を維持するための地球→月面輸送能力が足りているか」「大型輸送船へ更新するか」「現地生産へ切り替えるか」とする。

手動貨物輸送や特定貨物への経路・輸送方式指定は必要に応じて残すが、通常運転の基本操作にはしない。

### 7.2 End-to-End輸送

プレイヤーは出発地と最終目的地を指定してEnd-to-End輸送を構成できる。Coreは利用可能な直行Missionまたは複数Legを選択でき、中継ノードごとの再発送操作を要求しない。

```text
A: 地球地表 → 月面 直行Mission
B: 地球地表 → LEO → 月面
C: 地球地表 → LEO → 月周回軌道 → 月面
```

LEOや月周回軌道は補給・積替え・再使用・造船を集積できる有力な経済ノードだが、進行上の必須ゲートではない。直行型機体、高度な補給網、中継型輸送等を性能と経済性から比較できるようにする。

宇宙船はCargoを運ぶだけの抽象容量ではなく、原則として自身がLocation間を移動する永続資産として扱う。打上げヴィークルは回収・整備、宇宙船は軌道上継続運用等、異なる状態遷移を持ち得る。

同一路線でもChemical Tug、Solar-Electric Tug等の複数方式を併存させ、速度、推進剤、積載量、再使用性、必要設備の差を投資判断にする。

到着先倉庫が満杯の場合、輸送中貨物は消失せず物流側の到着待機状態に残る。到着待機による渋滞は輸送資産やターミナルの利用可能性へ影響し得るが、輸送開始時から遠方の倉庫容量を予約する方式にはしない。

---

## 8. 打上げ窓・軌道条件

軌道力学はゲーム内部では考慮可能だが、プレイヤーに完全な軌道計算を要求しない。

火星輸送等では、

- 良好な輸送窓
- 通常条件
- 非効率な条件

としてコストや所要時間へ反映する。

基本的には「今は行けない」より「今行くと高くつく」という設計を優先する。

---

## 9. 研究システム

研究は本作の中心的な成長システムとする。

研究源は、人工衛星、有人実験、探査機、地上研究所、軌道研究設備、地表研究所、実証設備等からResearch Pointを継続生成する。研究源ごとに「この研究には使える／使えない」という適用可能研究範囲は原則として持たせない。

研究源の世代差はTierとして表現し、Tierが上がるとResearch Point生成効率を明確に、必要に応じて桁単位で向上させる。技術的に高度な研究は必要Research Pointも大きく増えるため、初期の人工衛星や有人実験だけで後期研究を進めることは理論上可能でも極めて遅くなる。

研究施設・研究資産はLevelを持つことができる。Level上昇は同一世代資産への追加投資を表し、Research Point生成量と研究点貯蔵容量を増加させる。新Tier解禁時には、既存の高Level資産をさらに強化するか、新しい高効率資産へ更新するかという比較を生む。

TierとLevelは同じ意味の倍率にしない。

- Tier：研究手段そのものの世代差・基礎効率差
- Level：既存設備への増設、拡張、改良、運用成熟

一世代前の高Level資産と新世代の低Level資産が一定範囲で競合できる一方、十分な規模では新Tierが効率面で優位になるよう調整する。旧資産を即座に撤去する一択にはしない。

研究Tierは地球からの距離ではなく技術的困難さを軸に設定する。高度な地上研究設備が単純な遠隔月面観測より高Tierであってよい。Locationは必要な真空、微小重力、放射線、地質試料等の研究環境を提供するが、距離だけでResearch Point倍率を決めない。

研究項目は単純な「生産量+10%」より、新しい施設、製法、推進方式、輸送方式、探査方法、建設方法、運用方法等の選択肢を開放することを優先する。研究完了によって既存設備を自動更新せず、新設備の建設、改修、試作、実証を必要に応じて要求する。

---

## 10. 研究点・研究進行

### 10.1 Research Pointの生成と貯蔵

Research Pointは研究源から時間経過に応じて生成され、組織の研究点プールへ蓄積する。

概念式：

```text
研究点生成量 = Tier基礎出力 × Level倍率 × 稼働率
研究点貯蔵上限 = Tier基礎容量 × Level容量倍率
```

具体的な倍率はバランス調整対象とし、構造テストで固定しない。重要なのは、Tier更新で明確な生産効率差が生まれ、Level投資によって既存資産も有用性を維持できることである。

貯蔵上限は研究基盤の規模を表す。研究に必要なResearch Pointが現在の貯蔵上限を超える場合、より高Tierの研究資産を建設するか、既存施設を増設・レベルアップして研究基盤を拡張する必要がある。

施設停止・電力不足等によって一時的な貯蔵上限が現在の保有Research Pointを下回っても、既に獲得した研究点を消滅させない。超過状態では新規生成を停止または制限し、容量回復後に再開する。

### 10.2 研究の消費と実証

研究開始・完了条件はResearch Pointだけに統一しない。研究ごとに以下を組み合わせる。

- Theory：蓄積Research Pointを消費する
- Prototype：実際の試作資材、設備、環境を要求する
- Demonstration：指定条件を満たした状態で一定期間の実証を要求する
- Operational Experience：実運用から経験を蓄積する

Theoryを実行できる研究源の種類を限定するのではなく、研究項目側の前提技術と、Prototype / Demonstration側の具体的条件によって技術体系を表現する。

実証場所は研究定義に特定Location IDとして固定せず、プレイヤーが候補地点を選び、その地点が必要な環境・設備・稼働条件を満たすかで判定する。

例：

High-Temperature Vacuum Regolith Electrolysis

Theory:
- 必要Research Point
- Electrochemistry系前提技術
- High-Temperature Materials系前提技術

Prototype:
- Precision Components
- Experimental Hardware
- 耐熱材料

Demonstration:
- 真空環境
- 所要電力
- 電解・材料処理Capability
- 規定期間の連続稼働

Result:
- 高温真空電解設備と関連レシピを利用可能

この方式により、研究点の世代拡大と、実際の産業・輸送・立地条件の双方を進行へ結び付ける。

---

## 11. 研究分野

初期設計では以下を主要分野とする。

### A. Launch & Propulsion

打上げシステム、地表離昇、高推力推進、再使用打上げ運用を中心に扱う。

例：
- Booster Recovery
- Reusable Booster Operations
- Rapid Vehicle Turnaround
- Reusable Upper Stage
- High-Thrust Engine Cycle
- Launch Pad Rapid Servicing
- Autonomous Precision Landing
- Surface Ascent Vehicle Operations

研究によって、地表→軌道投入能力、再使用率、整備回転率、搭載可能質量、運用コスト等が変化する。

軌道上推進や長距離宇宙輸送そのものはSpacecraft & Logistics側を中心に扱うが、推進技術など両分野に関係する前提研究は相互接続してよい。

---

### B. Spacecraft & Logistics

軌道投入後に独立して運用される宇宙船、軌道間輸送、補給、着陸船、物流インフラを中心に扱う。

例：
- Standardized Docking
- Autonomous Rendezvous
- Modular Spacecraft Bus
- Standard Cargo Container
- In-Space Propellant Transfer
- Long-Duration Cryogenic Storage
- Orbital Tanker
- Chemical Tug
- Solar Electric Propulsion
- Reusable Cargo Tug
- Cislunar Navigation
- Reusable Vacuum Descent / Ascent Stage
- Reusable Vacuum Cargo Lander

研究によって、宇宙船をLEO等で再使用すること、軌道上補給によって航続域を延ばすこと、軌道間輸送船と着陸船を分業すること、あるいは直接着陸型宇宙船を成立させること等、物流網の構造そのものを変える。

---

### C. Orbital Construction

例：
- Robotic Orbital Servicing
- Modular Orbital Structures
- Orbital Assembly
- Orbital Workshop
- Large Truss Construction
- Orbital Propellant Depot
- Spacecraft Maintenance Dock
- Orbital Shipyard

巨大宇宙機や軌道施設を地球から一体で打ち上げず、宇宙で組み立てる選択肢を開放する。

---

### D. Power & Thermal

例：
- High-Efficiency Space Solar Cells
- Large Deployable Arrays
- Regenerative Energy Storage
- High-Voltage Space Power
- Advanced Radiators
- Electrostatic Dust-Mitigation Solar Arrays
- Surface Power Distribution
- High-Voltage Surface Power Transmission
- Kilowatt Fission Surface Power
- Megawatt Surface Reactor

研究によって、単一設備の発電量だけでなく、発電所と消費地を分離可能にする等の構造変化を導入する。

---

### E. Survey & Planetary Science

例：
- High-Resolution Orbital Imaging
- Multispectral Mineral Mapping
- Neutron Spectrometry
- Precision Terrain Mapping
- Autonomous Surface Survey
- Ground-Penetrating Radar
- Regolith Core Sampling
- Volatile Prospecting
- Deep Geological Survey

資源情報は段階的に明らかにする。

Unknown  
→ Presence Probability  
→ Estimated Concentration  
→ Measured Concentration  
→ Estimated Reserve

探査自体をゲーム進行に含める。

---

### F. ISRU & Chemical Processing

例：
- Regolith Handling
- Vacuum Material Separation
- Low-Temperature Volatile Extraction
- Water Purification
- Industrial Electrolysis
- Oxygen Liquefaction
- Hydrogen Liquefaction
- Cryogenic Surface Storage
- In-Situ Cryogenic Propellant Production
- Molten Regolith Electrolysis
- Carbothermal Reduction

完全自給だけでなく、中間的な混成サプライチェーンを許容する。

例：

月産LOX  
＋  
地球産LH2

---

### G. Materials & Metallurgy

例：
- Vacuum Sintering
- Regolith Aggregate
- Regolith Glass Refining
- Basic Iron Extraction
- Aluminum Extraction
- Vacuum Casting
- Structural Extrusion
- Pipe and Tank Fabrication
- Vacuum-Processed Structural Alloys
- Precision Vacuum Metallurgy

現地資源から生産可能な部品カテゴリが徐々に増える。

---

### H. Manufacturing & Construction

例：
- Automated Surface Construction
- Regolith Landing Pads
- Modular Pressure Structures
- Additive Metal Fabrication
- Precision Vacuum Machine Shop
- Industrial Tool Production
- Heavy Equipment Assembly
- Surface Factory Modules
- Autonomous Heavy Surface Construction

最終的には「設備を作るための設備」を現地生産可能にする。

---

### I. Robotics & Automation

例：
- High-Latency Teleoperation
- Autonomous Surface Navigation
- Robotic Cargo Handling
- Autonomous Excavation
- Predictive Maintenance
- Robotic Field Repair
- Coordinated Haulage Fleets
- Autonomous Plant Operation
- Robotic Construction
- Self-Maintaining Industrial Systems

単純な効率上昇ではなく、遠隔操作前提から無人長期運転へ運用方式を変える。

---

### J. Communications, Navigation & Computing

例：
- High-Bandwidth Space Communications
- Cislunar Relay Constellation
- Precision Cislunar Navigation
- Surface Positioning Network
- Delay-Tolerant Networking
- Distributed Industrial Control
- Fault-Tolerant Space Computing
- Autonomous Traffic Management

通信・航法インフラ整備により、新地域や高度な自動運転を可能にする。

---

### K. Human Spaceflight

例：
- Long-Duration Life Support
- Water Recycling
- Radiation Shelter Design
- Electrostatic Abrasive-Dust Mitigation
- Surface Habitat
- Closed-Loop Oxygen Recovery
- Long-Duration Surface Medicine
- Reduced-Gravity Agricultural Trials
- Semi-Closed Ecological Support

無人開発を長く続ける戦略と、有人開発を早期に進める戦略を併存させる。

---

## 12. 研究ツリーの設計原則

一本道にはしない。

研究項目は「地域を解除する鍵」ではなく、新しい性能、設備、製法、運用方式を成立させる知識として設計する。目的地や航路の利用可否は、研究IDそのものではなく、研究によって利用可能になった機体・設備が実際の能力条件を満たすかで決める。

例えば発電なら、大規模太陽光発電を発展させる経路、核分裂電源を早期導入する経路、高効率蓄電・送電へ投資する経路等を並存させる。

物流でも、大型輸送能力を先に整える、再使用率を高める、現地生産で必要輸送量を減らす、小型高頻度輸送を自動運転する等の違いを許容する。

研究点生成についても、一世代前の高Level研究資産を使い続ける、新Tier設備を早期導入する、複数地域へ研究基盤を分散する等の合理的選択肢を作る。

研究は「正解の順番を探すもの」ではなく、「限られた産業・研究能力をどの技術体系へ先に投資するかを選ぶもの」とする。

---

## 13. Operational Experience

一部技術には運用経験を導入する。

研究直後から利用可能だが、長期運用によって新しい手順や次世代研究が開放される。

例：

Cryogenic Propellant Handling

Experience 0  
→ 基本運用可能

Experience 250  
→ Improved Operating Procedure

Experience 700  
→ Rapid Transfer Procedure

Experience 1000  
→ Next-Generation Storage Research

単純な効率ボーナスだけにはしない。

---

## 14. 月面開発の段階

月面は以下のように徐々に発展する。

### Stage 1: 軌道観測

月面には設備なし。

資源情報は低精度。

---

### Stage 2: 無人探査

- Lander
- Rover
- Temporary Power
- Surface Survey

資源濃度や地質条件が徐々に判明する。

---

### Stage 3: ロボット拠点

- Solar Farm
- Cargo Depot
- Regolith Harvester
- Volatile Extraction

依然ほぼ完全地球依存。

---

### Stage 4: 初期ISRU

- Water Extraction
- Oxygen Production
- Landing Pad
- Small Propellant Production

輸送コスト構造が部分的に変化する。

---

### Stage 5: 基礎工業

- Metal Extraction
- Sintering
- Structural Material Production
- Simple Fabrication

月面建設物の一部を現地生産。

---

### Stage 6: 部分的工業化

- Machine Shop
- Pipe / Tank Fabrication
- Surface Construction
- Industrial Power Grid

構造物や単純機械の地球依存が低下。

---

### Stage 7: 重工業化

- Heavy Equipment Assembly
- Major Propellant Export
- Large Surface Factory
- Large Power System

月が他地域の開発を支える産業拠点になる。

この段階でも高度電子部品等は地球依存し得る。

---

## 15. 自給率

植民地の自給度は単一値だけで扱わない。

例：

Mass Dependency  
Energy Dependency  
Propellant Dependency  
Machinery Dependency  
Electronics Dependency  
Food Dependency  
Replacement Parts Dependency

月が物量の大半を自給していても、少量の電子部品不足で設備停止する状況などを表現可能にする。

総合自給率は補助表示として利用できる。

---

## 16. 既存植民地を陳腐化させない

発展した植民地を操作不能化するPrestige方式は採用しない。

植民地は最後までプレイヤーの発展対象として残す。

新技術は新天地だけでなく、既存拠点の再開発理由にもする。

例：

Mass Driver 開発  
→ 月面物流を全面再構築

核融合  
→ 電力制約の変化

大型軌道建造  
→ 月面重工業の価値上昇

高性能材料  
→ 既存工場の再編

古い拠点へ何度でも戻って発展させられる構造とする。

---

## 17. 自動進行と自動化

ゲーム時間は通常状態で自動進行する。プレイヤーは一時停止と複数段階の速度変更を行い、状況を観察しながら介入する。日数を選択して進行させる方式はテスト・デバッグ用内部操作として残してよいが、通常UIの中心操作にはしない。

Idleゲームとして反復作業は自動化する。ただし、プレイヤーが楽しむべき設計判断を自動化しすぎない。

自動化対象：

- 定常生産
- 研究点生成
- 設定済み研究の進行
- 拠点間物流レーン上の貨物割当
- 建設進行
- 保守
- 既定の生産レシピ
- Offline Progress

プレイヤー判断として残すもの：

- 研究対象と研究順序
- 旧研究資産のLevelアップと新Tier資産建設の比較
- 新規産業配置
- 拠点間物流能力の増強
- 輸送方式・輸送資産の選択
- 新地域への進出
- 発電方式
- 技術経路
- 大規模再開発

施設、建設案件、研究、探査、物流レーン等は必要に応じて手動停止・再開できるようにする。停止は設定や進捗を失う取消とは区別し、再開時には従来の設定を保持する。

自動化は「設定した仕組みを繰り返し運転する」ことを担当する。品目ごとの日常的な積載判断は物流システムへ任せる一方、輸送能力を増やすか、別方式へ切り替えるか、現地生産へ移行するかという戦略判断はプレイヤーに残す。

---

## 18. LLM利用方針

ローカルLLMをゲームプレイへ利用するが、プレイヤーの主要判断を代行させない。

基本原則：

「LLMによってプレイヤーが考える対象が増えるなら利用する。プレイヤーが考える必要を減らす用途には原則利用しない。」

LLMに植民地最適化、物流最適化、研究選択等を委任することは避ける。

---

## 19. LLMの候補用途

有力候補：

- 外部組織の要求・提案生成
- 特殊イベント生成
- 組織間交渉
- 科学的不確実性の表現
- 研究上の問題生成
- 状況依存ミッション生成
- 世界側の反応やニュース生成

外部組織の要求や契約的イベントを導入する場合も、それを「契約をこなして資金を稼ぎ、次の設備を買う」中心ループにはしない。報酬は共同研究機会、試料、限定的な設備利用、外部支援、特殊な要求、世界状態の変化等を含められる。

例：

Simulation Core が、

研究点生成能力の大幅増加  
軌道造船能力拡大  
火星到達能力成立

という状態を検出する。

LLMが、

「外部研究機関が長期深宇宙実験への共同参加を提案」

という状況を生成する。

必要資源、期間、条件、ゲーム上の効果はSimulation Coreが決定する。LLMは世界側の目的や状況を構成するが、ゲーム状態を自由改変しない。

---

## 20. LLMとシミュレーションの分離

通常シミュレーションとLLMは完全分離する。

FAST PATH
- 時間進行
- 生産
- 物流
- 建設
- Research Point生成
- 研究
- 探査
- Offline Progress

SLOW PATH
- LLMイベント
- 外部組織の要求・提案
- NPC反応
- 研究上の問題
- 交渉

LLM応答待ちでゲームを停止しない。

ローカルLLMが数秒〜数十秒かかっても通常進行に影響しない設計とする。

---

## 21. プラットフォーム構成

想定プレイ環境：

PCをサーバー  
iPadをクライアント

第一候補はPWA/Web UI。

Webに固執するのではなく、

- iPadで扱いやすい
- PC上のローカルLLMを利用しやすい
- Simulation CoreとUIを分離しやすい
- チャット環境でテストしやすい
- 将来SwiftUI等へUIのみ置換可能

という理由から採用候補とする。

構成：

iPad  
↓  
Web/PWA UI  
↓  
PC Server  
├ Application API  
├ Simulation Core  
├ Save Data  
└ Local LLM

Simulation Serverを正準状態の保持主体とし、UIは状態表示とCommand発行を担当する。ブラウザを閉じてもServerが稼働している限りゲーム状態はServer側で継続管理できる構造を基本とする。

---

## 22. Simulation Core

ゲームルールはUI、HTTP、LLMから独立させる。

外部からSimulation Core内部のInventory、Facility、Project等を直接操作せず、Application層のCommand / Query境界を正式な操作面とする。

Commandの例：

- 時間の一時停止・再開・速度変更
- 建設計画・取消・停止・再開
- 建設優先度・建設能力配分
- 設備停止・再開・Levelアップ
- 電力優先度変更
- 生産レシピ変更
- 研究開始・停止・再開
- 探査開始・停止・再開
- 打上げヴィークル・宇宙船の配備、補給、整備方針
- 拠点間物流レーンの設定・能力変更
- 手動貨物輸送や特殊Mission設定
- 外部提案への応答

Queryの例：

- 世界概要
- 地点概要
- 在庫・フロー
- 電力
- 設備・Level
- 建設候補・建設案件
- 物流レーン・輸送待ち
- Research Point生成量・貯蔵量・上限
- 研究
- 探査
- 外部イベント
- ボトルネック・停止理由

QueryはUIがCore内部式を再実装しなくても、「なぜ進んでいないのか」を取得できるようにする。ただし最適な解決策の選択はプレイヤーへ残す。

理想的な内部操作モデル：

```python
state = new_game(seed)
state = apply_command(state, BuildFacility(...))
state = apply_command(state, SetTimeSpeed(...))
state = advance_time(state, duration)
```

通常UIでは時間が連続進行するが、テストでは決定論的な `advance_time` を利用できるようにする。

同一の初期状態、コマンド履歴、経過ゲーム時間、乱数seedからは同一結果を得られることを基本とする。

---

## 23. テスト可能性・Save/Load・Offline Progress

チャット環境でもゲーム状態を再現可能にする。

内部操作例：

```text
new_game(seed)
set_time_speed(multiplier)
start_research(id)
upgrade_facility(facility)
build(location, facility)
set_recipe(facility, recipe)
set_logistics_lane(source, destination, capacity, mode)
plan_manual_transport(source, destination, cargo)
advance_time(duration)
get_state()
get_research_report()
get_flow_report(location)
get_bottlenecks(location)
```

これによりGUIなしでも、Research Point生成・貯蔵、研究進行、生産、電力不足、輸送能力不足、施設建設、施設Level、Offline Progress、ボトルネック、Save/Load、バランスを検証可能にする。

Saveはversion付きSnapshotを基本とし、静的な施設・資源・研究等のDefinitionは現在のcontent定義から再構築し、可変ゲーム状態を復元する。ゲーム性評価段階では旧仕様・旧Saveとの後方互換維持を目的化せず、設計改善のために必要なら破壊的変更を行う。正式な保存互換性は仕様安定後に改めて導入する。

Offline Progressは通常シミュレーションと別ルールにせず、実時間をゲーム時間へ変換した上で通常の時間進行経路を利用する。同じ状態から同じゲーム時間だけ進めた場合、通常進行とOffline進行は原則として同じ結果になるようにする。

テストは暫定バランス数値や個別施設の仮数値を徒に固定しない。優先して検証するのは、

- 資源が負にならない
- 倉庫容量・予約量の整合
- 資源保存・Cargo質量保存
- Research Pointが貯蔵上限を超えて新規生成されない
- 研究点貯蔵上限低下で既獲得点が消滅しない
- Tier/Levelの変更が定義された研究能力へ一貫して反映される
- 研究源の種類で研究対象を不必要にハード制限しない
- 航路可否が技術名やLocation名ではなく実能力から決まる
- 物流需要が品目数に比例して手動設定を要求しない
- 状態遷移の妥当性
- 停止・再開の継続性
- Save/Load後の決定論
- Offline進行との同値性
- 同一seed・同一Command列の再現性
- 登録順や固有Location IDに依存しないこと

等、設計変更後も意味を持つ構造的不変条件とする。

LLM部分は固定応答またはMock Providerへ差し替えて再現テストする。

---

## 24. 初期施設・研究資産候補

研究資産はTierとLevelを持ち得る。名称は「月面研究所I」のような抽象的な地域名＋番号ではなく、実際の研究手段・装置・運用形態を示す名称を優先する。

### 地球地表

- General Research Laboratory
- High-Energy Propulsion Test Stand
- Vacuum Materials Laboratory
- Launch Vehicle Factory
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

### 月周回・深宇宙探査

- Multispectral Survey Orbiter
- Neutron Spectrometry Orbiter
- Cislunar Relay Constellation
- Sample Return Vehicle
- Deep-Space Experiment Platform

### 地表研究・産業拠点

- Robotic Geology Station
- Sample Analysis Laboratory
- Vacuum Regolith Process Laboratory
- Surface Materials Test Facility
- High-Temperature Electrochemistry Laboratory
- Pilot ISRU Plant
- Precision Vacuum Machine Shop
- Large Experimental Power System
- Long-Duration Surface Research Complex

これらはLocation固有名を直接能力条件にするものではない。必要な環境・電力・物流・Capabilityを満たせば、同型または派生設備を他地域へ展開できる。

---

## 25. 基本的なデザイン原則

1. ゲームの中心成長ループは、研究点生成 → 技術 → 産業・物流拡大 → 高度研究手段 → より大きな研究点生成とする。

2. Research Point源に研究分野ごとの適用可能範囲を原則設けず、Tier差、Level、出力、貯蔵容量、建設・維持コストで世代差を表現する。

3. 一世代前の高Level資産と新世代の低Level資産が比較対象になり、旧資産が解禁直後に無価値にならないようにする。

4. 研究の難易度・必要点数は地球からの距離ではなく技術的困難さを中心に決める。

5. 技術研究は航路を直接解除せず、機体・設備・推進・補給等の能力を成立させる。目的地利用可否は実際の能力条件から決める。

6. 研究完了後も、必要に応じて設備投資、試作、実証、運用経験を要求する。

7. 技術名は地域名を付けただけの抽象名称を避け、具体的な原理、装置、工程、運用技術として技術発展を感じられる名称にする。

8. 資源・中間材の種類は産業ゲームとして増やしてよいが、物流設定の種類は増やさない。

9. 定常物流では品目別補充プランより、拠点間輸送能力、輸送方式、優先度を主要判断とし、個別貨物割当は自動化する。

10. 各地点の資源と立地条件に意味を持たせるが、固有Location IDへの特例をCoreへ持ち込まない。

11. 新技術により古い拠点にも再開発価値を与える。

12. Idle自動化は反復処理を担当し、戦略判断を奪わない。時間は自動進行を基本とし、速度変更と一時停止を可能にする。

13. LLMは世界側の問題や主体を増やすために使い、プレイヤーのゲームプレイを代行させない。

14. Simulation CoreをUIから独立させ、チャット環境で広範囲に再現テスト可能にする。

15. 建設能力、研究能力、輸送能力等は、可能な限り設備・資産から発生するフローとして扱い、固定の地点ボーナスだけで表現しない。

16. フロー中心であっても在庫・倉庫・輸送中在庫を明示し、物流変動や供給途絶を吸収する能力そのものを投資判断にする。

17. 天体そのものと、地表・軌道等の経済ノードを分離し、在庫・施設・輸送状態は実際のSpatial Nodeへ所属させる。

18. 打上げと宇宙輸送を異なる運用概念として扱い、地表→軌道投入の高コスト性と、軌道投入後の再使用宇宙輸送の経済性を別々の投資対象にする。

19. 打上げヴィークル、宇宙船、着陸船等の名称は説明・分類に利用してよいが、輸送可否は用途ラベルではなく性能、環境、必要Operation、インフラ条件で決める。

20. 契約・資金獲得を主要進行にせず、外部組織は研究・世界イベント・共同事業等を生む補助システムとして扱う。

---

## 26. ゲーム性評価段階

現在のゲーム性評価では、最終仕様や全コンテンツを固定するのではなく、本作の中心的な判断構造が成立する程度までメカニクスを実装して比較する。

初期評価では、人工衛星・地上研究設備を中心とする低出力研究段階から、有人・軌道実験、無人地表探査を経て、恒久的な月面研究所を維持できる段階までを一本の研究・産業ループとして成立させることを優先する。その後、ISRU、現地材料加工、部分的工業化へ拡張する。

評価に必要な主要メカニクス：

- 自動時間進行、速度変更、一時停止
- Research Point生成・貯蔵・消費
- 研究資産のTierとLevel
- 高Level旧資産と低Level新資産の投資比較
- Theory / Prototype / Demonstration / Operational Experience
- 具体的技術名による研究体系
- 施設建設と並列建設能力配分
- 生産レシピと設備稼働優先度
- 発電・配電・部分稼働
- 在庫・倉庫・保管サービス
- 天体・地表・軌道を分離したSpatial Node
- 打上げヴィークルと宇宙船の異なる状態遷移
- Powered Ascent / Spaceflight / Landing / Atmospheric Entry等のOperation要件
- 拠点間物流レーンと共有輸送能力
- 貨物需要の自動割当
- 推進剤の実資源化
- 探査による資源情報の段階的開示
- 月面資源採掘・ISRU
- 手動停止・再開
- Save/Load
- Offline Progress
- ボトルネック表示

契約報酬と受託判断を中心とする資金獲得ループは評価対象から外す。外部サービスに会計資源が必要な場合も、研究・産業成長の主軸とは分離する。

仮数値はゲーム性検証のための調整対象であり、評価段階では旧仕様との後方互換や個別数値の固定を優先しない。必要ならデータ構造やルールを破壊的に変更してでも、より妥当なモデルへ更新する。

複数の研究・投資戦略をSimulation Core上で比較し、

- 低Tier研究資産を長く育てる戦略と新Tierへ早期更新する戦略の双方に合理性があるか
- Research Point生成量と貯蔵容量が次世代研究への自然な規模要件になるか
- 技術的困難さの増加が研究点必要量と研究設備コストの桁上昇として感じられるか
- 距離だけで研究価値が決まっていないか
- 特定研究を航路解除キーとして扱わず、実能力から到達可能性を判定できているか
- 資源種類増加が物流設定数の爆発を生まないか
- 拠点間輸送能力不足が新たな投資判断を生むか
- 月面等の高度研究拠点を支えるために電力・中間材・輸送・建設能力の拡大が必要になるか
- ボトルネック解消が次の問題につながるか
- 地球依存100%から部分的な現地自立へ移行する過程に複数の合理的な投資順序が存在するか

を検証する。

---

## 27. 現時点でのゲーム定義

本作は、

「探査・実験・研究設備からResearch Pointを継続生成し、その研究成果で産業・輸送・研究基盤を拡大し、より高い桁の知識生産と技術的に困難な宇宙開発へ進むIdle型宇宙産業シミュレーション」

と定義する。

ゲームの成長感は、契約を繰り返して資金残高を増やすことではなく、

「人工衛星や地上研究設備から少量の知識を得る段階」
から
「有人・軌道実験や高度探査を継続運用する段階」
へ、
さらに
「恒久研究所を遠隔地へ建設し、大量の電力・物資・物流を投入して高効率研究を行う段階」
へ、
さらに
「現地産業が研究設備そのものを支え、複数地域の研究・産業圏が相互に強化される段階」
へ移行することで表現する。

新しい研究Tierは旧設備を自動的に無価値にしない。成熟した既存資産をさらに拡張するか、新世代資産へ置き換えるかを常に比較できるようにする。

物流は個々の資源配送計画を大量に最適化する別ゲームにはせず、増大する研究・産業規模を支える拠点間輸送能力として扱う。プレイヤーはネットワークの容量と方式を設計し、定常的な貨物割当は自動運転へ任せる。

この「知識生産の拡大 → 技術 → 産業規模拡大 → より高度な知識生産」という循環を、本作の長期的なIdleゲームループの核とする。

---
