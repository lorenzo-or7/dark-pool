// Runs the DARK POOL migration on PGlite (embedded Postgres) with minimal stand-ins
// for Supabase's auth/storage schemas, then checks the RLS policies as two users.
import { PGlite } from '@electric-sql/pglite'
import { readFileSync } from 'node:fs'

const migration = readFileSync(process.argv[2], 'utf8')
const db = new PGlite()

await db.exec(`
  create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  create schema auth; create schema storage;
  create table auth.users (id uuid primary key, email text);
  create function auth.uid() returns uuid language sql stable as
    $$ select nullif(current_setting('request.jwt.claims', true)::json->>'sub', '')::uuid $$;
  grant usage on schema auth to authenticated, anon; grant execute on function auth.uid() to authenticated, anon;
  create table storage.buckets (id text primary key, name text, public boolean, file_size_limit bigint, allowed_mime_types text[]);
  create table storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text, name text);
  create function storage.foldername(name text) returns text[] language sql immutable as $$ select string_to_array(name, '/') $$;
  alter table storage.objects enable row level security;
  grant usage on schema storage to authenticated; grant select, insert, delete on storage.objects to authenticated;
  grant execute on function storage.foldername(text) to authenticated;
`)
await db.exec(migration)

const A = '00000000-0000-4000-8000-0000000000aa'
const B = '00000000-0000-4000-8000-0000000000bb'
const L = '00000000-0000-4000-8000-0000000000cc' // a second member of A's workspace ("Lipe")
await db.exec(`
  insert into auth.users values ('${A}','a@x.test'),('${B}','b@x.test'),('${L}','l@x.test');
  insert into public.workspaces (id, name) values ('10000000-0000-4000-8000-00000000000a','A'),('10000000-0000-4000-8000-00000000000b','B');
  insert into public.workspace_members values ('10000000-0000-4000-8000-00000000000a','${A}','owner', now()),
    ('10000000-0000-4000-8000-00000000000a','${L}','member', now()),('10000000-0000-4000-8000-00000000000b','${B}','owner', now());
`)
const WA = '10000000-0000-4000-8000-00000000000a'
const WB = '10000000-0000-4000-8000-00000000000b'

let pass = 0, fail = 0
const check = (name, ok, extra = '') => { ok ? pass++ : fail++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`) }

async function as(uid, fn) {
  await db.exec('begin')
  await db.query(`select set_config('request.jwt.claims', $1, true)`, [JSON.stringify({ sub: uid, role: 'authenticated' })])
  await db.exec('set local role authenticated')
  try { return await fn() } finally { await db.exec('rollback') }
}
async function asCommit(uid, fn) {
  await db.exec('begin')
  await db.query(`select set_config('request.jwt.claims', $1, true)`, [JSON.stringify({ sub: uid, role: 'authenticated' })])
  await db.exec('set local role authenticated')
  try { const r = await fn(); await db.exec('commit'); return r } catch (e) { await db.exec('rollback'); throw e }
}
async function fails(fn) {
  await db.exec('savepoint t')
  try { await fn(); await db.exec('release savepoint t'); return false } catch { await db.exec('rollback to savepoint t'); return true }
}

check('profiles created by the auth trigger', (await db.query('select count(*)::int n from public.profiles')).rows[0].n === 3)

await asCommit(A, () => db.query(`insert into public.strategies (workspace_id, name, rule_type) values ($1, 'A strat', 'orb')`, [WA]))
await asCommit(B, () => db.query(`insert into public.strategies (workspace_id, name, rule_type) values ($1, 'B strat', 'orb')`, [WB]))

await as(A, async () => {
  const r = await db.query('select name from public.strategies order by name')
  check('A sees only workspace A strategies', r.rows.map((x) => x.name).join() === 'A strat', JSON.stringify(r.rows))
  check('A cannot insert into workspace B', await fails(() => db.query(`insert into public.strategies (workspace_id, name, rule_type) values ($1, 'x', 'orb')`, [WB])))
  await db.exec('savepoint u')
  const u = await db.query(`update public.strategies set name = 'hacked' where workspace_id = $1`, [WB])
  check('A cannot update workspace B rows (0 rows affected)', u.affectedRows === 0)
  const d = await db.query(`delete from public.strategies where workspace_id = $1`, [WB])
  check('A cannot delete workspace B rows (0 rows affected)', d.affectedRows === 0)
  check('A cannot add members (no insert policy / revoked)', await fails(() => db.query(`insert into public.workspace_members values ($1, $2, 'member', now())`, [WB, A])))
  check('A cannot create workspaces', await fails(() => db.query(`insert into public.workspaces (name) values ('rogue')`)))
  const ws = await db.query('select name from public.workspaces')
  check('A sees only own workspace', ws.rows.map((x) => x.name).join() === 'A')
  const pr = await db.query('select email from public.profiles order by email')
  check('A sees own and co-member profiles only', pr.rows.map((x) => x.email).join() === 'a@x.test,l@x.test', JSON.stringify(pr.rows))
  check('A cannot forge created_by', await fails(() => db.query(`insert into public.strategies (workspace_id, name, rule_type, created_by) values ($1, 'forged', 'orb', $2)`, [WA, L])))
  check('A cannot rewrite audit history', await fails(() => db.query(`update public.audit_events set action = 'x'`)))
})

await as(L, async () => {
  const r = await db.query('select name, created_by from public.strategies')
  check('co-member L sees A strategy (shared workspace)', r.rows.length === 1 && r.rows[0].name === 'A strat')
  const u = await db.query(`update public.strategies set description = 'edited by L' where workspace_id = $1`, [WA])
  check('co-member L can edit shared strategies', u.affectedRows === 1)
})

await as(null, async () => {
  const r = await db.query('select count(*)::int n from public.strategies')
  check('no user (no claims) sees nothing', r.rows[0].n === 0)
})

await as(A, async () => {
  check('storage: A can write under own workspace folder', !(await fails(() => db.query(`insert into storage.objects (bucket_id, name) values ('attachments', $1)`, [`${WA}/e/f.png`]))))
  check('storage: A cannot write under workspace B folder', await fails(() => db.query(`insert into storage.objects (bucket_id, name) values ('attachments', $1)`, [`${WB}/e/f.png`])))
})

await db.exec('reset role')
console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
