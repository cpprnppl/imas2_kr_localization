-- iM@S2 KOR 번역 플랫폼 — Supabase 설정 v2 (SQL Editor에서 1회 실행)
-- __TEAM_CODE__ 를 팀 암호로 바꾼 뒤 전체 실행.
-- 접근 통제: 요청 헤더 x-team-code = 팀 암호일 때만 읽기/쓰기 허용 (RLS).
-- v1의 tr 테이블은 rows로 대체 (사용 전이면 drop해도 무방).

create or replace function public.team_ok()
returns boolean language sql stable as $$
  select coalesce(
    current_setting('request.headers', true)::json->>'x-team-code', ''
  ) = '__TEAM_CODE__'
$$;

-- ---------- 번역 행 (xmb / script / image 공용)
create table if not exists public.rows (
  id   text primary key,          -- "<cat>:<grp>:<key>"
  cat  text not null,             -- xmb | script | image
  grp  text not null,             -- 소분류 (install / all / chi / scene …)
  seq  int  not null default 0,   -- 원본 순서
  key  text not null,             -- 원본 식별자 (xmb id / 파일:오프셋 / md5)
  jp   text not null default '',
  kr   text not null default '',
  st   smallint not null default 0,  -- 0 미번역 / 1 번역완료 / 2 검수완료
  ts   bigint not null default 0,    -- 마지막 수정 ms
  by   text not null default '',
  meta jsonb not null default '{}'   -- script: 화자/파일/오프셋, image: 치수/위치
);
create index if not exists rows_cat_grp_seq on public.rows (cat, grp, seq);
create index if not exists rows_ts on public.rows (ts);

alter table public.rows enable row level security;
drop policy if exists rows_select on public.rows;
drop policy if exists rows_insert on public.rows;
drop policy if exists rows_update on public.rows;
create policy rows_select on public.rows for select using (public.team_ok());
create policy rows_insert on public.rows for insert with check (public.team_ok());
create policy rows_update on public.rows for update
  using (public.team_ok()) with check (public.team_ok());
-- delete 정책 없음 = 삭제 불가

-- ---------- 수정 이력 (append-only)
create table if not exists public.hist (
  n      bigint generated always as identity primary key,
  row_id text not null,
  cat    text not null,
  grp    text not null,
  key    text not null,
  ts     bigint not null,
  by     text not null default '',
  kr     text not null default '',
  st     smallint not null default 0
);
create index if not exists hist_row on public.hist (row_id, n desc);
create index if not exists hist_ts on public.hist (ts desc);
create index if not exists hist_by on public.hist (by);

alter table public.hist enable row level security;
drop policy if exists hist_select on public.hist;
drop policy if exists hist_insert on public.hist;
create policy hist_select on public.hist for select using (public.team_ok());
create policy hist_insert on public.hist for insert with check (public.team_ok());
-- update/delete 정책 없음 = 이력 불변

-- ---------- 이미지 작업본 (작업자 업로드 PNG, base64)
create table if not exists public.tex_kr (
  md5  text primary key,          -- rows(cat=image)의 key
  data text not null,             -- PNG base64 (data: URI 아님, 순수 base64)
  ts   bigint not null default 0,
  by   text not null default ''
);
alter table public.tex_kr enable row level security;
drop policy if exists texkr_select on public.tex_kr;
drop policy if exists texkr_insert on public.tex_kr;
drop policy if exists texkr_update on public.tex_kr;
create policy texkr_select on public.tex_kr for select using (public.team_ok());
create policy texkr_insert on public.tex_kr for insert with check (public.team_ok());
create policy texkr_update on public.tex_kr for update
  using (public.team_ok()) with check (public.team_ok());

-- 암호 변경: team_ok() 함수만 새 암호로 다시 실행
