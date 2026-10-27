// GBO -- shared WHOOP code for the whoop-oauth-callback and whoop-sync Edge
// Functions (Oct 2026 WHOOP pilot). WHOOP API v2.
//
// Secrets:
//   WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET -- set by hand under
//     Edge Functions > Secrets (from the WHOOP Developer Dashboard).
//   SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY -- provided by Supabase.
//   whoop_token_key / whoop_sync_key -- generated in Vault by
//     migrations/migrate_whoop.py, read through public.whoop_secret().

import { createClient, SupabaseClient } from "npm:@supabase/supabase-js@2.45.4";

export const WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth";
export const WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token";
export const WHOOP_API = "https://api.prod.whoop.com/developer";
// read:profile left out: not enabled on the GBO WHOOP Pilot app (WHOOP rejects the whole
// request with invalid_scope). The profile call in whoop-oauth-callback is optional.
export const SCOPES = "offline read:recovery read:cycles read:sleep read:workout read:body_measurement";
export const BACKFILL_DAYS = 90;   // history pulled on first connect
export const OVERLAP_DAYS = 4;     // WHOOP can re-score recent days; re-pull them each sync

export function env(name: string): string {
  const v = Deno.env.get(name);
  if (!v) throw new Error(`Missing secret ${name}`);
  return v;
}

export function callbackUrl(): string {
  return `${env("SUPABASE_URL")}/functions/v1/whoop-oauth-callback`;
}

export function db(): SupabaseClient {
  return createClient(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"), {
    auth: { persistSession: false },
  });
}

export async function vaultSecret(sb: SupabaseClient, name: string): Promise<string> {
  const { data, error } = await sb.rpc("whoop_secret", { secret_name: name });
  if (error || !data) throw new Error(`Vault secret ${name} unavailable: ${error?.message ?? "missing"}`);
  return data as string;
}

// ---------------------------------------------------------------- crypto
// AES-256-GCM. Stored as base64(iv[12] + ciphertext).
async function aesKey(sb: SupabaseClient): Promise<CryptoKey> {
  const raw = Uint8Array.from(atob(await vaultSecret(sb, "whoop_token_key")), (c) => c.charCodeAt(0));
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

export async function encrypt(sb: SupabaseClient, plain: string): Promise<string> {
  const key = await aesKey(sb);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(plain)));
  const all = new Uint8Array(iv.length + ct.length);
  all.set(iv);
  all.set(ct, iv.length);
  let s = "";
  all.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s);
}

export async function decrypt(sb: SupabaseClient, enc: string): Promise<string> {
  const key = await aesKey(sb);
  const all = Uint8Array.from(atob(enc), (c) => c.charCodeAt(0));
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: all.slice(0, 12) }, key, all.slice(12));
  return new TextDecoder().decode(pt);
}

// ---------------------------------------------------------------- tokens
export interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  scope?: string;
}

async function tokenRequest(params: Record<string, string>): Promise<TokenResponse> {
  const res = await fetch(WHOOP_TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: env("WHOOP_CLIENT_ID"),
      client_secret: env("WHOOP_CLIENT_SECRET"),
      ...params,
    }),
  });
  const body = await res.text();
  if (!res.ok) throw new Error(`WHOOP token request failed (${res.status}): ${body.slice(0, 300)}`);
  return JSON.parse(body);
}

export function exchangeCode(code: string): Promise<TokenResponse> {
  return tokenRequest({ grant_type: "authorization_code", code, redirect_uri: callbackUrl() });
}

export function refresh(refreshToken: string): Promise<TokenResponse> {
  return tokenRequest({ grant_type: "refresh_token", refresh_token: refreshToken, scope: "offline" });
}

export async function saveTokens(sb: SupabaseClient, playerId: number, t: TokenResponse, oldRefreshEnc?: string | null) {
  const expires = new Date(Date.now() + (t.expires_in ?? 3600) * 1000).toISOString();
  const row = {
    player_id: playerId,
    access_token_enc: await encrypt(sb, t.access_token),
    // WHOOP returns a new refresh token on every refresh; keep the old one only if it didn't.
    refresh_token_enc: t.refresh_token ? await encrypt(sb, t.refresh_token) : (oldRefreshEnc ?? null),
    expires_at: expires,
    updated_at: new Date().toISOString(),
  };
  const { error } = await sb.from("whoop_tokens").upsert(row, { onConflict: "player_id" });
  if (error) throw new Error(`Saving tokens failed: ${error.message}`);
}

