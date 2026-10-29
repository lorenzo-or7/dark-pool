-- DARK POOL v0.1 schema: a private research lab shared by invited members.
-- Every row belongs to a workspace; RLS lets members of that workspace read and
-- write it and nobody else. Membership itself is managed only with the service
-- role (scripts/invite_member.py), never from the browser.


-- ---------------------------------------------------------------- profiles

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text,
  display_name text check (char_length(display_name) <= 80),
  preferences jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, split_part(new.email, '@', 1))
  on conflict (id) do nothing;
  return new;
end $$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------- workspaces

create table public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 120),
  is_demo boolean not null default false,
  settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.workspace_members (
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  user_id uuid not null references public.profiles (id) on delete cascade,
  role text not null default 'member' check (role in ('owner', 'member')),
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);
create index workspace_members_user_idx on public.workspace_members (user_id);

-- Membership check used by every policy. SECURITY DEFINER avoids recursive RLS
-- on workspace_members; it only answers "is the caller a member of ws".
create or replace function public.is_member(ws uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.workspace_members m
    where m.workspace_id = ws and m.user_id = (select auth.uid())
  );
$$;
revoke all on function public.is_member(uuid) from public;
grant execute on function public.is_member(uuid) to authenticated;

-- ---------------------------------------------------------------- research data

create table public.watchlists (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  created_by uuid references public.profiles (id),
  updated_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.watchlist_assets (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  watchlist_id uuid not null references public.watchlists (id) on delete cascade,
  symbol text not null check (symbol ~ '^[A-Z]{1,5}(\.[A-Z])?$'),
  note text check (char_length(note) <= 280),
  added_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  unique (watchlist_id, symbol)
);

create table public.strategies (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  name text not null check (char_length(name) between 2 and 120),
  description text,
  symbol text check (symbol ~ '^[A-Z]{1,5}(\.[A-Z])?$'),
  rule_type text not null,
  current_version integer not null default 1 check (current_version >= 1),
  is_demo boolean not null default false,
  archived boolean not null default false,
  created_by uuid references public.profiles (id),
  updated_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.strategy_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  strategy_id uuid not null references public.strategies (id) on delete cascade,
  version integer not null check (version >= 1),
  config jsonb not null,
  note text check (char_length(note) <= 280),
  created_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  unique (strategy_id, version)
);

create table public.data_snapshots (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  symbol text not null,
  interval text not null,
  range text not null,
  source text not null,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  storage_path text not null,
  bars integer not null check (bars >= 0),
  first_bar timestamptz,
  last_bar timestamptz,
  fetched_at timestamptz not null,
  is_fixture boolean not null default false,
  created_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  unique (workspace_id, sha256)
);

create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  type text not null,
  params jsonb not null,
  dedupe_key text not null,
  status text not null default 'queued'
    check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  progress integer not null default 0 check (progress between 0 and 100),
  stage text,
  result jsonb,
  error text,
  cancel_requested boolean not null default false,
  created_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index jobs_dedupe_idx on public.jobs (workspace_id, dedupe_key) where status in ('queued', 'running');

create table public.experiments (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  strategy_id uuid references public.strategies (id) on delete set null,
  strategy_version integer,
  kind text not null check (kind in ('backtest', 'monte_carlo')),
  title text not null,
  status text not null default 'queued'
    check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  params jsonb not null,
  data_snapshot_id uuid references public.data_snapshots (id) on delete set null,
  dataset text not null default 'full' check (dataset in ('full', 'split', 'development', 'out_of_sample')),
  results jsonb,
  error text,
  job_id uuid references public.jobs (id) on delete set null,
  created_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index experiments_ws_created_idx on public.experiments (workspace_id, created_at desc);

create table public.simulation_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  experiment_id uuid not null references public.experiments (id) on delete cascade,
  symbol text not null,
  plan jsonb not null,
  seed integer not null,
  replays integer not null check (replays > 0),
  algorithm_version text not null,
  data_source text not null,
  data_snapshot_id uuid references public.data_snapshots (id) on delete set null,
  snapshot_sha256 text not null,
  pool_from text,
  pool_to text,
  pool_sessions integer,
  results jsonb not null,
  created_by uuid references public.profiles (id),
  created_at timestamptz not null default now()
);

create table public.simulated_trades (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  experiment_id uuid not null references public.experiments (id) on delete cascade,
  source text not null check (source in ('backtest', 'timemachine_history', 'paper')),
  dataset text not null default 'full' check (dataset in ('full', 'development', 'out_of_sample')),
  symbol text not null,
  entry_date text not null,
  entry_time text,
  entry double precision not null,
  stop double precision not null,
  target double precision,
  exit_price double precision,
  exit_date text,
  outcome text not null check (outcome in ('target', 'stop', 'close', 'time')),
  r_multiple double precision not null,
  created_at timestamptz not null default now()
);
create index simulated_trades_experiment_idx on public.simulated_trades (experiment_id);

create table public.scan_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  mode text not null,
  params jsonb not null,
  status text not null default 'queued',
  result jsonb,
  error text,
  job_id uuid references public.jobs (id) on delete set null,
  created_by uuid references public.profiles (id),
  created_at timestamptz not null default now()
);

