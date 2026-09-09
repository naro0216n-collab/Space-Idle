# 宇宙開発Idleゲーム デザイン案 v0.4.0

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
- 保守
- 研究点生成
- 研究点貯蔵

能力はLocationへ固定値として付与するより、施設・資産から発生するフローとして扱う。「設備が存在すること」と「現在実際に供給可能な能力」を分離する。

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

地球の鉱床は開始時から既知のDepositとしてよく、月面と同じSurvey進行を毎回要求しない。これは地球Location IDへのCore特例ではなく、初期KnowledgeとDeposit Definitionの差として表現する。

初期設備は低効率・高維持比率・大規模という性格を持たせ、後に高効率設備や宇宙資源利用へ置換する理由を作る。

---

## 8. 地点と経済ノード

天体そのものと、実際に在庫・施設・物流状態を持つSpatial Nodeを分離する。

```text
Earth
├ Earth Surface
└ LEO

Moon
├ Lunar Orbit
├ South Polar Surface
├ Polar Cold Trap
└ Nearside Surface
```

地球地表とLEO、月面と月周回軌道は別Inventory Nodeである。施設定義や建設Recipeは特定Location IDへ直接依存せず、必要な重力、大気、圧力、温度、日照、地表・軌道条件、資源、通信、Capability等から建設・運転可否を決める。

「設置できる条件」と「正常運転できる条件」は分離する。

---

## 9. 輸送と物流

本作では、地表から軌道へ質量を投入するPowered Ascentと、軌道投入後のSpaceflight、Landing、Atmospheric Entry等を異なるOperationとして扱う。ただしLaunch Vehicle / Spacecraftという名称を排他的な可否ラベルにはしない。

輸送可否は、機体のDry Mass、Payload、Propellant、Delta-v、Thrust、Mission Duration、Atmospheric / Landing Capability、Docking / Refueling Compatibility、Turnaround Requirementと、Route側のOperation要件・端点条件から決める。

研究は新しい機体・推進・補給方式を解禁するが、航路そのものを技術IDで直接アンロックしない。

### 9.1 拠点間物流レーン

定常物流でプレイヤーが主に設計する対象は、品目ごとの補充ルールではなく拠点間輸送能力とする。

```text
Earth Surface → LEO       30 t/day
LEO → Lunar Surface        8 t/day
```

施設・建設案件・維持需要・産業は必要資源からResource Demandを生成する。物流システムは有効なLaneの空き能力へ貨物を自動割当する。プレイヤーは接続、能力、輸送方式、優先度を設計する。

### 9.2 End-to-End輸送

プレイヤーは出発地と最終目的地を指定でき、中継ノードごとの再発送操作を要求しない。

```text
Earth Surface → Lunar Surface
Earth Surface → LEO → Lunar Surface
Earth Surface → LEO → Lunar Orbit → Lunar Surface
```

LEOや月周回軌道は有力な補給・積替え・整備ノードだが、必須ゲートではない。

到着先倉庫が満杯の場合、Cargoは物流側のarrival waitingに残る。輸送中から目的地倉庫を予約しない。

---

## 10. ロケット・宇宙船の建造と保有

ロケットや宇宙船は外部サービスだけでなく、プレイヤーが建造・保有できる物理資産とする。

Vehicle Definitionは性能に加え、必要に応じて以下を持つ。

- Production Capability
- 建造期間
- 2〜3種類程度の実Resource投入量
- 整備Capability
- Turnaround期間
- 維持・交換資材

Vehicle Assembly Facility等へ建造を指示すると、製造Capabilityと資源を消費してProduction状態へ入り、完了後に利用可能なVehicle Stateとなる。

UIでは機体一覧だけでなく、建造候補について以下を表示する。

- 機種
- 建造可能地点
- 必要Capability
- 必要資源
- 建造期間
- 現在のblocker
- 建造中機体と完成見込み

打上げヴィークル、軌道間輸送船、着陸船、統合型宇宙船等を用途名称だけで使用制限しない。実性能がOperation要件を満たすかで判定する。

