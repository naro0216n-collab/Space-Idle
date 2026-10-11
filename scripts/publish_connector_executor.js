// Fixed functions.exec body. Define INDEX_PATH with the local connector-plan execution_index.
// All original packet files are checked and temporary Library registrations trashed before GitHub writes.
const root = INDEX_PATH.slice(0, Math.max(INDEX_PATH.lastIndexOf('/'), INDEX_PATH.lastIndexOf('\\')) + 1);
const requestId = /(?:^|[\\/])execution-index-([a-f0-9]{32})\.json$/.exec(INDEX_PATH)?.[1];
if (!requestId) throw Error('Invalid transaction index path; no GitHub write');
const tempPrefix = 'space-idle-publish-' + requestId + '-';
const tempPattern = new RegExp('^' + tempPrefix + '(?:index|[0-9]+)\\.json$');
const fingerprint = value => {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code > 127) throw Error('Non-ASCII Connector packet');
    hash = Math.imul(hash ^ code, 16777619) >>> 0;
  }
  return hash;
};
const sha = value => typeof value === 'string' && /^[a-f0-9]{40}$/.test(value);

async function ownedFiles() {
  const items = [];
  let cursor;
  for (let page = 0; page < 100; page++) {
    const args = {surface:'library',library_path:'/temp',limit:250};
    if (cursor) args.cursor = cursor;
    const response = await tools.files__list(args);
    if (!Array.isArray(response.items)) throw Error('Cannot enumerate temporary Library files');
    for (const item of response.items) {
      if (item.kind === 'file' && typeof item.name === 'string' &&
          tempPattern.test(item.name)) {
        if (!item.library_file_id) throw Error('Temporary file has no Library ID');
        items.push(item.library_file_id);
      }
    }
    if (!response.next_cursor) return [...new Set(items)];
    cursor = response.next_cursor;
  }
  throw Error('Temporary Library listing exceeded page limit');
}

async function deleteIds(ids) {
  for (let first = 0; first < ids.length; first += 20) {
    const group = ids.slice(first, first + 20);
    try {
      await tools.files__manage_library({operations:group.map(id => ({
        operation:'delete',target:{kind:'file',library_file_id:id},
      }))});
    } catch (_) { /* The scoped inventory pass handles missing acknowledgements. */ }
  }
}

async function cleanupOwnedFiles() {
  for (let attempt = 0; attempt < 3; attempt++) {
    const ids = await ownedFiles();
    if (!ids.length) return;
    await deleteIds(ids);
  }
  if ((await ownedFiles()).length) throw Error('Temporary file cleanup failed; no GitHub write');
}

async function loadInputs(files, offset, trackedIds) {
  const contents = Array(files.length);
  for (let start = 0; start < files.length; start += 20) {
    const group = files.slice(start, start + 20);
    const registered = [];
    const operations = group.map((file, index) => ({
      operation:'upload',container_path:file.path,
      destination_path:'/temp/' + tempPrefix + (offset < 0 ? 'index' : offset + start + index) + '.json',
      overwrite:false,
    }));
    const response = await tools.files__manage_library({operations});
    const rows = response.results;
    if (Array.isArray(rows)) {
      for (let i = 0; i < rows.length; i++) {
        if (rows[i]?.library_file_id) registered.push({
          fileId:rows[i].file_id, libraryId:rows[i].library_file_id, index:start+i,
        });
      }
    }
    trackedIds.push(...registered.map(row => row.libraryId));
    if (rows?.length !== group.length || registered.length !== group.length ||
        rows.some(row => row.status !== 'succeeded' || !row.file_id))
      throw Error('Temporary registration failed');
    for (let first = 0; first < registered.length; first += 5) {
      let pending = registered.slice(first, first + 5);
      for (let attempt = 0; attempt < 12 && pending.length; attempt++) {
        const reads = await tools.files__read({read:pending.map(r => ({ref_id:r.fileId,max_lines:1000}))});
        const next = [];
        for (let i = 0; i < pending.length; i++) {
          const row = pending[i], response = reads.results?.[i], file = files[row.index];
          if (response?.has_more === true || !Array.isArray(response?.content) ||
              !response.content.every(part => typeof part === 'string')) {
            next.push(row); continue;
          }
          let raw = response.content.join('');
          // Files.read can omit the original trailing newline in a text file.
          if (file.size != null && raw.length === file.size - 1 &&
              file.fnv32 != null && fingerprint(raw + '\n') === file.fnv32)
            raw += '\n';
          if (file.size != null && raw.length !== file.size) {next.push(row); continue;}
          if (file.fnv32 != null && fingerprint(raw) !== file.fnv32)
            throw Error('Connector packet fingerprint mismatch');
          if (!raw.startsWith('{') || !raw.trimEnd().endsWith('}')) {next.push(row); continue;}
          contents[row.index] = raw;
        }
        pending = next;
      }
      if (pending.length) throw Error('Temporary file unreadable or truncated');
    }
  }
  if (contents.some(x => typeof x !== 'string') || contents.length !== files.length)
    throw Error('Incomplete Connector inputs');
  return contents;
}

