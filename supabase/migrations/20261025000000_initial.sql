-- AnalytIQ AI initial secure project schema
create extension if not exists pgcrypto;
create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 140),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.datasets (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  original_filename text not null,
  storage_path text not null unique,
  sha256 text,
  file_bytes bigint not null default 0 check (file_bytes>=0),
  status text not null default 'uploaded' check(status in ('uploaded','processing','ready','failed')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create table if not exists public.analysis_runs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  dataset_id uuid references public.datasets(id) on delete set null,
  question text not null,
  plan jsonb not null default '{}'::jsonb,
  result jsonb,
  status text not null default 'planned' check(status in ('planned','running','completed','validated','failed')),
  created_at timestamptz not null default now()
);
create index if not exists idx_projects_owner on public.projects(owner_id);
create index if not exists idx_datasets_project on public.datasets(project_id);
create index if not exists idx_runs_project on public.analysis_runs(project_id);
alter table public.projects enable row level security;
alter table public.datasets enable row level security;
alter table public.analysis_runs enable row level security;
create policy "Owners manage projects" on public.projects for all to authenticated
  using ((select auth.uid())=owner_id)
  with check ((select auth.uid())=owner_id);
create policy "Owners read own datasets" on public.datasets for select to authenticated
  using ((select auth.uid())=owner_id and exists(select 1 from public.projects p where p.id=project_id and p.owner_id=(select auth.uid())));
create policy "Owners insert own datasets" on public.datasets for insert to authenticated
  with check ((select auth.uid())=owner_id and exists(select 1 from public.projects p where p.id=project_id and p.owner_id=(select auth.uid())));
create policy "Owners update own datasets" on public.datasets for update to authenticated
  using ((select auth.uid())=owner_id and exists(select 1 from public.projects p where p.id=project_id and p.owner_id=(select auth.uid())))
  with check ((select auth.uid())=owner_id and exists(select 1 from public.projects p where p.id=project_id and p.owner_id=(select auth.uid())));
create policy "Owners delete own datasets" on public.datasets for delete to authenticated
  using ((select auth.uid())=owner_id);
create policy "Owners manage runs" on public.analysis_runs for all to authenticated
  using ((select auth.uid())=owner_id and exists(select 1 from public.projects p where p.id=project_id and p.owner_id=(select auth.uid())))
  with check ((select auth.uid())=owner_id and exists(select 1 from public.projects p where p.id=project_id and p.owner_id=(select auth.uid())));
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('analytiq-originals','analytiq-originals',false,20971520,array['text/csv','text/tab-separated-values','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/vnd.ms-excel.sheet.macroEnabled.12','application/octet-stream'])
on conflict (id) do nothing;
create policy "Read own originals" on storage.objects for select to authenticated
using (bucket_id='analytiq-originals' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy "Upload own originals" on storage.objects for insert to authenticated
with check (bucket_id='analytiq-originals' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy "Delete own originals" on storage.objects for delete to authenticated
using (bucket_id='analytiq-originals' and (storage.foldername(name))[1]=(select auth.uid())::text);