---

## 11. 科学探査とResearch Point

資源Surveyとは別にScientific Exploration Campaignを導入する。

Scientific Explorationは宇宙船等のVehicleを割り当て、一定期間の科学観測、近接探査、有人活動等を行うことでResearch Pointを得るシステムとする。

Campaignは必要に応じて以下を持つ。

- 探査対象・科学目的
- 必要Operation / Delta-v / Mission Duration
- 必要環境・Infrastructure
- 所要期間
- Research Point総量または生成率と上限
- 消耗資源

割当中Vehicleは物流Missionや別Campaignへ同時に使えない。適合判定は「探査船」タグではなくVehicle性能から行う。

同じ科学探査を無期限に繰り返すだけで無限Research Pointを得る構造は避ける。基本は有限Campaignとし、継続観測型は明示的な逓減・上限・運用コストを持たせる。

これにより、

宇宙船を建造する  
→ 輸送に使うか探査に割り当てるか選ぶ  
→ 探査でResearch Pointを得る  
→ 新技術を研究する  
→ より高度な宇宙船・研究設備・探査手段を成立させる

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

資源情報は段階的に明らかにする。

```text
Unknown
→ Presence Probability
→ Estimated Concentration
→ Measured Concentration
→ Estimated Reserve
```

Survey Campaignは地点・資源ごとのKnowledgeを更新する。完了Campaignは能力配分対象から自動的に外し、余剰Survey能力を未完了対象へ再配分する。

地球の一般鉱物等、開始時点で既知とする資源は初期Knowledgeを高い状態で定義してよい。

---

## 15. 月面開発と産業自立

月面は以下のように発展する。

1. 軌道観測
2. 無人探査
3. ロボット拠点
4. 初期ISRU
5. 基礎工業
6. 部分的工業化
7. 重工業化

月に到達すること、基地を作ること、資源を採掘すること、加工すること、研究所を維持すること、設備を現地製造すること、産業を自己拡張可能にすることは別段階として扱う。

自給度は単一値にせず、Mass、Energy、Propellant、Machinery、Electronics、Food、Replacement Parts等のDependencyを個別に見られるようにする。

発展した拠点をPrestige等で操作不能にしない。新技術は古い拠点の再開発理由にもする。

---

## 16. 自動進行と自動化

ゲーム時間は通常状態で自動進行する。プレイヤーは一時停止と複数段階の速度変更を行う。

自動化対象：

- 定常生産・採掘
- 維持Resource Demandの生成
- Research Point生成
- 設定済み研究・Survey・Scientific Explorationの進行
- 物流Lane上の貨物割当
- 建設進行
- 保守
- Offline Progress

プレイヤー判断として残すもの：

- 研究対象と研究順序
- 旧研究資産のLevelアップと新Tier資産建設の比較
- 新規産業配置
- 拠点間物流能力の増強
- Vehicle建造と用途配分
- 輸送方式・輸送資産の選択
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
- 建設計画・停止・再開・取消
- 設備停止・再開・Levelアップ
- Process選択・電力優先度
- Vehicle建造・補給・配備
- Logistics Lane設定
- 手動Cargo / Transport Mission
- Research開始・停止・再開
- Scientific Exploration開始・停止・Vehicle割当
- Resource Survey開始・停止・配分

主要Query例：

- 世界・地点概要
- 在庫・フロー・保管
- Facility / Level / 維持充足率
- Process投入・産出・稼働率・limiting factor
- 建設候補・案件
- Vehicle建造候補・必要資材・blocker
- Vehicle / Mission / Logistics Lane
- Research Point生成量・保有量・上限
- Research / Scientific Exploration / Survey
- Bottleneck / blocker

UIは建設可否、維持率、機体適合、研究条件等を独自再計算しない。Core/Applicationが判断材料と停止理由を返す。

---

## 19. Save / Load / Offline / テスト

