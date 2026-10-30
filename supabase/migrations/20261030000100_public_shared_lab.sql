-- DARK POOL: public shared lab (incremental; the v0.1 migration is not changed).
--
-- Anyone with the link uses ONE existing workspace. Nobody logs in. The backend runs every
-- request as a dedicated technical identity:
--   * a row in auth.users with no password, banned for 100 years and flagged
--     raw_app_meta_data.dp_technical = true, so it can never sign in interactively;
--   * a 'member' (never 'owner') of exactly one workspace, the shared lab.
-- The backend sets request.jwt.claims.sub to that id and switches to the `authenticated`
-- role, so the existing RLS policies, author triggers and audit rules keep applying.
-- Nothing here grants anything to `anon`, disables RLS or deletes data.

-- ---------------------------------------------------------------- is the caller the lab identity?

create or replace function public.is_technical_identity()
returns boolean language sql stable security definer set search_path = '' as $$
  select coalesce(
    (select (u.raw_app_meta_data ->> 'dp_technical')::boolean from auth.users u where u.id = (select auth.uid())),
    false);
$$;
revoke all on function public.is_technical_identity() from public, anon;
grant execute on function public.is_technical_identity() to authenticated;

-- ---------------------------------------------------------------- narrower reads for the lab identity
-- Restrictive policies are ANDed with the existing permissive ones. The lab identity shares
-- the workspace with the people who created it, but it must not read their profiles (e-mails,
-- names, preferences) or the member list. People keep exactly the access they had.

drop policy if exists profiles_technical_scope on public.profiles;
create policy profiles_technical_scope on public.profiles as restrictive for select to authenticated
  using (not public.is_technical_identity() or id = (select auth.uid()));

drop policy if exists profiles_technical_no_update on public.profiles;
create policy profiles_technical_no_update on public.profiles as restrictive for update to authenticated
  using (not public.is_technical_identity());

drop policy if exists members_technical_scope on public.workspace_members;
create policy members_technical_scope on public.workspace_members as restrictive for select to authenticated
  using (not public.is_technical_identity() or user_id = (select auth.uid()));

-- The lab identity never deletes audit history (already revoked for everyone) and never
-- changes membership (no insert/update/delete policy exists on workspace_members).

-- ---------------------------------------------------------------- setup procedure (server only)
-- Idempotent. Run by scripts/setup_public_lab.py with the database owner's connection.
-- It validates the workspace, creates the identity once, and adds the membership once.

create or replace function public.dp_setup_public_lab(p_workspace uuid, p_identity uuid)
returns table (identity_id uuid, workspace_name text)
language plpgsql set search_path = '' as $$
declare
  v_name text;
  v_email text := 'laboratorio-publico+' || replace(p_workspace::text, '-', '') || '@darkpool.invalid';
  v_col text;
begin
  select w.name into v_name from public.workspaces w where w.id = p_workspace;
  if v_name is null then
    raise exception 'O workspace % não existe. Use o id do workspace DARK POOL existente.', p_workspace;
  end if;

  if exists (select 1 from public.workspace_members m
             where m.user_id = p_identity and m.workspace_id <> p_workspace) then
    raise exception 'A identidade técnica % já pertence a outro workspace.', p_identity;
  end if;

  if exists (select 1 from auth.users u where u.id = p_identity) then
    if not coalesce((select (u.raw_app_meta_data ->> 'dp_technical')::boolean from auth.users u
                     where u.id = p_identity), false) then
      raise exception 'O id % pertence a uma conta pessoal; escolha outro DP_PUBLIC_IDENTITY_ID.', p_identity;
    end if;
    update auth.users set encrypted_password = '', banned_until = now() + interval '100 years', updated_at = now()
     where id = p_identity;
  else
    insert into auth.users (id, aud, role, email, encrypted_password, raw_app_meta_data, raw_user_meta_data,
                            banned_until, created_at, updated_at)
    values (p_identity, 'authenticated', 'authenticated', v_email, '',
            jsonb_build_object('provider', 'none', 'providers', '[]'::jsonb, 'dp_technical', true),
            jsonb_build_object('display_name', 'Laboratório compartilhado'),
            now() + interval '100 years', now(), now());
  end if;

  -- Supabase Auth reads these as text; NULLs break its admin listing.
  for v_col in
    select c.column_name from information_schema.columns c
     where c.table_schema = 'auth' and c.table_name = 'users'
       and c.column_name in ('confirmation_token', 'recovery_token', 'email_change_token_new', 'email_change',
                             'email_change_token_current', 'phone_change', 'phone_change_token',
                             'reauthentication_token')
  loop
    execute format('update auth.users set %1$I = coalesce(%1$I, '''') where id = $1', v_col) using p_identity;
  end loop;

  -- public.handle_new_user() created the profile; keep it free of any e-mail.
  insert into public.profiles (id, email, display_name)
  values (p_identity, null, 'Laboratório compartilhado')
  on conflict (id) do update set email = null, display_name = 'Laboratório compartilhado', updated_at = now();

  insert into public.workspace_members (workspace_id, user_id, role)
  values (p_workspace, p_identity, 'member')
  on conflict (workspace_id, user_id) do update set role = 'member';

  return query select p_identity, v_name;
end $$;

-- Only the owner of the database (the backend's DATABASE_URL / the SQL editor) may run it.
revoke all on function public.dp_setup_public_lab(uuid, uuid) from public, anon, authenticated;

-- ---------------------------------------------------------------- private bucket for frozen snapshots
-- Object names are "<workspace_id>/<sha256>.json.gz". The backend reads and writes them with
-- the server-side key; members (and the lab identity) are also limited to their workspace's
-- folder by these policies. There is no policy for anon.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('snapshots', 'snapshots', false, 52428800, array['application/gzip'])
on conflict (id) do update set public = false;

-- The attachments bucket already exists (v0.1). Make sure it stays private.
update storage.buckets set public = false where id in ('attachments', 'snapshots');

drop policy if exists snapshots_read on storage.objects;
create policy snapshots_read on storage.objects for select to authenticated
  using (bucket_id = 'snapshots' and public.is_member(((storage.foldername(name))[1])::uuid));
drop policy if exists snapshots_write on storage.objects;
create policy snapshots_write on storage.objects for insert to authenticated
  with check (bucket_id = 'snapshots' and public.is_member(((storage.foldername(name))[1])::uuid));
