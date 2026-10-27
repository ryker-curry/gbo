// GBO -- whoop-sync Edge Function (Oct 2026 WHOOP pilot).
//
// Pulls fresh WHOOP data for every connected player. Called by the pg_cron
// job 'gbo-whoop-sync' (migrations/migrate_whoop.py) twice a day, and by the
// "Sync now" button on Player Profile > Recovery.
//
// POST, header x-sync-key: <Vault secret whoop_sync_key>
// Body (optional): {"player_id": 12}  -- one player only.
// Deployed with verify_jwt = false; the sync key is the auth.

import { db, syncPlayer, vaultSecret } from "../_shared/whoop.ts";

Deno.serve(async (req: Request) => {
  const sb = db();
  const key = req.headers.get("x-sync-key") ?? "";
  let expected = "";
  try {
    expected = await vaultSecret(sb, "whoop_sync_key");
  } catch (e) {
    return Response.json({ ok: false, error: String(e) }, { status: 500 });
  }
  if (!key || key !== expected) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });

  let body: { player_id?: number } = {};
  try { body = await req.json(); } catch (_) { /* empty body is fine */ }

  let q = sb.from("whoop_connections").select("player_id").eq("active", true).in("status", ["connected", "error"]);
  if (body.player_id) q = q.eq("player_id", body.player_id);
  const { data: conns, error } = await q;
  if (error) return Response.json({ ok: false, error: error.message }, { status: 500 });

  const results = [];
  for (const c of conns ?? []) results.push(await syncPlayer(sb, Number(c.player_id)));
  return Response.json({ ok: results.every((r) => r.ok), results });
});