Saveはversion付きSnapshotを基本とし、静的Definitionは現在のContentから再構築し、可変Stateだけを復元する。ゲーム性評価段階では旧仕様・旧Saveとの後方互換を目的化しない。

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
- VehicleがMissionとScientific Explorationへ二重割当されない
- Research Pointの生成・貯蔵上限が整合する
- Route可否が技術名や用途ラベルではなく実能力から決まる
- Save/Load後の決定論
- Offline進行との同値性
- 登録順や固有Location IDに依存しない

---

## 20. 初期施設・資産候補

### 地球地表

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
11. ロケット・宇宙船はCapability・資源・時間を使って建造可能な物理資産とする。
12. 宇宙船をScientific Explorationへ割り当ててResearch Pointを得られるようにする。
13. Scientific ExplorationとResource Surveyを別状態として扱う。
14. 資源・中間材の種類は増やしてよいが、物流設定数の爆発を避ける。
15. 定常物流では品目別補充より拠点間輸送能力、方式、優先度を主要判断とする。
16. 各地点の立地条件に意味を持たせるが、固有Location ID特例をCoreへ持ち込まない。
17. 新技術により古い拠点にも再開発価値を与える。
18. Idle自動化は反復処理を担当し、戦略判断を奪わない。
19. 天体と地表・軌道等のSpatial Nodeを分離する。
20. 打上げと宇宙輸送を異なるOperationとして扱うが、Vehicle名称だけで可否を固定しない。
21. 輸送中貨物は目的地倉庫容量を事前予約しない。
22. LLMは世界側の問題や主体を増やすために使い、プレイヤー判断を代行させない。
23. Simulation CoreをUIから独立させ、決定論的に再現・テスト可能にする。
24. ゲーム性評価段階では後方互換や暫定バランス数値の固定を優先しない。

---

## 22. ゲーム性評価段階

現在の評価では、最終仕様や全コンテンツを固定するのではなく、本作の中心的な判断構造が成立する程度までメカニクスを実装して比較する。

優先評価対象：

- 自動時間進行、速度変更、一時停止
- Research Point生成・貯蔵・消費
- Scientific ExplorationによるVehicle拘束とResearch Point獲得
- Research Tier / Level
- Theory / Prototype / Demonstration / Operational Experience
- 建築物の2〜3資源建造Recipe
- 建築物の維持Resource Demand
- Process入出力とUI可視化
- 地球初期採掘・基礎産業
- Vehicle建造
- 発電・配電・部分稼働
- 在庫・倉庫・保管サービス
- Spatial Node
- Transport Operation
- Logistics Laneと共有輸送能力
- 貨物需要の自動割当
- 推進剤の実資源化
- Resource Survey
- 月面ISRU・現地加工
- Save/Load / Offline Progress
- Bottleneck表示

契約報酬と受託判断を中心とする資金獲得ループは評価対象から外す。

複数戦略を比較し、低Tier研究資産を長く育てる戦略と新Tierへ早期更新する戦略、輸送力増強と現地生産、Vehicleを物流へ使うか探査へ使うか、地球産業を拡張するか宇宙資源利用へ早期移行するか等に合理的なトレードオフが生まれることを確認する。

---

## 23. 現時点でのゲーム定義

本作は、

「探査・実験・研究設備からResearch Pointを獲得し、その研究成果で産業・輸送・研究基盤を拡大し、建設・維持・物流・Vehicle配分のボトルネックを解消しながら、より高い桁の知識生産と技術的に困難な宇宙開発へ進むIdle型宇宙産業シミュレーション」

と定義する。

ゲームの成長感は、契約を繰り返して資金残高を増やすことではなく、

「地球の低効率産業と人工衛星・地上研究設備で基礎知識を得る段階」
から
「自前のロケット・宇宙船を建造し、輸送と科学探査へ配分する段階」
へ、
さらに
「恒久研究所を遠隔地へ建設し、大量の電力・物資・維持物流を投入して高効率研究を行う段階」
へ、
さらに
「現地産業が建設資材と維持資材を供給し、複数地域の研究・産業圏が相互に強化される段階」
へ移行することで表現する。