/** A fresh access token for this player (refreshes and stores the new pair). */
export async function accessTokenFor(sb: SupabaseClient, playerId: number): Promise<string> {
  const { data, error } = await sb.from("whoop_tokens").select("*").eq("player_id", playerId).maybeSingle();
  if (error || !data) throw new Error("No WHOOP tokens stored -- he needs to connect again.");
  if (data.expires_at && new Date(data.expires_at + "Z").getTime() - Date.now() > 5 * 60 * 1000) {
    return await decrypt(sb, data.access_token_enc);
  }
  if (!data.refresh_token_enc) throw new Error("No refresh token stored -- he needs to connect again.");
  const t = await refresh(await decrypt(sb, data.refresh_token_enc));
  await saveTokens(sb, playerId, t, data.refresh_token_enc);
  return t.access_token;
}

// ---------------------------------------------------------------- API
export async function whoopGet(token: string, path: string, query: Record<string, string> = {}) {
  const url = new URL(`${WHOOP_API}${path}`);
  for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
  for (let attempt = 0; attempt < 3; attempt++) {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (res.status === 429) {
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
      continue;
    }
    const body = await res.text();
    if (!res.ok) throw new Error(`WHOOP ${path} failed (${res.status}): ${body.slice(0, 300)}`);
    return JSON.parse(body);
  }
  throw new Error(`WHOOP ${path}: rate limited`);
}

/** Every record of a paginated v2 collection between start and end (ISO). */
export async function collect(token: string, path: string, start: string, end: string): Promise<any[]> {
  const out: any[] = [];
  let next: string | undefined;
  for (let page = 0; page < 60; page++) {
    const q: Record<string, string> = { limit: "25", start, end };
    if (next) q.nextToken = next;
    const body = await whoopGet(token, path, q);
    out.push(...(body.records ?? []));
    next = body.next_token ?? body.nextToken ?? undefined;
    if (!next) break;
  }
  return out;
}

// ---------------------------------------------------------------- mapping
const MIN = 60000;
const toMin = (ms: unknown) => (typeof ms === "number" ? Math.round((ms / MIN) * 10) / 10 : null);
const ts = (iso: unknown) => (typeof iso === "string" ? iso.replace("Z", "").replace(/\+00:00$/, "") : null);

function offsetMinutes(off: unknown): number {
  const m = typeof off === "string" ? off.match(/^([+-])(\d{2}):?(\d{2})$/) : null;
  if (!m) return -5 * 60; // fall back to Central (CDT)
  return (m[1] === "-" ? -1 : 1) * (parseInt(m[2]) * 60 + parseInt(m[3]));
}

/** The day he woke up: cycle start (he fell asleep) in local time + 12 h. */
export function dayDate(startIso: string, off: unknown): string {
  const t = new Date(startIso).getTime() + (offsetMinutes(off) + 12 * 60) * MIN;
  return new Date(t).toISOString().slice(0, 10);
}

export function dailyRows(playerId: number, cycles: any[], recoveries: any[], sleeps: any[]) {
  const recByCycle = new Map<number, any>();
  for (const r of recoveries) recByCycle.set(Number(r.cycle_id), r);
  const sleepById = new Map<string, any>();
  const sleepByCycle = new Map<number, any>();
  for (const s of sleeps) {
    sleepById.set(String(s.id), s);
    if (!s.nap && s.cycle_id != null) sleepByCycle.set(Number(s.cycle_id), s);
  }
  return cycles.map((c) => {
    const rec = recByCycle.get(Number(c.id));
    const sl = (rec?.sleep_id && sleepById.get(String(rec.sleep_id))) || sleepByCycle.get(Number(c.id));
    const cs = c.score ?? {};
    const rs = rec?.score ?? {};
    const ss = sl?.score ?? {};
    const st = ss.stage_summary ?? {};
    const need = ss.sleep_needed ?? {};
    const light = st.total_light_sleep_time_milli, deep = st.total_slow_wave_sleep_time_milli, rem = st.total_rem_sleep_time_milli;
    const total = [light, deep, rem].every((v) => typeof v === "number") ? light + deep + rem : null;
    const needMs = [need.baseline_milli, need.need_from_sleep_debt_milli, need.need_from_recent_strain_milli, need.need_from_recent_nap_milli]
      .filter((v) => typeof v === "number").reduce((a: number, b: number) => a + b, 0);
    return {
      player_id: playerId,
      cycle_id: Number(c.id),
      day_date: dayDate(c.start, c.timezone_offset),
      cycle_start: ts(c.start),
      cycle_end: ts(c.end),
      timezone_offset: c.timezone_offset ?? null,
      cycle_score_state: c.score_state ?? null,
      day_strain: cs.strain ?? null,
      kilojoule: cs.kilojoule ?? null,
      avg_hr: cs.average_heart_rate ?? null,
      max_hr: cs.max_heart_rate ?? null,
      recovery_score_state: rec?.score_state ?? null,
      recovery_score: rs.recovery_score ?? null,
      hrv_rmssd_ms: rs.hrv_rmssd_milli ?? null,
      resting_hr: rs.resting_heart_rate ?? null,
      spo2_pct: rs.spo2_percentage ?? null,
      skin_temp_c: rs.skin_temp_celsius ?? null,
      user_calibrating: rs.user_calibrating ?? null,
      sleep_id: sl ? String(sl.id) : null,
      sleep_start: ts(sl?.start),
      sleep_end: ts(sl?.end),
      sleep_score_state: sl?.score_state ?? null,
      sleep_performance_pct: ss.sleep_performance_percentage ?? null,
      sleep_consistency_pct: ss.sleep_consistency_percentage ?? null,
      sleep_efficiency_pct: ss.sleep_efficiency_percentage ?? null,
      respiratory_rate: ss.respiratory_rate ?? null,
      total_sleep_min: toMin(total),
      in_bed_min: toMin(st.total_in_bed_time_milli),
      light_sleep_min: toMin(light),
      deep_sleep_min: toMin(deep),
      rem_sleep_min: toMin(rem),
      awake_min: toMin(st.total_awake_time_milli),
      sleep_need_min: needMs ? toMin(needMs) : null,
      disturbances: st.disturbance_count ?? null,
      updated_at: new Date().toISOString(),
    };
  });
}

