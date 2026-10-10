// Fixed functions.exec body. Define INDEX_PATH with the local connector-plan execution_index.
// All original packet files are checked and temporary Library registrations trashed before GitHub writes.
const root = INDEX_PATH.slice(0, INDEX_PATH.lastIndexOf('/') + 1);
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

async function loadAndTrash(files, requestId, ensureTempFolder = false) {
  const contents = Array(files.length);
  for (let start = 0; start < files.length; start += 20) {
    const group = files.slice(start, start + 20);
    const registered = [];
    let cleanupFailure = false;
    try {
      const createFolder = ensureTempFolder && start === 0;
      const operations = group.map((file, index) => ({
        operation: 'upload', container_path: file.path,
        destination_path: '/temp/space-idle-publish-' + requestId + '-' + (start + index) + '.json',
        overwrite: false,
      }));
      if (createFolder) operations.unshift({operation:'create_folder',path:'/temp',parents:true});
      const result = await tools.files__manage_library({operations});
      if (result.results?.length !== operations.length ||
          (createFolder && result.results[0]?.status !== 'succeeded'))
        throw Error('Temporary folder or registration failed');
      const rows = createFolder ? result.results.slice(1) : result.results;
      for (let i = 0; i < group.length; i++) {
        const row = rows[i];
        if (row?.library_file_id) registered.push({fileId:row.file_id, libraryId:row.library_file_id, index:start+i});
      }
      if (registered.length !== group.length || rows.some(r => r.status !== 'succeeded' || !r.file_id))
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
            // Restore it only when the exact original size and fingerprint prove it.
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
    } finally {
      for (let first = 0; first < registered.length; first += 20) {
        const subset = registered.slice(first, first + 20);
        try {
          const result = await tools.files__manage_library({operations:subset.map(r => ({
            operation: 'delete', target:{kind:'file',library_file_id:r.libraryId},
          }))});
          if (result.results?.length !== subset.length || result.results.some(r => r.status !== 'succeeded'))
            cleanupFailure = true;
        } catch (_) {cleanupFailure = true;}
      }
      if (cleanupFailure) throw Error('Temporary file cleanup failed; no GitHub write');
    }
  }
  if (contents.some(x => typeof x !== 'string') || contents.length !== files.length)
    throw Error('Incomplete Connector inputs');
  return contents;
}

// One small index locates exact original packets; it does not contain copies of their contents.
const indexText = (await loadAndTrash([{path:INDEX_PATH}], 'index', true))[0];
const index = JSON.parse(indexText);
if (index.version !== 1 || !/^[a-f0-9]{32}$/.test(index.request_id) ||
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
const payloads = await loadAndTrash(index.packets.map(row => ({
  path:root + row.name, size:row.size, fnv32:row.fnv32,
})), index.request_id);
const packets = payloads.map(raw => JSON.parse(raw));
let prior = index.publish_base_tree;
for (let i = 0; i < packets.length - 1; i++) {
  const p = packets[i], a = p.action_args;
  if (p.action !== 'GitHub.create_tree' || p.tree_batch_index !== i ||
      a?.repository_full_name !== index.repository || a.base_tree_sha !== prior ||
      !Array.isArray(a.tree_elements) || !sha(p.expected_tree))
    throw Error('Invalid tree packet chain; no GitHub write');
  prior = p.expected_tree;
}
const last = packets[packets.length - 1], commit = last.action_args;
if (last.action !== 'GitHub.create_commit' || commit?.repository_full_name !== index.repository ||
    commit.tree_sha !== prior || commit.parent_sha !== index.publish_base_head ||
    commit.message !== 'Publish transport ' + index.request_id)
  throw Error('Invalid commit packet; no GitHub write');
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
