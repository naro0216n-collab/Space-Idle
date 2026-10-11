"""Pure presentation geometry contracts, without a real browser or server."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess



def test_map_layout_scales_without_overlapping_hit_targets_or_registration_order_dependency():
    node = shutil.which("node")
    assert node is not None, "Node.js is required to verify browser-independent presentation geometry"
    source = Path(__file__).resolve().parents[1] / "space_idle" / "webui" / "system_map.js"
    script = r"""
      const fs=require('node:fs');
      const vm=require('node:vm');
      const context={
        window:{SpaceIdleApp:{state:{}}},
        document:{addEventListener:()=>{}},
      };
      vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
      const nodes=Array.from({length:36},(_,i)=>({
        id:`stress.node.${i}`,body_id:`stress.body.${Math.floor(i/12)}`,kind:'surface'
      }));
      const layout=context.window.SpaceIdleSystemMap.positionsFor(nodes);
      const reversed=context.window.SpaceIdleSystemMap.positionsFor([...nodes].reverse());
      const points=Object.values(layout.positions);
      if(JSON.stringify(layout)!==JSON.stringify(reversed))throw Error('registration order');
      if(points.length!==nodes.length||layout.height<=420)throw Error('map does not expand');
      if(!points.every((p,i)=>points.every((q,j)=>i===j||
        Math.abs(p[0]-q[0])>=142||Math.abs(p[1]-q[1])>=132)))throw Error('overlapping targets');
    """
    result = subprocess.run(
        [node, "-e", script, str(source)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