export function workoutRows(playerId: number, workouts: any[]) {
  return workouts.map((w) => {
    const s = w.score ?? {};
    return {
      whoop_workout_id: String(w.id),
      player_id: playerId,
      day_date: w.start ? new Date(new Date(w.start).getTime() + offsetMinutes(w.timezone_offset) * MIN).toISOString().slice(0, 10) : null,
      start_time: ts(w.start),
      end_time: ts(w.end),
      timezone_offset: w.timezone_offset ?? null,
      sport_name: w.sport_name ?? null,
      score_state: w.score_state ?? null,
      strain: s.strain ?? null,
      avg_hr: s.average_heart_rate ?? null,
      max_hr: s.max_heart_rate ?? null,
      kilojoule: s.kilojoule ?? null,
      zone_durations: s.zone_durations ?? s.zone_duration ?? null,
      updated_at: new Date().toISOString(),
    };
  });
}

/** Pull and store one player's data. days = how far back (used when he has never synced). */
export async function syncPlayer(sb: SupabaseClient, playerId: number, days = BACKFILL_DAYS) {
  const { data: conn } = await sb.from("whoop_connections").select("last_synced_at").eq("player_id", playerId).maybeSingle();
  const now = new Date();
  const since = conn?.last_synced_at
    ? new Date(new Date(conn.last_synced_at + "Z").getTime() - OVERLAP_DAYS * 86400000)
    : new Date(now.getTime() - days * 86400000);
  const start = since.toISOString();
  const end = new Date(now.getTime() + 86400000).toISOString();
  try {
    const token = await accessTokenFor(sb, playerId);
    const [cycles, recoveries, sleeps, workouts] = [
      await collect(token, "/v2/cycle", start, end),
      await collect(token, "/v2/recovery", start, end),
      await collect(token, "/v2/activity/sleep", start, end),
      await collect(token, "/v2/activity/workout", start, end),
    ];
    const daily = dailyRows(playerId, cycles, recoveries, sleeps);
    if (daily.length) {
      const { error } = await sb.from("whoop_daily").upsert(daily, { onConflict: "player_id,cycle_id" });
      if (error) throw new Error(`Saving daily rows failed: ${error.message}`);
    }
    const wk = workoutRows(playerId, workouts);
    if (wk.length) {
      const { error } = await sb.from("whoop_workouts").upsert(wk, { onConflict: "whoop_workout_id" });
      if (error) throw new Error(`Saving workouts failed: ${error.message}`);
    }
    await sb.from("whoop_connections").update({
      status: "connected", last_error: null, last_synced_at: now.toISOString(), updated_at: now.toISOString(),
    }).eq("player_id", playerId);
    return { player_id: playerId, ok: true, days: daily.length, workouts: wk.length };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const plain = /401|invalid_grant|refresh token|connect again/i.test(msg)
      ? "WHOOP access was revoked or expired -- make a new Connect WHOOP link for him. (" + msg.slice(0, 200) + ")"
      : msg.slice(0, 500);
    await sb.from("whoop_connections").update({ status: "error", last_error: plain, updated_at: now.toISOString() })
      .eq("player_id", playerId);
    return { player_id: playerId, ok: false, error: plain };
  }
}