const folder = await tools.files__manage_library({operations:[
  {operation:'create_folder',path:'/temp',parents:true},
]});
if (folder.results?.length !== 1 || folder.results[0]?.status !== 'succeeded')
  throw Error('Temporary folder unavailable; no GitHub write');
await cleanupOwnedFiles();

// Retain both the index and packet registrations until all source material has
// been verified. A single scoped cleanup then certifies that the transaction
// has no temporary Library files before any GitHub write.
const trackedIds = [];
let packets, index, commit;
try {
  // One small index locates exact original packets; it does not contain copies of their contents.
  const indexText = (await loadInputs([{path:INDEX_PATH}], -1, trackedIds))[0];
  index = JSON.parse(indexText);
  if (index.version !== 1 || index.request_id !== requestId ||
      index.repository !== 'naro0216n-collab/Space-Idle' ||
      !sha(index.develop_head) || !sha(index.publish_base_head) || !sha(index.publish_base_tree) ||
      !Array.isArray(index.packets) || index.packets.length < 2 || index.packets.length > 300)
    throw Error('Invalid Connector execution index; no GitHub write');
  for (let i = 0; i < index.packets.length; i++) {
    const row = index.packets[i];
    const name = i === index.packets.length - 1 ? 'create-transport-commit.json' :
      'tree-batch-' + String(i).padStart(3, '0') + '.json';
    if (row.name !== name || !Number.isSafeInteger(row.size) || row.size <= 0 ||
        row.size > 200000 || !Number.isSafeInteger(row.fnv32) || row.fnv32 < 0 || row.fnv32 > 0xffffffff)
      throw Error('Invalid Connector packet descriptor; no GitHub write');
  }
  const payloads = await loadInputs(index.packets.map(row => ({
    path:root + row.name, size:row.size, fnv32:row.fnv32,
  })), 0, trackedIds);
  packets = payloads.map(raw => JSON.parse(raw));
  let prior = index.publish_base_tree;
  for (let i = 0; i < packets.length - 1; i++) {
    const p = packets[i], a = p.action_args;
    if (p.action !== 'GitHub.create_tree' || p.tree_batch_index !== i ||
        a?.repository_full_name !== index.repository || a.base_tree_sha !== prior ||
        !Array.isArray(a.tree_elements) || !sha(p.expected_tree))
      throw Error('Invalid tree packet chain; no GitHub write');
    prior = p.expected_tree;
  }
  const last = packets[packets.length - 1];
  commit = last.action_args;
  if (last.action !== 'GitHub.create_commit' || commit?.repository_full_name !== index.repository ||
      commit.tree_sha !== prior || commit.parent_sha !== index.publish_base_head ||
      commit.message !== 'Publish transport ' + index.request_id)
    throw Error('Invalid commit packet; no GitHub write');
} finally {
  await deleteIds(trackedIds);
  await cleanupOwnedFiles();
}
for (let i = 0; i < packets.length - 1; i++) {
  const result = await tools.mcp__GitHub__create_tree(packets[i].action_args);
  if (result.result?.sha !== packets[i].expected_tree)
    throw Error('GitHub tree SHA mismatch: transaction stopped');
  text(JSON.stringify({stage:'tree-established',index:i,sha:result.result.sha}));
}
const created = await tools.mcp__GitHub__create_commit(commit);
if (!sha(created.result?.sha)) throw Error('GitHub commit SHA missing');
const updated = await tools.mcp__GitHub__update_ref({
  repository_full_name:index.repository, branch_name:'publish',sha:created.result.sha,force:false,
});
if (updated.result?.success !== true) throw Error('Publish ref update failed');
text(JSON.stringify({stage:'transport-ref-updated',transport_commit:created.result.sha}));
