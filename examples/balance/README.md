# 全体系Content調整の条件付き数量比較例

以下は**現在登録されたContentを比較するための分析者による仮定**であり、推奨攻略手順、初期プレイヤー状態、理想日数、正式なBalance値ではない。実ゲームの研究完了・建設完了・交通開通・貨物着荷・人口生存を予測しない。

```bash
python scripts/analysis_balance.py examples/balance/mars_titan_development.json
python scripts/analysis_balance.py examples/balance/mars_titan_development.json \
  --content-variant examples/balance/research_rp_hypothesis.json --content-impact
python scripts/analysis_balance.py examples/balance/solar_system_volatile_development.json
```

`mars_titan_development.json` は火星の研究・上流採掘・居住負担、タイタンの揮発性資源採掘と火星向け輸送需要を、設備投資期・研究/操業期・後続投資期で比較する。二つのケースは初期条件・期間を共通にし、条件付きの研究所規模と事前投資を変える。各Phaseの `habitation_demands` は人数と登録Life Support設備から使うResource係数を指定する**需要条件**であり、当該設備の保有やPopulation Allocationを意味しない。表示されるHousing / Life Supportの不足は名目設備能力との単純な数量差である。研究目標の実行能力に基づく時間下界とRP不足を分けて読み、建設Resource・Construction work・継続Maintenanceも併記する。遠隔地Stockを相殺せず、選択した輸送需要に対応するCapacityが不明なら制約として残す。

`research_rp_hypothesis.json` は現在登録された研究ProviderのRP生成係数だけを増加させる**検討用仮説**。研究時間の全体下界が変わらず、投資変更と違う効果になる場合を確認するためのもので、ゲーム本体のContentは変更しない。

`solar_system_volatile_development.json` は研究を起点にせず、同一の名目採掘・太陽光発電設備を水星・火星・ガニメデ・タイタン・ウンブリエルの登録Surface Contextへ置いた場合の係数・取得後の数量を比較する。各天体に実在する拠点・輸送路・利用可能電力・Resource Stockを仮定せず、選択方法と登録World Potentialの条件付き結果だけを見る。水星や火星を標準立地として固定しない。

概要は不足数量・時間・共有Capacity・立地係数・条件差に絞る。`--details` は同じ元ProjectionのResource別・用途別台帳、出典、未成立条件を確認するときに使用する。異なる立地の基準値やケース差をContent採否の判断につなげるときは、定義値・期間・需要・輸送路・Nodeを変数として再評価する。これらの例の数値をテストで固定しない。
