# 第1表示段階 — 地球基礎産業・軌道活動・近傍天体探査の調整プラン

## 活動像と評価の性質

現代水準の地球産業・研究から始め、有限の採掘・加工・研究設備と初期Fleetを増設・運用し、地球近傍の観測・研究、資材を実際に輸送する月面無人Foundingを検討する。第1表示段階の全研究完了や月面拠点の特定数を前提にしない。立地・投資構成・取得研究は評価対象であり、以下の数値は登録Definitionから読み取った**条件付き係数**である。現物生産・技術取得・物流成功は別に検証する。

累計設計目標は実時間4時間＝14,400 game days（1日＝実時間1秒）。研究表示段階1には64件、全Theoryを取得した場合は373,200 RPあるが、これは当期間内の必修量ではない。

## 初期からの資産・研究供給

標準Scenarioの地球には研究所1、農場1、基礎構造材工場1、基礎機械工場1、鉱山・採石・取水施設、Vehicle組立1、発電設備等があり、LEOには観測機1、月軌道にはSurvey機1と無人着陸貨物艇1がある。地球保有人口は30人、初期資材は構造材120 t・機械100 t・精密電子70 t・推進剤40 t（その他Resourceも有限）。Earth market interfaceは存在するが、無市場の継続発展の根拠にしない。施設・Fleetの初期配置は研究技術の取得や将来の増設を意味しない。

現在の1研究所は4 RP/day、Research execution 1/day、RP保存180。LEOのFleet-backed軌道観測研究は2 RP/day、Research execution 1/day、RP保存120。双方が有効に稼働・Poolへadmissionできるときの**名目上限**は合計6 RP/day、Research execution 2/day、RP保存300。14,400日間これらが初日からフル稼働したと仮定しても86,400 RPであり、全64件の373,200 RPには達しない。RP生成の実効成立、Research Stage進行、Capacity競合、初期資産の維持と新規研究基盤への投資は別問題である。

既存研究設備の追加建設は構造材12 t・機械10 t・精密電子8 t・Construction work55を要する。段階1技術 `CO-RF-COMMUNICATIONS-01` によって小型Archive (`planned.facility.basic_data_archive`) が取得候補となる。ArchiveはRP生成0、貯蔵120/基であり、RP/dayの不足を解消する設備ではない。

## 地球産業の需給起点

登録された原料・中間材と設備を次のように一つの供給系へ接続する。地球の採掘対象、Cellごとの実Physical Potentialと受給配分は別途確認し、名目採掘能力を実産出と同一視しない。

| 系統 | 登録済みの名目係数（単一設備、技術前提を満たす場合） | 産業全体で競合する需要 |
|---|---|---|
| 鉱石・鉱物 | 地球初期鉱山1.7 t/day、採石2.4 t/day、取水1.0 t/dayの名目Extraction | 基礎構造材・機械・電子・セラミックス・水、人口・推進剤 |
| 基礎構造材 | `base.process.basic_structural_material`: 鉱石0.4 + 鉱物1.2 t/回 → 構造材0.3 t/回、初期工場1回/day | 新規Facility・Vehicle・研究基盤・Founding、機械工場の投入 |
| 基礎機械 | `base.process.basic_machinery`: 鉱石0.7 + 構造材0.2 t/回 → 機械0.16 t/回、初期工場1回/day | 建設・Fleet取得・工場増設。構造材の総生産0.3を純余剰として扱わない |
| 基礎電子 | `planned.process.earth_basic_electronics`: 鉱石0.6 + 鉱物0.8 + 水0.1 t/回 → 電子0.12 t/回。対応工場は0.8回/day、最大0.096 t/day | 電子工場の建設・運用は `PL-EARTH-PRECISION-PARTS` の研究取得後。研究設備・Vehicle・電子を必要とする他工程 |
| 食料 | `base.process.food_production`: 栄養原料0.25 + 水0.18 t/回 → 食料0.36 t/回、農場1回/day | 地球居住人口と将来の有人輸送。栄養原料は有限初期在庫と現地Extractionに依存 |
| 推進剤 | `planned.process.earth_electrolysis_basic` と `base.process.propellant_blending` が水→水素・酸素→推進剤を構成 | 電解・混合設備の建設、電力、輸送燃料と工場・研究の共通資材を同時評価 |

例として基礎構造材・機械・電子の3工程を上記最大回数で並行運用する**名目投入**は鉱石1.58 t/day、鉱物1.84 t/day、構造材0.2 t/day、水0.08 t/dayである。初期鉱山・採石の名目Extraction容量とは比較できるが、Worldに基づく採掘応答、実Allocation、Power、設備適合と研究解禁を通した持続供給をまだ実証しない。供給余剰0.3 t/dayという見かけの構造材出力を、上流の機械投入や他の建設需要を差し引かずに計上しない。

地球30人に対する地上生活供給設備の定義上のResource需要は、食品0.03 t/day、水0.06 t/dayである（人口増加・設備停止のない当日の仮定）。初期食品500 tを恒久供給とみなさず、農業・栄養原料・水・Powerの実稼働まで含めて維持負荷を検証する。

## 技術・取得負担と月面へつながる活動

地球の基礎電子・小型研究Archive・推進剤工程に関係する技術集合 `PL-EARTH-PRECISION-PARTS` / `CO-RF-COMMUNICATIONS-01` / `CR-CRYOGENIC-STORAGE-TRANSFER-02` とそのdirect prerequisiteの和集合は現在5技術、Theory合計29,000 RP。これは一つの取得経路を評価する**部分集合**であり、Stage1研究の代表選択を義務化する数値ではない。試作・実証・Operational Experienceの要求が別枝に現れたら、それぞれの実資産・実行条件で評価する。

無人Surface Foundingは登録済み `base.founding.robotic_surface_outpost` がPayload 5.2 t、建設投資としてConstruction equipment 0.5 t・機械1.5 t・構造材2.7 t、初期在庫として各資材を明示する。`base.vehicle.reusable_surface_cargo_lander` は地表アクセスのための着陸能力とPayload 6 tを持つが、着陸先のSite Eligibility、Cargo実到着、月軌道までの上流輸送、燃料・帰還・荷役条件を満たす必要がある。地表Cell選択はSurveyのKnowledgeと物理Worldに依存し、特定の月面Cellで成功することは事前に仮定しない。

## 調整判断

- 研究所の4 RP/dayと実際の設備取得量を起点に、最初の電子・Archive・基礎推進剤・観測／ロボット枝を取得する時間配分とその間の産業投資を評価する。全Theory RP÷4時間でRP/dayを決めない。
- 研究所や輸送機を1基増設する負担を、初期在庫だけでなく基礎構造材・機械・電子の**純生産**と並行需要へ戻し、運転とMaintenanceを継続可能か確認する。
- 研究・建設・科学探査用Fleetの配分、RP Pool admission、Vehicleの燃料・整備・輸送拘束を同時に評価する。月面Foundingを輸送手段の名目payloadのみで成立としない。
- 第2段階に引き継ぐのは資産と需給の説明可能な蓄積であり、Stage1技術全取得や月面複数拠点の無償配置ではない。後続の長期無人施設・有人輸送・生命維持を支える投資能力まで評価する。

**現時点で数値上の成立を実証していない点**：Worldによる実採掘量、設備ごとのプロセス選択・稼働とPower／Service競合、現物Construction、始点から月面までのCargo輸送、Scenarioからの所要時間。次の調整ではこれらを所有Domain / Application経路で必要範囲確認し、単純な名目能力表によって実行済みと扱わない。
