# 第2表示段階 — 長期無人域外活動と初期有人域外拠点の調整プラン

## 活動像と第1段階からの接続

長期の遠隔無人作業を拡張しつつ、与圧・生命維持・低重力での有人移送、複数Surface Locationの継続居住を成立させ得る物理Contentを吟味する。並行して火星方面の無人探査・Founding準備を検討する。第2段階は有人活動を禁止する排他的区分ではなく、第3段階の長距離有人運用とも区別する。第1段階から取得した研究・製造・研究基盤・Fleetを引き継ぐ設計仮説であり、第2段階の開始時に完成した設備を配置しない。

累計実時間の設計目標は12時間＝43,200 game days（第1段階からの増分8時間＝28,800日）。第2段階の76研究の全Theoryは1,289,500 RPだが、全件取得を想定しない。第1段階のRP/day・研究設備・産業力を評価した上で、`planned.facility.remote_operations_lab`（Tier2、12 RP/day、Research execution 2.5/day、保存432）や `planned.facility.robotic_data_archive`（保存600）を取得・維持できるか調べる。前者は `X2-REMOTE-OPERATIONS-LAB`、後者は `X2-DATA-RETENTION` のTechnology条件を持つ。両研究とdirect prerequisiteの和集合は現行10技術、Theory合計101,000 RPであり、Prototypeも1件含むためRPだけでは成立しない。初期6 RP/dayを固定したまま第2段階の全研究を負担させない。

## 月面有人移送への物理的接続

軌道間有人輸送船 `base.vehicle.crew_transfer_spacecraft` は12席を持つが、地表着陸Operationを持たない。従来の小型再使用着陸貨物艇はPayload 6 tを持つが旅客席0。惑星間地表輸送機は4席・着陸能力を持つものの、第3表示段階 `EDL-EDL-08` が必要である。この組み合わせでは第2段階の低重力有人Surface移送を構成しにくい。

そこで汎用Vehicle Content `base.vehicle.crewed_low_gravity_lander`（低重力有人着陸連絡艇）を登録する。低重力・低圧・温度範囲に制限されたLanding/Powered Ascent、4席・有限Life Support・燃料・整備負担を持つ。月専用航路や技術解禁例外ではなく、Body/Environment/Movement能力によって移動可否が決まる。

| 項目 | 登録値・区別 |
|---|---|
| 技術前提 | `EDL-EDL-06`、`LS-ATMOSPHERE-WATER-WASTE-01`（Stage1）と `BIO-HUMAN-BIOLOGY-MEDICINE-04`（Stage2） |
| Technology DAG投資 | 上記3件とdirect prerequisiteの和集合は現行12研究、Theory 81,000 RP（Stage1:11件、Stage2:1件）。第1段階で取得済みなら重複投資しない |
| 製造 | 構造材4.5 t、機械2.5 t、精密電子2.0 t、組立Service7日/機の名目製造work |
| 移送 | 旅客4席、cargo payload 2 t、Life Support 4 person-days/day、endurance 45日、有限推進剤・電力 |
| 物理限界 | vacuum landing / powered ascent 2.1 km/s、地表重力上限2.0 m/s²、地表圧力上限1,000 Pa。火星地表へのアクセスまで黙示的に解放しない |
| 整備 | spacecraft_servicing 2日、basic machine parts 0.06 t／turnaround |

実MovementのWorld由来係数では、月軌道→2つの異なる月面Cellに向かう着陸Operationはいずれも名目2 game days、Vehicle physical failureなし。これは**物理性能の検証**であり、Fleet実在・実Cargo・実旅客輸送・Destination受入、往復推進剤補給、Location Foundingを成立させた証拠ではない。往路・復路を連続運転する場合は月面側のrefueling／servicing／Cargo handoffと地球起点の補給が追加負担になる。

## 複数拠点の維持需給を伴う数量仮説

異なる月面2拠点にそれぞれ8人、合計16人を仮置きし、資材・居住・輸送・研究・人口維持の競合を観測する。この人数と拠点数は規模感を吟味するための**可変入力**であり、段階のノルマでもPlayerの正解配置でもない。両拠点へFounding packageと貨物が実到着していること、`base.facility.habitat`（24人Housing・Life Support）の実建設・Power・維持が可能であることは別途必要である。

`base.facility.habitat` の1人1日当たり消費定義は食品0.001 t、水0.002 t、酸素0.003 t。2拠点・16人が各8人で継続生活するとき、名目需給負担は食品0.016 t/day、水0.032 t/day、酸素0.048 t/day。30日換算では順に0.48 t・0.96 t・1.44 tで、合計2.88 t／30日。これは**消費のみ**であり、輸送推進剤・Maintenance・施設建設・Research・Vehicle組立・貨物配送の追加負担を含まない。30日一括補給の成立や往復Fleet能力、実容量を証明しない。人口自然増加・停止や他施設のCrew占有を含む際は数値を再計算する。

2基の標準居住Facilityの建設投入だけでも（配置・建設の成立を仮定した名目値）構造材10 t、機械8 t、Construction work56が必要となる。別途2箇所の初期Surface Foundingの資材・貨物移送、Power、Site Eligibility、観測Knowledge、実Vehicle所有、Fleet commitmentと旅客輸送を加える。車両4席に対して16人の移動は**少なくとも4回の全席使用旅客輸送**が必要であり、軌道間船と着陸艇の接続／回収、乗員の二重計上を禁じる。実際の適格輸送量と所要時間はMovement・Fleet・Population Domainの契約で確かめる。

火星方面の無人活動は、単純な名称上の「深宇宙探査機」ではなく時点の技術前提と物理性能を照合する。`base.vehicle.radar_mapping_orbiter` は Stage2 `SS-SENSING-06` 等を前提とし、LEO→Mars orbitの物理経路の名目259日・Vehicle failureなし、軌道レーダーSurvey providerは `radar_sounder` を要求する。ただし出発機体取得、推進剤、当該ノードでのObservation開始・Fleet commitment、実Knowledge進行は未検証。`base.vehicle.deep_space_probe` は Stage3 `GN-NAVIGATION-06` を要求するので、第2段階の成立をその機体へ依存させない。

## 全体系の調整判断

- 第1段階で建設した工場・研究所・観測機の稼働とMaintenanceを残したまま、研究基盤のTier2化、複数Founding、Crew船製造、食料・水・酸素・部品加工の総需要を同じ期間・地点で照合する。
- 二拠点への搬入量だけでなく、その上流Earth／LEO／月軌道からの出発可能在庫と再補給・帰還・荷役、長距離移動中のFleet拘束を計上する。現地生産へ移るなら、その加工設備取得と電力投資を輸送節約量と比較する。
- Stage2の進行をTier2研究施設のRP/dayだけで設計せず、建設・研究の先行投資、Prototype、Pool容量、既存ProviderとのCompetitionを考慮する。月面有人成立とStage3火星有人の時間・負担を混同しない。
- 月面各CellのEnvironment・Terrain・PotentialとSurvey公開状態を独立に見て、両拠点が同じ資源配置・同じ最適な成立方法になることを強制しない。

**残る実行上の未確認**：異なる月面CellでのFounding・Habitatの実建設、旅客の起点・中継・到着受入、地域間の物流補給とReturn operation、研究Provider設備とRPの同時稼働、火星軌道でのFleet-backed Survey開始。これらは名目Projectionから成功宣言せず、実Application / Domainの短い横断検証を要する。時間目標そのものも、累積取得投資と並行活動に照らして再調整可能である。
