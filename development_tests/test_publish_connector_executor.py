"""Connector registration visibility is retried without bypassing input verification."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_executor_refreshes_temporarily_invisible_inputs_and_fails_closed() -> None:
    script = r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const source = fs.readFileSync('scripts/publish_connector_executor.js','utf8');
const request = 'a'.repeat(32), repo = 'naro0216n-collab/Space-Idle';
const head = '1'.repeat(40), parent = '2'.repeat(40), base = '3'.repeat(40);
const target = '4'.repeat(40), committed = '5'.repeat(40);
const fnv = value => {
  let h = 2166136261;
  for(let i=0;i<value.length;i++) h = Math.imul(h ^ value.charCodeAt(i), 16777619) >>> 0;
  return h;
};
const tree = JSON.stringify({action:'GitHub.create_tree',tree_batch_index:0,
  expected_tree:target,action_args:{repository_full_name:repo,base_tree_sha:base,
  tree_elements:[{path:'.publish/transport/develop/0000.b64',mode:'100644',type:'blob',content:'Zg=='}]}});
const commit = JSON.stringify({action:'GitHub.create_commit',action_args:{repository_full_name:repo,
  tree_sha:target,parent_sha:parent,message:'Publish transport '+request}});
const index = JSON.stringify({version:1,request_id:request,repository:repo,develop_head:head,
  publish_base_head:parent,publish_base_tree:base,
  packets:[{name:'tree-batch-000.json',size:tree.length,fnv32:fnv(tree)},
           {name:'create-transport-commit.json',size:commit.length,fnv32:fnv(commit)}]});
const content = {index,'0':tree,'1':commit};
const path = '/tmp/inputs-002/execution-index-'+request+'.json';
async function trial(visibleLater){
  let reads = 0, refreshes = 0, deletes = 0, writes = 0;
  const tools = {
    files__manage_library:async ({operations})=>({results:operations.map(op=>{
      if(op.operation==='upload') {
        const label=op.destination_path.split('-').at(-1).replace('.json','');
        return {status:'succeeded',file_id:'initial-'+label,library_file_id:'library-'+label};
      }
      if(op.operation==='delete') deletes++;
      return {status:'succeeded'};
    })}),
    files__read:async ({read})=>{reads++;
      return {results:read.map(({ref_id})=>{
        if(ref_id==='initial-index' && (reads===1 || !visibleLater))
          return {content:['The requested file reference is not currently visible.'],
            warnings:['File is not visible in the requested files surface.']};
        const label=ref_id.split('-').at(-1);
        return {content:[content[label]],has_more:false,warnings:[]};
      })};
    },
    files__list:async ()=>{refreshes++;return {items:visibleLater ?
      [{kind:'file',name:'space-idle-publish-'+request+'-index.json',file_id:'fresh-index',library_file_id:'library-index'}] : []};},
    mcp__GitHub__create_tree:async ()=>{writes++;return {result:{sha:target}};},
    mcp__GitHub__create_commit:async ()=>{writes++;return {result:{sha:committed}};},
    mcp__GitHub__update_ref:async ()=>{writes++;return {result:{success:true}};},
  };
  const executor=new AsyncFunction('tools','text','INDEX_PATH',source);
  let failure='';
  try {await executor(tools,()=>{},path);}catch(e){failure=String(e);}
  return {reads,refreshes,deletes,writes,failure};
}
(async()=>{
  const success=await trial(true);
  assert.equal(success.failure,'');
  assert.equal(success.writes,3);
  assert.equal(success.deletes,3);
  assert.ok(success.reads>=2);
  assert.ok(success.refreshes>=1);
  const blocked=await trial(false);
  assert.match(blocked.failure,/registration not yet visible/);
  assert.equal(blocked.reads,12);
  assert.equal(blocked.writes,0);
  assert.equal(blocked.deletes,3);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
