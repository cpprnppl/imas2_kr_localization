-- iM@S2 XMB 번역표 — Supabase 설정 (SQL Editor에서 1회 실행)
-- __TEAM_CODE__ 를 디스코드에 공지할 팀 암호로 바꾼 뒤 실행할 것.
-- 접근 통제: 모든 읽기/쓰기는 요청 헤더 x-team-code 가 팀 암호와 일치할 때만 허용.
-- (anon key는 페이지에 공개되지만, 암호 없이는 RLS가 전부 거부한다)

create table if not exists public.tr (
  id text primary key,          -- "<파일>__<행키>" (예: install__farea_000)
  f  text not null,             -- install | ranker | exep_init
  k  text not null,             -- 행 키 (xmb id)
  kr text not null default '',  -- 한국어 번역
  st smallint not null default 0, -- 0 미번역 / 1 번역완료 / 2 검수완료
  ts bigint not null default 0,   -- 마지막 수정 (ms epoch) — 증분 동기화용
  by text not null default ''     -- 작성자 이름 (자율 입력)
);

create index if not exists tr_ts on public.tr (ts);

alter table public.tr enable row level security;

create or replace function public.team_ok()
returns boolean language sql stable as $$
  select coalesce(
    current_setting('request.headers', true)::json->>'x-team-code', ''
  ) = '__TEAM_CODE__'
$$;

drop policy if exists team_select on public.tr;
drop policy if exists team_insert on public.tr;
drop policy if exists team_update on public.tr;
create policy team_select on public.tr for select using (public.team_ok());
create policy team_insert on public.tr for insert with check (public.team_ok());
create policy team_update on public.tr for update
  using (public.team_ok()) with check (public.team_ok());
-- delete 정책 없음 = 삭제 불가 (실수 방지)

-- 암호 변경: team_ok() 함수만 다시 만들면 됨 (테이블/정책 그대로)