create table public.journal_entries (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  title text not null check (char_length(title) between 1 and 160),
  body text not null default '',
  kind text not null default 'note' check (kind in ('note', 'hypothesis', 'simulated_trade', 'lesson', 'error')),
  symbol text,
  strategy_id uuid references public.strategies (id) on delete set null,
  experiment_id uuid references public.experiments (id) on delete set null,
  tags jsonb not null default '[]'::jsonb,
  trade jsonb,
  entry_date text not null,
  is_demo boolean not null default false,
  created_by uuid references public.profiles (id),
  updated_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index journal_ws_date_idx on public.journal_entries (workspace_id, entry_date desc);

create table public.attachments (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  journal_entry_id uuid not null references public.journal_entries (id) on delete cascade,
  filename text not null,
  content_type text not null check (content_type in ('image/png', 'image/jpeg', 'image/webp')),
  size integer not null check (size between 1 and 5242880),
  storage text not null check (storage in ('local', 'supabase')),
  path text not null,
  created_by uuid references public.profiles (id),
  created_at timestamptz not null default now()
);

create table public.audit_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  actor_id uuid references public.profiles (id),
  action text not null,
  entity text not null,
  entity_id text,
  detail jsonb,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- row level security

alter table public.profiles enable row level security;
alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;

-- A profile is visible to its owner and to people sharing a workspace with them.
create policy profiles_select on public.profiles for select to authenticated using (
  id = (select auth.uid())
  or exists (select 1 from public.workspace_members m
             where m.user_id = profiles.id and public.is_member(m.workspace_id))
);
create policy profiles_update_self on public.profiles for update to authenticated
  using (id = (select auth.uid())) with check (id = (select auth.uid()));

create policy workspaces_select on public.workspaces for select to authenticated
  using (public.is_member(id));

create policy members_select on public.workspace_members for select to authenticated
  using (public.is_member(workspace_id));
-- No insert/update/delete policy on workspaces or workspace_members: only the
-- service role (invite script) can change who is in a workspace.

do $$
declare t text;
begin
  foreach t in array array['watchlists', 'watchlist_assets', 'strategies', 'strategy_versions', 'data_snapshots',
                           'jobs', 'experiments', 'simulation_runs', 'simulated_trades', 'scan_runs',
                           'journal_entries', 'attachments']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create policy %I on public.%I for select to authenticated using (public.is_member(workspace_id))',
                   t || '_select', t);
    execute format('create policy %I on public.%I for insert to authenticated with check (public.is_member(workspace_id))',
                   t || '_insert', t);
    execute format('create policy %I on public.%I for update to authenticated using (public.is_member(workspace_id)) with check (public.is_member(workspace_id))',
                   t || '_update', t);
    execute format('create policy %I on public.%I for delete to authenticated using (public.is_member(workspace_id))',
                   t || '_delete', t);
  end loop;
end $$;

-- Audit events: members read and append; nobody edits or deletes history.
alter table public.audit_events enable row level security;
create policy audit_select on public.audit_events for select to authenticated using (public.is_member(workspace_id));
create policy audit_insert on public.audit_events for insert to authenticated
  with check (public.is_member(workspace_id) and actor_id = (select auth.uid()));

-- Authors are stamped by the database, not trusted from the client.
create or replace function public.stamp_author()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    if new.created_by is null then new.created_by := auth.uid(); end if;
    if new.created_by is distinct from auth.uid() and auth.uid() is not null then
      raise exception 'created_by must be the caller';
    end if;
  end if;
  return new;
end $$;

do $$
declare t text;
begin
  foreach t in array array['watchlists', 'strategies', 'strategy_versions', 'experiments', 'journal_entries',
                           'scan_runs', 'jobs', 'attachments']
  loop
    execute format('create trigger %I before insert on public.%I for each row execute function public.stamp_author()',
                   t || '_stamp_author', t);
  end loop;
end $$;

grant usage on schema public to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
revoke insert, update, delete on public.workspaces, public.workspace_members from authenticated;
revoke update, delete on public.audit_events from authenticated;
revoke all on all tables in schema public from anon;

-- ---------------------------------------------------------------- storage for journal captures

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('attachments', 'attachments', false, 5242880, array['image/png', 'image/jpeg', 'image/webp'])
on conflict (id) do nothing;

-- Object names are "<workspace_id>/<journal_entry_id>/<file>".
create policy attachments_read on storage.objects for select to authenticated
  using (bucket_id = 'attachments' and public.is_member(((storage.foldername(name))[1])::uuid));
create policy attachments_write on storage.objects for insert to authenticated
  with check (bucket_id = 'attachments' and public.is_member(((storage.foldername(name))[1])::uuid));
create policy attachments_delete on storage.objects for delete to authenticated
  using (bucket_id = 'attachments' and public.is_member(((storage.foldername(name))[1])::uuid));
